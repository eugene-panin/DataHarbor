import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
from typing import Any

from apps.db.clickhouse_client import insert_batch
from apps.db.connection import get_connection_params, get_db_cursor
from apps.storage.s3 import get_s3_client

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _split_sql_statements(sql_content: str) -> list[str]:
    """Split the Python-fallback dump into individual statements.

    Not a naive ``split(";\\n")``: a TEXT/JSONB value can itself legitimately
    contain the two characters ``;`` then newline — found live restoring
    scraped documentation content (devops_knowledge's markdown/code-block
    text does this routinely) — and a blind split breaks mid string literal,
    turning one row into a run of "syntax error" / "unterminated quoted
    string" failures. This tracks whether we're inside a single-quoted
    string (the only quoting this dump format uses, with '' as the escaped
    quote) and only treats ``;\\n`` as a statement boundary outside of one.
    """
    statements: list[str] = []
    buf: list[str] = []
    in_string = False
    i, n = 0, len(sql_content)
    while i < n:
        ch = sql_content[i]
        if in_string:
            if ch == "'":
                if i + 1 < n and sql_content[i + 1] == "'":
                    buf.append("''")
                    i += 2
                    continue
                in_string = False
            buf.append(ch)
            i += 1
            continue
        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";" and i + 1 < n and sql_content[i + 1] == "\n":
            statements.append("".join(buf))
            buf = []
            i += 2
            continue
        buf.append(ch)
        i += 1
    if buf:
        statements.append("".join(buf))
    return statements


