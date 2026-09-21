"""Tests for dynamic extractor plugin registry and contracts."""
import json
import os
import shutil
import tempfile
import textwrap
import unittest

from apps.bundle.validator import BundleValidator
from apps.extractor.requirements import (
    derive_extractor_name_from_source,
    parse_extractor_requirement,
    parse_extractor_requirements,
    resolve_bundle_extractors,
)
from apps.extractor.validator import EXTRACTORS_DIR, ExtractorValidator
from apps.scraper.extractors.registry import (
    clear_registry_cache,
    generate_page_urls_for_domain,
    get_extractor,
    list_installed_extractors,
    require_extractor,
)


class ExtractorRegistryTests(unittest.TestCase):
    def setUp(self):
        clear_registry_cache()

    def tearDown(self):
        clear_registry_cache()

    def test_demo_site_is_discoverable(self):
        installed = {item["id"] for item in list_installed_extractors()}
        self.assertIn("demo_site", installed)

    def test_get_extractor_by_id_and_domain(self):
        by_id = get_extractor("demo_site")
        by_domain = get_extractor("https://demo_site.example/list")
        self.assertIsNotNone(by_id)
        self.assertIsNotNone(by_domain)
        self.assertIs(by_id, get_extractor("demo_site"))

    def test_require_extractor_missing_raises(self):
        with self.assertRaises(LookupError):
            require_extractor("definitely_missing_extractor_xyz")

    def test_domain_match_is_not_a_loose_substring(self):
        """F17: `domain in host` let a manifest domain like "github.com"
        match "github.com.evil-phishing.example" (lookalike prefix, attacker
        suffix) and "notgithub.com" (unrelated host containing the string),
        silently routing scraped content through the wrong extractor.

        Uses its own throwaway extractor rather than a real installed one —
        every non-demo_site extractor is private/gitignored (see
        .gitignore's `extractors/*` rule), so any test that depends on one
        being present only ever passes on a machine that happens to have it
        checked out locally, not in CI against a clean clone.
        """
        target_name = "zz_domain_match_ext"
        target_path = os.path.join(EXTRACTORS_DIR, target_name)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)
        try:
            os.makedirs(target_path)
            with open(os.path.join(target_path, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": target_name,
                        "version": "0.1.0",
                        "description": "domain-match test fixture",
                        "domains": ["github.com"],
                        "entrypoint": "extractor:parse",
                    },
                    f,
                )
            with open(os.path.join(target_path, "__init__.py"), "w", encoding="utf-8") as f:
                f.write("")
            with open(os.path.join(target_path, "extractor.py"), "w", encoding="utf-8") as f:
                f.write("def parse(html, source_url):\n    return []\n")
            clear_registry_cache()

            self.assertIsNone(get_extractor("https://github.com.evil-phishing.example/x"))
            self.assertIsNone(get_extractor("https://notgithub.com/x"))
            self.assertIsNotNone(get_extractor("https://github.com/x"))
            self.assertIsNotNone(get_extractor("https://docs.github.com/x"))
        finally:
            if os.path.exists(target_path):
                shutil.rmtree(target_path)
            clear_registry_cache()

    def test_parse_returns_source_url(self):
        parse_fn = require_extractor("demo_site")
        html = """
        <html><body>
          <h1>Acme Agency</h1>
          <div class="card">Beta Co</div>
        </body></html>
        """
        records = parse_fn(html, "https://demo_site.example/list")
        self.assertGreaterEqual(len(records), 1)
        self.assertEqual(records[0]["source_url"], "https://demo_site.example/list")

    def test_generate_page_urls_for_domain(self):
        urls = generate_page_urls_for_domain("https://demo_site.example/list", max_pages=3)
        self.assertEqual(len(urls), 3)
        self.assertEqual(urls[0], "https://demo_site.example/list")
        self.assertIn("page=1", urls[1])


