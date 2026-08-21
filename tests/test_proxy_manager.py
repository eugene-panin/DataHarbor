import os
from unittest import TestCase
from unittest.mock import patch

from apps.scraper.proxy_manager import ProxyManager


class ProxyManagerTests(TestCase):
    def test_single_proxy_url_is_returned(self):
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "http://geo-user:geo-pass@proxy.example:9000",
                "PROXY_LIST": "",
            },
            clear=False,
        ):
            manager = ProxyManager()

        self.assertEqual(
            manager.get_proxy_url(),
            "http://geo-user:geo-pass@proxy.example:9000",
        )

    def test_proxy_list_uses_first_entry_in_core(self):
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "",
                "PROXY_LIST": "http://a:1@proxy.example:1,http://b:2@proxy.example:2",
            },
            clear=False,
        ):
            manager = ProxyManager()

        self.assertEqual(manager.get_proxy_url(), "http://a:1@proxy.example:1")

    def test_missing_proxy_returns_none(self):
        with patch.dict(os.environ, {"PROXY_URL": "", "PROXY_LIST": ""}, clear=False):
            manager = ProxyManager()
        self.assertIsNone(manager.get_proxy_url())
