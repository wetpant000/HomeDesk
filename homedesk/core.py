"""HomeDesk's logic, shared by the web app and the MCP server."""

import calendar
import mimetypes
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from . import config, extract
from .db import row, rows

FIELDS = ("kind", "title", "vendor", "item_name", "category", "amount", "doc_date", "expiry_date",
          "warranty_months", "contact_email", "notes", "file_name", "needs_review")
EDITABLE = FIELDS[:-2]
MAX_UPLOAD = 15 * 1024 * 1024
ANOMALY_THRESHOLD = 1.3
FOLLOW_UP_DAYS = 7
ID_PROOF_HORIZON = 180

CASE_STATUSES = ("awaiting_approval", "sent", "resolved")


class HomeDeskError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean_date(value) -> str | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10]).isoformat()
    except ValueError:
        return None


def add_months(d: date, months: int) -> date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _normalise(fields: dict) -> dict:
    f = dict(fields)
    if "kind" in f and f["kind"] not in extract.KINDS:
        f["kind"] = "other"
    if "title" in f:
        f["title"] = (f["title"] or "").strip() or "Untitled document"
    for k in ("doc_date", "expiry_date"):
        if k in f:
            f[k] = _clean_date(f[k])
    if "amount" in f:
        try:
            f["amount"] = float(f["amount"]) if f["amount"] not in (None, "") else None
        except (TypeError, ValueError):
            f["amount"] = None
    if "warranty_months" in f:
        try:
            f["warranty_months"] = int(f["warranty_months"]) if f["warranty_months"] not in (None, "") else None
        except (TypeError, ValueError):
            f["warranty_months"] = None
    for k in ("vendor", "item_name", "category", "contact_email", "notes"):
        if k in f and isinstance(f[k], str):
            f[k] = f[k].strip() or None
    return f


def _fill_expiry(f: dict) -> None:
    """Warranty end = purchase date + warranty months, when not printed."""
    if not f.get("expiry_date") and f.get("warranty_months") and f.get("doc_date"):
        f["expiry_date"] = add_months(date.fromisoformat(f["doc_date"]), f["warranty_months"]).isoformat()


# ---------- documents ----------

def get_document(conn: sqlite3.Connection, doc_id: int) -> dict:
    doc = row(conn.execute("SELECT * FROM documents WHERE id = ?", (doc_id,)))
    if not doc:
        raise HomeDeskError(f"Document {doc_id} not found.", 404)
    doc["anomaly"] = bill_anomaly(conn, doc)
    return doc


def add_document(conn: sqlite3.Connection, fields: dict) -> dict:
    f = _normalise({k: fields.get(k) for k in FIELDS})
    f["kind"] = f["kind"] or "other"
    f["title"] = f["title"] or "Untitled document"
    f["needs_review"] = int(bool(f.get("needs_review")))
    _fill_expiry(f)
    cur = conn.execute(
        f"INSERT INTO documents ({', '.join(FIELDS)}, created_at) VALUES ({', '.join('?' * len(FIELDS))}, ?)",
        [f[k] for k in FIELDS] + [_now()],
    )
    conn.commit()
    return get_document(conn, cur.lastrowid)


def update_document(conn: sqlite3.Connection, doc_id: int, fields: dict) -> dict:
    current = get_document(conn, doc_id)
    f = _normalise({k: v for k, v in fields.items() if k in EDITABLE})
    if ("warranty_months" in f or "doc_date" in f) and "expiry_date" not in f:
        merged = {**current, **f, "expiry_date": None}
        _fill_expiry(merged)
        if merged["expiry_date"]:
            f["expiry_date"] = merged["expiry_date"]
    f["needs_review"] = 0
    sets = ", ".join(f"{k} = ?" for k in f)
    conn.execute(f"UPDATE documents SET {sets} WHERE id = ?", [*f.values(), doc_id])
    conn.commit()
    return get_document(conn, doc_id)


def list_documents(conn: sqlite3.Connection, kind: str | None = None) -> list[dict]:
    if kind:
        return rows(conn.execute("SELECT * FROM documents WHERE kind = ? ORDER BY id DESC", (kind,)))
    return rows(conn.execute("SELECT * FROM documents ORDER BY id DESC"))


SYNONYMS = {
    "fridge": ("fridge", "refrigerator"), "refrigerator": ("fridge", "refrigerator"),
    "ac": (" ac ", "air conditioner", "split ac", "window ac"), "tv": (" tv", "television"),
    "phone": ("phone", "mobile"), "mobile": ("phone", "mobile"), "id": ("id_proof", "passport", "aadhaar"),
    "power": ("electricity",), "current": ("electricity",), "wifi": ("internet", "broadband"),
}


