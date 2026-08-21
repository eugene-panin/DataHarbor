"""Smoke tests for Qdrant helper wiring."""
from unittest import TestCase
from unittest.mock import MagicMock, patch

from apps.db import qdrant_client as qc


class QdrantHelperTests(TestCase):
    def test_ensure_collection_short_circuits_when_client_missing(self):
        with patch.object(qc, "get_qdrant_client", return_value=None):
            self.assertFalse(qc.ensure_collection("demo"))

    def test_upsert_vectors_noop_on_empty(self):
        self.assertTrue(qc.upsert_vectors([]))

    def test_search_vectors_returns_mapped_hits(self):
        hit = MagicMock()
        hit.id = "a1"
        hit.score = 0.91
        hit.payload = {"name": "Acme"}

        client = MagicMock()
        client.search.return_value = [hit]

        with patch.object(qc, "get_qdrant_client", return_value=client):
            rows = qc.search_vectors([0.1, 0.2], limit=1)

        self.assertEqual(rows, [{"id": "a1", "score": 0.91, "payload": {"name": "Acme"}}])
        client.search.assert_called_once()
