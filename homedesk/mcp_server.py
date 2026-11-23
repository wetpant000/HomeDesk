"""HomeDesk as an MCP server, for Claude Desktop or any MCP client (stdio).

There is deliberately no tool that approves or sends anything: drafts are
approved by a person in the HomeDesk app.
"""

import mimetypes
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import config, core
from .db import session

mcp = MCPServer(
    "HomeDesk",
    instructions=(
        "HomeDesk keeps a household's paperwork: invoices, bills, warranties, insurance and ID proofs. "
        "Use whats_due to answer 'what needs attention'. Use open_case when something breaks or a bill is wrong; "
        "it only drafts an email. The user approves and sends drafts in the HomeDesk app, never through these tools."
    ),
)

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf", "text/plain"}


def _slim(doc: dict) -> dict:
    keys = ("id", "kind", "title", "vendor", "item_name", "category", "amount", "doc_date",
            "expiry_date", "warranty_months", "contact_email", "needs_review", "anomaly")
    return {k: doc.get(k) for k in keys if doc.get(k) not in (None, "")}


def _slim_case(c: dict) -> dict:
    keys = ("id", "document_id", "issue", "status", "to_email", "subject", "body", "escalation_level", "follow_up_on")
    return {k: c.get(k) for k in keys} | {"approve_in_app": f"{config.app_url()}/#cases"}


@mcp.tool()
def whats_due(days: int = 30) -> list[dict]:
    """List what needs attention in the next `days` days: warranty ends, policy renewals, bill due dates,
    ID proofs expiring within 6 months, drafts waiting for approval, unanswered complaints and unusual bills."""
    with session() as conn:
        return core.whats_due(conn, days)


@mcp.tool()
def add_document_file(path: str) -> dict:
    """File a document from a local file: a photo (jpg, png, webp) or PDF of an invoice, bill, receipt,
    warranty card, insurance policy or ID proof. Returns the extracted fields."""
    p = Path(path).expanduser()
    if not p.is_file():
        raise ValueError(f"No file at {path}")
    media_type = mimetypes.guess_type(p.name)[0]
    if media_type not in ALLOWED_TYPES:
        raise ValueError("Only images, PDFs and plain text files can be added.")
    with session() as conn:
        result = core.ingest(conn, data=p.read_bytes(), filename=p.name, media_type=media_type)
    return {"document": _slim(result["document"]), "used_ai": result["used_ai"], "warning": result["warning"]}


@mcp.tool()
def add_document_text(text: str) -> dict:
    """File a document from pasted text, such as an order-confirmation or bill email."""
    with session() as conn:
        result = core.ingest(conn, text=text)
    return {"document": _slim(result["document"]), "used_ai": result["used_ai"], "warning": result["warning"]}


@mcp.tool()
def find_document(query: str) -> list[dict]:
    """Search filed documents by words in the title, vendor, item, kind or category, e.g. "AC invoice" or "passport"."""
    with session() as conn:
        return [_slim(d) for d in core.find_documents(conn, query)]


@mcp.tool()
def document_timeline(document_id: int) -> dict:
    """Full history of one document: its details, warranty status and every complaint about it."""
    with session() as conn:
        t = core.timeline(conn, document_id)
    return {"document": _slim(t["document"]), "warranty": t["warranty"],
            "cases": [_slim_case(c) for c in t["cases"]], "events": t["events"]}


@mcp.tool()
def open_case(issue: str, document_id: int | None = None) -> dict:
    """Open a complaint or service request and draft the email, linked to a filed document when one applies
    (find it first with find_document). Nothing is sent: the user approves the draft in the HomeDesk app."""
    with session() as conn:
        return _slim_case(core.open_case(conn, issue, document_id))


@mcp.tool()
def list_cases(status: str | None = None) -> list[dict]:
    """List complaint cases. status: awaiting_approval, sent or resolved; omit for all."""
    with session() as conn:
        return [_slim_case(c) for c in core.list_cases(conn, status)]


@mcp.tool()
def escalate_case(case_id: int) -> dict:
    """Draft an escalation for a sent complaint that got no reply. The user approves it in the HomeDesk app."""
    with session() as conn:
        return _slim_case(core.escalate_case(conn, case_id))


def main():
    mcp.run()


if __name__ == "__main__":
    main()
