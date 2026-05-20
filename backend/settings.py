import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=ENV_PATH)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


PORT = int(_env("PORT", "4000") or "4000")
AUTO_OPEN_FRONTEND = (_env("AUTO_OPEN_FRONTEND", "true") or "true").lower() in {"1", "true", "yes", "on"}
OLLAMA_BASE_URL = (_env("OLLAMA_BASE_URL", "http://127.0.0.1:11434") or "").rstrip("/")
OLLAMA_CHAT_MODEL = _env("OLLAMA_CHAT_MODEL", "gemma4:e2b")
OLLAMA_EMBED_MODEL = _env("OLLAMA_EMBED_MODEL")
HF_EMBED_MODEL = _env("HF_EMBED_MODEL")
EMBEDDING_PROVIDER = _env(
    "EMBEDDING_PROVIDER",
    "ollama" if OLLAMA_EMBED_MODEL else ("huggingface" if HF_EMBED_MODEL else "ollama"),
)

MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024
MAX_TEXT_CHARS = int(_env("MAX_TEXT_CHARS", "16000") or "16000")
MAX_PDF_PAGES = int(_env("MAX_PDF_PAGES", "8") or "8")
LEGAL_CONTEXT_TOP_K = int(_env("LEGAL_CONTEXT_TOP_K", "4") or "4")
CORS_ORIGINS = [origin.strip() for origin in (_env("CORS_ORIGINS", "*") or "*").split(",") if origin.strip()]

ALLOWED_MIME_TYPES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/webp",
    "image/bmp",
    "image/tiff",
}

LEGAL_CHAT_SYSTEM_PROMPT = """You are Legal Buddy, an Indian legal assistant powered by Gemma running locally through Ollama.

Rules:
- Answer only legal, rights, compliance, contracts, consumer protection, cyber safety, labour, tenancy, civil, criminal, and constitutional questions.
- Ground answers in the provided Indian legal context when it is available.
- If the context is incomplete, say what is missing instead of inventing facts.
- Use simple language for non-lawyers.
- Highlight practical risks, next steps, and relevant acts or sections when present in context.
- Write in plain text only. Do not use markdown: no # headings, no **bold** or *italic*, no bullet lists with leading - or *, no numbered markdown lists, and no ``` code fences.
- Use short paragraphs. If you need a list, write numbered lines like 1) 2) 3) on their own lines.
- Do not mention retrieval systems, embeddings, chunk numbers, vector search, or internal passage labels.
- Never claim to be a lawyer. End with a short disclaimer that this is general legal information, not formal legal advice.
"""

DOCUMENT_ANALYSIS_PROMPT = """You are reviewing a legal or quasi-legal document for a normal Indian user.

Your task:
- Summarize what the document is really asking the user to accept.
- Highlight harmful clauses, red flags, unfair conditions, privacy concerns, auto-renewals, data sharing, penalties, broad permissions, dispute clauses, and cancellation issues.
- Extract important obligations, rights, dates, money-related clauses, and penalties.
- Mention which points are common and which points are risky or unusual.
- If the document appears mostly safe, say that clearly but still list caution points.
- Return valid markdown with short sections and short bullet points, not long paragraphs.
- Use exactly these section headings in this order:
  ## Snapshot
  ## What This Document Says
  ## Risks And Red Flags
  ## Important Obligations, Dates, And Money
  ## What Looks Standard
  ## What The User Should Do Next
- Under each section, use bullets wherever possible.
- If a section has no meaningful items, say "- No major issue found here."
- Finish with 3 practical bullets under "## What The User Should Do Next".
"""
