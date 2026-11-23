"""Web app and JSON API. Serves the installable phone/desktop app from homedesk/web."""

import os

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, core
from .db import connect

app = FastAPI(title="HomeDesk", version="0.1.0")


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@app.exception_handler(core.HomeDeskError)
async def homedesk_error(_: Request, exc: core.HomeDeskError):
    return JSONResponse({"detail": str(exc)}, status_code=exc.status)


class DocumentUpdate(BaseModel):
    kind: str | None = None
    title: str | None = None
    vendor: str | None = None
    item_name: str | None = None
    category: str | None = None
    amount: float | None = None
    doc_date: str | None = None
    expiry_date: str | None = None
    warranty_months: int | None = None
    contact_email: str | None = None
    notes: str | None = None


class CaseCreate(BaseModel):
    issue: str
    document_id: int | None = None


class CaseApproval(BaseModel):
    subject: str | None = None
    body: str | None = None
    to_email: str | None = None


class CaseResolve(BaseModel):
    note: str | None = None


@app.get("/api/status")
def status():
    return {"ai": config.ai_enabled(), "model": config.model() if config.ai_enabled() else None}


@app.get("/api/due")
def due(days: int = 30, conn=Depends(get_conn)):
    return core.whats_due(conn, days)


@app.get("/api/documents")
def documents(q: str | None = None, kind: str | None = None, conn=Depends(get_conn)):
    return core.find_documents(conn, q) if q else core.list_documents(conn, kind)


@app.post("/api/documents/ingest")
async def ingest(file: UploadFile | None = File(None), text: str | None = Form(None), conn=Depends(get_conn)):
    data = await file.read() if file else None
    return core.ingest(conn, data=data or None, filename=file.filename if file else None,
                       media_type=file.content_type if file else None, text=text)


@app.patch("/api/documents/{doc_id}")
def update_document(doc_id: int, body: DocumentUpdate, conn=Depends(get_conn)):
    return core.update_document(conn, doc_id, body.model_dump(exclude_unset=True))


@app.get("/api/documents/{doc_id}/timeline")
def timeline(doc_id: int, conn=Depends(get_conn)):
    return core.timeline(conn, doc_id)


@app.get("/api/documents/{doc_id}/file")
def document_file(doc_id: int, conn=Depends(get_conn)):
    path = core.file_path(core.get_document(conn, doc_id))
    if not path:
        raise core.HomeDeskError("No file stored for this document.", 404)
    return FileResponse(path)


@app.get("/api/cases")
def cases(status: str | None = None, conn=Depends(get_conn)):
    return core.list_cases(conn, status)


@app.post("/api/cases")
def open_case(body: CaseCreate, conn=Depends(get_conn)):
    return core.open_case(conn, body.issue, body.document_id)


@app.post("/api/cases/{case_id}/approve")
def approve(case_id: int, body: CaseApproval, conn=Depends(get_conn)):
    return core.approve_case(conn, case_id, body.subject, body.body, body.to_email)


@app.post("/api/cases/{case_id}/escalate")
def escalate(case_id: int, conn=Depends(get_conn)):
    return core.escalate_case(conn, case_id)


@app.post("/api/cases/{case_id}/resolve")
def resolve(case_id: int, body: CaseResolve, conn=Depends(get_conn)):
    return core.resolve_case(conn, case_id, body.note)


@app.get("/api/calendar.ics")
def calendar(conn=Depends(get_conn)):
    return Response(core.calendar_ics(conn), media_type="text/calendar",
                    headers={"Content-Disposition": 'attachment; filename="homedesk.ics"'})


app.mount("/", StaticFiles(directory=config.WEB_DIR, html=True), name="web")


def main():
    import uvicorn

    host = os.environ.get("HOMEDESK_HOST", "127.0.0.1")
    port = int(os.environ.get("HOMEDESK_PORT", "8000"))
    print(f"HomeDesk running at http://{host}:{port}  (AI reading: {'on' if config.ai_enabled() else 'off'})")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
