from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import faiss
import numpy as np
import requests

from backend import settings


BASE_DIR = Path(__file__).resolve().parents[2]
FAISS_INDEX_PATH = BASE_DIR / "legal_faiss.index"
TEXTS_PATH = BASE_DIR / "legal_texts.npy"
METADATA_PATH = BASE_DIR / "legal_metadata.json"

_FAISS_INDEX: Optional[faiss.Index] = None
_LEGAL_TEXTS: List[str] = []
_LEGAL_METADATA: List[Dict[str, Any]] = []
_TOKENIZED_TEXTS: List[set[str]] = []
_EMBED_DIM: Optional[int] = None
_HF_EMBED_MODEL: Any = None


def _load_legal_corpus() -> None:
    global _FAISS_INDEX, _LEGAL_TEXTS, _LEGAL_METADATA, _TOKENIZED_TEXTS, _EMBED_DIM

    if _LEGAL_TEXTS:
        return

    if TEXTS_PATH.exists():
        texts = np.load(str(TEXTS_PATH), allow_pickle=True).tolist()
        if isinstance(texts, list):
            _LEGAL_TEXTS = [str(text).strip() for text in texts if str(text).strip()]
            _TOKENIZED_TEXTS = [_tokenize(text) for text in _LEGAL_TEXTS]

    if METADATA_PATH.exists():
        try:
            metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
            if isinstance(metadata, list):
                _LEGAL_METADATA = [item if isinstance(item, dict) else {} for item in metadata[: len(_LEGAL_TEXTS)]]
        except (json.JSONDecodeError, OSError):
            _LEGAL_METADATA = []

    if len(_LEGAL_METADATA) < len(_LEGAL_TEXTS):
        _LEGAL_METADATA.extend({} for _ in range(len(_LEGAL_TEXTS) - len(_LEGAL_METADATA)))

    if FAISS_INDEX_PATH.exists():
        _FAISS_INDEX = faiss.read_index(str(FAISS_INDEX_PATH))
        _EMBED_DIM = _FAISS_INDEX.d


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-zA-Z]{3,}", text.lower()))


def _strip_chat_markdown(text: str) -> str:
    """Normalize model output to plain text for the chat UI."""
    s = (text or "").strip()
    if not s:
        return s

    s = re.sub(r"^```[\w-]*\s*\n", "", s, flags=re.MULTILINE)
    s = re.sub(r"\n```\s*$", "", s)

    s = re.sub(r"(?m)^#{1,6}\s+", "", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"`([^`]+)`", r"\1", s)

    for _ in range(12):
        before = s
        s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
        s = re.sub(r"\*([^*]+)\*", r"\1", s)
        s = re.sub(r"__([^_]+)__", r"\1", s)
        if s == before:
            break

    return s.strip()


def _truncate(text: str, limit: int = 1800) -> str:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _metadata_for_index(index: int) -> Dict[str, Any]:
    if 0 <= index < len(_LEGAL_METADATA):
        item = _LEGAL_METADATA[index]
        if isinstance(item, dict):
            return item
    return {}


def _build_source_label(index: int) -> str:
    metadata = _metadata_for_index(index)
    citation = str(metadata.get("citation") or "").strip()
    if citation:
        return citation

    title = str(metadata.get("title") or "").strip()
    document = str(metadata.get("document") or metadata.get("source") or "").strip()
    article = metadata.get("article")
    section = metadata.get("section")

    if article not in (None, "") and title:
        return f"{document or 'Constitution of India'} Article {article}: {title}"
    if section not in (None, "") and title:
        return f"{document or 'Legal source'} Section {section}: {title}"
    if title and document:
        return f"{document}: {title}"
    if title:
        return title
    if document:
        return document
    return f"Legal corpus chunk {index + 1}"


