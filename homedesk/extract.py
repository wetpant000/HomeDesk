"""Reading documents and drafting emails.

Uses Claude when credentials are configured. Without them, a simple
rule-based reader fills what it can and the document is marked for review.
"""

import base64
import json
import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel

from . import config

KINDS = ("invoice", "bill", "id_proof", "warranty", "insurance", "receipt", "other")
BILL_CATEGORIES = ("electricity", "water", "gas", "phone", "internet", "rent", "other")
IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PDF_TYPE = "application/pdf"


class ExtractionError(Exception):
    pass


class Extracted(BaseModel):
    kind: Literal["invoice", "bill", "id_proof", "warranty", "insurance", "receipt", "other"]
    title: str
    vendor: Optional[str]
    item_name: Optional[str]
    category: Optional[str]
    amount: Optional[float]
    doc_date: Optional[str]
    expiry_date: Optional[str]
    warranty_months: Optional[int]
    contact_email: Optional[str]
    summary: str


class Draft(BaseModel):
    subject: str
    body: str


EXTRACT_SYSTEM = """You read household documents for HomeDesk, a paperwork assistant for households in India: purchase invoices, utility bills, receipts, warranty cards, insurance policies and ID proofs.

Return the fields exactly as the document states them:
- kind: invoice (a purchase with an item), bill (a recurring utility or service bill), receipt, warranty, insurance, id_proof or other.
- title: a short label a person would recognise, e.g. "LG split AC invoice" or "BESCOM electricity bill, Oct 2026".
- vendor: the seller, utility or issuer.
- item_name: the product, for invoices and warranty cards.
- category: for bills only, one of electricity, water, gas, phone, internet, rent, other.
- amount: the total payable in rupees, as a number.
- doc_date: the invoice, bill or issue date.
- expiry_date: the printed warranty end, policy renewal, document expiry or bill due date.
- warranty_months: the warranty length in months, if stated.
- contact_email: the support or service email printed on the document.
- summary: one plain sentence.

Write dates as YYYY-MM-DD. Use null for anything the document does not state; never guess a value."""

DRAFT_SYSTEM = """You write short emails for a household in India: service requests and complaints to sellers, service centres and utilities.

Write a polite, firm email under 180 words. Use only the facts given in the <document> and <issue> tags, such as the invoice date, amount, item and warranty end date; do not invent order numbers or other details. Leave [Your name] and [Your phone] as the only placeholders.

Escalation level 0 is the first request. At level 1 or higher, say that an earlier request got no reply, ask for a response within 7 days, and say the next step is a complaint to the National Consumer Helpline (1915)."""


# ---------- Claude ----------

def _client():
    import anthropic

    return anthropic.Anthropic()


def _parse(content: list[dict], system: str, output_model: type[BaseModel]) -> BaseModel:
    import anthropic

    try:
        response = _client().beta.messages.parse(
            model=config.model(),
            max_tokens=16000,
            system=system,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": content}],
            output_format=output_model,
        )
    except anthropic.AuthenticationError as e:
        raise ExtractionError("Claude rejected the API key.") from e
    except anthropic.RateLimitError as e:
        raise ExtractionError("Claude is rate limited; try again in a minute.") from e
    except anthropic.APIStatusError as e:
        raise ExtractionError(f"Claude API error {e.status_code}.") from e
    except anthropic.APIConnectionError as e:
        raise ExtractionError("Could not reach the Claude API.") from e

    if response.stop_reason == "refusal":
        raise ExtractionError("Claude declined to read this document.")
    if response.stop_reason == "max_tokens" or response.parsed_output is None:
        raise ExtractionError("Claude returned an incomplete answer.")
    return response.parsed_output


def _document_blocks(data: bytes | None, media_type: str | None, text: str | None) -> list[dict]:
    blocks: list[dict] = []
    if data:
        b64 = base64.standard_b64encode(data).decode("ascii")
        if media_type in IMAGE_TYPES:
            blocks.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}})
        elif media_type == PDF_TYPE:
            blocks.append({"type": "document", "source": {"type": "base64", "media_type": PDF_TYPE, "data": b64}})
        else:
            text = (text or "") + "\n" + data.decode("utf-8", errors="ignore")
    if text and text.strip():
        blocks.append({"type": "text", "text": f"<document_text>\n{text.strip()}\n</document_text>"})
    return blocks


def extract_with_claude(data: bytes | None, media_type: str | None, text: str | None) -> Extracted:
    blocks = _document_blocks(data, media_type, text)
    if not blocks:
        raise ExtractionError("Nothing to read: add a file or paste some text.")
    blocks.append({"type": "text", "text": f"Today is {date.today().isoformat()}. Extract the fields from this document."})
    return _parse(blocks, EXTRACT_SYSTEM, Extracted)


# ---------- rule-based fallback ----------

