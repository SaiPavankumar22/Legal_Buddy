from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence

import faiss
import numpy as np
import requests


ROOT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_CONSTITUTION_JSON = ROOT_DIR / "oss_bns" / "constitution_of_india.json"
DEFAULT_DOWNLOAD_DIR = ROOT_DIR / "oss_bns" / "hf_bns_law_rag_db"
DEFAULT_INDEX_PATH = ROOT_DIR / "legal_faiss.index"
DEFAULT_TEXTS_PATH = ROOT_DIR / "legal_texts.npy"
DEFAULT_METADATA_PATH = ROOT_DIR / "legal_metadata.json"
DEFAULT_HF_DATASET = "Hrutik2003/Bns_Law_Rag_DB"

TEXT_EXTENSIONS = {".txt", ".md", ".json", ".jsonl", ".csv"}
DATASET_EXTENSIONS = TEXT_EXTENSIONS | {".sqlite3"}


@dataclass
class SourceRecord:
    text: str
    metadata: Dict[str, Any]


def normalize_text(text: str) -> str:
    cleaned = text.replace("\xa0", " ")
    cleaned = re.sub(r"\r\n?", "\n", cleaned)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return text or "record"


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    text = normalize_text(text)
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= chunk_size:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(paragraph) <= chunk_size:
            current = paragraph
            continue

        start = 0
        while start < len(paragraph):
            end = min(len(paragraph), start + chunk_size)
            if end < len(paragraph):
                split_at = paragraph.rfind(" ", start, end)
                if split_at > start + 200:
                    end = split_at
            piece = paragraph[start:end].strip()
            if piece:
                chunks.append(piece)
            if end >= len(paragraph):
                break
            start = max(end - chunk_overlap, start + 1)
        current = ""

    if current:
        chunks.append(current)

    deduped: List[str] = []
    for item in chunks:
        if not deduped or deduped[-1] != item:
            deduped.append(item)
    return deduped


