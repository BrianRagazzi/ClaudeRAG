#!/usr/bin/env python3
"""
ClaudeRAG — PDF Ingestion Script
Indexes PDF files into ChromaDB so Claude can search them via the MCP server.

Usage:
    python ingest.py /path/to/pdfs           # index a folder of PDFs
    python ingest.py /path/to/file.pdf       # index a single PDF
    python ingest.py /path/to/pdfs --reset   # wipe and re-index
    python ingest.py --list                  # show what's already indexed
"""

import argparse
import os
import sys
from pathlib import Path

# ── Configuration (override with environment variables) ──────────────────────
CHROMA_DB_PATH  = os.getenv("CHROMA_DB_PATH",  str(Path(__file__).parent / "chroma_db"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pdf_docs")
CHUNK_SIZE      = int(os.getenv("CHUNK_SIZE",  "400"))   # words per chunk
CHUNK_OVERLAP   = int(os.getenv("CHUNK_OVERLAP", "50"))  # word overlap between chunks
MODEL_NAME      = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
# ────────────────────────────────────────────────────────────────────────────


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping word-count chunks."""
    words = text.split()
    if not words:
        return []
    step = max(1, chunk_size - overlap)
    chunks = []
    for i in range(0, len(words), step):
        chunk = " ".join(words[i : i + chunk_size])
        if chunk.strip():
            chunks.append(chunk)
    return chunks


def ingest_pdf(pdf_path: Path, collection) -> tuple[int, int]:
    """
    Extract text from every page, chunk it, and upsert into ChromaDB.
    Returns (pages_processed, chunks_added).
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(pdf_path))
    except Exception as e:
        print(f"  ✗  Could not open {pdf_path.name}: {e}", file=sys.stderr)
        return 0, 0

    doc_key = pdf_path.stem  # used as part of the chunk ID
    pages_done = 0
    total_chunks = 0

    for page_num, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue

        text = text.strip()
        if not text:
            continue

        chunks = chunk_text(text)
        if not chunks:
            continue

        ids       = [f"{doc_key}__p{page_num + 1}__c{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "filename": pdf_path.name,
                "doc":      doc_key,
                "page":     page_num + 1,
                "chunk":    i,
            }
            for i in range(len(chunks))
        ]

        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        pages_done  += 1
        total_chunks += len(chunks)

    return pages_done, total_chunks


def get_collection(client):
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
    ef = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
    return client.get_or_create_collection(COLLECTION_NAME, embedding_function=ef)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest PDFs into ChromaDB for ClaudeRAG",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("path", nargs="?", help="PDF file or directory of PDFs to index")
    parser.add_argument("--reset", action="store_true", help="Delete the collection and re-index from scratch")
    parser.add_argument("--list",  action="store_true", help="List indexed documents and exit")
    args = parser.parse_args()

    import chromadb
    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    # ── List mode ────────────────────────────────────────────────────────────
    if args.list:
        try:
            collection = get_collection(client)
            results    = collection.get(include=["metadatas"])
        except Exception as e:
            print(f"Error reading collection: {e}", file=sys.stderr)
            sys.exit(1)

        if not results["ids"]:
            print("No documents indexed yet.")
            return

        from collections import Counter
        counts = Counter(m["filename"] for m in results["metadatas"])
        print(f"Collection '{COLLECTION_NAME}' — {len(results['ids'])} chunks across {len(counts)} file(s):\n")
        for filename, n in sorted(counts.items()):
            print(f"  {filename}  ({n} chunks)")
        return

    # ── Ingest mode ──────────────────────────────────────────────────────────
    if not args.path:
        parser.print_help()
        sys.exit(1)

    source = Path(args.path)
    if not source.exists():
        print(f"Error: '{source}' does not exist.", file=sys.stderr)
        sys.exit(1)

    pdf_files = (
        sorted(source.rglob("*.pdf")) if source.is_dir() else [source]
    )

    if not pdf_files:
        print(f"No PDF files found in '{source}'.", file=sys.stderr)
        sys.exit(1)

    print(f"ChromaDB path : {CHROMA_DB_PATH}")
    print(f"Collection    : {COLLECTION_NAME}")
    print(f"Embed model   : {MODEL_NAME}")
    print(f"Chunk size    : {CHUNK_SIZE} words  (overlap {CHUNK_OVERLAP})")
    print(f"PDFs found    : {len(pdf_files)}")

    if args.reset:
        try:
            client.delete_collection(COLLECTION_NAME)
            print("\nCollection reset (deleted).")
        except Exception:
            pass

    print("\nLoading embedding model (downloads ~80 MB on first run)…")
    collection = get_collection(client)
    print("Model ready.\n")

    grand_chunks = 0
    for pdf_path in pdf_files:
        print(f"  ▶  {pdf_path.name}")
        pages, chunks = ingest_pdf(pdf_path, collection)
        print(f"      {pages} page(s), {chunks} chunk(s)")
        grand_chunks += chunks

    print(f"\n✓ Done — {grand_chunks} chunk(s) indexed.")
    print(f"  Run 'python mcp_server.py' or configure Claude desktop to start searching.")


if __name__ == "__main__":
    main()
