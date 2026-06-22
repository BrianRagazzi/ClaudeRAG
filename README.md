# ClaudeRAG

A local Retrieval-Augmented Generation (RAG) system that gives Claude semantic search over your documents — running entirely on your machine, with no cloud uploads and no API key required.

Drop files into a folder. Restart Claude. Ask questions.

---

## How it works

```
docs/   →   mcp_server.py (auto-indexes on startup)   →   chroma_db/
                                    ↑
                                 Claude
```

When Claude starts `mcp_server.py`, it immediately:
1. Compares files in `docs/` to what's already indexed in ChromaDB
2. Ingests any new or modified files in a background task (so Claude is responsive immediately)
3. Removes index entries for files that have been deleted from `docs/`

After that, Claude can call `search`, `list_files`, and `indexing_status` against your documents automatically.

**Supported file types:** `.pdf` `.docx` `.txt` `.md` `.html`

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | **3.10 or higher** | Check with `python3 --version`. macOS ships with 3.9 or older — install 3.10+ via [python.org](https://www.python.org/downloads/) or `brew install python@3.12` |
| pip | any recent | Included with Python |
| Disk space | ~600 MB | chromadb + sentence-transformers + the `all-MiniLM-L6-v2` model (~80 MB, downloaded on first use) |
| RAM | ~500 MB | For the embedding model at startup |

> **No API keys required.** Embeddings run entirely on your machine.

---

## Setup

```bash
cd /path/to/ClaudeRAG

# Creates .venv/, installs dependencies, creates docs/ folder
bash setup.sh
```

Run once. Re-running is safe.

---

## Adding documents

Copy or move files into the `docs/` folder:

```
ClaudeRAG/
└── docs/
    ├── product-manual.pdf
    ├── api-reference.docx
    ├── release-notes.md
    └── troubleshooting.html
```

The next time Claude starts, it will pick up any new or changed files automatically. No manual indexing step required.

**To force a full re-index** (e.g. after bulk changes), delete the `chroma_db/` folder and restart Claude.

---

## Connecting to Claude

> **Before editing any config, update all paths** to match where you cloned this repo on your machine. Replace `/Users/username/Documents/Claude/Projects/ClaudeRAG/` with your actual path.

### Claude Desktop app

Open (or create) your Claude desktop config:
```
~/Library/Application Support/Claude/claude_desktop_config.json
```

Merge in the `mcpServers` block from `claude_config.json`:

```json
{
  "mcpServers": {
    "doc-rag": {
      "command": "/Users/username/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python",
      "args": [
        "/Users/username/Documents/Claude/Projects/ClaudeRAG/mcp_server.py"
      ]
    }
  }
}
```

> **Update the paths.** `command` and the first item in `args` must point to your ClaudeRAG install. That's all that's required — documents are read from `docs/` inside the ClaudeRAG folder by default. Add `"env": {"DOCS_PATH": "/path/to/your/docs"}` only if you want to point at a folder elsewhere on your machine.

Restart Claude desktop. The `doc-rag` server will appear in the MCP panel.

---

### Claude Code CLI

> **Update the paths** in the commands below before running them.

**Option A — add globally (available in every project):**

```bash
claude mcp add doc-rag \
  /Users/username/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python \
  -- \
  /Users/username/Documents/Claude/Projects/ClaudeRAG/mcp_server.py
```

**Option B — add to a specific project only:**

Create or edit `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "doc-rag": {
      "command": "/Users/username/Documents/Claude/Projects/ClaudeRAG/.venv/bin/python",
      "args": [
        "/Users/username/Documents/Claude/Projects/ClaudeRAG/mcp_server.py"
      ]
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

The VS Code Claude extension reads MCP servers from `.mcp.json` in your workspace root (same format as Option B above). Place the file at the root of your project and reload the window (`Cmd+Shift+P` → "Developer: Reload Window").

Confirm it loaded by asking Claude: *"What MCP tools do you have available?"*

---

## Using it

Claude searches your documents automatically when relevant. You can also ask directly:

- *"What does the documentation say about authentication?"*
- *"List all the documents you have indexed."*
- *"Is indexing still running?"*

The three available tools are:

| Tool | What it does |
|---|---|
| `search` | Semantic search — returns the most relevant passages with file and page |
| `list_files` | Lists every indexed file and its chunk count |
| `indexing_status` | Reports whether background indexing is still in progress |
| `sync` | Scans docs/ for new or changed files and indexes them in the background |
| `restart` | Restarts the server process; Claude reconnects automatically |

---

## Configuration

All settings are optional. Set them in the `env` block of your MCP config.

| Variable | Default | Description |
|---|---|---|
| `DOCS_PATH` | `./docs` (next to `mcp_server.py`) | Override if your docs live elsewhere on disk |
| `COLLECTION_NAME` | `knowledge_base` | ChromaDB collection name |
| `EMBED_MODEL` | `all-MiniLM-L6-v2` | sentence-transformers model |
| `CHUNK_SIZE` | `400` | Words per chunk |
| `CHUNK_OVERLAP` | `50` | Word overlap between chunks |

`chroma_db/` is always created in the same directory as `mcp_server.py` and is not configurable.

To use a different embedding model, pick any name from [Sentence Transformers](https://www.sbert.net/docs/sentence_transformer/pretrained_models.html). **If you change the model, delete `chroma_db/` and let it re-index** — vectors from different models are not comparable.

---

## Caveats

**File changes are detected by modification time.** If you update a file's content, its chunks will be re-indexed on next startup. If you replace a file without changing its name or mtime (unusual), delete `chroma_db/` to force a full re-index.

**Startup is fast when nothing is new.** If there are many new files, background indexing runs while Claude is already available. The `indexing_status` tool tells you when it's done and `search` results will note if indexing is still in progress.

**PDF and DOCX quality matters.** Digitally-created files extract cleanly. Scanned PDFs (photos of pages) produce garbled or empty text — run them through OCR (e.g. `ocrmypdf`, Adobe Acrobat) first. Complex multi-column layouts and tables may extract imperfectly.

**The database is single-writer.** Don't point two running instances of `mcp_server.py` at the same `chroma_db/`. Multiple read-only queries are fine.

**The docs folder is not watched in real time.** New files are only picked up when `mcp_server.py` restarts (i.e. when Claude restarts or reconnects).

---

## Project layout

```
ClaudeRAG/
├── mcp_server.py       — MCP server + auto-sync (the only script needed)
├── docs/               — drop your documents here
├── chroma_db/          — vector store (auto-created on first run)
├── requirements.txt    — Python dependencies
├── setup.sh            — one-command install
└── claude_config.json  — example MCP config (update paths before use)
```

To move the system to another machine: copy the whole `ClaudeRAG/` directory, run `bash setup.sh`, and update the paths in your MCP config. The `chroma_db/` folder travels with it — no need to re-index.
