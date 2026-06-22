#!/usr/bin/env bash
# ClaudeRAG — one-command setup
# Usage: bash setup.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "=== ClaudeRAG Setup ==="
echo "Project: $SCRIPT_DIR"
echo ""

# Create virtual environment
if [ ! -d "$VENV" ]; then
    echo "Creating virtual environment…"
    python3 -m venv "$VENV"
fi

# Activate and install
echo "Installing dependencies (sentence-transformers downloads ~80 MB on first model use)…"
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"

# Create docs folder if it doesn't exist
mkdir -p "$SCRIPT_DIR/docs"

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "  1. Drop your documents into:"
echo "     $SCRIPT_DIR/docs/"
echo "     (Supported: .pdf  .docx  .txt  .md  .html)"
echo ""
echo "  2. Add the MCP server to Claude. Open:"
echo "     ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "     Merge in the contents of: $SCRIPT_DIR/claude_config.json"
echo "     Update the paths to match your machine."
echo ""
echo "  3. Restart Claude — it will index your docs automatically on startup."
echo ""
echo "  To force a full re-index, delete the chroma_db/ folder and restart Claude."
