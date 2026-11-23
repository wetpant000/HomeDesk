# HomeDesk

**An MCP agent that files your household paperwork, tracks every date, and chases issues until they're resolved.**

Built by **Team Loreal** for **wHACKiest 2026** (Ramaiah Institute of Technology), Track 1: *Make MCP Matter: Less Magic, More Utility*.

> Status: idea stage. This repository has no code yet.

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
| Background jobs | Python, APScheduler |
| Frontend | Next.js approval dashboard |

## Principles

- **Human in the loop:** nothing is sent or submitted without your approval.
- **Local-first:** documents stay on your machine, and only the text a task needs is sent to the model.
- **Built on an open standard:** works with any MCP client.

## Roadmap

- [ ] MVP: ingest from Gmail, photos and PDFs; the four modules on one SQLite store; `whats_due` digest; complaint drafting with approval
- [ ] Browser agent for complaint portals that have no API
- [ ] Hardware add-ons: ESP32 + current sensor for appliance health, NFC tags on appliances
- [ ] More modules: pantry and medicine tracking

## Team Loreal

- K Vijay Kumar (lead)
- Anil Kumar
- Abhijay Singh
