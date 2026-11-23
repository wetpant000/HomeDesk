# HomeDesk

**An MCP agent that files your household paperwork, tracks every date, and chases issues until they're resolved.**

Built by **Team Loreal** for **wHACKiest 2026** (Ramaiah Institute of Technology), Track 1: *Make MCP Matter: Less Magic, More Utility*.

> Status: working MVP. Web/phone app, MCP server for Claude Desktop, and AI document reading.

---

## The problem

Household paperwork has no owner, so dates lapse and refunds go unclaimed.

- **Lost documents:** invoices, warranty cards and ID proofs end up spread across email, WhatsApp and paper.
- **Missed deadlines:** warranties, insurance and passport renewals lapse because nobody tracks the dates.
- **Dropped complaints:** refunds and billing errors go unclaimed because chasing them takes weeks of follow-ups.

India's National Consumer Helpline received an average of about **1.1 lakh complaints a month** from April to December 2024 (Rajya Sabha, Unstarred Question 267, 11 Feb 2025).

## The solution

HomeDesk is an MCP (Model Context Protocol) server. It works as a back office for your household, inside Claude Desktop or any other MCP client.

| Module | What it does |
|---|---|
| **Document vault** | Finds the right ID or proof when you need it and warns before it expires |
| **Warranty tracker** | Logs invoices, warranty end dates and service contacts for each appliance |
| **Bill watcher** | Compares each utility bill with past months and flags unusual jumps |
| **Complaint chaser** | Opens a case, drafts the request, follows up and escalates |

### How it works for the user

1. Forward an email or snap a photo of a bill, invoice or receipt.
2. HomeDesk files it and extracts the dates, amounts and vendor.
3. You get a daily digest of what's due.
4. You approve the drafted action, and only then is anything sent.

### Example

> "My AC stopped cooling."
> HomeDesk finds the invoice, confirms the warranty is still valid, drafts the service request with the invoice attached, and sends it once you approve. If nobody replies in 7 days, it drafts an escalation.

## Planned architecture

```
 Inputs: Claude Desktop · Gmail MCP · photo/PDF upload · scheduler
                         │
                         ▼
              HomeDesk MCP server (Python, FastMCP)
              1. Ingest + classify   (Claude vision)
              2. Extract fields      (dates, amounts, vendor)
              3. Store + link        (SQLite: docs, items, cases)
              4. Approval gate       (nothing sent unapproved)
                         │
                         ▼
 Outputs: Google Calendar MCP · Gmail MCP · Playwright browser agent · approval dashboard
```

### Planned MCP tools

| Tool | Purpose |
|---|---|
| `ingest(file \| email \| photo)` | Classify a document and route it to a module |
| `whats_due(days)` | List expiries, refills, renewals and follow-ups |
| `find_document(query)` | Find a document, e.g. "address proof" or "AC invoice" |
| `open_case(issue, related_docs)` | Open a complaint with evidence attached |
| `draft_action(case_id)` | Draft an email or form text and wait for approval |
| `timeline(item)` | Show the full history of an appliance, bill or case |

## Planned tech stack

| Layer | Tool |
|---|---|
| AI / ML | Claude API (vision + text) |
| Agent protocol | MCP Python SDK (FastMCP) |
| Integrations | Gmail and Google Calendar |
| Browser agent | Playwright |
| Database | SQLite + local file store |
| Web / API | FastAPI (Python) |
| Background jobs | Due dates checked on every request in the MVP; APScheduler daily digest planned |
| Frontend | Installable web app (PWA) for phone and desktop; the MVP uses plain HTML/JS served by FastAPI |

## Principles

- **Human in the loop:** nothing is sent or submitted without your approval.
- **Local-first:** documents stay on your machine, and only the text a task needs is sent to the model.
- **Built on an open standard:** works with any MCP client.

## Run the MVP

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                       # install dependencies
uv run homedesk-seed          # optional: load demo data (dates relative to today)
uv run homedesk-web           # open http://127.0.0.1:8000
```

**AI reading.** Set `ANTHROPIC_API_KEY` to have Claude read photos, PDFs and pasted emails and write the complaint emails. Without a key, HomeDesk still works: pasted text is read with simple rules, files are stored, and you fill in or correct the details in the app. Optional settings: `HOMEDESK_MODEL` (default `claude-opus-5-5`), `HOMEDESK_AI=off`, `HOMEDESK_DATA` (where the database and files are kept, default `./data`).

**On your phone.** Run with `HOMEDESK_HOST=0.0.0.0 uv run homedesk-web`, open `http://<your-laptop-ip>:8000` on a phone on the same Wi-Fi, and use the browser's *Add to Home Screen*. The MVP has no login, so only do this on a network you trust.

**In Claude Desktop.** Add HomeDesk as an MCP server in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "homedesk": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/HomeDesk", "homedesk-mcp"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

Then ask things like *"What's due this month?"*, *"File ~/Downloads/ac-invoice.pdf"* or *"My AC stopped cooling, start a complaint."* The MCP tools can draft emails but cannot send them; you approve every draft in the app.

**Tests.** `uv run pytest`

### What the MVP does

| Feature | MVP |
|---|---|
| Add documents | Photo (phone camera), PDF, or pasted email text; Claude extracts the fields; you review and edit |
| Document vault | Search with everyday words ("fridge", "power bill"), timeline per document, original file kept |
| Warranty tracker | Warranty end date worked out from purchase date and length; shown before it runs out |
| Bill watcher | Flags a bill 30% or more above the average of earlier bills of the same kind |
| Complaint chaser | Drafts the email, checks the warranty, waits for your approval, opens it in your mail app, reminds you after 7 days, drafts an escalation |
| Reminders | *What needs attention* list, and a calendar file (`.ics`) with every expiry date |
| MCP server | `whats_due`, `add_document_file`, `add_document_text`, `find_document`, `document_timeline`, `open_case`, `list_cases`, `escalate_case` |

Not in the MVP yet: reading Gmail directly, sending email without your mail app, Google Calendar sync and a login.

## Roadmap

- [x] MVP: photos, PDFs and pasted emails; the four modules on one SQLite store; `whats_due` digest; complaint drafting with approval
- [ ] Gmail and Google Calendar integration; sending approved emails directly
- [ ] Browser agent for complaint portals that have no API
- [ ] Hardware add-ons: ESP32 + current sensor for appliance health, NFC tags on appliances
- [ ] More modules: pantry and medicine tracking

## Team Loreal

- K Vijay Kumar (lead)
- Anil Kumar
- Abhijay Singh
