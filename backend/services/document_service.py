from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from backend import settings
from backend.services.ollama_service import _run_chat, _strip_chat_markdown


CHUNK_SIZE = 3500
SESSION_TTL = 3600  # 1 hour


@dataclass
class DocumentSession:
    document_id: str
    filename: str
    full_text: str
    chunks: List[str]
    analysis: str
    total_pages: int
    chunk_count: int
    created_at: float = field(default_factory=time.time)


_SESSIONS: Dict[str, DocumentSession] = {}


def _cleanup() -> None:
    now = time.time()
    expired = [k for k, v in _SESSIONS.items() if now - v.created_at > SESSION_TTL]
    for k in expired:
        del _SESSIONS[k]


def _split_text(text: str) -> List[str]:
    """Split document into overlapping paragraph-aligned chunks."""
    paragraphs = re.split(r"\n{2,}", text.strip())
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if buf_len + len(para) > CHUNK_SIZE and buf:
            chunks.append("\n\n".join(buf))
            # one-paragraph overlap for context continuity
            overlap = buf[-1]
            buf = [overlap, para]
            buf_len = len(overlap) + len(para)
        else:
            buf.append(para)
            buf_len += len(para)

    if buf:
        chunks.append("\n\n".join(buf))

    return chunks or [text[:CHUNK_SIZE]]


def _analyze_chunk(chunk: str, idx: int, total: int) -> str:
    """Extract brief findings from one document section."""
    reply = _run_chat(
        [
            {
                "role": "system",
                "content": "You are a concise Indian legal risk analyst. Be brief and specific.",
            },
            {
                "role": "user",
                "content": (
                    f"Review section {idx + 1} of {total} from a legal document.\n\n"
                    "Identify briefly:\n"
                    "1) Risky or one-sided clauses\n"
                    "2) Obligations placed on the user\n"
                    "3) Unusual or concerning terms\n"
                    "4) Key dates, fees, or penalties\n\n"
                    "Write 3-6 bullet points only. If nothing notable, write: No major issues.\n\n"
                    f"Document section:\n{chunk}"
                ),
            },
        ],
        temperature=0.1,
    )
    return reply.strip()


def analyze_document_full(
    *,
    full_text: str,
    filename: str,
    total_pages: int,
    user_prompt: str = "",
) -> DocumentSession:
    """
    Map-reduce analysis:
    1. Split full document text into chunks
    2. Analyze each chunk for risks
    3. Synthesize all findings into a structured report
    """
    _cleanup()
    chunks = _split_text(full_text)

    findings: List[str] = []
    for i, chunk in enumerate(chunks):
        finding = _analyze_chunk(chunk, i, len(chunks))
        findings.append(f"Section {i + 1} of {len(chunks)}:\n{finding}")

    combined_findings = "\n\n".join(findings)

    synthesis_prompt = (
        f"{settings.DOCUMENT_ANALYSIS_PROMPT}\n\n"
        f"Document: {filename} ({total_pages} pages, {len(chunks)} sections reviewed)\n"
        f"User request: {user_prompt or 'Check this document for legal risks.'}\n\n"
        "Findings extracted from every section of the document:\n\n"
        f"{combined_findings}\n\n"
        "Now write the complete structured analysis for the full document based on all findings above."
    )

    analysis = _run_chat(
        [
            {
                "role": "system",
                "content": "You are a careful legal document reviewer for Indian users.",
            },
            {"role": "user", "content": synthesis_prompt},
        ],
        temperature=0.1,
    )

    doc_id = str(uuid.uuid4())
    session = DocumentSession(
        document_id=doc_id,
        filename=filename,
        full_text=full_text,
        chunks=chunks,
        analysis=analysis,
        total_pages=total_pages,
        chunk_count=len(chunks),
    )
    _SESSIONS[doc_id] = session
    return session


def chat_with_document(*, document_id: str, question: str) -> str:
    """Answer a question about a previously scanned document using keyword-ranked chunk retrieval."""
    session = _SESSIONS.get(document_id)
    if not session:
        return "This document session has expired. Please re-upload the document to continue asking questions."

    q_words = set(re.findall(r"[a-zA-Z]{3,}", question.lower()))

    scored: List[Tuple[int, int, str]] = []
    for i, chunk in enumerate(session.chunks):
        c_words = set(re.findall(r"[a-zA-Z]{3,}", chunk.lower()))
        scored.append((len(q_words & c_words), i, chunk))

    scored.sort(reverse=True)
    context = "\n\n---\n\n".join(c[2] for c in scored[:3])

    reply = _run_chat(
        [
            {
                "role": "system",
                "content": (
                    f'You are answering questions about the document "{session.filename}". '
                    "Answer only from the document content provided. Use plain text only, no markdown."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Relevant parts of the document:\n\n{context}\n\n"
                    f"Question: {question}\n\n"
                    "Answer clearly and specifically from the document. "
                    "If the answer is not in these sections, say that and suggest re-uploading may help."
                ),
            },
        ],
        temperature=0.2,
    )
    return _strip_chat_markdown(reply)


def draft_legal_document(
    *,
    document_type: str,
    party_a: str,
    party_b: str,
    key_terms: str,
    jurisdiction: str = "India",
) -> str:
    """Generate a professional Indian legal document draft."""
    return _run_chat(
        [
            {
                "role": "system",
                "content": (
                    "You are an experienced Indian legal document drafter. "
                    "Write complete, professional legal documents with proper structure and numbered sections."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Draft a complete {document_type} under Indian law.\n\n"
                    f"Party A: {party_a}\n"
                    f"Party B: {party_b}\n"
                    f"Jurisdiction: {jurisdiction}\n\n"
                    f"Key terms and requirements:\n{key_terms}\n\n"
                    "Include:\n"
                    "- Document title and date placeholder\n"
                    "- Recitals / Whereas clauses\n"
                    "- All standard clauses for this document type\n"
                    "- The specific key terms incorporated above\n"
                    "- Governing law and dispute resolution clause\n"
                    "- Signature blocks for both parties\n\n"
                    "Use proper Indian legal format with numbered sections."
                ),
            },
        ],
        temperature=0.1,
    )


def get_session(document_id: str) -> Optional[DocumentSession]:
    return _SESSIONS.get(document_id)