def _ollama_post(path: str, payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}{path}",
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {settings.OLLAMA_BASE_URL}. Start Ollama and make sure the model is available."
        ) from exc

    if not response.ok:
        raise RuntimeError(f"Ollama request failed with {response.status_code}: {response.text[:500]}")

    return response.json()


def _get_hf_embedder() -> Any:
    global _HF_EMBED_MODEL

    if _HF_EMBED_MODEL is not None:
        return _HF_EMBED_MODEL

    if not settings.HF_EMBED_MODEL:
        return None

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "HF_EMBED_MODEL is configured, but sentence-transformers is not installed."
        ) from exc

    _HF_EMBED_MODEL = SentenceTransformer(settings.HF_EMBED_MODEL)
    return _HF_EMBED_MODEL


def check_ollama_health() -> Dict[str, Any]:
    try:
        tags = requests.get(f"{settings.OLLAMA_BASE_URL}/api/tags", timeout=20)
        tags.raise_for_status()
        models = tags.json().get("models", [])
    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not reach Ollama at {settings.OLLAMA_BASE_URL}. Start Ollama before using Legal Buddy."
        ) from exc

    available_models = [model.get("name", "") for model in models if isinstance(model, dict)]
    return {
        "baseUrl": settings.OLLAMA_BASE_URL,
        "chatModel": settings.OLLAMA_CHAT_MODEL,
        "embedModel": settings.OLLAMA_EMBED_MODEL or settings.HF_EMBED_MODEL,
        "embeddingProvider": settings.EMBEDDING_PROVIDER,
        "modelLoaded": settings.OLLAMA_CHAT_MODEL in available_models,
        "availableModels": available_models,
        "corpusLoaded": bool(_LEGAL_TEXTS),
        "faissLoaded": _FAISS_INDEX is not None,
    }


def _embed_query(query: str) -> Optional[np.ndarray]:
    if _FAISS_INDEX is None or _EMBED_DIM is None:
        return None

    if settings.EMBEDDING_PROVIDER == "huggingface":
        embedder = _get_hf_embedder()
        if embedder is None:
            return None
        vector = embedder.encode(
            [f"Represent this sentence for searching relevant passages: {query.strip()}"],
            normalize_embeddings=True,
        )
        array = np.array(vector, dtype="float32")
        if array.shape[1] != _EMBED_DIM:
            return None
        return array

    if not settings.OLLAMA_EMBED_MODEL:
        return None

    response = _ollama_post(
        "/api/embed",
        {"model": settings.OLLAMA_EMBED_MODEL, "input": query},
        timeout=90,
    )
    embeddings = response.get("embeddings") or []
    if not embeddings:
        return None

    vector = np.array(embeddings[0], dtype="float32")
    if vector.shape[0] != _EMBED_DIM:
        return None

    return np.expand_dims(vector, axis=0)


def _retrieve_semantic(query: str, top_k: int) -> List[Tuple[int, float]]:
    if _FAISS_INDEX is None:
        return []

    vector = _embed_query(query)
    if vector is None:
        return []

    distances, indices = _FAISS_INDEX.search(vector, top_k)
    results: List[Tuple[int, float]] = []
    for idx, distance in zip(indices[0], distances[0]):
        if 0 <= idx < len(_LEGAL_TEXTS):
            results.append((int(idx), float(distance)))
    return results


