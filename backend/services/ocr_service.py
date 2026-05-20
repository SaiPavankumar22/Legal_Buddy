from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import List, Optional

import fitz

from backend import settings


@dataclass
class DocumentPage:
    page_number: int
    image_bytes: bytes
    image_data_url: str
    extracted_text: str


@dataclass
class DocumentPayload:
    text: str
    method: str
    pages: List[DocumentPage]
    total_pages: int
    truncated: bool


def _to_data_url(image_bytes: bytes) -> str:
    return f"data:image/png;base64,{base64.b64encode(image_bytes).decode('utf-8')}"


def _extract_from_pdf(pdf_bytes: bytes) -> DocumentPayload:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)
    if total_pages == 0:
        raise ValueError("The uploaded PDF has no pages.")

    pages: List[DocumentPage] = []
    text_chunks: List[str] = []
    max_pages = min(total_pages, settings.MAX_PDF_PAGES)

    for page_index in range(max_pages):
        page = doc[page_index]
        page_text = (page.get_text("text") or "").strip()
        if page_text:
            text_chunks.append(f"[Page {page_index + 1}]\n{page_text}")

        pix = page.get_pixmap(dpi=144)
        image_bytes = pix.tobytes("png")
        pages.append(
            DocumentPage(
                page_number=page_index + 1,
                image_bytes=image_bytes,
                image_data_url=_to_data_url(image_bytes),
                extracted_text=page_text,
            )
        )

    return DocumentPayload(
        text="\n\n".join(text_chunks).strip(),
        method="pdf-text-layer-and-page-render",
        pages=pages,
        total_pages=total_pages,
        truncated=total_pages > max_pages,
    )


def _extract_from_image(image_bytes: bytes, original_name: Optional[str]) -> DocumentPayload:
    return DocumentPayload(
        text=f"Uploaded image document: {original_name or 'document image'}",
        method="image-upload",
        pages=[
            DocumentPage(
                page_number=1,
                image_bytes=image_bytes,
                image_data_url=_to_data_url(image_bytes),
                extracted_text="",
            )
        ],
        total_pages=1,
        truncated=False,
    )


def extract_document_payload(*, file_bytes: bytes, mime_type: str, original_name: Optional[str]) -> DocumentPayload:
    if not file_bytes:
        raise ValueError("Empty file received.")

    is_pdf = mime_type == "application/pdf" or (original_name or "").lower().endswith(".pdf")
    if is_pdf:
        return _extract_from_pdf(file_bytes)
    return _extract_from_image(file_bytes, original_name)