def find_documents(conn: sqlite3.Connection, query: str) -> list[dict]:
    """Every word must match (or one of its synonyms) somewhere in the document's text fields."""
    words = [w for w in query.lower().split() if w]
    if not words:
        return list_documents(conn)
    haystack = ("(' '||lower(coalesce(title,'')||' '||coalesce(vendor,'')||' '||coalesce(item_name,'')||' '||kind"
                "||' '||coalesce(category,'')||' '||coalesce(notes,''))||' ')")
    clauses, params = [], []
    for w in words:
        options = SYNONYMS.get(w, (w,))
        clauses.append("(" + " OR ".join(f"{haystack} LIKE ?" for _ in options) + ")")
        params += [f"%{o}%" for o in options]
    return rows(conn.execute(f"SELECT * FROM documents WHERE {' AND '.join(clauses)} ORDER BY id DESC", params))


def file_path(doc: dict) -> Path | None:
    if not doc.get("file_name"):
        return None
    p = config.upload_dir() / Path(doc["file_name"]).name
    return p if p.is_file() else None


def ingest(conn: sqlite3.Connection, data: bytes | None = None, filename: str | None = None,
           media_type: str | None = None, text: str | None = None) -> dict:
    """Read a photo, PDF or pasted text and file it as a document."""
    if not data and not (text and text.strip()):
        raise HomeDeskError("Add a photo or PDF, or paste the text of an email or bill.")
    if data and len(data) > MAX_UPLOAD:
        raise HomeDeskError("File is larger than 15 MB.")

    saved = None
    if data:
        media_type = media_type or mimetypes.guess_type(filename or "")[0] or "application/octet-stream"
        ext = Path(filename or "").suffix.lower()[:8] or (mimetypes.guess_extension(media_type) or "")
        saved = f"{uuid.uuid4().hex}{ext}"
        config.upload_dir().mkdir(parents=True, exist_ok=True)
        (config.upload_dir() / saved).write_bytes(data)

    warning = None
    used_ai = False
    readable_by_rules = media_type in (None, "text/plain") or not data
    if config.ai_enabled():
        try:
            result = extract.extract_with_claude(data, media_type, text)
            used_ai = True
        except extract.ExtractionError as e:
            warning = f"{e} Filled what I could; please check the fields."
            result = extract.extract_with_rules(text, filename)
    else:
        result = extract.extract_with_rules(
            (text or "") + ("\n" + data.decode("utf-8", "ignore") if data and readable_by_rules else ""), filename)
        if data and not readable_by_rules:
            warning = "AI reading is off, so only the file was saved. Please fill in the details."

    fields = result.model_dump()
    fields["notes"] = fields.pop("summary")
    fields["file_name"] = saved
    fields["needs_review"] = not used_ai
    doc = add_document(conn, fields)
    return {"document": doc, "used_ai": used_ai, "warning": warning}


# ---------- bills ----------

def bill_anomaly(conn: sqlite3.Connection, doc: dict) -> dict | None:
    """Flag a bill that is well above the average of the same kind of bill before it."""
    if doc.get("kind") != "bill" or not doc.get("amount") or not doc.get("category"):
        return None
    if doc.get("doc_date"):
        prev = conn.execute(
            "SELECT amount FROM documents WHERE kind = 'bill' AND category = ? AND id != ? AND amount IS NOT NULL "
            "AND doc_date IS NOT NULL AND doc_date < ? ORDER BY doc_date DESC LIMIT 6",
            (doc["category"], doc["id"], doc["doc_date"]))
    else:
        prev = conn.execute(
            "SELECT amount FROM documents WHERE kind = 'bill' AND category = ? AND id < ? AND amount IS NOT NULL "
            "ORDER BY id DESC LIMIT 6", (doc["category"], doc["id"]))
    amounts = [r[0] for r in prev.fetchall()]
    if len(amounts) < 2:
        return None
    avg = sum(amounts) / len(amounts)
    if avg <= 0 or doc["amount"] < avg * ANOMALY_THRESHOLD:
        return None
    pct = round((doc["amount"] / avg - 1) * 100)
    return {
        "average": round(avg, 2),
        "increase_pct": pct,
        "message": f"This {doc['category']} bill (₹{doc['amount']:,.0f}) is {pct}% higher than your recent average of ₹{avg:,.0f}.",
    }


# ---------- what's due ----------

def _expiry_label(kind: str) -> str:
    return {"bill": "Bill due", "invoice": "Warranty ends", "warranty": "Warranty ends",
            "insurance": "Policy renewal", "id_proof": "Expires"}.get(kind, "Due")


