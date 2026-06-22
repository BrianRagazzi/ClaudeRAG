#!/usr/bin/env python3
"""
ClaudeRAG — MCP Server with auto-sync
On startup, compares files in docs/ to the ChromaDB index and ingests
any new or modified files before (or while) serving Claude requests.

Supported file types: .pdf  .txt  .md  .html  .htm  .docx

Folder layout (all relative to this script's directory):
    docs/       — drop your documents here
    chroma_db/  — vector store, created automatically

Environment variables (all optional):
    DOCS_PATH        — override the docs folder location
    COLLECTION_NAME  — ChromaDB collection name  (default: knowledge_base)
    EMBED_MODEL      — sentence-transformers model (default: all-MiniLM-L6-v2)
    CHUNK_SIZE       — words per chunk             (default: 400)
    CHUNK_OVERLAP    — word overlap between chunks (default: 50)
"""

import asyncio
import logging
import os
from collections import Counter
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

# ── Paths ────────────────────────────────────────────────────────────────────
SCRIPT_DIR      = Path(__file__).parent
CHROMA_DB_PATH  = SCRIPT_DIR / "chroma_db"          # always here, not configurable
DOCS_PATH       = Path(os.getenv("DOCS_PATH", SCRIPT_DIR / "docs"))

# ── Tuning ───────────────────────────────────────────────────────────────────
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "knowledge_base")
MODEL_NAME      = os.getenv("EMBED_MODEL",     "all-MiniLM-L6-v2")
CHUNK_SIZE      = int(os.getenv("CHUNK_SIZE",   "400"))
CHUNK_OVERLAP   = int(os.getenv("CHUNK_OVERLAP", "50"))

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".html", ".htm", ".docx"}
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.WARNING)

# Global state shared between the sync task and tool handlers
_collection    = None
_db_error      = None
_sync_running  = False
_sync_message  = "Not started"


# ── Text extraction ──────────────────────────────────────────────────────────

def _extract_pdf(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    pages = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((i + 1, text))
    return pages


def _extract_docx(path: Path) -> list[tuple[int, str]]:
    import docx
    doc = docx.Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    return [(1, text)] if text.strip() else []


def _extract_html(path: Path) -> list[tuple[int, str]]:
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self._skip = False
            self.parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "head"):
                self._skip = True

        def handle_endtag(self, tag):
            if tag in ("script", "style", "head"):
                self._skip = False

        def handle_data(self, data):
            if not self._skip and data.strip():
                self.parts.append(data.strip())

    p = _Extractor()
    p.feed(path.read_text(errors="replace"))
    text = " ".join(p.parts).strip()
    return [(1, text)] if text else []