def build_constitution_records(path: Path, chunk_size: int, chunk_overlap: int) -> List[SourceRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records: List[SourceRecord] = []

    for item in data:
        if not isinstance(item, dict):
            continue
        article = item.get("article")
        title = normalize_text(str(item.get("title") or "Untitled"))
        description = normalize_text(str(item.get("description") or ""))
        if not description:
            continue

        article_label = "Preamble" if article == 0 else f"Article {article}"
        citation = f"Constitution of India, {article_label}"
        if title and title.lower() != "preamble":
            citation = f"{citation} - {title}"

        base_text = f"{citation}\n\n{description}"
        chunks = chunk_text(base_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        for index, chunk in enumerate(chunks, start=1):
            records.append(
                SourceRecord(
                    text=chunk,
                    metadata={
                        "source_type": "constitution",
                        "document": "Constitution of India",
                        "article": article,
                        "title": title,
                        "citation": citation,
                        "source_file": str(path.relative_to(ROOT_DIR)).replace("\\", "/"),
                        "chunk_index": index,
                        "record_id": f"constitution-{article}-{index}",
                    },
                )
            )

    return records


def download_hf_dataset_files(repo_id: str, output_dir: Path, token: Optional[str] = None) -> List[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    api_url = f"https://huggingface.co/api/datasets/{repo_id}"
    response = requests.get(api_url, headers=headers, timeout=30)
    response.raise_for_status()
    payload = response.json()
    siblings = payload.get("siblings") or []

    downloaded: List[Path] = []
    for item in siblings:
        if not isinstance(item, dict):
            continue
        remote_path = str(item.get("rfilename") or "").strip()
        if not remote_path:
            continue
        ext = Path(remote_path).suffix.lower()
        if ext not in DATASET_EXTENSIONS:
            continue

        local_path = output_dir / remote_path
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.exists() and local_path.stat().st_size > 0:
            downloaded.append(local_path)
            continue

        raw_url = f"https://huggingface.co/datasets/{repo_id}/resolve/main/{remote_path}?download=true"
        file_response = requests.get(raw_url, headers=headers, timeout=120)
        file_response.raise_for_status()
        local_path.write_bytes(file_response.content)
        downloaded.append(local_path)

    return downloaded


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="ignore")


def extract_json_records(value: Any, path_hint: str = "") -> Iterator[SourceRecord]:
    if isinstance(value, dict):
        metadata = {
            key: val
            for key, val in value.items()
            if key.lower() in {"source", "title", "act", "section", "chapter", "page", "article", "law", "type"}
            and isinstance(val, (str, int, float))
        }

        text_fields = []
        for key in ("text", "content", "page_content", "description", "body", "chunk", "excerpt"):
            field_value = value.get(key)
            if isinstance(field_value, str) and field_value.strip():
                text_fields.append(field_value)

        if text_fields:
            text = normalize_text("\n\n".join(text_fields))
            if text:
                yield SourceRecord(text=text, metadata=metadata)

        for key, child in value.items():
            child_hint = f"{path_hint}.{key}" if path_hint else str(key)
            yield from extract_json_records(child, child_hint)
        return

    if isinstance(value, list):
        for index, item in enumerate(value):
            child_hint = f"{path_hint}[{index}]"
            yield from extract_json_records(item, child_hint)
        return

    if isinstance(value, str):
        text = normalize_text(value)
        if len(text) >= 80:
            yield SourceRecord(text=text, metadata={})


def parse_dataset_file(path: Path) -> List[SourceRecord]:
    suffix = path.suffix.lower()
    records: List[SourceRecord] = []

    if suffix in {".txt", ".md"}:
        text = normalize_text(read_text_file(path))
        if text:
            records.append(SourceRecord(text=text, metadata={}))
        return records

    if suffix == ".json":
        try:
            payload = json.loads(read_text_file(path))
        except json.JSONDecodeError:
            return records
        return list(extract_json_records(payload, path.name))

    if suffix == ".jsonl":
        for line in read_text_file(path).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.extend(extract_json_records(payload, path.name))
        return records

    if suffix == ".csv":
        reader = csv.DictReader(read_text_file(path).splitlines())
        for row in reader:
            text_parts = [str(value).strip() for value in row.values() if isinstance(value, str) and value.strip()]
            text = normalize_text("\n".join(text_parts))
            if text:
                records.append(SourceRecord(text=text, metadata={key: value for key, value in row.items() if value}))
        return records

    if suffix == ".sqlite3":
        return parse_chroma_sqlite(path)

    return records


def parse_chroma_sqlite(path: Path) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    db = sqlite3.connect(str(path))
    cur = db.cursor()

    rows = cur.execute(
        """
        SELECT
            em.id,
            MAX(CASE WHEN em.key = 'chroma:document' THEN em.string_value END) AS document_text,
            MAX(CASE WHEN em.key = 'source' THEN em.string_value END) AS source,
            MAX(CASE WHEN em.key = 'title' THEN em.string_value END) AS title,
            MAX(CASE WHEN em.key = 'page' THEN em.int_value END) AS page
        FROM embedding_metadata em
        GROUP BY em.id
        ORDER BY em.id
        """
    ).fetchall()
    db.close()

    for row_id, document_text, source, title, page in rows:
        text = normalize_text(str(document_text or ""))
        if not text:
            continue
        source_text = str(source or "").strip()
        title_text = str(title or Path(source_text).stem or "BNS Source").strip()
        metadata: Dict[str, Any] = {
            "source": source_text,
            "title": title_text,
        }
        if page is not None:
            metadata["page"] = int(page)
        records.append(SourceRecord(text=text, metadata=metadata))

    return records


def infer_bns_metadata(path: Path, record: SourceRecord, index: int) -> Dict[str, Any]:
    relative = str(path.relative_to(ROOT_DIR)).replace("\\", "/") if path.is_relative_to(ROOT_DIR) else str(path)
    metadata = dict(record.metadata)
    raw_source = str(metadata.get("source") or "").strip()
    source_path = Path(raw_source) if raw_source else path
    source_name = source_path.stem.replace("_", " ").replace(",", ", ").strip()
    source_name = re.sub(r"\s{2,}", " ", source_name)
    title = str(metadata.get("title") or source_name).replace("_", " ").replace(",", ", ").strip()
    title = re.sub(r"\s{2,}", " ", title)
    act = str(metadata.get("act") or metadata.get("law") or "").strip()
    page = metadata.get("page")

    document = act or title or source_name or "BNS Law Dataset"
    citation = document

    section = metadata.get("section")
    if section not in (None, ""):
        citation = f"{citation}, Section {section}".strip()
    if page not in (None, ""):
        citation = f"{citation} (Page {page})"

    metadata.update(
        {
            "source_type": "bns_dataset",
            "document": document or "BNS Law Dataset",
            "title": title,
            "citation": citation or f"BNS Law Dataset - {path.name}",
            "source_file": relative,
            "chunk_index": index,
            "record_id": f"bns-{slugify(document)}-{page or 'na'}-{index}",
        }
    )
    return metadata


def build_bns_records(dataset_dir: Path, chunk_size: int, chunk_overlap: int) -> List[SourceRecord]:
    records: List[SourceRecord] = []
    has_chroma_sqlite = any(path.name == "chroma.sqlite3" for path in dataset_dir.rglob("chroma.sqlite3"))
    for path in sorted(dataset_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in DATASET_EXTENSIONS:
            continue
        if has_chroma_sqlite and path.suffix.lower() in {".md", ".txt"} and path.name.lower() == "readme.md":
            continue
        parsed_records = parse_dataset_file(path)
        for parsed in parsed_records:
            chunks = chunk_text(parsed.text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            for index, chunk in enumerate(chunks, start=1):
                records.append(
                    SourceRecord(
                        text=chunk,
                        metadata=infer_bns_metadata(path, parsed, index),
                    )
                )
    return records


def get_ollama_embeddings(texts: Sequence[str], model: str, base_url: str, batch_size: int) -> np.ndarray:
    if not model:
        raise ValueError("An Ollama embedding model is required. Example: --ollama-embed-model nomic-embed-text")

    embeddings: List[List[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = list(texts[start:start + batch_size])
        response = requests.post(
            f"{base_url.rstrip('/')}/api/embed",
            json={"model": model, "input": batch},
            timeout=180,
        )
        response.raise_for_status()
        payload = response.json()
        vectors = payload.get("embeddings") or []
        if len(vectors) != len(batch):
            raise RuntimeError(f"Expected {len(batch)} embeddings, received {len(vectors)}.")
        embeddings.extend(vectors)
        print(f"Embedded {min(start + len(batch), len(texts))}/{len(texts)} chunks")

    array = np.array(embeddings, dtype="float32")
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return array / norms


def get_huggingface_embeddings(texts: Sequence[str], model_name: str, batch_size: int) -> np.ndarray:
    if not model_name:
        raise ValueError("A Hugging Face embedding model is required. Example: --hf-embed-model BAAI/bge-large-en-v1.5")

    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is required for Hugging Face embeddings. Install backend requirements first."
        ) from exc

    model = SentenceTransformer(model_name)
    vectors = model.encode(
        list(texts),
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
    )
    return np.array(vectors, dtype="float32")


def save_index(
    records: Sequence[SourceRecord],
    vectors: np.ndarray,
    index_path: Path,
    texts_path: Path,
    metadata_path: Path,
) -> None:
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    faiss.write_index(index, str(index_path))

    np.save(str(texts_path), np.array([record.text for record in records], dtype=object))
    metadata_path.write_text(
        json.dumps([record.metadata for record in records], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a local FAISS legal RAG index.")
    parser.add_argument("--constitution-json", type=Path, default=DEFAULT_CONSTITUTION_JSON)
    parser.add_argument("--hf-dataset", default=DEFAULT_HF_DATASET)
    parser.add_argument("--hf-download-dir", type=Path, default=DEFAULT_DOWNLOAD_DIR)
    parser.add_argument("--hf-token", default=os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_TOKEN"))
    parser.add_argument("--skip-hf-download", action="store_true")
    parser.add_argument("--skip-bns", action="store_true")
    parser.add_argument("--skip-constitution", action="store_true")
    parser.add_argument("--embedding-provider", choices=("ollama", "huggingface"), default="huggingface")
    parser.add_argument("--ollama-base-url", default=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--ollama-embed-model", default=os.getenv("OLLAMA_EMBED_MODEL", ""))
    parser.add_argument("--hf-embed-model", default=os.getenv("HF_EMBED_MODEL", "BAAI/bge-large-en-v1.5"))
    parser.add_argument("--chunk-size", type=int, default=1200)
    parser.add_argument("--chunk-overlap", type=int, default=180)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--index-path", type=Path, default=DEFAULT_INDEX_PATH)
    parser.add_argument("--texts-path", type=Path, default=DEFAULT_TEXTS_PATH)
    parser.add_argument("--metadata-path", type=Path, default=DEFAULT_METADATA_PATH)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    all_records: List[SourceRecord] = []

    if not args.skip_constitution:
        if not args.constitution_json.exists():
            raise FileNotFoundError(f"Constitution JSON not found: {args.constitution_json}")
        constitution_records = build_constitution_records(
            path=args.constitution_json,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        print(f"Loaded {len(constitution_records)} Constitution chunks")
        all_records.extend(constitution_records)

    if not args.skip_bns:
        if not args.skip_hf_download:
            print(f"Downloading text files from Hugging Face dataset {args.hf_dataset} ...")
            downloaded_files = download_hf_dataset_files(
                repo_id=args.hf_dataset,
                output_dir=args.hf_download_dir,
                token=args.hf_token,
            )
            print(f"Prepared {len(downloaded_files)} dataset files in {args.hf_download_dir}")
        if not args.hf_download_dir.exists():
            raise FileNotFoundError(f"Hugging Face dataset directory not found: {args.hf_download_dir}")
        bns_records = build_bns_records(
            dataset_dir=args.hf_download_dir,
            chunk_size=args.chunk_size,
            chunk_overlap=args.chunk_overlap,
        )
        print(f"Loaded {len(bns_records)} BNS dataset chunks")
        all_records.extend(bns_records)

    if not all_records:
        raise RuntimeError("No records were loaded. Nothing to index.")

    texts = [record.text for record in all_records]
    if args.embedding_provider == "huggingface":
        vectors = get_huggingface_embeddings(
            texts=texts,
            model_name=args.hf_embed_model,
            batch_size=args.batch_size,
        )
    else:
        vectors = get_ollama_embeddings(
            texts=texts,
            model=args.ollama_embed_model,
            base_url=args.ollama_base_url,
            batch_size=args.batch_size,
        )
    print(f"Embedding shape: {vectors.shape}")

    save_index(
        records=all_records,
        vectors=vectors,
        index_path=args.index_path,
        texts_path=args.texts_path,
        metadata_path=args.metadata_path,
    )

    source_counts: Dict[str, int] = {}
    for record in all_records:
        key = str(record.metadata.get("source_type") or "unknown")
        source_counts[key] = source_counts.get(key, 0) + 1

    print("Build complete.")
    print(f"Saved index: {args.index_path}")
    print(f"Saved texts: {args.texts_path}")
    print(f"Saved metadata: {args.metadata_path}")
    print(f"Chunks by source: {source_counts}")


if __name__ == "__main__":
    main()
