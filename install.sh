#!/usr/bin/env bash
set -e

echo "================================================================================"
echo "🌊 DATAHARBOR SOLUTION & CLI SYSTEM INSTALLER (uv-based One-Click Setup)"
echo "================================================================================"

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${INSTALL_DIR}/.venv"
cd "$INSTALL_DIR"

echo "📍 Installation Directory: ${INSTALL_DIR}"

# 1. Require uv (industrial Python toolchain)
if ! command -v uv >/dev/null 2>&1; then
    echo "❌ Error: 'uv' is required but not found on PATH."
    echo "Install: https://docs.astral.sh/uv/getting-started/installation/"
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
echo "⚡ Using uv: $(uv --version)"

# 2. Auto-create .env configuration if missing
ENV_FILE="${INSTALL_DIR}/.env"
ENV_EXAMPLE="${INSTALL_DIR}/.env.example"
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "$ENV_EXAMPLE" ]; then
        echo "⚙️ Creating .env configuration from template (.env.example)..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
    else
        echo "⚙️ Initializing default .env file..."
        touch "$ENV_FILE"
    fi
fi

# 3. Create venv + sync dependencies from pyproject.toml / uv.lock
echo "📦 Syncing DataHarbor environment with uv..."
uv venv "$VENV_DIR"
# Prefer lockfile when present; otherwise resolve from pyproject
if [ -f "${INSTALL_DIR}/uv.lock" ]; then
    uv sync --frozen
else
    uv sync
fi

# 4. Create system-wide 'harbor' CLI executable wrapper
BIN_TARGET="/usr/local/bin/harbor"
ALT_BIN_TARGET="${HOME}/.local/bin/harbor"

WRAPPER_CONTENT="#!/usr/bin/env bash
export PYTHONPATH=\"${INSTALL_DIR}:\${PYTHONPATH}\"
exec \"${VENV_DIR}/bin/harbor\" \"\$@\"
"

echo "🔗 Registering system CLI executable 'harbor'..."
if [ -w "/usr/local/bin" ]; then
    echo "$WRAPPER_CONTENT" > "$BIN_TARGET"
    chmod +x "$BIN_TARGET"
    GLOBAL_HARBOR="$BIN_TARGET"
else
    mkdir -p "${HOME}/.local/bin"
    echo "$WRAPPER_CONTENT" > "$ALT_BIN_TARGET"
    chmod +x "$ALT_BIN_TARGET"
    GLOBAL_HARBOR="$ALT_BIN_TARGET"

    SHELL_PROFILE=""
    if [ -n "$ZSH_VERSION" ] || [ -f "${HOME}/.zshrc" ]; then
        SHELL_PROFILE="${HOME}/.zshrc"
    elif [ -f "${HOME}/.bashrc" ]; then
        SHELL_PROFILE="${HOME}/.bashrc"
    elif [ -f "${HOME}/.bash_profile" ]; then
        SHELL_PROFILE="${HOME}/.bash_profile"
    fi

    if [ -n "$SHELL_PROFILE" ]; then
        if ! grep -q '\.local/bin' "$SHELL_PROFILE"; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$SHELL_PROFILE"
            echo "💡 Added ~/.local/bin to your PATH in ${SHELL_PROFILE}"
        fi
    fi
fi

echo "✅ 'harbor' CLI binary linked at: ${GLOBAL_HARBOR}"

# 5. Auto-register AI Agent Skills (Codex, Antigravity, Claude Code, Gemini CLI)
echo "🤖 Auto-registering AI Agent Skills & resolving runtime environment..."
"$GLOBAL_HARBOR" skill install

echo "================================================================================"
echo "🎉 DATAHARBOR INSTALLATION COMPLETE! NO DEVOPS EXPERIENCE NEEDED."
echo "================================================================================"
echo ""
echo "🚀 HOW TO START DATAHARBOR (JUST 1 COMMAND):"
echo "  harbor up"
echo ""
echo "🌐 LOCAL WEB DASHBOARDS (AFTER STARTING):"
echo "  • Dagster ETL Pipelines UI  : http://localhost:3000"
echo "  • Qdrant Vector Search     : http://localhost:6333/dashboard"
echo "  • Grafana Observability    : http://localhost:3001"
echo "  • n8n (optional)           : harbor up --compose --with-n8n"
echo ""
echo "🛠 HELPFUL COMMANDS:"
echo "  harbor status               # Check running microservices status"
echo "  harbor health               # Audit scrapers & run AI self-healing"
echo "  harbor bundle new <name>    # Scaffold a new bundle"
echo "  harbor extractor new <name> # Scaffold a new extractor"
echo "  harbor backup create        # 1-click full platform master backup"
echo "  harbor --help               # Show full interactive CLI help"
echo "================================================================================"
echo ""
