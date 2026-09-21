"""Regression tests for F06: backup/restore correctness fixes.

Covers what was found live against a real Postgres instance with real
scraped data (not just synthetic inputs):
- _sql_literal must produce valid SQL for real column types, including
  non-ASCII text (psycopg2.extensions.adapt() used standalone assumes
  latin-1 and raised UnicodeEncodeError on this).
- _split_sql_statements must not treat a ';\\n' sequence *inside* a text
  value as a statement boundary — routine in scraped documentation content.
- The Python restore fallback must isolate each statement with a SAVEPOINT
  so one bad row doesn't poison the whole transaction and cascade into every
  subsequent statement failing too (found live: ~87,000 false failures from
  a single malformed JSONB value).
"""
from __future__ import annotations

import gzip

from apps.backup.backup_engine import _sql_literal
from apps.backup.restore_engine import _split_sql_statements


class TestSqlLiteral:
    def test_none(self):
        assert _sql_literal(None) == "NULL"

    def test_bool(self):
        assert _sql_literal(True) == "TRUE"
        assert _sql_literal(False) == "FALSE"

    def test_int_and_float(self):
        assert _sql_literal(42) == "42"
        assert _sql_literal(3.14) == "3.14"

    def test_string_with_single_quote_is_doubled(self):
        assert _sql_literal("O'Brien") == "'O''Brien'"

    def test_unicode_text_does_not_raise(self):
        # Regression: psycopg2.extensions.adapt(value).getquoted() without a
        # live connection defaults to latin-1 and crashes on ordinary
        # non-ASCII text — hit immediately against real scraped data.
        assert _sql_literal("Café – naïve 🚀") == "'Café – naïve 🚀'"

    def test_backslash_is_not_doubled(self):
        # standard_conforming_strings=on (Postgres default): backslash is a
        # literal character in a plain '...' string, not an escape char.
        assert _sql_literal("a\\b") == "'a\\b'"

    def test_dict_serializes_as_json_text(self):
        assert _sql_literal({"a": 1}) == '\'{"a": 1}\''

    def test_list_serializes_as_json_text(self):
        assert _sql_literal([1, 2, "x"]) == '\'[1, 2, "x"]\''

    def test_bytes_becomes_postgres_hex_bytea_literal(self):
        assert _sql_literal(b"AB") == "'\\x4142'"


class TestSplitSqlStatements:
    def test_simple_two_statement_split(self):
        sql = "INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);\n"
        assert _split_sql_statements(sql) == [
            "INSERT INTO t VALUES (1)",
            "INSERT INTO t VALUES (2)",
        ]

    def test_semicolon_newline_inside_string_literal_does_not_split(self):
        sql = "INSERT INTO t (a) VALUES ('line one;\nline two');\n"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1
        assert "line one;\nline two" in stmts[0]

    def test_doubled_quote_before_embedded_delimiter(self):
        sql = "INSERT INTO t (a) VALUES ('it''s here;\nstill here');\n"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1
        assert "it''s here" in stmts[0]

    def test_comment_glued_to_first_insert_stays_one_chunk(self):
        # Matches the dump writer's actual output shape: "-- Table: X\n"
        # immediately followed by the first INSERT, no ';\n' between them.
        # restore_postgresql strips comment *lines* from within a chunk
        # rather than discarding the whole chunk when it starts with one.
        sql = "-- Table: t\nINSERT INTO t VALUES (1);\n"
        stmts = _split_sql_statements(sql)
        assert len(stmts) == 1
        assert "-- Table: t" in stmts[0]
        assert "INSERT INTO t VALUES (1)" in stmts[0]

    def test_trailing_content_without_final_delimiter_is_kept(self):
        sql = "INSERT INTO t VALUES (1);\nSELECT 1"
        stmts = _split_sql_statements(sql)
        assert stmts[-1] == "SELECT 1"


class _FakeCursor:
    """Records executed SQL; raises once for statements matching a marker,
    to verify the savepoint/rollback control flow without a real Postgres
    connection (transaction-poisoning is server-side behavior no mock can
    reproduce faithfully any other way)."""

    def __init__(self, fail_marker: str):
        self.fail_marker = fail_marker
        self.calls: list[str] = []
        self._already_failed = False

    def execute(self, sql, *args):
        self.calls.append(sql)
        if self.fail_marker in sql and not self._already_failed and "SAVEPOINT" not in sql:
            self._already_failed = True
            raise RuntimeError("simulated statement failure")


class _FakeCursorCtx:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self._cursor

    def __exit__(self, *exc):
        return False


def test_restore_savepoint_isolates_a_failing_statement(tmp_path, monkeypatch):
    """The critical regression: one bad statement must not cascade."""
    import apps.backup.restore_engine as re_module

    fake_cursor = _FakeCursor(fail_marker="bad_table")
    monkeypatch.setattr(re_module, "get_db_cursor", lambda commit=True: _FakeCursorCtx(fake_cursor))
    monkeypatch.setattr(re_module.shutil, "which", lambda name: None)  # force the Python fallback

    sql_content = (
        "INSERT INTO good_table_1 VALUES (1);\n"
        "INSERT INTO bad_table VALUES (2);\n"
        "INSERT INTO good_table_2 VALUES (3);\n"
    )
    with gzip.open(tmp_path / "postgres_backup.sql.gz", "wt", encoding="utf-8") as f:
        f.write(sql_content)

    engine = re_module.MasterRestoreEngine.__new__(re_module.MasterRestoreEngine)
    result = engine.restore_postgresql(str(tmp_path))

    assert result["statements_ok"] == 2
    assert result["statements_failed"] == 1
    executed = " ".join(fake_cursor.calls)
    # Both the statement before AND after the failure must have run — proof
    # the transaction was not left poisoned for the rest of the loop.
    assert "good_table_1" in executed
    assert "good_table_2" in executed
    assert "ROLLBACK TO SAVEPOINT" in executed


def test_restore_missing_dump_file_is_reported_as_skipped(tmp_path):
    import apps.backup.restore_engine as re_module

    engine = re_module.MasterRestoreEngine.__new__(re_module.MasterRestoreEngine)
    result = engine.restore_postgresql(str(tmp_path))
    assert result["status"] == "skipped"
