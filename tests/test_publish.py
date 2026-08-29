"""Tests for plugin publish staging and dry-run planning."""
from __future__ import annotations

import os
import tempfile
import unittest

from apps.cli.publish import (
    _copy_plugin_snapshot,
    _default_repo_name,
    check_publish_readiness,
    publish_plugin,
)


class PublishHelperTests(unittest.TestCase):
    def test_default_repo_names(self):
        self.assertEqual(_default_repo_name("extractor", "demo_site"), "dh-extractor-demo-site")
        self.assertEqual(_default_repo_name("bundle", "my_leads"), "dh-bundle-my-leads")

    def test_copy_excludes_junk(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest_parent:
            with open(os.path.join(src, "extractor.py"), "w", encoding="utf-8") as f:
                f.write("x=1\n")
            with open(os.path.join(src, "manifest.json"), "w", encoding="utf-8") as f:
                f.write("{}\n")
            with open(os.path.join(src, ".env"), "w", encoding="utf-8") as f:
                f.write("SECRET=1\n")
            os.makedirs(os.path.join(src, "__pycache__"))
            with open(os.path.join(src, "__pycache__", "x.pyc"), "w", encoding="utf-8") as f:
                f.write("")

            dest = os.path.join(dest_parent, "snap")
            _copy_plugin_snapshot(src, dest)
            self.assertTrue(os.path.exists(os.path.join(dest, "extractor.py")))
            self.assertFalse(os.path.exists(os.path.join(dest, ".env")))
            self.assertFalse(os.path.exists(os.path.join(dest, "__pycache__")))

    def test_readiness_structure(self):
        readiness = check_publish_readiness()
        self.assertTrue(hasattr(readiness, "git_ok"))
        self.assertIsInstance(readiness.warnings, list)
        self.assertIsInstance(readiness.hard_failures, list)


class PublishDryRunTests(unittest.TestCase):
    def test_extractor_dry_run_demo_site(self):
        result = publish_plugin("extractor", "demo_site", dry_run=True)
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["kind"], "extractor")
        self.assertEqual(result["name"], "demo_site")
        self.assertEqual(result["repo_name"], "dh-extractor-demo-site")
        self.assertIn("source", result)
        self.assertTrue(os.path.isdir(result["source"]))

    def test_dry_run_visibility_public(self):
        result = publish_plugin("extractor", "demo_site", visibility="public", dry_run=True)
        self.assertEqual(result["visibility"], "public")

    def test_invalid_visibility_raises(self):
        with self.assertRaises(ValueError):
            publish_plugin("extractor", "demo_site", visibility="secret", dry_run=True)

    def test_find_unpublished_skips_core_ids(self):
        from apps.extractor.requirements import find_unpublished_local_extractors

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
                f.write(
                    '{"name":"x","version":"0.1.0","description":"d",'
                    '"requirements":{"extractors":["demo_site","custom_local"]}}'
                )
            found = find_unpublished_local_extractors(tmp)
            names = [x["name"] for x in found]
            self.assertNotIn("demo_site", names)
            self.assertIn("custom_local", names)

    def test_bundle_publish_blocks_on_local_extractors(self):
        from apps.extractor.requirements import find_unpublished_local_extractors

        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as f:
                f.write(
                    '{"name":"pub_dep_bundle","version":"0.1.0","description":"d",'
                    '"requirements":{"extractors":["custom_local_ext"]}}'
                )
            found = find_unpublished_local_extractors(tmp)
            self.assertTrue(any(x["name"] == "custom_local_ext" for x in found))

    def test_missing_plugin_raises(self):
        with self.assertRaises(ValueError):
            publish_plugin("extractor", "definitely_missing_xyz", dry_run=True)

    def test_publish_requires_identity_when_not_dry_run(self):
        readiness = check_publish_readiness()
        if readiness.can_commit:
            self.skipTest("git identity already configured on this machine")
        with self.assertRaises(ValueError) as ctx:
            publish_plugin("extractor", "demo_site", dry_run=False, remote="git@example.com:x/y.git")
        self.assertIn("user.name", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