def _retrieve_keyword(query: str, top_k: int) -> List[Tuple[int, float]]:
    query_tokens = _tokenize(query)
    if not query_tokens:
        return []

    scored: List[Tuple[int, float]] = []
    for index, tokens in enumerate(_TOKENIZED_TEXTS):
        overlap = query_tokens.intersection(tokens)
        if overlap:
            scored.append((index, len(overlap) / max(len(query_tokens), 1)))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def retrieve_legal_context(query: str, top_k: Optional[int] = None) -> List[Dict[str, Any]]:
    _load_legal_corpus()
    limit = top_k or settings.LEGAL_CONTEXT_TOP_K
    seen: set[int] = set()
    snippets: List[Dict[str, Any]] = []

    for idx, score in _retrieve_semantic(query, limit):
        if idx in seen:
            continue
        seen.add(idx)
        metadata = _metadata_for_index(idx)
        snippets.append(
            {
                "source": _build_source_label(idx),
                "score": round(score, 4),
                "text": _truncate(_LEGAL_TEXTS[idx]),
                "retrieval": "faiss",
                "metadata": metadata,
            }
        )

    if len(snippets) < limit:
        for idx, score in _retrieve_keyword(query, limit * 2):
            if idx in seen:
                continue
            seen.add(idx)
            metadata = _metadata_for_index(idx)
            snippets.append(
                {
                    "source": _build_source_label(idx),
                    "score": round(score, 4),
                    "text": _truncate(_LEGAL_TEXTS[idx]),
                    "retrieval": "keyword",
                    "metadata": metadata,
                }
            )
            if len(snippets) >= limit:
                break

    return snippets


def _history_to_messages(history: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = []
    for item in history or []:
        role = item.get("role")
        if role not in {"user", "assistant", "model"}:
            continue
        normalized_role = "assistant" if role == "model" else role
        content = item.get("content")
        if not isinstance(content, str):
            parts = item.get("parts")
            if isinstance(parts, list) and parts and isinstance(parts[0], dict):
                content = parts[0].get("text")
        if isinstance(content, str) and content.strip():
            messages.append({"role": normalized_role, "content": content.strip()})
    return messages


def _run_chat(messages: List[Dict[str, Any]], temperature: float = 0.2) -> str:
    response = _ollama_post(
        "/api/chat",
        {
            "model": settings.OLLAMA_CHAT_MODEL,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        },
    )
    message = response.get("message") or {}
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("Ollama returned an empty response.")
    return content.strip()


def generate_chat_reply(*, message: str, history: Optional[List[Dict[str, Any]]]) -> Dict[str, Any]:
    _load_legal_corpus()
    context_chunks = retrieve_legal_context(message, settings.LEGAL_CONTEXT_TOP_K)
    context_block = "\n\n".join(
        f"Passage {index + 1}:\n{item['text']}"
        for index, item in enumerate(context_chunks)
    )

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": settings.LEGAL_CHAT_SYSTEM_PROMPT},
        *_history_to_messages(history),
        {
            "role": "user",
            "content": (
                "User question:\n"
                f"{message.strip()}\n\n"
                "Relevant Indian legal context (plain excerpts only):\n"
                f"{context_block or 'No matching context found in the local legal corpus.'}\n\n"
                "Respond in plain text only (no markdown). Cover: a direct plain-English answer; "
                "relevant law or section references if the context supports them; practical next steps; "
                "a short disclaimer. Do not name passages, chunks, or retrieval methods."
            ),
        },
    ]

    reply = _strip_chat_markdown(_run_chat(messages))
    return {"reply": reply, "sources": context_chunks}


def analyze_document(*, user_prompt: str, text_context: str, image_bytes_list: List[bytes]) -> str:
    if not text_context.strip() and not image_bytes_list:
        raise ValueError("No document content was available for analysis.")

    prompt = (
        f"{settings.DOCUMENT_ANALYSIS_PROMPT}\n\n"
        f"User request:\n{user_prompt.strip() or 'Check this document for harmful clauses and explain it simply.'}\n\n"
        "Document text extracted locally:\n"
        f"{text_context[: settings.MAX_TEXT_CHARS]}\n\n"
        "Please analyze the document carefully."
    )

    message: Dict[str, Any] = {"role": "user", "content": prompt}
    if image_bytes_list:
        message["images"] = [base64.b64encode(image_bytes).decode("utf-8") for image_bytes in image_bytes_list]

    return _run_chat(
        [
            {"role": "system", "content": "You are a careful legal document reviewer focused on Indian users."},
            message,
        ],
        temperature=0.1,
    )


_load_legal_corpus()
