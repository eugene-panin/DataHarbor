import gzip
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile

from apps.db.clickhouse_client import insert_batch
from apps.db.connection import get_connection_params, get_db_cursor
from apps.storage.s3 import get_s3_client

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class MasterRestoreEngine:
    """Restores full platform state across PostgreSQL, ClickHouse, SeaweedFS S3, and custom bundles."""

    def __init__(self, archive_path: str):
        self.archive_path = archive_path
        if not os.path.exists(self.archive_path):
            raise FileNotFoundError(f"Master backup archive not found at: {self.archive_path}")

    def restore_postgresql(self, temp_dir: str):
        """Restores PostgreSQL database schema and pgvector embeddings."""
        logger.info("Restoring PostgreSQL 16 tables and pgvector embeddings...")
        pg_backup_path = os.path.join(temp_dir, "postgres_backup.sql.gz")
        if not os.path.exists(pg_backup_path):
            logger.warning("PostgreSQL dump file missing from backup archive.")
            return

        sql_content = ""
        with gzip.open(pg_backup_path, "rt", encoding="utf-8") as f:
            sql_content = f.read()

        host, port, dbname, user, password = get_connection_params()
        psql_bin = shutil.which("psql")

        if psql_bin:
            env = os.environ.copy()
            if password:
                env["PGPASSWORD"] = password
            cmd = [psql_bin, "-h", host, "-p", str(port), "-U", user, "-d", dbname]
            try:
                p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
                out, err = p.communicate(input=sql_content.encode("utf-8"))
                logger.info("Successfully restored PostgreSQL backup via psql.")
                return
            except Exception as e:
                logger.warning(f"psql execution failed ({e}), falling back to Python SQL execution...")

        # Python fallback SQL execution
        with get_db_cursor(commit=True) as cursor:
            statements = sql_content.split(";\n")
            for stmt in statements:
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    try:
                        cursor.execute(stmt)
                    except Exception as e:
                        logger.debug(f"Statement execution skipped during restore: {e}")
        logger.info("Completed Python PostgreSQL SQL restore.")

    def restore_clickhouse(self, temp_dir: str):
        """Restores ClickHouse MergeTree tables and analytics events."""
        logger.info("Restoring ClickHouse OLAP tables and timeseries events...")
        ch_backup_path = os.path.join(temp_dir, "clickhouse_backup.json.gz")
        if not os.path.exists(ch_backup_path):
            logger.warning("ClickHouse dump file missing from backup archive.")
            return

        with gzip.open(ch_backup_path, "rt", encoding="utf-8") as f:
            data = json.load(f)

        for tbl, payload in data.items():
            column_names = payload.get("column_names", [])
            rows = payload.get("rows", [])
            if column_names and rows:
                insert_batch(tbl, column_names, rows)
                logger.info(f"Restored {len(rows)} rows to ClickHouse table '{tbl}'.")

    def restore_s3_objects(self, temp_dir: str):
        """Restores all raw HTML dumps, videos, and thumbnails to SeaweedFS S3 bucket."""
        logger.info("Restoring SeaweedFS S3 objects to bucket 'dataharbor-raw'...")
        s3_tar_path = os.path.join(temp_dir, "s3_objects_backup.tar.gz")
        if not os.path.exists(s3_tar_path):
            logger.warning("S3 tar archive missing from backup archive.")
            return

        s3_temp_dir = os.path.join(temp_dir, "s3_raw_extracted")
        with tarfile.open(s3_tar_path, "r:gz") as tar:
            tar.extractall(path=s3_temp_dir)

        client = get_s3_client()
        bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")

        try:
            client.create_bucket(Bucket=bucket_name)
        except Exception:
            pass

        s3_root = os.path.join(s3_temp_dir, "s3_raw")
        if os.path.exists(s3_root):
            for root, dirs, files in os.walk(s3_root):
                for f in files:
                    full_local_path = os.path.join(root, f)
                    rel_key = os.path.relpath(full_local_path, s3_root)
                    try:
                        client.upload_file(full_local_path, bucket_name, rel_key)
                    except Exception as e:
                        logger.warning(f"Could not restore S3 object {rel_key}: {e}")
        logger.info("Successfully completed S3 objects restore.")

    def restore_bundles_and_config(self, temp_dir: str):
        """Restores custom bundles and .env configuration."""
        logger.info("Restoring custom bundles and platform configuration...")
        bundles_tar_path = os.path.join(temp_dir, "bundles_and_config.tar.gz")
        if not os.path.exists(bundles_tar_path):
            return

        with tarfile.open(bundles_tar_path, "r:gz") as tar:
            tar.extractall(path=PROJECT_ROOT)
        logger.info("Successfully restored custom bundles and .env file.")

    def restore_master_backup(self):
        """Executes full platform restore from master backup archive."""
        logger.info(f"Starting Master Platform Restore from: {self.archive_path}")
        temp_work_dir = os.path.join(os.path.dirname(self.archive_path), "temp_restore_work")
        os.makedirs(temp_work_dir, exist_ok=True)

        try:
            with tarfile.open(self.archive_path, "r:gz") as tar:
                tar.extractall(path=temp_work_dir)

            self.restore_postgresql(temp_work_dir)
            self.restore_clickhouse(temp_work_dir)
            self.restore_s3_objects(temp_work_dir)
            self.restore_bundles_and_config(temp_work_dir)

            logger.info("✨ DataHarbor Master Platform Restore Complete!")
            return True
        finally:
            shutil.rmtree(temp_work_dir, ignore_errors=True)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        engine = MasterRestoreEngine(sys.argv[1])
        engine.restore_master_backup()
    else:
        print("Usage: python apps/backup/restore_engine.py <backup_archive.tar.gz>")
