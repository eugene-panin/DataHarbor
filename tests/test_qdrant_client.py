"""Smoke tests for Qdrant helper wiring."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

from qdrant_client import QdrantClient

from apps.db import qdrant_client as qc


class QdrantHelperTests(TestCase):
    def test_ensure_collection_short_circuits_when_client_missing(self):
        with patch.object(qc, "get_qdrant_client", return_value=None):
            self.assertFalse(qc.ensure_collection("demo"))

    def test_upsert_vectors_noop_on_empty(self):
        self.assertTrue(qc.upsert_vectors([]))

    def test_search_vectors_returns_mapped_hits(self):
        # F14 regression: the previous version of this test mocked
        # `client.search` with a bare MagicMock(), which happily fabricates
        # *any* attribute regardless of whether the real QdrantClient class
        # has it — so it kept passing even after QdrantClient.search() was
        # removed from the library (this project pins qdrant-client>=1.9.0;
        # 1.19.0 has no `search` method at all, only `query_points`), and
        # search_vectors() silently returned [] on every real call in
        # production. spec=QdrantClient makes the mock raise AttributeError
        # for any method the real class doesn't have, so a test built against
        # a since-removed API can't pass by accident again.
        hit = MagicMock()
        hit.id = "a1"
        hit.score = 0.91
        hit.payload = {"name": "Acme"}
        response = MagicMock()
        response.points = [hit]

        client = MagicMock(spec=QdrantClient)
        client.query_points.return_value = response

        with patch.object(qc, "get_qdrant_client", return_value=client):
            rows = qc.search_vectors([0.1, 0.2], limit=1)

        self.assertEqual(rows, [{"id": "a1", "score": 0.91, "payload": {"name": "Acme"}}])
        client.query_points.assert_called_once()