def whats_due(conn: sqlite3.Connection, days: int = 30, today: date | None = None) -> list[dict]:
    today = today or date.today()
    items: list[dict] = []

    start = (today - timedelta(days=7)).isoformat()
    end = (today + timedelta(days=max(days, ID_PROOF_HORIZON))).isoformat()
    for d in rows(conn.execute(
            "SELECT * FROM documents WHERE expiry_date BETWEEN ? AND ? ORDER BY expiry_date", (start, end))):
        expiry = date.fromisoformat(d["expiry_date"])
        left = (expiry - today).days
        horizon = ID_PROOF_HORIZON if d["kind"] == "id_proof" else days
        if left > horizon:
            continue
        when = "today" if left == 0 else (f"in {left} days" if left > 0 else f"{-left} days ago")
        items.append({
            "type": "expiry", "date": d["expiry_date"], "days_left": left,
            "urgency": "high" if left <= 7 else ("medium" if left <= 30 else "low"),
            "title": f"{_expiry_label(d['kind'])}: {d['item_name'] or d['title']}",
            "detail": f"{d['expiry_date']} ({when})", "document_id": d["id"], "kind": d["kind"],
        })

    for c in rows(conn.execute("SELECT * FROM cases WHERE status != 'resolved'")):
        if c["status"] == "awaiting_approval":
            items.append({"type": "approval", "date": today.isoformat(), "days_left": 0, "urgency": "high",
                          "title": f"Approve draft: {c['subject'] or c['issue']}",
                          "detail": "A drafted email is waiting for your approval.", "case_id": c["id"]})
        elif c["status"] == "sent" and c["follow_up_on"]:
            left = (date.fromisoformat(c["follow_up_on"]) - today).days
            if left <= days:
                items.append({"type": "follow_up", "date": c["follow_up_on"], "days_left": left,
                              "urgency": "high" if left <= 0 else "low",
                              "title": f"{'No reply yet' if left <= 0 else 'Follow-up due'}: {c['subject'] or c['issue']}",
                              "detail": "Escalate if nobody has replied." if left <= 0 else f"Check for a reply by {c['follow_up_on']}.",
                              "case_id": c["id"]})

    since = (today - timedelta(days=60)).isoformat()
    for d in rows(conn.execute(
            "SELECT * FROM documents WHERE kind = 'bill' AND (doc_date >= ? OR (doc_date IS NULL AND created_at >= ?))",
            (since, since))):
        a = bill_anomaly(conn, d)
        if a:
            items.append({"type": "anomaly", "date": d["doc_date"] or d["created_at"][:10], "days_left": 0,
                          "urgency": "medium", "title": f"Unusual bill: {d['title']}", "detail": a["message"],
                          "document_id": d["id"]})

    order = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: (order[i["urgency"]], i["days_left"]))
    return items


# ---------- complaint cases ----------

def _event(conn: sqlite3.Connection, case_id: int, kind: str, note: str | None = None) -> None:
    conn.execute("INSERT INTO case_events (case_id, at, kind, note) VALUES (?, ?, ?, ?)", (case_id, _now(), kind, note))


def get_case(conn: sqlite3.Connection, case_id: int) -> dict:
    c = row(conn.execute("SELECT * FROM cases WHERE id = ?", (case_id,)))
    if not c:
        raise HomeDeskError(f"Case {case_id} not found.", 404)
    c["events"] = rows(conn.execute("SELECT at, kind, note FROM case_events WHERE case_id = ? ORDER BY id", (case_id,)))
    c["mailto"] = mailto(c)
    return c