def extract_text(path: Path) -> list[tuple[int, str]]:
    """Return [(page_number, text), ...] for a document. Non-paged formats use page 1."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            return _extract_pdf(path)
        if ext == ".docx":
            return _extract_docx(path)
        if ext in {".html", ".htm"}:
            return _extract_html(path)
        if ext in {".txt", ".md"}:
            text = path.read_text(errors="replace").strip()
            return [(1, text)] if text else []
    except Exception as e:
        logging.warning(f"Could not extract text from {path.name}: {e}")
    return []


# ── Chunking ─────────────────────────────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(1, CHUNK_SIZE - CHUNK_OVERLAP)
    return [
        " ".join(words[i : i + CHUNK_SIZE])
        for i in range(0, len(words), step)
        if words[i : i + CHUNK_SIZE]
    ]


# ── Index helpers ─────────────────────────────────────────────────────────────

def indexed_file_mtimes(collection) -> dict[str, float]:
    """Return {filename: mtime} for every file currently in the index."""
    data = collection.get(include=["metadatas"])
    seen: dict[str, float] = {}
    for m in data["metadatas"]:
        fname = m["filename"]
        if fname not in seen:
            seen[fname] = float(m.get("mtime", 0))
    return seen


def ingest_file(path: Path, collection) -> int:
    """Ingest one file. Returns number of chunks added."""
    pages = extract_text(path)
    if not pages:
        return 0

    mtime    = path.stat().st_mtime
    doc_key  = path.stem
    total    = 0

    for page_num, text in pages:
        chunks = chunk_text(text)
        if not chunks:
            continue
        ids = [f"{doc_key}__p{page_num}__c{i}" for i in range(len(chunks))]
        metadatas = [
            {
                "filename": path.name,
                "doc":      doc_key,
                "page":     page_num,
                "chunk":    i,
                "mtime":    mtime,
            }
            for i in range(len(chunks))
        ]
        collection.upsert(ids=ids, documents=chunks, metadatas=metadatas)
        total += len(chunks)

    return total


def remove_file_chunks(filename: str, collection) -> int:
    """Delete all chunks belonging to a filename. Returns count removed."""
    results = collection.get(where={"filename": filename})
    if results["ids"]:
        collection.delete(ids=results["ids"])
        return len(results["ids"])
    return 0


# ── Background sync ───────────────────────────────────────────────────────────

async def sync_docs(collection) -> None:
    """
    Compare docs/ to the index and:
      - ingest files that are new or modified (mtime changed)
      - remove chunks for files that no longer exist
    Runs as a background task so the MCP server stays responsive.
    """
    global _sync_running, _sync_message

    _sync_running = True
    _sync_message = "Scanning docs folder…"

    try:
        DOCS_PATH.mkdir(parents=True, exist_ok=True)

        disk_files = {
            f for f in DOCS_PATH.iterdir()
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        }
        disk_map   = {f.name: f for f in disk_files}
        index_mtimes = await asyncio.to_thread(indexed_file_mtimes, collection)

        # Files to remove: indexed but no longer on disk
        orphans = set(index_mtimes) - set(disk_map)
        for name in orphans:
            _sync_message = f"Removing deleted file: {name}"
            await asyncio.to_thread(remove_file_chunks, name, collection)
            logging.warning(f"Removed orphan: {name}")

        # Files to ingest: new on disk, or mtime has changed
        to_ingest = [
            path for name, path in disk_map.items()
            if name not in index_mtimes
            or path.stat().st_mtime > index_mtimes[name]
        ]

        if not to_ingest and not orphans:
            _sync_message = "Index is up to date."
            return

        for path in sorted(to_ingest):
            _sync_message = f"Indexing {path.name}…"
            await asyncio.sleep(0)   # yield so the server can handle requests
            n = await asyncio.to_thread(ingest_file, path, collection)
            logging.warning(f"Indexed {path.name}: {n} chunks")

        _sync_message = (
            f"Sync complete. "
            f"{len(to_ingest)} file(s) indexed, {len(orphans)} removed."
        )

    except Exception as e:
        _sync_message = f"Sync error: {e}"
        logging.error(f"sync_docs failed: {e}")
    finally:
        _sync_running = False


# ── MCP server ────────────────────────────────────────────────────────────────

server = Server("doc-rag")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description=(
                "Semantic search over the indexed document knowledge base. "
                "Returns the most relevant passages with source file and page number. "
                "Use this whenever a question might be answered by the indexed documents."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for",
                    },
                    "n_results": {
                        "type": "integer",
                        "description": "Number of passages to return (default 5, max 20)",
                        "default": 5,
                        "minimum": 1,
                        "maximum": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="list_files",
            description="List all documents currently indexed in the knowledge base.",
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="indexing_status",
            description=(
                "Check whether the background indexing task is still running. "
                "If it is, search results may be incomplete until it finishes."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="sync",
            description=(
                "Scan the docs folder for new or changed files and index them. "
                "Returns immediately — use indexing_status to track progress. "
                "Safe to call at any time; ignored if a sync is already running."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        types.Tool(
            name="restart",
            description=(
                "Restart the MCP server process. Use this after adding many new files "
                "or if the server appears stuck. Claude will reconnect automatically."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    # DB failed to open (e.g. lock held by another process)
    if _collection is None:
        return [types.TextContent(
            type="text",
            text=(
                f"Knowledge base unavailable: {_db_error}\n"
                "Check that no other process has the database locked and restart the server."
            ),
        )]

    if name == "indexing_status":
        status = "running" if _sync_running else "complete"
        return [types.TextContent(
            type="text",
            text=f"Indexing {status}. {_sync_message}",
        )]

    if name == "list_files":
        data = _collection.get(include=["metadatas"])
        if not data["ids"]:
            return [types.TextContent(
                type="text",
                text=(
                    f"No documents indexed yet.\n"
                    f"Drop files into: {DOCS_PATH}\n"
                    f"Supported formats: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                ),
            )]
        counts = Counter(m["filename"] for m in data["metadatas"])
        total  = len(data["ids"])
        lines  = [
            f"Indexed knowledge base — {total} chunks across {len(counts)} file(s):",
            *(f"  • {fname}  ({n} chunks)" for fname, n in sorted(counts.items())),
        ]
        if _sync_running:
            lines.append(f"\n⏳ Indexing in progress: {_sync_message}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    if name == "search":
        query = arguments["query"]
        n     = min(int(arguments.get("n_results", 5)), 20)

        try:
            results = await asyncio.to_thread(
                _collection.query,
                query_texts=[query],
                n_results=n,
            )
        except Exception as e:
            return [types.TextContent(
                type="text",
                text=f"Search failed: {e}",
            )]

        docs      = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        if not docs:
            msg = "No results found."
            if _sync_running:
                msg += f" Indexing is still in progress ({_sync_message}) — try again shortly."
            else:
                msg += f" Make sure documents are in: {DOCS_PATH}"
            return [types.TextContent(type="text", text=msg)]

        parts = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            relevance = max(0.0, 1.0 - dist)
            header    = f"[{i}] {meta['filename']}  —  page {meta['page']}  (relevance {relevance:.0%})"
            parts.append(f"{header}\n{doc}")

        text = "\n\n---\n\n".join(parts)
        if _sync_running:
            text += f"\n\n⏳ Note: indexing is still in progress ({_sync_message}). Results may be incomplete."
        return [types.TextContent(type="text", text=text)]

    if name == "sync":
        if _sync_running:
            return [types.TextContent(
                type="text",
                text=f"Sync already in progress: {_sync_message}",
            )]
        asyncio.ensure_future(sync_docs(_collection))
        return [types.TextContent(
            type="text",
            text=f"Sync started. Scanning {DOCS_PATH} for new or changed files.\nCall indexing_status to track progress.",
        )]

    if name == "restart":
        import os, sys
        # Replace this process with a fresh copy — Claude will reconnect automatically.
        logging.warning("Restarting server on request.")
        os.execv(sys.executable, [sys.executable] + sys.argv)
        # execv does not return; the line below is unreachable but satisfies type checkers
        return []  # pragma: no cover

    raise ValueError(f"Unknown tool: {name}")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    global _collection, _db_error

    # Open ChromaDB — fail gracefully so the MCP handshake can still complete
    try:
        ef          = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
        client      = chromadb.PersistentClient(path=str(CHROMA_DB_PATH))
        _collection = client.get_or_create_collection(COLLECTION_NAME, embedding_function=ef)
    except Exception as e:
        _db_error = str(e)
        logging.error(f"Failed to open ChromaDB: {e}")

    # Launch background sync (non-blocking — server starts immediately)
    if _collection is not None:
        asyncio.ensure_future(sync_docs(_collection))

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
