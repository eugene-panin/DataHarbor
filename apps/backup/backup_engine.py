import gzip
import json
import logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime
from typing import Any

from apps.db.clickhouse_client import get_clickhouse_client
from apps.db.connection import get_connection_params, get_db_cursor
from apps.storage.s3 import get_s3_client

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUPS_DIR = os.path.join(PROJECT_ROOT, "backups")

# Below this many bytes, a .sql.gz is almost certainly not a real dump (pg_dump
# --clean --if-exists against an *empty* database still emits several hundred
# bytes of DDL preamble/comments) — a strong signal something failed silently.
_MIN_PLAUSIBLE_DUMP_BYTES = 100


def _sql_literal(value: Any) -> str:
    """Render a Python value as a safe SQL literal for an INSERT statement.

    Not repr(): repr(True) is "True" (not valid SQL), repr(a_datetime) is a
    Python constructor call, repr(a_dict) is a Python literal — none of that
    is executable SQL. This also deliberately avoids
    psycopg2.extensions.adapt() used standalone: without being bound to a
    live connection (via .prepare(conn)) it assumes latin-1 and raises
    UnicodeEncodeError on ordinary non-ASCII text (an em dash, a name with
    accents) — caught live while testing this against real scraped data.
    Under Postgres's default standard_conforming_strings=on, only the
    single-quote delimiter needs doubling; backslashes are literal, not an
    escape character, so they must NOT be doubled here.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (bytes, bytearray)):
        return "'\\x" + value.hex() + "'"
    text = json.dumps(value) if isinstance(value, (dict, list)) else str(value)
    return "'" + text.replace("'", "''") + "'"


class MasterBackupEngine:
    """Master Backup Engine capturing PostgreSQL pgvector, ClickHouse OLAP, SeaweedFS S3 objects, and custom bundles.

    Every component method returns a status dict — never just a path — because
    a component can "complete" while producing nothing usable (ClickHouse
    unreachable, S3 empty, pg_dump failing after the output file was already
    opened). ``create_master_backup`` aggregates those into a manifest bundled
    inside the archive and an overall status, so a partial backup is reported
    as partial instead of masquerading as a full one.
    """

    def __init__(self, output_dir: str = BACKUPS_DIR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def backup_postgresql(self, temp_dir: str) -> dict[str, Any]:
        """Dumps PostgreSQL via pg_dump if available, else a data-only Python fallback.

        The fallback captures table *rows* only — no schema, indexes, views, or
        constraints, and restoring it assumes the target tables already exist
        (e.g. via ``init_metrics_db`` / bundle ``db.py`` re-running). It is not
        a substitute for pg_dump; callers should surface ``method`` so the user
        knows which one they got.
        """
        logger.info("Backing up PostgreSQL 16 (relational tables & pgvector embeddings)...")
        pg_backup_path = os.path.join(temp_dir, "postgres_backup.sql.gz")
        host, port, dbname, user, password = get_connection_params()

        pg_dump_bin = shutil.which("pg_dump")
        if pg_dump_bin:
            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password
            cmd = [
                pg_dump_bin,
                "-h", host,
                "-p", str(port),
                "-U", user,
                "-d", dbname,
                "--clean",
                "--if-exists",
                # DataHarbor's own tables all live in `public` (matches the
                # Python fallback's own `table_schema = 'public'` scope below).
                # A whole-database dump tries to LOCK every table in every
                # schema up front — on a Postgres instance shared with other
                # apps/schemas this DB user doesn't own, one denied schema
                # fails the entire dump. Found live: a dev Postgres with an
                # unrelated app's schema caused exactly this.
                "--schema", "public",
            ]
            try:
                with open(pg_backup_path, "wb") as f_out:
                    p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                    p2 = subprocess.Popen(["gzip", "-c"], stdin=p1.stdout, stdout=f_out)
                    p1.stdout.close()
                    p2.communicate()
                    p1_stderr = (p1.stderr.read() or b"").decode("utf-8", "ignore")
                    p1.stderr.close()
                    p1_rc = p1.wait()
                size = os.path.getsize(pg_backup_path) if os.path.exists(pg_backup_path) else 0
                if p1_rc == 0 and p2.returncode == 0 and size >= _MIN_PLAUSIBLE_DUMP_BYTES:
                    logger.info(f"Successfully generated pg_dump backup at: {pg_backup_path}")
                    return {"status": "ok", "method": "pg_dump", "path": pg_backup_path, "bytes": size}
                logger.warning(
                    f"pg_dump did not produce a usable dump (exit {p1_rc}/{p2.returncode}, "
                    f"{size} bytes): {p1_stderr[-500:]}. Falling back to Python DB dump..."
                )
            except Exception as e:
                logger.warning(f"pg_dump execution failed ({e}), falling back to Python DB dump...")

        # Python fallback: data only, via a real DB connection (surfaces a clear
        # exception — not a silently empty backup — if Postgres is unreachable).
        sql_dump_path = os.path.join(temp_dir, "postgres_backup.sql")
        table_row_counts: dict[str, int] = {}
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
            """)
            tables = [r['table_name'] for r in cursor.fetchall()]

            with open(sql_dump_path, "w", encoding="utf-8") as f:
                f.write("-- DataHarbor PostgreSQL data-only backup (Python fallback; NO schema/indexes/views/constraints)\n")
                f.write(f"-- Generated {datetime.now().isoformat()}\n\n")
                for table in tables:
                    cursor.execute(f'SELECT * FROM "{table}";')
                    rows = cursor.fetchall()
                    table_row_counts[table] = len(rows)
                    if not rows:
                        continue
                    f.write(f"-- Table: {table} ({len(rows)} rows)\n")
                    cols = list(rows[0].keys())
                    col_list = ", ".join(f'"{c}"' for c in cols)
                    for row in rows:
                        vals = ", ".join(_sql_literal(row[c]) for c in cols)
                        f.write(f'INSERT INTO "{table}" ({col_list}) VALUES ({vals}) ON CONFLICT DO NOTHING;\n')
                    f.write("\n")

                # Sequence continuity: without this, SERIAL/IDENTITY columns
                # restart at 1 after restore and immediately collide with the
                # just-restored rows' existing ids on the next insert.
                cursor.execute("SELECT sequencename, last_value FROM pg_sequences WHERE schemaname = 'public';")
                sequences = cursor.fetchall()
                if sequences:
                    f.write("-- Sequence positions\n")
                    for seq in sequences:
                        if seq["last_value"] is not None:
                            f.write(f"SELECT setval('\"{seq['sequencename']}\"', {int(seq['last_value'])}, true);\n")

        with open(sql_dump_path, "rb") as f_in, gzip.open(pg_backup_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(sql_dump_path)
        total_rows = sum(table_row_counts.values())
        logger.info(f"Generated Python SQL dump (data only, {total_rows} rows across {len(tables)} tables) at: {pg_backup_path}")
        return {
            "status": "ok" if total_rows > 0 else "empty",
            "method": "python_fallback",
            "path": pg_backup_path,
            "row_counts": table_row_counts,
            "warning": "Data only — schema, indexes, views, and constraints are NOT captured. Install pg_dump for a full backup.",
        }

    def backup_clickhouse(self, temp_dir: str) -> dict[str, Any]:
        """Dumps ClickHouse MergeTree tables and analytics events."""
        logger.info("Backing up ClickHouse OLAP tables and timeseries events...")
        ch_backup_path = os.path.join(temp_dir, "clickhouse_backup.json.gz")
        client = get_clickhouse_client()
        backup_data: dict[str, Any] = {}
        table_errors: dict[str, str] = {}

        if client is None:
            with gzip.open(ch_backup_path, "wt", encoding="utf-8") as f:
                json.dump(backup_data, f)
            return {"status": "failed", "path": ch_backup_path, "detail": "ClickHouse client unavailable."}

        tables = ["clickhouse_scraper_telemetry"]
        for tbl in tables:
            try:
                res = client.query(f"SELECT * FROM {tbl}")
                backup_data[tbl] = {
                    "column_names": res.column_names,
                    "rows": [list(row) for row in res.result_rows],
                }
            except Exception as e:
                logger.warning(f"Could not dump ClickHouse table '{tbl}': {e}")
                table_errors[tbl] = str(e)

        with gzip.open(ch_backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)

        total_rows = sum(len(v["rows"]) for v in backup_data.values())
        if table_errors and not backup_data:
            status = "failed"
        elif not backup_data or total_rows == 0:
            status = "empty"
        else:
            status = "ok"
        logger.info(f"ClickHouse backup: {total_rows} row(s) across {len(backup_data)}/{len(tables)} table(s) at: {ch_backup_path}")
        return {"status": status, "path": ch_backup_path, "row_counts": {k: len(v["rows"]) for k, v in backup_data.items()}, "errors": table_errors}

    def backup_s3_objects(self, temp_dir: str) -> dict[str, Any]:
        """Downloads all raw HTML dumps, videos, and thumbnails from SeaweedFS S3 storage."""
        logger.info("Backing up SeaweedFS S3 objects ('dataharbor-raw' bucket)...")
        s3_temp_dir = os.path.join(temp_dir, "s3_raw")
        os.makedirs(s3_temp_dir, exist_ok=True)
        s3_tar_path = os.path.join(temp_dir, "s3_objects_backup.tar.gz")

        client = get_s3_client()
        bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")
        object_count = 0
        status = "ok"
        detail = None

        try:
            paginator = client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    local_obj_path = os.path.join(s3_temp_dir, key)
                    os.makedirs(os.path.dirname(local_obj_path), exist_ok=True)
                    client.download_file(bucket_name, key, local_obj_path)
                    object_count += 1
            logger.info(f"Downloaded {object_count} S3 object(s) from bucket '{bucket_name}'.")
        except Exception as e:
            logger.warning(f"S3 backup failed: {e}")
            status = "failed"
            detail = str(e)

        with tarfile.open(s3_tar_path, "w:gz") as tar:
            tar.add(s3_temp_dir, arcname="s3_raw")
        shutil.rmtree(s3_temp_dir, ignore_errors=True)
        if status == "ok" and object_count == 0:
            status = "empty"
        return {"status": status, "path": s3_tar_path, "object_count": object_count, "detail": detail}

    def backup_bundles_and_config(self, temp_dir: str) -> dict[str, Any]:
        """Packs custom bundles and .env configuration."""
        logger.info("Backing up custom bundles and platform configuration...")
        bundles_tar_path = os.path.join(temp_dir, "bundles_and_config.tar.gz")
        bundles_src = os.path.join(PROJECT_ROOT, "bundles")
        env_file = os.path.join(PROJECT_ROOT, ".env")

        included = []
        with tarfile.open(bundles_tar_path, "w:gz") as tar:
            if os.path.exists(bundles_src):
                tar.add(bundles_src, arcname="bundles")
                included.append("bundles")
            if os.path.exists(env_file):
                tar.add(env_file, arcname=".env")
                included.append(".env")
        status = "ok" if included else "empty"
        return {"status": status, "path": bundles_tar_path, "included": included}

    def create_master_backup(self) -> dict[str, Any]:
        """Executes full platform backup and returns a result with the archive
        path, a manifest of what was actually captured, and an overall status
        ('complete' | 'partial' | 'failed') — never a bare "it worked" path."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        master_archive_name = f"dataharbor_backup_{timestamp}.tar.gz"
        master_archive_path = os.path.join(self.output_dir, master_archive_name)

        logger.info(f"Starting DataHarbor Master Backup -> {master_archive_path}")
        temp_work_dir = os.path.join(self.output_dir, f"temp_{timestamp}")
        os.makedirs(temp_work_dir, exist_ok=True)

        components: dict[str, Any] = {}
        try:
            components["postgresql"] = self.backup_postgresql(temp_work_dir)
            components["clickhouse"] = self.backup_clickhouse(temp_work_dir)
            components["s3"] = self.backup_s3_objects(temp_work_dir)
            components["bundles_and_config"] = self.backup_bundles_and_config(temp_work_dir)

            manifest = {
                "created_at": datetime.now().isoformat(),
                "components": components,
            }
            manifest_path = os.path.join(temp_work_dir, "backup_manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2, default=str)

            with tarfile.open(master_archive_path, "w:gz") as tar:
                for fname in os.listdir(temp_work_dir):
                    fpath = os.path.join(temp_work_dir, fname)
                    tar.add(fpath, arcname=fname)

            size_mb = os.path.getsize(master_archive_path) / (1024 * 1024)
            statuses = {c["status"] for c in components.values()}
            if statuses == {"ok"}:
                overall = "complete"
            elif "ok" in statuses or "empty" in statuses:
                overall = "partial"
            else:
                overall = "failed"
            logger.info(f"Master Backup finished ({overall}). Archive Size: {size_mb:.2f} MB at {master_archive_path}")
            return {
                "status": overall,
                "archive_path": master_archive_path,
                "size_mb": round(size_mb, 2),
                "components": components,
            }
        finally:
            shutil.rmtree(temp_work_dir, ignore_errors=True)

if __name__ == "__main__":
    engine = MasterBackupEngine()
    result = engine.create_master_backup()
    print(json.dumps(result, indent=2, default=str))
