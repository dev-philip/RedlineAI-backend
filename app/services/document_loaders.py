# app/services/document_loaders.py
from __future__ import annotations

import hashlib
import os
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_community.document_loaders import (
    PyPDFLoader,
    Docx2txtLoader,
    UnstructuredFileLoader,
)
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings


SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt", ".html"}


def compute_sha256(path: str) -> str:
    """Return SHA-256 of a file in a streaming-safe way."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_pdf(path: str, ocr_if_needed: bool) -> List[Document]:
    """
    Try fast text-native PDF first; fallback to Unstructured for scanned PDFs / OCR.
    """
    try:
        return PyPDFLoader(path).load()
    except Exception:
        if ocr_if_needed:
            # Unstructured will OCR if needed (requires tesseract/ocr deps if you want hi-res OCR)
            return UnstructuredFileLoader(path, mode="elements").load()
        return []


def _load_docx(path: str) -> List[Document]:
    return Docx2txtLoader(path).load()


def _load_unstructured(path: str) -> List[Document]:
    # Works for .doc (if antiword installed), .txt, .html, and other miscellaneous formats
    return UnstructuredFileLoader(path, mode="elements").load()


def load_any(
    path: str,
    *,
    base_metadata: Optional[Dict[str, Any]] = None,
    ocr_if_needed: bool = True,
) -> List[Document]:
    """
    Load a file into LangChain Documents with basic metadata attached.

    base_metadata: e.g. {
      "tenant": "acme",
      "doc_type": "Lease",
      "original_filename": "Lease_Office_30p.pdf",
    }
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in SUPPORTED_EXTS:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {sorted(SUPPORTED_EXTS)}")

    if ext == ".pdf":
        docs = _load_pdf(path, ocr_if_needed)
    elif ext == ".docx":
        docs = _load_docx(path)
    else:
        # .doc, .txt, .html, etc.
        docs = _load_unstructured(path)

    meta = base_metadata or {}
    for d in docs:
        # Normalize per-document metadata
        d.metadata = {
            **meta,
            **d.metadata,  # keep loader-provided fields like page/source when present
            "source_file": meta.get("original_filename") or os.path.basename(path),
        }

        # Ensure a page key exists (helps UI even when loader didn't supply it)
        d.metadata.setdefault("page", d.metadata.get("page", None))

    return docs


def split_docs(
    docs: List[Document],
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 120,
) -> List[Document]:
    """
    Split documents into retrieval-friendly chunks and add a chunk_index to metadata.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        add_start_index=True,
        separators=["\n\n", "\n", " ", ""],
    )
    chunks = splitter.split_documents(docs)

    for i, ch in enumerate(chunks):
        ch.metadata["chunk_index"] = i
    return chunks
