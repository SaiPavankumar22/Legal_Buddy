from __future__ import annotations

import time
import webbrowser
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import settings
from backend.services.document_service import (
    analyze_document_full,
    chat_with_document,
    draft_legal_document,
)
from backend.services.ocr_service import extract_document_payload
from backend.services.ollama_service import check_ollama_health, generate_chat_reply


app = FastAPI(title="Legal Buddy Backend")
FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"
APP_URL = f"http://127.0.0.1:{settings.PORT}"
_frontend_opened = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[Dict[str, Any]]] = None


class DocumentChatRequest(BaseModel):
    document_id: str
    question: str


class DraftRequest(BaseModel):
    document_type: str
    party_a: str
    party_b: str
    key_terms: str
    jurisdiction: str = "India"


def _status_from_error(message: str) -> int:
    text = message.lower()
    if "could not reach ollama" in text:
        return 503
    if "empty response" in text:
        return 502
    if "too large" in text or "maximum size" in text:
        return 413
    return 500


@app.on_event("startup")
def open_frontend_in_browser() -> None:
    global _frontend_opened

    if _frontend_opened or not settings.AUTO_OPEN_FRONTEND:
        return

    _frontend_opened = True
    try:
        webbrowser.open(APP_URL, new=2)
    except Exception:
        pass


@app.get("/api")
def api_root() -> Dict[str, Any]:
    return {
        "name": "Legal Buddy Backend",
        "mode": "local-only",
        "ollamaModel": settings.OLLAMA_CHAT_MODEL,
        "endpoints": ["/api/health", "/api/chat", "/api/scan", "/api/document-chat", "/api/draft"],
    }


@app.get("/api/health")
def health() -> Dict[str, Any]:
    try:
        ollama = check_ollama_health()
        status = "OK"
    except Exception as exc:
        ollama = {
            "baseUrl": settings.OLLAMA_BASE_URL,
            "chatModel": settings.OLLAMA_CHAT_MODEL,
            "embedModel": settings.OLLAMA_EMBED_MODEL or settings.HF_EMBED_MODEL,
            "embeddingProvider": settings.EMBEDDING_PROVIDER,
            "modelLoaded": False,
            "availableModels": [],
            "corpusLoaded": True,
            "faissLoaded": True,
            "warning": str(exc),
        }
        status = "DEGRADED"

    return {
        "status": status,
        "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        "port": settings.PORT,
        "ollama": ollama,
        "endpoints": ["/api/chat", "/api/scan", "/api/document-chat", "/api/draft"],
    }


@app.post("/api/chat")
def chat(req: ChatRequest) -> Dict[str, Any]:
    if not req.message or not isinstance(req.message, str):
        raise HTTPException(status_code=400, detail={"error": "A message is required."})

    try:
        return generate_chat_reply(message=req.message, history=req.history)
    except Exception as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_from_error(detail),
            detail={"error": "Failed to process legal chat request.", "details": detail},
        ) from exc


@app.post("/api/scan")
async def scan(
    document: UploadFile = File(...),
    question: str = Form("Check this document for legal risks."),
) -> Dict[str, Any]:
    start = time.time()

    if document.content_type not in settings.ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail={"error": f"Unsupported file type: {document.content_type}"})

    file_bytes = await document.read()
    if len(file_bytes) > settings.MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": f"File too large. Max size is {settings.MAX_FILE_SIZE_BYTES // (1024 * 1024)} MB."},
        )

    try:
        payload = extract_document_payload(
            file_bytes=file_bytes,
            mime_type=document.content_type or "",
            original_name=document.filename,
        )

        session = analyze_document_full(
            full_text=payload.text,
            filename=document.filename or "document",
            total_pages=payload.total_pages,
            user_prompt=question,
        )

        return {
            "success": True,
            "documentId": session.document_id,
            "fileName": document.filename,
            "summary": session.analysis,
            "ocrMethod": payload.method,
            "pagesAnalyzed": payload.total_pages,
            "totalPages": payload.total_pages,
            "chunkCount": session.chunk_count,
            "truncated": False,
            "pagePreviews": [
                {"pageNumber": page.page_number, "imageDataUrl": page.image_data_url}
                for page in payload.pages
            ],
            "model": settings.OLLAMA_CHAT_MODEL,
            "processingTime": f"{(time.time() - start):.1f}s",
        }
    except Exception as exc:
        detail = str(exc)
        raise HTTPException(
            status_code=_status_from_error(detail),
            detail={"error": detail, "processingTime": f"{(time.time() - start):.1f}s"},
        ) from exc


@app.post("/api/document-chat")
def document_chat(req: DocumentChatRequest) -> Dict[str, Any]:
    if not req.document_id or not req.question:
        raise HTTPException(status_code=400, detail={"error": "document_id and question are required."})

    try:
        answer = chat_with_document(document_id=req.document_id, question=req.question)
        return {"answer": answer}
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={"error": str(exc)},
        ) from exc


@app.post("/api/draft")
def draft(req: DraftRequest) -> Dict[str, Any]:
    if not req.document_type or not req.party_a or not req.party_b:
        raise HTTPException(status_code=400, detail={"error": "document_type, party_a, and party_b are required."})

    try:
        document = draft_legal_document(
            document_type=req.document_type,
            party_a=req.party_a,
            party_b=req.party_b,
            key_terms=req.key_terms or "Standard terms apply.",
            jurisdiction=req.jurisdiction or "India",
        )
        return {"document": document, "documentType": req.document_type}
    except Exception as exc:
        raise HTTPException(
            status_code=_status_from_error(str(exc)),
            detail={"error": str(exc)},
        ) from exc


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
