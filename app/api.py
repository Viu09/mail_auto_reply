from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from app.auth import create_token, verify_credentials, verify_token
from app.services import AccountNotFound, EmailNotFound, EmailService, build_context


# ------------------------------------------------------------------ schemas


class LoginRequest(BaseModel):
    email: str
    password: str


class ReplyUpdate(BaseModel):
    reply: str


class RefineRequest(BaseModel):
    instructions: str


class CategoryRename(BaseModel):
    from_name: str
    to_name: str


class RulePayload(BaseModel):
    account_id: str | None = None
    name: str = ""
    category: str | None = None
    max_priority: str | None = None
    action: str = "flag"
    enabled: bool = True


# ------------------------------------------------------------------ app


@asynccontextmanager
async def lifespan(app: FastAPI):
    context = build_context(build_gmail=True)
    app.state.context = context
    app.state.service = EmailService(context)
    yield


app = FastAPI(title="Mail Auto Reply Dashboard API", lifespan=lifespan)

_origins = [o.strip() for o in os.getenv("FRONTEND_ORIGIN", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


def get_service() -> EmailService:
    return app.state.service


def require_auth(credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> str:
    settings = app.state.context.settings
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentification requise.")
    email = verify_token(credentials.credentials, settings)
    if not email:
        raise HTTPException(status_code=401, detail="Session invalide ou expiree.")
    return email


def require_auth_download(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(default=None),
) -> str:
    """Autorise via l'en-tete Bearer OU un token en query (pour les liens de telechargement natifs)."""
    settings = app.state.context.settings
    candidate = credentials.credentials if credentials and credentials.scheme.lower() == "bearer" else token
    email = verify_token(candidate, settings) if candidate else None
    if not email:
        raise HTTPException(status_code=401, detail="Session invalide ou expiree.")
    return email


# ------------------------------------------------------------------ auth routes


@app.post("/auth/login")
def login(payload: LoginRequest):
    settings = app.state.context.settings
    if not verify_credentials(payload.email, payload.password, settings):
        raise HTTPException(status_code=401, detail="Identifiants invalides.")
    token = create_token(payload.email.strip().lower(), settings)
    return {"token": token, "email": payload.email.strip().lower()}


@app.get("/me")
def me(email: str = Depends(require_auth)):
    return {"email": email}


# ------------------------------------------------------------------ dashboard routes


@app.get("/accounts")
def accounts(email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    return service.account_summary()


@app.get("/emails")
def list_emails(
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
    account: str | None = Query(default=None),
    status: str | None = Query(default=None),
    category: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
):
    return service.list_emails(
        account_id=account,
        status=status,
        category=category,
        priority=priority,
        search=search,
        limit=limit,
        offset=offset,
    )


@app.get("/emails/{email_id}")
def get_email(email_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    try:
        return service.get_email(email_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.patch("/emails/{email_id}/reply")
def update_reply(
    email_id: int,
    payload: ReplyUpdate,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    try:
        return service.update_reply(email_id, payload.reply)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.post("/emails/{email_id}/refine")
def refine(
    email_id: int,
    payload: RefineRequest,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    if not payload.instructions.strip():
        raise HTTPException(status_code=400, detail="Consignes vides.")
    try:
        return service.refine_reply(email_id, payload.instructions)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.post("/emails/{email_id}/send")
def send(email_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    try:
        return service.send(email_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")
    except AccountNotFound as exc:
        raise HTTPException(status_code=400, detail=f"Compte introuvable: {exc}")


@app.post("/emails/{email_id}/reject")
def reject(email_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    try:
        return service.reject(email_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.post("/emails/{email_id}/mark_read")
def mark_read(email_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    try:
        return service.mark_read(email_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.delete("/emails/{email_id}")
def delete_email(email_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    try:
        return service.delete_email(email_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.get("/categories")
def email_categories(
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
    account: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    return service.email_categories(account_id=account, status=status)


@app.post("/categories/rename")
def rename_email_category(
    payload: CategoryRename,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    return service.rename_email_category(payload.from_name, payload.to_name)


@app.post("/emails/{email_id}/attachments")
async def add_attachment(
    email_id: int,
    file: UploadFile,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    content = await file.read()
    try:
        return service.add_outbound_attachment(email_id, file.filename or "piece_jointe", content, file.content_type)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Email introuvable.")


@app.get("/emails/{email_id}/incoming/{file_name}")
def incoming_attachment(
    email_id: int,
    file_name: str,
    email: str = Depends(require_auth_download),
    service: EmailService = Depends(get_service),
):
    try:
        path, mime_type = service.get_incoming_attachment(email_id, file_name)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Piece jointe introuvable.")
    return FileResponse(Path(path), media_type=mime_type, filename=Path(path).name)


# ------------------------------------------------------------------ documents routes


@app.get("/documents")
def list_documents(
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
    account: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
):
    return service.list_documents(
        account_id=account, category=category, search=search, limit=limit, offset=offset
    )


@app.get("/documents/categories")
def document_categories(
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
    account: str | None = Query(default=None),
):
    return service.document_categories(account_id=account)


@app.post("/documents/categories/rename")
def rename_document_category(
    payload: CategoryRename,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    return service.rename_document_category(payload.from_name, payload.to_name)


@app.post("/documents/{document_id}/summary")
def summarize_document(
    document_id: int,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    try:
        return service.summarize_document(document_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Document introuvable.")


@app.get("/documents/{document_id}/download")
def download_document(
    document_id: int,
    email: str = Depends(require_auth_download),
    service: EmailService = Depends(get_service),
):
    try:
        path, mime_type, file_name = service.get_document_download(document_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Document introuvable.")
    return FileResponse(Path(path), media_type=mime_type, filename=file_name)


@app.delete("/documents/{document_id}")
def delete_document(
    document_id: int,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    try:
        return service.delete_document(document_id)
    except EmailNotFound:
        raise HTTPException(status_code=404, detail="Document introuvable.")


# ------------------------------------------------------------------ rules routes


@app.get("/rules")
def list_rules(email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    return service.list_rules()


@app.post("/rules")
def create_rule(payload: RulePayload, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    return service.create_rule(payload.model_dump())


@app.patch("/rules/{rule_id}")
def update_rule(
    rule_id: int,
    payload: RulePayload,
    email: str = Depends(require_auth),
    service: EmailService = Depends(get_service),
):
    updated = service.update_rule(rule_id, payload.model_dump())
    if updated is None:
        raise HTTPException(status_code=404, detail="Regle introuvable.")
    return updated


@app.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, email: str = Depends(require_auth), service: EmailService = Depends(get_service)):
    if not service.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Regle introuvable.")
    return {"ok": True}


@app.get("/health")
def health():
    return {"status": "ok"}
