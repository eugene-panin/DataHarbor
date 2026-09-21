#!/usr/bin/env bash
set -e

echo "================================================================================"
echo "🗑️ DATAHARBOR UNINSTALLATION ENGINE (With Data Preservation Safety)"
echo "================================================================================"

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${INSTALL_DIR}/.venv"
GLOBAL_HARBOR_BIN="${HOME}/.local/bin/harbor"
SYS_HARBOR_BIN="/usr/local/bin/harbor"
USER_BACKUPS_DIR="${HOME}/DataHarbor_Backups"

KEEP_DATA="yes"

# Parse non-interactive flags if passed
for arg in "$@"; do
    case $arg in
        --purge)
            KEEP_DATA="no"
            shift
            ;;
        --keep-data)
            KEEP_DATA="yes"
            shift
            ;;
    esac
done

# Interactive prompt if running in interactive terminal without flags
if [ -t 0 ] && [ "$#" -eq 0 ]; then
    echo "❓ Would you like to create a FULL MASTER BACKUP before uninstalling?"
    echo "   (This saves PostgreSQL vectors, ClickHouse OLAP, S3 media, and custom bundles to ${USER_BACKUPS_DIR})"
    read -p "Save master backup? [Y/n]: " choice
    case "$choice" in
        [nN][oO]|[nN])
            KEEP_DATA="no"
            ;;
        *)
            KEEP_DATA="yes"
            ;;
    esac
fi

# 1. Create Master Backup if requested
if [ "$KEEP_DATA" = "yes" ]; then
    echo ""
    echo "🔒 CREATING MASTER BACKUP TO PRESERVE ALL PLATFORM DATA..."
    mkdir -p "$USER_BACKUPS_DIR"
    # `|| true` here used to swallow any backup failure — including "no harbor
    # CLI found at all" (neither branch below even runs then) — and the
    # script printed "successfully preserved" unconditionally regardless,
    # right before stopping services and deleting the venv. BACKUP_OK now
    # tracks the real outcome instead of assuming success.
    BACKUP_OK="no"
    if [ -f "$GLOBAL_HARBOR_BIN" ]; then
        if "$GLOBAL_HARBOR_BIN" backup create --output "$USER_BACKUPS_DIR"; then
            BACKUP_OK="yes"
        fi
    elif [ -f "$VENV_DIR/bin/harbor" ]; then
        if "$VENV_DIR/bin/harbor" backup create --output "$USER_BACKUPS_DIR"; then
            BACKUP_OK="yes"
        fi
    else
        echo "⚠️  No harbor CLI found (checked ${GLOBAL_HARBOR_BIN} and ${VENV_DIR}/bin/harbor) — cannot create a backup."
    fi

    if [ "$BACKUP_OK" = "yes" ]; then
        echo "✨ All platform data successfully preserved at: ${USER_BACKUPS_DIR}"
    else
        echo "❌ Backup FAILED — nothing was saved to ${USER_BACKUPS_DIR}."
        if [ -t 0 ]; then
            echo "   Continuing will still stop services and delete the venv/CLI — destructive, with no backup."
            read -p "Continue WITHOUT a successful backup? [y/N]: " confirm
            case "$confirm" in
                [yY][eE][sS]|[yY]) ;;
                *)
                    echo "Aborted. Fix the backup error above and re-run, or pass --purge to skip the backup entirely."
                    exit 1
                    ;;
            esac
        else
            echo "   Non-interactive run — aborting rather than deleting the install with no working backup."
            echo "   Fix the backup error above and re-run, or pass --purge to skip the backup entirely."
            exit 1
        fi
    fi
fi

# 2. Stop running services
echo ""
echo "🛑 Stopping DataHarbor running microservices..."
if [ -f "$GLOBAL_HARBOR_BIN" ]; then
    "$GLOBAL_HARBOR_BIN" down || true
elif command -v docker-compose >/dev/null 2>&1; then
    (cd "$INSTALL_DIR" && docker-compose down) || true
fi

# 3. Remove system CLI wrappers
echo "🗑️ Removing system CLI executable wrappers..."
rm -f "$GLOBAL_HARBOR_BIN"
if [ -w "/usr/local/bin" ]; then
    rm -f "$SYS_HARBOR_BIN"
fi

# 4. Remove registered global AI agent skills
echo "🤖 Removing global AI agent skills..."
GLOBAL_SKILLS_DIR="${HOME}/.gemini/config/skills"
rm -rf "${GLOBAL_SKILLS_DIR}/dataharbor-remediator"
rm -rf "${GLOBAL_SKILLS_DIR}/dataharbor-bundle-designer"

# 5. Remove Python virtual environment
if [ -d "$VENV_DIR" ]; then
    echo "📦 Removing Python virtual environment (.venv)..."
    rm -rf "$VENV_DIR"
fi

echo "================================================================================"
echo "✨ DATAHARBOR UNINSTALLATION COMPLETE!"
if [ "$KEEP_DATA" = "yes" ]; then
    echo "📦 Your data backup is safely stored at: ${USER_BACKUPS_DIR}"
fi
echo "================================================================================"
echo ""
