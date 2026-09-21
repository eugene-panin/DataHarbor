"""Tests for apps.storage.s3 (additional observation): download_media_stream_to_s3
must actually stream, not buffer the whole remote response into memory first.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from apps.storage import s3 as s3_module


def test_download_media_stream_uploads_via_fileobj_not_full_read():
    """Before the fix, response.read() buffered the ENTIRE remote body into
    memory before calling put_object() — for the multi-GB video files this
    function targets, that's a full in-memory copy per download despite
    being named/documented as streaming. upload_fileobj() reads the source
    in chunks instead."""
    fake_response = MagicMock()
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    fake_client = MagicMock()

    with (
        patch.object(s3_module, "get_s3_client", return_value=fake_client),
        patch("urllib.request.urlopen", return_value=fake_response),
    ):
        result = s3_module.download_media_stream_to_s3("http://example.com/video.mp4", "key.mp4")

    assert result["status"] == "success"
    fake_client.upload_fileobj.assert_called_once()
    args, kwargs = fake_client.upload_fileobj.call_args
    assert args[0] is fake_response  # the raw response object, not a materialized buffer
    fake_response.read.assert_not_called()
    fake_client.put_object.assert_not_called()
