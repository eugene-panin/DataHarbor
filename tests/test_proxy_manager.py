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
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "",
                "PROXY_LIST": "",
                "RESIDENTIAL_PROXY_URL": "",
                "RESIDENTIAL_PROXY_LIST": "",
                "DATACENTER_PROXY_URL": "",
                "DATACENTER_PROXY_LIST": "",
            },
            clear=False,
        ):
            manager = ProxyManager()
        self.assertIsNone(manager.get_proxy_url())

    def test_named_pools_are_isolated_and_legacy_defaults_to_residential(self):
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "http://legacy:pass@residential.example:9000",
                "PROXY_LIST": "",
                "RESIDENTIAL_PROXY_URL": "",
                "RESIDENTIAL_PROXY_LIST": "",
                "DATACENTER_PROXY_URL": "http://dc:pass@datacenter.example:9000",
                "DATACENTER_PROXY_LIST": "",
            },
            clear=False,
        ):
            manager = ProxyManager()

        self.assertEqual(
            manager.get_proxy_url(pool="residential"),
            "http://legacy:pass@residential.example:9000",
        )
        self.assertEqual(
            manager.get_proxy_url(pool="datacenter"),
            "http://dc:pass@datacenter.example:9000",
        )

    def test_default_pool_uses_residential_when_only_named_pool_is_configured(self):
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "",
                "PROXY_LIST": "",
                "RESIDENTIAL_PROXY_URL": "http://res:pass@residential.example:9000",
                "RESIDENTIAL_PROXY_LIST": "",
                "DATACENTER_PROXY_URL": "",
                "DATACENTER_PROXY_LIST": "",
            },
            clear=False,
        ):
            manager = ProxyManager()

        self.assertEqual(
            manager.get_proxy_url(),
            "http://res:pass@residential.example:9000",
        )

    def test_geonode_host_port_username_password_format_is_normalized(self):
        with patch.dict(
            os.environ,
            {
                "PROXY_URL": "",
                "PROXY_LIST": "",
                "RESIDENTIAL_PROXY_URL": "",
                "RESIDENTIAL_PROXY_LIST": "",
                "DATACENTER_PROXY_URL": "",
                "DATACENTER_PROXY_LIST": "http://proxy.example:9000:geo user:p@ss word",
            },
            clear=False,
        ):
            manager = ProxyManager()

        self.assertEqual(
            manager.get_proxy_url(pool="datacenter"),
            "http://geo%20user:p%40ss%20word@proxy.example:9000",
        )

    def test_unknown_pool_is_rejected(self):
        manager = ProxyManager()
        with self.assertRaisesRegex(ValueError, "Unsupported proxy pool"):
            manager.get_proxy_url(pool="mobile")