class MasterRestoreEngine:
    """Restores full platform state across PostgreSQL, ClickHouse, SeaweedFS S3, and custom bundles.

    Every component method returns a status dict, mirroring MasterBackupEngine —
    a restore step that silently no-ops (missing file, every statement failing)
    must not be indistinguishable from one that actually worked.
    """

    def __init__(self, archive_path: str):
        self.archive_path = archive_path
        if not os.path.exists(self.archive_path):
            raise FileNotFoundError(f"Master backup archive not found at: {self.archive_path}")

    def restore_postgresql(self, temp_dir: str) -> dict[str, Any]:
        """Restores PostgreSQL database schema and pgvector embeddings."""
        logger.info("Restoring PostgreSQL 16 tables and pgvector embeddings...")
        pg_backup_path = os.path.join(temp_dir, "postgres_backup.sql.gz")
        if not os.path.exists(pg_backup_path):
            logger.warning("PostgreSQL dump file missing from backup archive.")
            return {"status": "skipped", "detail": "postgres_backup.sql.gz not present in archive."}

        with gzip.open(pg_backup_path, "rt", encoding="utf-8") as f:
            sql_content = f.read()

        host, port, dbname, user, password = get_connection_params()
        psql_bin = shutil.which("psql")

        if psql_bin:
            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password
            # ON_ERROR_STOP: a failing statement must abort with a non-zero exit
            # code instead of psql silently continuing past it.
            cmd = [psql_bin, "-h", host, "-p", str(port), "-U", user, "-d", dbname, "--set", "ON_ERROR_STOP=1"]
            try:
                p = subprocess.run(cmd, input=sql_content.encode("utf-8"), capture_output=True, env=env)
                if p.returncode == 0:
                    logger.info("Successfully restored PostgreSQL backup via psql.")
                    return {"status": "ok", "method": "psql"}
                err_text = (p.stderr or b"").decode("utf-8", "ignore")
                logger.warning(f"psql restore failed (exit {p.returncode}): {err_text[-800:]}. Falling back to Python SQL execution...")
            except Exception as e:
                logger.warning(f"psql execution failed ({e}), falling back to Python SQL execution...")

        # Python fallback: split on ';\n' (matching how the Python-fallback dump
        # writer terminates each INSERT), then drop only comment LINES from
        # each chunk rather than discarding the whole chunk when it starts with
        # a comment — a "-- Table: X" comment glued to the front of that
        # table's first INSERT (no ';\n' between them) previously made the
        # entire chunk look like "just a comment" and silently dropped that
        # first row.
        ok_count = 0
        failed: list[str] = []
        with get_db_cursor(commit=True) as cursor:
            for raw_stmt in _split_sql_statements(sql_content):
                lines = [ln for ln in raw_stmt.splitlines() if not ln.strip().startswith("--")]
                stmt = "\n".join(lines).strip()
                if not stmt:
                    continue
                # A statement failure poisons the whole Postgres transaction —
                # not just that statement — until it's rolled back; without a
                # savepoint, catching the exception in Python and moving on
                # doesn't help, every remaining statement then fails too with
                # "current transaction is aborted", turning one bad row into a
                # cascade of thousands of false failures (found live: a single
                # pre-existing malformed JSONB value cascaded into ~87k).
                try:
                    cursor.execute("SAVEPOINT restore_stmt;")
                    cursor.execute(stmt)
                    cursor.execute("RELEASE SAVEPOINT restore_stmt;")
                    ok_count += 1
                except Exception as e:
                    failed.append(f"{stmt[:80]}...: {e}")
                    logger.warning(f"Statement failed during Python restore fallback: {e}")
                    try:
                        cursor.execute("ROLLBACK TO SAVEPOINT restore_stmt;")
                    except Exception as rollback_err:
                        logger.error(f"Could not roll back failed statement's savepoint: {rollback_err}")
                        raise
        if failed:
            logger.warning(f"Python PostgreSQL restore: {ok_count} statement(s) OK, {len(failed)} failed.")
        else:
            logger.info(f"Completed Python PostgreSQL SQL restore ({ok_count} statements).")
        return {
            "status": "ok" if ok_count and not failed else ("partial" if ok_count else "failed"),
            "method": "python_fallback",
            "statements_ok": ok_count,
            "statements_failed": len(failed),
            "errors": failed[:10],
        }

    def restore_clickhouse(self, temp_dir: str) -> dict[str, Any]:
        """Restores ClickHouse MergeTree tables and analytics events."""
        logger.info("Restoring ClickHouse OLAP tables and timeseries events...")
        ch_backup_path = os.path.join(temp_dir, "clickhouse_backup.json.gz")
        if not os.path.exists(ch_backup_path):
            logger.warning("ClickHouse dump file missing from backup archive.")
            return {"status": "skipped", "detail": "clickhouse_backup.json.gz not present in archive."}

        with gzip.open(ch_backup_path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        if not data:
            return {"status": "empty", "detail": "Backup contains no ClickHouse rows."}

        restored: dict[str, int] = {}
        errors: dict[str, str] = {}
        for tbl, payload in data.items():
            column_names = payload.get("column_names", [])
            rows = payload.get("rows", [])
            if not (column_names and rows):
                continue
            try:
                insert_batch(tbl, column_names, rows)
                restored[tbl] = len(rows)
                logger.info(f"Restored {len(rows)} rows to ClickHouse table '{tbl}'.")
            except Exception as e:
                errors[tbl] = str(e)
                logger.warning(f"Could not restore ClickHouse table '{tbl}': {e}")

        if errors and not restored:
            status = "failed"
        elif errors:
            status = "partial"
        else:
            status = "ok"
        return {"status": status, "row_counts": restored, "errors": errors}

    def restore_s3_objects(self, temp_dir: str) -> dict[str, Any]:
        """Restores all raw HTML dumps, videos, and thumbnails to SeaweedFS S3 bucket."""
        logger.info("Restoring SeaweedFS S3 objects to bucket 'dataharbor-raw'...")
        s3_tar_path = os.path.join(temp_dir, "s3_objects_backup.tar.gz")
        if not os.path.exists(s3_tar_path):
            logger.warning("S3 tar archive missing from backup archive.")
            return {"status": "skipped", "detail": "s3_objects_backup.tar.gz not present in archive."}

        s3_temp_dir = os.path.join(temp_dir, "s3_raw_extracted")
        with tarfile.open(s3_tar_path, "r:gz") as tar:
            tar.extractall(path=s3_temp_dir, filter="data")

        client = get_s3_client()
        bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")

        try:
            client.create_bucket(Bucket=bucket_name)
        except Exception:
            pass

        s3_root = os.path.join(s3_temp_dir, "s3_raw")
        uploaded = 0
        errors: list[str] = []
        if os.path.exists(s3_root):
            for root, _dirs, files in os.walk(s3_root):
                for f in files:
                    full_local_path = os.path.join(root, f)
                    rel_key = os.path.relpath(full_local_path, s3_root)
                    try:
                        client.upload_file(full_local_path, bucket_name, rel_key)
                        uploaded += 1
                    except Exception as e:
                        errors.append(f"{rel_key}: {e}")
                        logger.warning(f"Could not restore S3 object {rel_key}: {e}")
        logger.info(f"S3 objects restore: {uploaded} uploaded, {len(errors)} failed.")
        if errors and not uploaded:
            status = "failed"
        elif errors:
            status = "partial"
        elif uploaded == 0:
            status = "empty"
        else:
            status = "ok"
        return {"status": status, "uploaded": uploaded, "errors": errors[:10]}

    def restore_bundles_and_config(self, temp_dir: str) -> dict[str, Any]:
        """Restores custom bundles and .env configuration."""
        logger.info("Restoring custom bundles and platform configuration...")
        bundles_tar_path = os.path.join(temp_dir, "bundles_and_config.tar.gz")
        if not os.path.exists(bundles_tar_path):
            return {"status": "skipped", "detail": "bundles_and_config.tar.gz not present in archive."}

        with tarfile.open(bundles_tar_path, "r:gz") as tar:
            names = tar.getnames()
            tar.extractall(path=PROJECT_ROOT, filter="data")
        logger.info("Successfully restored custom bundles and .env file.")
        return {"status": "ok" if names else "empty", "entries": len(names)}

    def restore_master_backup(self) -> dict[str, Any]:
        """Executes full platform restore from master backup archive and returns
        a result with per-component status and an overall
        'complete' | 'partial' | 'failed' verdict — never a bare True."""
        logger.info(f"Starting Master Platform Restore from: {self.archive_path}")
        temp_work_dir = os.path.join(os.path.dirname(self.archive_path), "temp_restore_work")
        os.makedirs(temp_work_dir, exist_ok=True)

        try:
            with tarfile.open(self.archive_path, "r:gz") as tar:
                tar.extractall(path=temp_work_dir, filter="data")

            manifest_path = os.path.join(temp_work_dir, "backup_manifest.json")
            backup_manifest = None
            if os.path.isfile(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        backup_manifest = json.load(f)
                except Exception:
                    backup_manifest = None

            components: dict[str, Any] = {
                "postgresql": self.restore_postgresql(temp_work_dir),
                "clickhouse": self.restore_clickhouse(temp_work_dir),
                "s3": self.restore_s3_objects(temp_work_dir),
                "bundles_and_config": self.restore_bundles_and_config(temp_work_dir),
            }

            statuses = {c["status"] for c in components.values()}
            bad = statuses - {"ok", "skipped", "empty"}
            if not bad and statuses <= {"ok", "skipped"}:
                overall = "complete"
            elif statuses & {"ok", "partial"}:
                overall = "partial"
            else:
                overall = "failed"

            logger.info(f"DataHarbor Master Platform Restore finished: {overall}")
            return {
                "status": overall,
                "backup_manifest": backup_manifest,
                "components": components,
            }
        finally:
            shutil.rmtree(temp_work_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        engine = MasterRestoreEngine(sys.argv[1])
        result = engine.restore_master_backup()
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python apps/backup/restore_engine.py <backup_archive.tar.gz>")
