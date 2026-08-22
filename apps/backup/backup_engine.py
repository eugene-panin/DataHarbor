import gzip
import json
import logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime

from apps.db.clickhouse_client import get_clickhouse_client
from apps.db.connection import get_connection_params, get_db_cursor
from apps.storage.s3 import get_s3_client

logger = logging.getLogger(__name__)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKUPS_DIR = os.path.join(PROJECT_ROOT, "backups")

class MasterBackupEngine:
    """Master Backup Engine capturing PostgreSQL pgvector, ClickHouse OLAP, SeaweedFS S3 objects, and custom bundles."""

    def __init__(self, output_dir: str = BACKUPS_DIR):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def backup_postgresql(self, temp_dir: str) -> str:
        """Dumps PostgreSQL database schema, tables, and vector embeddings using pg_dump or Python SQL dump."""
        logger.info("Backing up PostgreSQL 16 (relational tables & pgvector embeddings)...")
        pg_backup_path = os.path.join(temp_dir, "postgres_backup.sql.gz")
        host, port, dbname, user, password = get_connection_params()

        # Try pg_dump binary first
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
                "--if-exists"
            ]
            try:
                with open(pg_backup_path, "wb") as f_out:
                    p1 = subprocess.Popen(cmd, stdout=subprocess.PIPE, env=env)
                    p2 = subprocess.Popen(["gzip", "-c"], stdin=p1.stdout, stdout=f_out)
                    p1.stdout.close()
                    p2.communicate()
                logger.info(f"Successfully generated pg_dump backup at: {pg_backup_path}")
                return pg_backup_path
            except Exception as e:
                logger.warning(f"pg_dump binary execution failed ({e}), falling back to Python DB dump...")

        # Python fallback SQL table dumper
        sql_dump_path = os.path.join(temp_dir, "postgres_backup.sql")
        with get_db_cursor(commit=False) as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE';
            """)
            tables = [r['table_name'] for r in cursor.fetchall()]

            with open(sql_dump_path, "w", encoding="utf-8") as f:
                f.write(f"-- DataHarbor PostgreSQL Backup Generated {datetime.now().isoformat()}\n\n")
                for table in tables:
                    f.write(f"-- Table: {table}\n")
                    cursor.execute(f"SELECT * FROM {table};")
                    rows = cursor.fetchall()
                    for row in rows:
                        cols = list(row.keys())
                        vals = [repr(row[k]) if row[k] is not None else "NULL" for k in cols]
                        f.write(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(vals)}) ON CONFLICT DO NOTHING;\n")
                    f.write("\n")

        with open(sql_dump_path, "rb") as f_in, gzip.open(pg_backup_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        os.remove(sql_dump_path)
        logger.info(f"Successfully generated Python SQL dump at: {pg_backup_path}")
        return pg_backup_path

    def backup_clickhouse(self, temp_dir: str) -> str:
        """Dumps ClickHouse MergeTree tables and analytics events."""
        logger.info("Backing up ClickHouse OLAP tables and timeseries events...")
        ch_backup_path = os.path.join(temp_dir, "clickhouse_backup.json.gz")
        client = get_clickhouse_client()
        backup_data = {}

        if client:
            try:
                tables = ["clickhouse_scraper_telemetry"]
                for tbl in tables:
                    try:
                        res = client.query(f"SELECT * FROM {tbl}")
                        backup_data[tbl] = {
                            "column_names": res.column_names,
                            "rows": [list(row) for row in res.result_rows]
                        }
                    except Exception as e:
                        logger.warning(f"Could not dump ClickHouse table '{tbl}': {e}")
            except Exception as e:
                logger.error(f"Error querying ClickHouse for backup: {e}")

        with gzip.open(ch_backup_path, "wt", encoding="utf-8") as f:
            json.dump(backup_data, f, ensure_ascii=False, indent=2, default=str)
        logger.info(f"Successfully generated ClickHouse JSON backup at: {ch_backup_path}")
        return ch_backup_path

    def backup_s3_objects(self, temp_dir: str) -> str:
        """Downloads all raw HTML dumps, videos, and thumbnails from SeaweedFS S3 storage."""
        logger.info("Backing up SeaweedFS S3 objects ('dataharbor-raw' bucket)...")
        s3_temp_dir = os.path.join(temp_dir, "s3_raw")
        os.makedirs(s3_temp_dir, exist_ok=True)
        s3_tar_path = os.path.join(temp_dir, "s3_objects_backup.tar.gz")

        client = get_s3_client()
        bucket_name = os.getenv("S3_BUCKET_NAME", "dataharbor-raw")

        try:
            paginator = client.get_paginator('list_objects_v2')
            for page in paginator.paginate(Bucket=bucket_name):
                for obj in page.get('Contents', []):
                    key = obj['Key']
                    local_obj_path = os.path.join(s3_temp_dir, key)
                    os.makedirs(os.path.dirname(local_obj_path), exist_ok=True)
                    client.download_file(bucket_name, key, local_obj_path)
            logger.info(f"Successfully downloaded S3 objects from bucket '{bucket_name}'.")
        except Exception as e:
            logger.warning(f"S3 backup warning: {e}")

        with tarfile.open(s3_tar_path, "w:gz") as tar:
            tar.add(s3_temp_dir, arcname="s3_raw")
        shutil.rmtree(s3_temp_dir, ignore_errors=True)
        return s3_tar_path

    def backup_bundles_and_config(self, temp_dir: str) -> str:
        """Packs custom bundles and .env configuration."""
        logger.info("Backing up custom bundles and platform configuration...")
        bundles_tar_path = os.path.join(temp_dir, "bundles_and_config.tar.gz")
        bundles_src = os.path.join(PROJECT_ROOT, "bundles")
        env_file = os.path.join(PROJECT_ROOT, ".env")

        with tarfile.open(bundles_tar_path, "w:gz") as tar:
            if os.path.exists(bundles_src):
                tar.add(bundles_src, arcname="bundles")
            if os.path.exists(env_file):
                tar.add(env_file, arcname=".env")
        return bundles_tar_path

    def create_master_backup(self) -> str:
        """Executes full platform backup and returns path to final compressed master archive."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        master_archive_name = f"dataharbor_backup_{timestamp}.tar.gz"
        master_archive_path = os.path.join(self.output_dir, master_archive_name)

        logger.info(f"Starting DataHarbor Master Backup -> {master_archive_path}")
        temp_work_dir = os.path.join(self.output_dir, f"temp_{timestamp}")
        os.makedirs(temp_work_dir, exist_ok=True)

        try:
            # 1. Backup PostgreSQL
            self.backup_postgresql(temp_work_dir)
            # 2. Backup ClickHouse
            self.backup_clickhouse(temp_work_dir)
            # 3. Backup S3 Objects
            self.backup_s3_objects(temp_work_dir)
            # 4. Backup Bundles & Config
            self.backup_bundles_and_config(temp_work_dir)

            # Pack all 4 layers into Master Archive
            with tarfile.open(master_archive_path, "w:gz") as tar:
                for fname in os.listdir(temp_work_dir):
                    fpath = os.path.join(temp_work_dir, fname)
                    tar.add(fpath, arcname=fname)

            size_mb = os.path.getsize(master_archive_path) / (1024 * 1024)
            logger.info(f"✨ Master Backup Complete! Archive Size: {size_mb:.2f} MB at {master_archive_path}")
            return master_archive_path
        finally:
            shutil.rmtree(temp_work_dir, ignore_errors=True)

if __name__ == "__main__":
    engine = MasterBackupEngine()
    backup_file = engine.create_master_backup()
    print("Generated Master Backup Archive:", backup_file)
