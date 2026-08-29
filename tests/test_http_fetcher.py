from unittest import TestCase
from unittest.mock import patch

from apps.scraper.http_fetcher import HttpFetcher


class HttpFetcherProxyPolicyTests(TestCase):
    def test_proxy_required_rejects_an_unconfigured_proxy_before_network_io(self):
        scraper = HttpFetcher(proxies={})
        with patch("apps.scraper.http_fetcher.build_opener") as build_opener:
            result = scraper.fetch("https://example.com", require_proxy=True)

        self.assertEqual(result["status"], 502)
        self.assertEqual(result["error"], "A proxy is required but none is configured")
        build_opener.assert_not_called()

    def test_fetch_returns_http_error_body(self):
        from io import BytesIO
        from urllib.error import HTTPError

        err = HTTPError("https://example.com", 404, "Not Found", hdrs=None, fp=BytesIO(b"missing"))
        scraper = HttpFetcher(use_proxy=False)
        with patch("apps.scraper.http_fetcher.build_opener") as build_opener:
            build_opener.return_value.open.side_effect = err
            result = scraper.fetch("https://example.com")

        self.assertEqual(result["status"], 404)
        self.assertIn("missing", result["content"])
