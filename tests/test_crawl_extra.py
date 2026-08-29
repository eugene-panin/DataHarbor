"""Tests for optional crawl extra and Common Crawl path helpers."""
from __future__ import annotations

from apps.crawl.constants import default_crawl_id
from apps.crawl.index import (
    download_index_parquet,
    index_from_clause,
    index_parquet_glob,
    index_paths_manifest_url,
)
from apps.crawl.warc import warc_data_url


def test_require_crawl_raises_when_missing(monkeypatch):
    import importlib
    import importlib.util

    mod = importlib.import_module("apps.crawl.gate")
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "duckdb":
            return None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
    try:
        mod.require_crawl("duckdb")
        raised = False
    except ImportError as exc:
        raised = True
        assert "crawl" in str(exc).lower()
    assert raised


def test_index_parquet_glob_uses_crawl_partition():
    glob_path = index_parquet_glob("CC-MAIN-2024-46")
    assert glob_path == (
        "s3://commoncrawl/cc-index/table/cc-main/warc/"
        "crawl=CC-MAIN-2024-46/subset=warc/*.parquet"
    )


def test_index_paths_manifest_url():
    assert index_paths_manifest_url("CC-MAIN-2024-46") == (
        "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-46/cc-index-table.paths.gz"
    )


def test_index_from_clause_https_uses_explicit_urls(monkeypatch):
    from apps.crawl import index as index_mod

    monkeypatch.setattr(
        index_mod,
        "list_index_parquet_urls",
        lambda crawl_id=None, subset="warc", max_shards=8: (
            "https://data.commoncrawl.org/cc-index/table/cc-main/warc/"
            "crawl=CC-MAIN-2024-46/subset=warc/part-0.parquet",
            "https://data.commoncrawl.org/cc-index/table/cc-main/warc/"
            "crawl=CC-MAIN-2024-46/subset=warc/part-1.parquet",
        ),
    )
    clause = index_from_clause("CC-MAIN-2024-46", alias="idx", max_shards=2, transport="https")
    assert "read_parquet([" in clause
    assert "https://data.commoncrawl.org/" in clause
    assert clause.endswith("AS idx")
    assert "part-0.parquet" in clause


def test_index_from_clause_s3_legacy_glob():
    clause = index_from_clause("CC-MAIN-2024-46", alias="idx", transport="s3")
    assert "read_parquet(" in clause
    assert "s3://commoncrawl/" in clause
    assert "crawl=CC-MAIN-2024-46" in clause
    assert clause.endswith("AS idx")


def test_download_index_parquet_streams_one_shard_atomically(monkeypatch, tmp_path):
    from io import BytesIO

    from apps.crawl import index as index_mod

    url = "https://data.commoncrawl.org/path/part-00003.zstd.parquet"
    monkeypatch.setattr(
        index_mod,
        "list_index_parquet_urls",
        lambda crawl_id=None, subset="warc", max_shards=8: (url,) * max_shards,
    )

    class _Response(BytesIO):
        headers = {"Content-Length": "7"}

    monkeypatch.setattr(index_mod, "urlopen", lambda request, timeout=120: _Response(b"parquet"))

    path = download_index_parquet(
        "CC-MAIN-2024-46",
        shard=3,
        output_dir=tmp_path,
    )

    assert path == tmp_path / "CC-MAIN-2024-46" / "warc" / "part-00003.zstd.parquet"
    assert path.read_bytes() == b"parquet"
    assert not path.with_name(f"{path.name}.part").exists()


def test_download_index_parquet_keeps_incomplete_partial(monkeypatch, tmp_path):
    from io import BytesIO

    from apps.crawl import index as index_mod

    url = "https://data.commoncrawl.org/path/part-00000.zstd.parquet"
    monkeypatch.setattr(index_mod, "list_index_parquet_urls", lambda *args, **kwargs: (url,))

    class _Response(BytesIO):
        headers = {"Content-Length": "10"}

    monkeypatch.setattr(index_mod, "urlopen", lambda request, timeout=120: _Response(b"short"))

    try:
        download_index_parquet("CC-MAIN-2024-46", output_dir=tmp_path)
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "Incomplete" in str(exc)

    partial = next(tmp_path.rglob("*.part"))
    assert raised
    assert partial.read_bytes() == b"short"


def test_warc_data_url():
    url = warc_data_url("crawl-data/CC-MAIN-2024-46/warc/file.warc.gz")
    assert url == "https://data.commoncrawl.org/crawl-data/CC-MAIN-2024-46/warc/file.warc.gz"


def test_default_crawl_id_env(monkeypatch):
    monkeypatch.setenv("COMMONCRAWL_CRAWL_ID", "CC-MAIN-2099-01")
    assert default_crawl_id() == "CC-MAIN-2099-01"


def test_connect_duckdb_creates_anonymous_s3_secret():
    from apps.crawl.index import connect_duckdb

    con = connect_duckdb()
    rows = con.execute("SELECT name, type FROM duckdb_secrets();").fetchall()
    names = {r[0] for r in rows}
    assert "commoncrawl_anon" in names


def test_cdx_index_url():
    from apps.crawl.cdx import cdx_index_url

    assert cdx_index_url("CC-MAIN-2024-46") == (
        "https://index.commoncrawl.org/CC-MAIN-2024-46-index"
    )


def test_query_cdx_treats_no_captures_404_as_empty(monkeypatch):
    from io import BytesIO
    from urllib.error import HTTPError

    import apps.crawl.cdx as cdx

    body = b'{"message": "No Captures found for: zzz.invalid/"}'

    def fake_urlopen(req, timeout=120):
        raise HTTPError(req.full_url, 404, "Not Found", hdrs=None, fp=BytesIO(body))

    monkeypatch.setattr(cdx, "urlopen", fake_urlopen)
    assert cdx.query_cdx("zzz.invalid/", crawl_id="CC-MAIN-2026-30", limit=5) == []


def test_query_cdx_retries_remote_disconnect(monkeypatch):
    from http.client import RemoteDisconnected

    import apps.crawl.cdx as cdx

    calls = {"n": 0}

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return (
                b'{"url":"https://a.myshopify.com/","filename":"crawl-data/x.warc.gz",'
                b'"offset":"1","length":"10","status":"200","mime":"text/html"}\n'
            )

    def fake_urlopen(req, timeout=120):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RemoteDisconnected("Remote end closed connection without response")
        return _Resp()

    monkeypatch.setattr(cdx, "urlopen", fake_urlopen)
    monkeypatch.setattr(cdx.time, "sleep", lambda *_: None)
    rows = cdx.query_cdx("*.myshopify.com/", crawl_id="CC-MAIN-2026-30", limit=5)
    assert calls["n"] == 3
    assert len(rows) == 1
    assert rows[0]["warc_filename"] == "crawl-data/x.warc.gz"
