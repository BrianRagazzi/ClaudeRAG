#!/usr/bin/env python3
"""
ClaudeRAG — MCP Server
Exposes ChromaDB semantic search to Claude via the MCP stdio transport.

Add to Claude desktop config (claude_desktop_config.json):
    "pdf-rag": {
        "command": "python",
        "args": ["/absolute/path/to/ClaudeRAG/mcp_server.py"]
    }

Environment variables (all optional):
    CHROMA_DB_PATH   — path to the ChromaDB directory  (default: ./chroma_db)
    COLLECTION_NAME  — collection name                  (default: pdf_docs)
    EMBED_MODEL      — sentence-transformers model      (default: all-MiniLM-L6-v2)
"""

import asyncio
import logging
import os
from pathlib import Path

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

# ── Configuration ────────────────────────────────────────────────────────────
CHROMA_DB_PATH  = os.getenv("CHROMA_DB_PATH",  str(Path(__file__).parent / "chroma_db"))
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "pdf_docs")
MODEL_NAME      = os.getenv("EMBED_MODEL",     "all-MiniLM-L6-v2")
# ────────────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.WARNING)

# Initialise ChromaDB and the embedding model once at startup
_ef         = SentenceTransformerEmbeddingFunction(model_name=MODEL_NAME)
_chroma     = chromadb.PersistentClient(path=CHROMA_DB_PATH)
_collection = _chroma.get_or_create_collection(COLLECTION_NAME, embedding_function=_ef)

server = Server("pdf-rag")


# ── Tool definitions ─────────────────────────────────────────────────────────

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_documents",
            description=(
                "Semantic search over ingested PDF documentation. "
                "Returns the most relevant passages, each tagged with the source filename and page number. "
                "Use this whenever the user asks about product features, APIs, configuration, or anything "
                "that might be covered in the documentation."
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
            name="list_documents",
            description=(
                "List all PDF documents currently indexed in the knowledge base, "
                "along with a chunk count per file."
            ),
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


# ── Tool implementations ─────────────────────────────────────────────────────

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:

    if name == "search_documents":
        query    = arguments["query"]
        n        = min(int(arguments.get("n_results", 5)), 20)

        results  = _collection.query(query_texts=[query], n_results=n)

        docs      = results["documents"][0]
        metas     = results["metadatas"][0]
        distances = results["distances"][0]

        if not docs:
            return [types.TextContent(
                type="text",
                text="No results found. Make sure you have ingested PDFs with ingest.py.",
            )]

        parts = []
        for i, (doc, meta, dist) in enumerate(zip(docs, metas, distances), 1):
            relevance = max(0.0, 1.0 - dist)  # cosine distance → similarity score
            header = (
                f"[{i}] {meta['filename']}  —  page {meta['page']}  "
                f"(relevance {relevance:.0%})"
            )
            parts.append(f"{header}\n{doc}")

        return [types.TextContent(type="text", text="\n\n---\n\n".join(parts))]

    elif name == "list_documents":
        data = _collection.get(include=["metadatas"])

        if not data["ids"]:
            return [types.TextContent(
                type="text",
                text="No documents indexed yet. Run: python ingest.py /path/to/your/pdfs",
            )]

        from collections import Counter
        counts = Counter(m["filename"] for m in data["metadatas"])
        total  = len(data["ids"])

        lines = [f"Indexed knowledge base — {total} chunks across {len(counts)} document(s):\n"]
        for filename, n in sorted(counts.items()):
            lines.append(f"  • {filename}  ({n} chunks)")

        return [types.TextContent(type="text", text="\n".join(lines))]

    else:
        raise ValueError(f"Unknown tool: {name}")


# ── Entry point ──────────────────────────────────────────────────────────────

async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())
