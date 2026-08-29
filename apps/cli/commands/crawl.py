"""Common Crawl dataset commands."""
from __future__ import annotations

from pathlib import Path

import typer

from apps.crawl.constants import DEFAULT_INDEX_SUBSET, default_crawl_id
from apps.crawl.index import DEFAULT_DOWNLOAD_DIR, download_index_parquet

app = typer.Typer(help="Download and query Common Crawl data", no_args_is_help=True)


@app.command("download-index")
def download_index(
    crawl_id: str = typer.Option(
        "",
        "--crawl-id",
        help="Crawl partition (default: COMMONCRAWL_CRAWL_ID or built-in default)",
    ),
    subset: str = typer.Option(
        DEFAULT_INDEX_SUBSET,
        "--subset",
        help="Index subset from the Common Crawl manifest",
    ),
    shard: int = typer.Option(
        0,
        "--shard",
        min=0,
        help="Zero-based Parquet shard number",
    ),
    output_dir: Path = typer.Option(
        DEFAULT_DOWNLOAD_DIR,
        "--output-dir",
        help="Root download directory",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Replace an existing completed shard",
    ),
) -> None:
    """Download exactly one Common Crawl Parquet index shard."""
    selected_crawl = crawl_id.strip() or default_crawl_id()
    print(f"Downloading index shard {shard}: crawl={selected_crawl}, subset={subset}")
    try:
        path = download_index_parquet(
            selected_crawl,
            subset=subset,
            shard=shard,
            output_dir=output_dir,
            overwrite=overwrite,
        )
    except (FileExistsError, IndexError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        raise typer.Exit(code=1) from exc

    size = path.stat().st_size
    print(f"Downloaded {size} bytes to {path}")
