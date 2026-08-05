#!/bin/bash
# RenPy-Fan-Video - macOS/Linux Launcher

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Installa uv se non presente
if ! command -v uv &>/dev/null; then
    echo "[FanVideo] uv not found. Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
fi

if ! command -v uv &>/dev/null; then
    echo "[FanVideo] ERROR: uv installation failed. Please install uv manually:"
    echo "  https://docs.astral.sh/uv/getting-started/installation/"
    read -p "Press Enter to exit..."
    exit 1
fi

echo "[FanVideo] Starting..."
cd "$SCRIPT_DIR"
export UV_LINK_MODE=copy

# Usa il python di sistema (ha Tcl/Tk) invece del bundled uv
PYTHON_BIN=$(command -v python3 || command -v python)
uv run --python "$PYTHON_BIN" fv_tool.py