def list_cases(conn: sqlite3.Connection, status: str | None = None) -> list[dict]:
    if status:
        ids = conn.execute("SELECT id FROM cases WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
    else:
        ids = conn.execute("SELECT id FROM cases ORDER BY id DESC").fetchall()
    return [get_case(conn, r[0]) for r in ids]


def mailto(c: dict) -> str:
    return f"mailto:{quote(c.get('to_email') or '')}?subject={quote(c.get('subject') or '')}&body={quote(c.get('body') or '')}"


def warranty_status(doc: dict | None, today: date | None = None) -> str | None:
    if not doc or doc.get("kind") not in ("invoice", "warranty") or not doc.get("expiry_date"):
        return None
    today = today or date.today()
    end = date.fromisoformat(doc["expiry_date"])
    return f"Under warranty until {end.isoformat()}" if end >= today else f"Warranty ended on {end.isoformat()}"


def open_case(conn: sqlite3.Connection, issue: str, document_id: int | None = None) -> dict:
    """Open a complaint and draft the first email. Nothing is sent until approved."""
    if not issue or not issue.strip():
        raise HomeDeskError("Describe the problem.")
    doc = get_document(conn, document_id) if document_id else None
    draft, used_ai = extract.draft_email(doc, issue, 0)
    now = _now()
    cur = conn.execute(
        "INSERT INTO cases (document_id, issue, status, to_email, subject, body, created_at, updated_at) "
        "VALUES (?, ?, 'awaiting_approval', ?, ?, ?, ?, ?)",
        (document_id, issue.strip(), (doc or {}).get("contact_email"), draft.subject, draft.body, now, now))
    case_id = cur.lastrowid
    _event(conn, case_id, "opened", issue.strip())
    status = warranty_status(doc)
    if status:
        _event(conn, case_id, "warranty_checked", status)
    _event(conn, case_id, "drafted", "Drafted with Claude" if used_ai else "Drafted from template")
    conn.commit()
    return get_case(conn, case_id)


def approve_case(conn: sqlite3.Connection, case_id: int, subject: str | None = None, body: str | None = None,
                 to_email: str | None = None, today: date | None = None) -> dict:
    """The approval gate: only a person calls this, from the app."""
    c = get_case(conn, case_id)
    if c["status"] != "awaiting_approval":
        raise HomeDeskError("This case has no draft waiting for approval.")
    today = today or date.today()
    follow_up = (today + timedelta(days=FOLLOW_UP_DAYS)).isoformat()
    conn.execute(
        "UPDATE cases SET status = 'sent', subject = ?, body = ?, to_email = ?, follow_up_on = ?, updated_at = ? WHERE id = ?",
        (subject if subject is not None else c["subject"], body if body is not None else c["body"],
         to_email if to_email is not None else c["to_email"], follow_up, _now(), case_id))
    _event(conn, case_id, "approved", f"Approved and sent; follow up on {follow_up}")
    conn.commit()
    return get_case(conn, case_id)


def escalate_case(conn: sqlite3.Connection, case_id: int) -> dict:
    c = get_case(conn, case_id)
    if c["status"] != "sent":
        raise HomeDeskError("Only a sent case can be escalated.")
    doc = get_document(conn, c["document_id"]) if c["document_id"] else None
    level = c["escalation_level"] + 1
    draft, used_ai = extract.draft_email(doc, c["issue"], level)
    conn.execute(
        "UPDATE cases SET status = 'awaiting_approval', escalation_level = ?, subject = ?, body = ?, follow_up_on = NULL, "
        "updated_at = ? WHERE id = ?", (level, draft.subject, draft.body, _now(), case_id))
    _event(conn, case_id, "escalated", f"Escalation level {level} drafted ({'Claude' if used_ai else 'template'})")
    conn.commit()
    return get_case(conn, case_id)


def resolve_case(conn: sqlite3.Connection, case_id: int, note: str | None = None) -> dict:
    get_case(conn, case_id)
    conn.execute("UPDATE cases SET status = 'resolved', updated_at = ? WHERE id = ?", (_now(), case_id))
    _event(conn, case_id, "resolved", note)
    conn.commit()
    return get_case(conn, case_id)


# ---------- timeline and calendar ----------

def timeline(conn: sqlite3.Connection, document_id: int) -> dict:
    doc = get_document(conn, document_id)
    events = [{"at": doc["created_at"], "kind": "filed", "note": doc["title"]}]
    if doc.get("expiry_date"):
        events.append({"at": doc["expiry_date"], "kind": "expiry", "note": _expiry_label(doc["kind"])})
    case_ids = [r[0] for r in conn.execute("SELECT id FROM cases WHERE document_id = ? ORDER BY id", (document_id,))]
    cases = [get_case(conn, i) for i in case_ids]
    for c in cases:
        events += [{**e, "case_id": c["id"]} for e in c["events"]]
    events.sort(key=lambda e: e["at"])
    return {"document": doc, "warranty": warranty_status(doc), "cases": cases, "events": events}


def _ics_text(s: str) -> str:
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def calendar_ics(conn: sqlite3.Connection, today: date | None = None) -> str:
    """Every upcoming expiry as an all-day event with a 3-day reminder."""
    today = today or date.today()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//HomeDesk//EN", "CALSCALE:GREGORIAN"]
    for d in rows(conn.execute("SELECT * FROM documents WHERE expiry_date >= ? ORDER BY expiry_date", (today.isoformat(),))):
        day = date.fromisoformat(d["expiry_date"])
        lines += [
            "BEGIN:VEVENT",
            f"UID:homedesk-doc-{d['id']}@homedesk",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
            f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
            f"SUMMARY:{_ics_text('HomeDesk: ' + _expiry_label(d['kind']) + ' - ' + (d['item_name'] or d['title']))}",
            "BEGIN:VALARM", "ACTION:DISPLAY", "DESCRIPTION:HomeDesk reminder", "TRIGGER:-P3D", "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines) + "\r\n"
