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

echo ""
echo "✓ Setup complete!"
echo ""
echo "Next steps:"
echo ""
echo "  1. Index your PDFs:"
echo "     $VENV/bin/python $SCRIPT_DIR/ingest.py /path/to/your/pdfs"
echo ""
echo "  2. Add the MCP server to Claude desktop."
echo "     Open: ~/Library/Application Support/Claude/claude_desktop_config.json"
echo "     Merge in the contents of: $SCRIPT_DIR/claude_config.json"
echo ""
echo "  3. Restart Claude desktop — you're ready to search your docs!"
