from datetime import date, timedelta

import pytest

from homedesk import core, extract
from homedesk.db import connect

TODAY = date(2026, 12, 1)


@pytest.fixture
def conn(tmp_path, monkeypatch):
    monkeypatch.setenv("HOMEDESK_DATA", str(tmp_path))
    monkeypatch.setenv("HOMEDESK_AI", "off")
    c = connect(tmp_path / "test.db")
    yield c
    c.close()


def d(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def test_warranty_end_is_computed_from_purchase_date(conn):
    doc = core.add_document(conn, {"kind": "invoice", "title": "AC", "doc_date": "2026-01-31", "warranty_months": 1})
    assert doc["expiry_date"] == "2026-02-28"


def test_bill_spike_is_flagged_only_against_history(conn):
    for amount, days in ((1400, -90), (1380, -60)):
        core.add_document(conn, {"kind": "bill", "title": "Power", "category": "electricity", "amount": amount, "doc_date": d(days)})
    normal = core.add_document(conn, {"kind": "bill", "title": "Power", "category": "electricity", "amount": 1500, "doc_date": d(-30)})
    assert normal["anomaly"] is None
    spike = core.add_document(conn, {"kind": "bill", "title": "Power", "category": "electricity", "amount": 2400, "doc_date": d(-1)})
    assert spike["anomaly"]["increase_pct"] == 68


def test_whats_due_lists_expiries_within_horizon(conn):
    core.add_document(conn, {"kind": "insurance", "title": "Car", "expiry_date": d(10)})
    core.add_document(conn, {"kind": "insurance", "title": "Health", "expiry_date": d(90)})
    core.add_document(conn, {"kind": "id_proof", "title": "Passport", "expiry_date": d(150)})
    titles = [i["title"] for i in core.whats_due(conn, 30, today=TODAY)]
    assert "Policy renewal: Car" in titles
    assert "Expires: Passport" in titles
    assert not any("Health" in t for t in titles)


def test_case_flow_needs_approval_then_follow_up_then_escalation(conn):
    doc = core.add_document(conn, {"kind": "invoice", "title": "Fridge", "item_name": "Fridge", "doc_date": d(-100),
                                   "warranty_months": 12, "contact_email": "help@example.com"})
    case = core.open_case(conn, "Not cooling", doc["id"])
    assert case["status"] == "awaiting_approval"
    assert case["to_email"] == "help@example.com"
    assert any(e["kind"] == "warranty_checked" for e in case["events"])

    with pytest.raises(core.HomeDeskError):
        core.escalate_case(conn, case["id"])

    sent = core.approve_case(conn, case["id"], today=TODAY)
    assert sent["status"] == "sent" and sent["follow_up_on"] == d(7)
    assert sent["mailto"].startswith("mailto:help%40example.com?subject=")

    overdue = [i for i in core.whats_due(conn, 30, today=TODAY + timedelta(days=8)) if i["type"] == "follow_up"]
    assert overdue and overdue[0]["urgency"] == "high"

    escalated = core.escalate_case(conn, case["id"])
    assert escalated["status"] == "awaiting_approval" and escalated["escalation_level"] == 1
    assert "1915" in escalated["body"]


def test_ingest_text_without_ai_marks_for_review(conn):
    text = "BESCOM Electricity Bill\nBill date 05/11/2026\nDue date 20/11/2026\nAmount payable Rs. 2,390\nUnits consumed 410"
    result = core.ingest(conn, text=text)
    doc = result["document"]
    assert result["used_ai"] is False and doc["needs_review"] == 1
    assert doc["kind"] == "bill" and doc["category"] == "electricity"
    assert doc["amount"] == 2390 and doc["doc_date"] == "2026-11-05" and doc["expiry_date"] == "2026-11-20"

    fixed = core.update_document(conn, doc["id"], {"title": "BESCOM Nov bill"})
    assert fixed["needs_review"] == 0 and fixed["title"] == "BESCOM Nov bill"


def test_rules_read_warranty_length():
    e = extract.extract_with_rules("Tax Invoice\nLG AC\nInvoice date 2026-01-10\n2 year warranty\nsupport@lg.example")
    assert e.kind == "invoice" and e.warranty_months == 24 and e.contact_email == "support@lg.example"


def test_calendar_has_upcoming_expiries(conn):
    core.add_document(conn, {"kind": "insurance", "title": "Car, policy; renewal", "expiry_date": d(10)})
    ics = core.calendar_ics(conn, today=TODAY)
    assert "DTSTART;VALUE=DATE:20261211" in ics
    assert "Car\\, policy\\; renewal" in ics


def test_search_understands_everyday_words(conn):
    core.add_document(conn, {"kind": "invoice", "title": "Samsung refrigerator invoice"})
    core.add_document(conn, {"kind": "invoice", "title": "LG split AC invoice"})
    core.add_document(conn, {"kind": "bill", "title": "Bescom bill", "category": "electricity"})
    assert [d["title"] for d in core.find_documents(conn, "fridge")] == ["Samsung refrigerator invoice"]
    assert [d["title"] for d in core.find_documents(conn, "ac invoice")] == ["LG split AC invoice"]
    assert [d["title"] for d in core.find_documents(conn, "power")] == ["Bescom bill"]