_AMOUNT = re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+(?:\.\d{1,2})?)", re.I)
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DMY_DATE = re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})\b")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_WARRANTY = re.compile(r"(\d+)\s*(year|yr|month)s?\s*warranty|warranty\D{0,20}(\d+)\s*(year|yr|month)", re.I)
_KEYWORDS = [
    ("bill", ("electricity", "bescom", "units consumed", "water bill", "broadband", "postpaid", "bill amount")),
    ("insurance", ("policy", "insurance", "premium")),
    ("id_proof", ("passport", "aadhaar", "driving licence", "driving license", "pan card")),
    ("warranty", ("warranty card",)),
    ("invoice", ("invoice", "tax invoice", "gstin")),
    ("receipt", ("receipt",)),
]
_CATEGORY_WORDS = {
    "electricity": ("electricity", "bescom", "kwh", "units"),
    "water": ("water",),
    "gas": ("gas", "lpg"),
    "phone": ("mobile", "postpaid"),
    "internet": ("broadband", "internet", "fiber", "fibre"),
}


def _dates(text: str) -> list[str]:
    found = []
    for y, m, d in _ISO_DATE.findall(text):
        found.append((int(y), int(m), int(d)))
    for d, m, y in _DMY_DATE.findall(text):
        found.append((int(y), int(m), int(d)))
    out = []
    for y, m, d in found:
        try:
            out.append(date(y, m, d).isoformat())
        except ValueError:
            pass
    return out


def extract_with_rules(text: str | None, file_name: str | None = None) -> Extracted:
    text = text or ""
    low = text.lower()
    kind = next((k for k, words in _KEYWORDS if any(w in low for w in words)), "other")
    if "warranty" in low and kind == "other":
        kind = "warranty"
    category = None
    if kind == "bill":
        category = next((c for c, words in _CATEGORY_WORDS.items() if any(w in low for w in words)), "other")

    amounts = [float(a.replace(",", "")) for a in _AMOUNT.findall(text)]
    dates = sorted(_dates(text))
    emails = _EMAIL.findall(text)

    warranty_months = None
    m = _WARRANTY.search(text)
    if m:
        n, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        warranty_months = int(n) * (1 if unit.lower().startswith("month") else 12)

    first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    title = first_line[:80] or (file_name or "New document")
    return Extracted(
        kind=kind,
        title=title,
        vendor=None,
        item_name=None,
        category=category,
        amount=max(amounts) if amounts else None,
        doc_date=dates[0] if dates else None,
        expiry_date=dates[-1] if len(dates) > 1 else None,
        warranty_months=warranty_months,
        contact_email=emails[0] if emails else None,
        summary="Read without AI; please check the fields.",
    )


# ---------- email drafts ----------

def _template_draft(doc: dict | None, issue: str, level: int) -> Draft:
    item = (doc or {}).get("item_name") or (doc or {}).get("title") or "my purchase"
    facts = []
    if doc:
        if doc.get("doc_date"):
            facts.append(f"purchased/dated {doc['doc_date']}")
        if doc.get("amount"):
            facts.append(f"amount ₹{doc['amount']:,.0f}")
        if doc.get("expiry_date") and doc.get("kind") in ("invoice", "warranty"):
            facts.append(f"warranty valid until {doc['expiry_date']}")
    fact_line = f" ({', '.join(facts)})" if facts else ""
    if level == 0:
        subject = f"Service request: {item}"
        body = (
            f"Dear Sir/Madam,\n\nI am writing about {item}{fact_line}. {issue.strip()}\n\n"
            "Please arrange a service visit or tell me the next steps. The invoice is attached.\n\n"
            "Regards,\n[Your name]\n[Your phone]"
        )
    else:
        subject = f"Second request (unanswered): {item}"
        body = (
            f"Dear Sir/Madam,\n\nI wrote earlier about {item}{fact_line} and have not received a reply. "
            f"The issue: {issue.strip()}\n\nPlease respond within 7 days. If I do not hear back, I will file a "
            "complaint with the National Consumer Helpline (1915).\n\nRegards,\n[Your name]\n[Your phone]"
        )
    return Draft(subject=subject, body=body)


def draft_email(doc: dict | None, issue: str, level: int = 0) -> tuple[Draft, bool]:
    """Return (draft, used_ai). Falls back to a template if Claude is unavailable."""
    if config.ai_enabled():
        facts = {k: v for k, v in (doc or {}).items()
                 if k in ("kind", "title", "vendor", "item_name", "amount", "doc_date", "expiry_date", "warranty_months") and v}
        content = [{
            "type": "text",
            "text": (
                f"<document>\n{json.dumps(facts, ensure_ascii=False)}\n</document>\n"
                f"<issue>\n{issue}\n</issue>\n"
                f"Escalation level: {level}. Today is {date.today().isoformat()}. Write the email."
            ),
        }]
        try:
            return _parse(content, DRAFT_SYSTEM, Draft), True
        except ExtractionError:
            pass
    return _template_draft(doc, issue, level), False
