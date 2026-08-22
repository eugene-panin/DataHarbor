"""Backup / restore commands."""
from __future__ import annotations

import os

import typer

app = typer.Typer(help="Master backup and restore engine", no_args_is_help=True)


@app.command("create")
def create_backup(
    output: str | None = typer.Option(None, "--output", help="Output directory"),
) -> None:
    """Create a full platform master backup archive."""
    from apps.backup.backup_engine import BACKUPS_DIR, MasterBackupEngine

    out_dir = output if output else BACKUPS_DIR
    engine = MasterBackupEngine(output_dir=out_dir)
    archive = engine.create_master_backup()
    print("\n✨ Full Platform Master Backup Created Successfully!")
    print(f"📦 Backup Archive: {archive}\n")


@app.command("restore")
def restore_backup(
    archive_file: str = typer.Argument(..., help="Path to dataharbor_backup_*.tar.gz"),
) -> None:
    """Restore full platform state from a backup archive."""
    from apps.backup.restore_engine import MasterRestoreEngine

    MasterRestoreEngine(archive_file).restore_master_backup()
    print("\n✨ Full Platform Master Restore Completed Successfully!\n")


@app.command("list")
def list_backups() -> None:
    """List existing platform master backup archives."""
    from apps.backup.backup_engine import BACKUPS_DIR

    print("\n📦 DATAHARBOR PLATFORM MASTER BACKUPS:")
    print("=" * 70)
    if os.path.exists(BACKUPS_DIR):
        files = [f for f in os.listdir(BACKUPS_DIR) if f.endswith(".tar.gz")]
        if files:
            for f in sorted(files, reverse=True):
                fpath = os.path.join(BACKUPS_DIR, f)
                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                print(f"• {f} ({size_mb:.2f} MB)")
        else:
            print("No backups found in backups/ directory.")
    else:
        print("No backups directory found.")
    print()
