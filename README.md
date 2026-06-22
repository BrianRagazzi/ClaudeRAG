# ClaudeRAG

A local Retrieval-Augmented Generation (RAG) system that lets Claude search and answer questions from your PDF documentation — without uploading files to any cloud service.

PDFs are chunked, embedded locally, and stored in a file-based ChromaDB vector store. A lightweight MCP server exposes the search capability to Claude so it can pull relevant passages on demand.

---

## How it works

```
PDFs  →  ingest.py  →  ChromaDB (chroma_db/)
                              ↑
                        mcp_server.py
                              ↑
                           Claude
```

1. **`ingest.py`** reads every PDF in a folder, splits each page into overlapping text chunks, embeds them with a local sentence-transformers model, and stores them in ChromaDB on disk.
2. **`mcp_server.py`** starts an MCP stdio server that exposes two tools to Claude: `search_documents` and `list_documents`.
3. Claude calls those tools automatically whenever a question might be answered by your docs.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.10 or higher** | Check with `python3 --version`. macOS ships with 3.9 or older — install 3.10+ via [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| pip | any recent | Included with Python |
| Disk space | ~600 MB | chromadb + sentence-transformers library + the `all-MiniLM-L6-v2` model (~80 MB, downloaded once on first ingest) |
| RAM | ~500 MB | For the embedding model during ingest and server startup |

> **No API keys required.** Embeddings run entirely on your machine.

---

## Setup

```bash
cd /Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG

# Create a virtual environment and install all dependencies
bash setup.sh
```

The setup script creates `.venv/` inside the project folder and installs everything. Run it once; re-running it is safe.

---

## Indexing your PDFs

```bash
# Index a folder of PDFs (searches subdirectories recursively)
.venv/bin/python ingest.py /path/to/your/pdfs

# Index a single file
.venv/bin/python ingest.py /path/to/manual.pdf

# Wipe the index and re-index from scratch
.venv/bin/python ingest.py /path/to/your/pdfs --reset

# See what's currently indexed
.venv/bin/python ingest.py --list
```

The first run downloads the embedding model (~80 MB). Subsequent runs use the cached model and are fast. Re-running ingest on the same files is safe — chunks are upserted by ID, so duplicates are not created.

---

## Connecting to Claude

Choose the method that matches how you run Claude.

### Claude Desktop app

Open your Claude desktop config file:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

If the file doesn't exist yet, create it. Merge in the `mcpServers` block from `claude_config.json`:

```json
{
  "mcpServers": {
    "pdf-rag": {
      "command": "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python",
      "args": [
        "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/mcp_server.py"
      ],
      "env": {
        "CHROMA_DB_PATH": "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/chroma_db"
      }
    }
  }
}
```

Restart Claude desktop. The `pdf-rag` server will appear in the MCP panel.

---

### Claude Code CLI

**Option A — add the server globally (available in every project):**

```bash
claude mcp add pdf-rag \
  /Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python \
  -- \
  /Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/mcp_server.py
```

**Option B — add it to a specific project only:**

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "pdf-rag": {
      "command": "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python",
      "args": [
        "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/mcp_server.py"
      ],
      "env": {
        "CHROMA_DB_PATH": "/Users/brianragazzi/Documents/Claude/Projects/ClaudeRAG/chroma_db"
      }
    }
  }
}
```

Verify the server is registered:
```bash
claude mcp list
```

---

### Claude Code in VS Code

The VS Code Claude extension reads MCP servers from `.mcp.json` in your workspace root (same format as Option B above). Place the file at the root of the project you're working in and reload the window (`Cmd+Shift+P` → "Developer: Reload Window").

You can confirm it loaded via the Claude panel's MCP status indicator, or by asking Claude: *"What MCP tools do you have available?"*

---

## Using it

Once connected, Claude searches your docs automatically when relevant. You can also ask directly:

- *"Search the documentation for how to configure authentication."*
- *"What does the API reference say about rate limits?"*
- *"List all the documents you have indexed."*

Claude uses `search_documents` for semantic search and `list_documents` to show what's in the index.

---

## Configuration

All settings can be overridden with environment variables — either in your shell or in the `env` block of your MCP config.

| Variable | Default | Description |
|---|---|---|
| `CHROMA_DB_PATH` | `./chroma_db` | Where ChromaDB stores its data |
| `COLLECTION_NAME` | `pdf_docs` | ChromaDB collection name |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |
| `CHUNK_SIZE` | `400` | Words per chunk (ingest only) |
| `CHUNK_OVERLAP` | `50` | Word overlap between chunks (ingest only) |

To use a different embedding model, set `EMBED_MODEL` to any model name from [Sentence Transformers](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html). Use the **same model** for both ingest and the server, or results will be garbage.

---

## Caveats

**PDF quality matters.** Text extraction works well for digitally-created PDFs. Scanned PDFs (photos of pages) produce garbled or empty text — run them through an OCR tool (e.g., Adobe Acrobat, `ocrmypdf`) first.

**Complex layouts.** Multi-column pages, tables, and heavy formatting can confuse text extraction. If results are poor for a specific document, check what `pypdf` extracts by running `ingest.py --list` and looking at chunk counts — very low counts usually mean extraction failed.

**First-run model download.** `sentence-transformers` downloads the embedding model on first use (~80 MB). This requires internet access once. After that, everything is offline.

**Single writer.** Don't run `ingest.py` at the same time as `mcp_server.py` is actively handling a query against the same collection. ChromaDB is safe for concurrent reads but not concurrent write+read on the same collection.

**Index is not updated automatically.** If you add new PDFs, re-run `ingest.py`. Existing chunks are upserted (not duplicated), so you don't need `--reset` unless you want to remove deleted files from the index.

**Model must match.** If you change `EMBED_MODEL`, you must `--reset` and re-ingest. Vectors from different models are not comparable.

---

## Project layout

```
ClaudeRAG/
├── ingest.py           — PDF → ChromaDB ingestion script
├── mcp_server.py       — MCP stdio server for Claude
├── requirements.txt    — Python dependencies
├── setup.sh            — One-command install script
├── claude_config.json  — Example MCP config snippet
└── chroma_db/          — Vector store (created on first ingest)
```

The `chroma_db/` folder is the entire knowledge base. To move the system to another machine, copy the whole `ClaudeRAG/` directory, run `bash setup.sh` on the new machine, and update the paths in your MCP config.
