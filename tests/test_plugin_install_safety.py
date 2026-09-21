"""Regression tests for install-path safety (F07): a manifest.json's `name` field
is untrusted content from the source being installed. Used unsanitized as a
directory-name component, a crafted value like "../../etc/cron.d/evil" would
install outside bundles_dir/extractors_dir.
"""
from __future__ import annotations

import apps.bundle.distributor as bundle_distributor
import apps.extractor.distributor as extractor_distributor

TRAVERSAL_NAMES = [
    "../../etc/cron.d/evil",
    "/etc/passwd",
    "..",
    "a/b",
    "a\\b",
    "",
]


def test_bundle_sanitize_rejects_path_traversal_names():
    for bad_name in TRAVERSAL_NAMES:
        safe = bundle_distributor._sanitize_plugin_name(bad_name, "fallback_name")
        assert safe == "fallback_name", f"{bad_name!r} was not rejected"
        assert "/" not in safe and "\\" not in safe and ".." not in safe


def test_bundle_sanitize_keeps_valid_names():
    assert bundle_distributor._sanitize_plugin_name("my-bundle", "fallback") == "my_bundle"
    assert bundle_distributor._sanitize_plugin_name("my_bundle_2", "fallback") == "my_bundle_2"


def test_bundle_sanitize_falls_back_safely_when_fallback_is_also_unsafe():
    # os.path.basename(source) could itself be unsafe in pathological cases;
    # the sanitizer must never return something with a path separator.
    safe = bundle_distributor._sanitize_plugin_name("../evil", "../also/evil")
    assert safe == "custom_bundle"


def test_extractor_sanitize_rejects_path_traversal_names():
    for bad_name in TRAVERSAL_NAMES:
        safe = extractor_distributor._sanitize_plugin_name(bad_name, "fallback_name")
        assert safe == "fallback_name", f"{bad_name!r} was not rejected"
        assert "/" not in safe and "\\" not in safe and ".." not in safe


def test_extractor_sanitize_falls_back_safely_when_fallback_is_also_unsafe():
    safe = extractor_distributor._sanitize_plugin_name("../evil", "../also/evil")
    assert safe == "custom_extractor"