class ExtractorRequirementParseTests(unittest.TestCase):
    def test_parse_local_id(self):
        req = parse_extractor_requirement("demo_site")
        self.assertEqual(req, {"name": "demo_site", "source": None})

    def test_parse_git_url(self):
        req = parse_extractor_requirement("git@github.com:acme/dh-extractor-example.git")
        self.assertEqual(req["name"], "example")
        self.assertIn("dh-extractor-example.git", req["source"])

    def test_parse_object_with_name_and_source(self):
        req = parse_extractor_requirement(
            {"name": "example", "source": "https://github.com/acme/custom-example.git"}
        )
        self.assertEqual(req["name"], "example")
        self.assertEqual(req["source"], "https://github.com/acme/custom-example.git")

    def test_derive_name_strips_prefix(self):
        self.assertEqual(
            derive_extractor_name_from_source("https://github.com/x/extractor-foo.git"),
            "foo",
        )

    def test_parse_mixed_list(self):
        parsed = parse_extractor_requirements(
            [
                "demo_site",
                "https://github.com/acme/dh-extractor-example.git",
                {"name": "custom", "source": "git@github.com:acme/custom.git"},
            ]
        )
        self.assertEqual([p["name"] for p in parsed], ["demo_site", "example", "custom"])


class ExtractorValidatorTests(unittest.TestCase):
    def test_demo_site_validates(self):
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "extractors", "demo_site"))
        is_valid, errors = ExtractorValidator(root).validate()
        self.assertTrue(is_valid, errors)

    def _write_extractor(self, root, *, entrypoint, extractor_body, helper_body=None):
        os.makedirs(root, exist_ok=True)
        with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "name": os.path.basename(root),
                    "version": "0.1.0",
                    "description": "test extractor",
                    "domains": ["example.com"],
                    "entrypoint": entrypoint,
                },
                f,
            )
        with open(os.path.join(root, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("")
        with open(os.path.join(root, "extractor.py"), "w", encoding="utf-8") as f:
            f.write(extractor_body)
        if helper_body is not None:
            with open(os.path.join(root, "helper.py"), "w", encoding="utf-8") as f:
                f.write(helper_body)

    def test_non_string_entrypoint_fails_validation(self):
        """F17: entrypoint: 123 previously passed both the required-field
        check (non-empty) and the string-type check (isinstance skip),
        so validate() silently accepted a manifest that could never work."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "zz_bad_entrypoint")
            os.makedirs(root)
            with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": "zz_bad_entrypoint",
                        "version": "0.1.0",
                        "description": "test",
                        "domains": ["example.com"],
                        "entrypoint": 123,
                    },
                    f,
                )
            with open(os.path.join(root, "extractor.py"), "w", encoding="utf-8") as f:
                f.write("def parse(html, source_url):\n    return []\n")

            is_valid, errors = ExtractorValidator(root).validate()
            self.assertFalse(is_valid)
            self.assertTrue(any("entrypoint" in e.lower() for e in errors), errors)

    def test_relative_import_does_not_break_validation(self):
        """F17: validate() loaded the entrypoint module with a dotless
        synthetic name (no parent package), so a real extractor split
        across local modules via `from . import helper` always failed
        validation with "no known parent package", even though the same
        import works fine at real runtime through the extractors.<id>
        package (apps/scraper/extractors/registry.py)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = os.path.join(tmp, "zz_relative_import")
            self._write_extractor(
                root,
                entrypoint="extractor:parse",
                extractor_body=(
                    "from .helper import greeting\n\n"
                    "def parse(html, source_url):\n"
                    "    return [{'msg': greeting(), 'source_url': source_url}]\n"
                ),
                helper_body="def greeting():\n    return 'hi'\n",
            )

            is_valid, errors = ExtractorValidator(root).validate()
            self.assertTrue(is_valid, errors)


class BundleExtractorRequirementTests(unittest.TestCase):
    def test_bundle_fails_when_required_extractor_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle_dir = os.path.join(tmp, "demo_bundle")
            os.makedirs(bundle_dir)
            with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as f:
                f.write(
                    textwrap.dedent(
                        """
                        {
                          "name": "demo_bundle",
                          "version": "0.1.0",
                          "description": "demo",
                          "requirements": {"extractors": ["missing_resource_xyz"]}
                        }
                        """
                    ).strip()
                )
            with open(os.path.join(bundle_dir, "scraper.py"), "w", encoding="utf-8") as f:
                f.write("def scrape():\n    return []\n")

            is_valid, errors = BundleValidator(bundle_dir).validate()
            self.assertFalse(is_valid)
            self.assertTrue(any("missing_resource_xyz" in err for err in errors))

    def test_clear_registry_cache_reimports_changed_code_from_disk(self):
        """F17: clear_registry_cache() only dropped the discovery _cache
        dict — the next _discover() still resolved extractors.<id>.extractor
        via importlib.import_module(), which returns whatever is already in
        sys.modules rather than re-reading the file. Reinstalling/upgrading
        an extractor kept serving the OLD parse() code until the whole
        process restarted."""
        target_name = "zz_hot_reload_ext"
        target_path = os.path.join(EXTRACTORS_DIR, target_name)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)

        def _write_version(text: str):
            os.makedirs(target_path, exist_ok=True)
            with open(os.path.join(target_path, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": target_name,
                        "version": "0.1.0",
                        "description": "hot reload test",
                        "domains": ["example.com"],
                        "entrypoint": "extractor:parse",
                    },
                    f,
                )
            with open(os.path.join(target_path, "__init__.py"), "w", encoding="utf-8") as f:
                f.write("")
            with open(os.path.join(target_path, "extractor.py"), "w", encoding="utf-8") as f:
                f.write(
                    f"def parse(html, source_url):\n"
                    f"    return [{{'version': '{text}', 'source_url': source_url}}]\n"
                )

        try:
            _write_version("v1")
            clear_registry_cache()
            parse_v1 = require_extractor(target_name)
            self.assertEqual(parse_v1("<html/>", "https://example.com")[0]["version"], "v1")

            _write_version("v2")
            clear_registry_cache()
            parse_v2 = require_extractor(target_name)
            self.assertEqual(parse_v2("<html/>", "https://example.com")[0]["version"], "v2")
        finally:
            if os.path.exists(target_path):
                shutil.rmtree(target_path)

    def test_resolve_installs_extractor_from_local_source(self):
        target_name = "demo_remote_ext"
        target_path = os.path.join(EXTRACTORS_DIR, target_name)
        if os.path.exists(target_path):
            shutil.rmtree(target_path)

        with tempfile.TemporaryDirectory() as tmp:
            src_ext = os.path.join(tmp, "demo_remote_ext")
            os.makedirs(src_ext)
            with open(os.path.join(src_ext, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": "demo_remote_ext",
                        "version": "0.1.0",
                        "description": "demo remote extractor",
                        "domains": ["example.com"],
                        "entrypoint": "extractor:parse",
                    },
                    f,
                )
            with open(os.path.join(src_ext, "extractor.py"), "w", encoding="utf-8") as f:
                f.write(
                    "def parse(html, source_url):\n"
                    "    return [{'company_name': 'Demo', 'source_url': source_url}]\n"
                )
            with open(os.path.join(src_ext, "__init__.py"), "w", encoding="utf-8") as f:
                f.write("")

            bundle_dir = os.path.join(tmp, "demo_bundle")
            os.makedirs(bundle_dir)
            with open(os.path.join(bundle_dir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "name": "demo_bundle",
                        "version": "0.1.0",
                        "description": "demo",
                        "requirements": {
                            "extractors": [
                                {"name": "demo_remote_ext", "source": src_ext},
                            ]
                        },
                    },
                    f,
                )
            with open(os.path.join(bundle_dir, "scraper.py"), "w", encoding="utf-8") as f:
                f.write("def scrape():\n    return []\n")

            try:
                report = resolve_bundle_extractors(bundle_dir, force=True)
                self.assertEqual(report[0]["status"], "installed")
                clear_registry_cache()
                self.assertIsNotNone(get_extractor("demo_remote_ext"))
                is_valid, errors = BundleValidator(bundle_dir).validate()
                self.assertTrue(is_valid, errors)
            finally:
                if os.path.exists(target_path):
                    shutil.rmtree(target_path)
                clear_registry_cache()


if __name__ == "__main__":
    unittest.main()
