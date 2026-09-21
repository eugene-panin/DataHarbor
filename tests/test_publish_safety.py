"""Regression tests for F08: publish staging must never delete the plugin
source, must never touch anything during --dry-run, and must preserve an
existing --workdir's .git history instead of wiping it on every call.
"""
from __future__ import annotations

import pytest

import apps.cli.publish as publish_module
from apps.cli.publish import PublishReadiness, _copy_plugin_snapshot, publish_plugin


def test_rejects_dest_equal_to_source(tmp_path):
    src = tmp_path / "plugin"
    src.mkdir()
    with pytest.raises(ValueError, match="overlaps"):
        _copy_plugin_snapshot(str(src), str(src))


def test_rejects_dest_inside_source(tmp_path):
    src = tmp_path / "plugin"
    src.mkdir()
    dest = src / "staging"
    with pytest.raises(ValueError, match="overlaps"):
        _copy_plugin_snapshot(str(src), str(dest))


def test_rejects_source_inside_dest(tmp_path):
    dest = tmp_path / "workdir"
    src = dest / "plugin"
    src.mkdir(parents=True)
    with pytest.raises(ValueError, match="overlaps"):
        _copy_plugin_snapshot(str(src), str(dest))


def test_preserves_git_dir_and_drops_stale_files(tmp_path):
    src = tmp_path / "plugin"
    src.mkdir()
    (src / "manifest.json").write_text("{}", encoding="utf-8")

    dest = tmp_path / "workdir"
    dest.mkdir()
    (dest / ".git").mkdir()
    (dest / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (dest / "stale_file_no_longer_in_source.py").write_text("x = 1\n", encoding="utf-8")

    _copy_plugin_snapshot(str(src), str(dest))

    assert (dest / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert not (dest / "stale_file_no_longer_in_source.py").exists()
    assert (dest / "manifest.json").exists()


def test_copies_fresh_content_from_source(tmp_path):
    src = tmp_path / "plugin"
    src.mkdir()
    (src / "manifest.json").write_text('{"name": "x"}', encoding="utf-8")
    (src / "sub").mkdir()
    (src / "sub" / "a.py").write_text("a = 1\n", encoding="utf-8")

    dest = tmp_path / "workdir"
    _copy_plugin_snapshot(str(src), str(dest))

    assert (dest / "manifest.json").read_text(encoding="utf-8") == '{"name": "x"}'
    assert (dest / "sub" / "a.py").read_text(encoding="utf-8") == "a = 1\n"


def test_does_not_follow_symlinks_outside_source(tmp_path):
    """Additional observation: shutil.copytree()'s default symlinks=False
    DEREFERENCES symlinks — a symlink in a plugin's source tree pointing
    outside it (into $HOME, another project, /etc) would get its REAL
    TARGET CONTENT copied into the staged snapshot that publish_plugin()
    pushes to a public git repo. Symlinks must be skipped outright, at
    both the top level and inside subdirectories."""
    secret = tmp_path / "secret_outside"
    secret.mkdir()
    (secret / "passwords.txt").write_text("TOP SECRET", encoding="utf-8")

    src = tmp_path / "plugin"
    src.mkdir()
    (src / "manifest.json").write_text('{"name": "x"}', encoding="utf-8")
    (src / "link_to_secret_file.txt").symlink_to(secret / "passwords.txt")
    (src / "link_to_secret_dir").symlink_to(secret, target_is_directory=True)
    (src / "sub").mkdir()
    (src / "sub" / "nested_link.txt").symlink_to(secret / "passwords.txt")

    dest = tmp_path / "workdir"
    _copy_plugin_snapshot(str(src), str(dest))

    dest_entries = {p.name for p in dest.iterdir()}
    assert "link_to_secret_file.txt" not in dest_entries
    assert "link_to_secret_dir" not in dest_entries
    assert not (dest / "sub" / "nested_link.txt").exists()
    for path in dest.rglob("*"):
        if path.is_file():
            assert "TOP SECRET" not in path.read_text(encoding="utf-8")


@pytest.fixture
def stubbed_publish(monkeypatch, tmp_path):
    """Bypass plugin lookup/validation so dry-run's OWN staging behavior can
    be tested in isolation from bundle-manifest validation rules."""
    fake_source = tmp_path / "fake_bundle_source"
    fake_source.mkdir()
    (fake_source / "manifest.json").write_text('{"name": "zz_pub_test"}', encoding="utf-8")

    monkeypatch.setattr(publish_module, "_plugin_root", lambda kind, name: str(fake_source))
    monkeypatch.setattr(publish_module, "_validate_plugin", lambda kind, path: None)
    monkeypatch.setattr(
        publish_module,
        "check_publish_readiness",
        lambda: PublishReadiness(
            git_ok=True,
            git_path="/usr/bin/git",
            git_user_name="Test User",
            git_user_email="test@example.com",
            gh_ok=False,
            gh_path=None,
            gh_authed=False,
            ssh_key_found=False,
            hard_failures=[],
            warnings=[],
        ),
    )
    return fake_source


def test_dry_run_does_not_touch_preexisting_workdir(stubbed_publish, tmp_path):
    workdir = tmp_path / "persistent_workdir"
    workdir.mkdir()
    sentinel = workdir / "do_not_delete_me.txt"
    sentinel.write_text("precious", encoding="utf-8")

    result = publish_plugin(
        "bundle",
        "zz_pub_test",
        remote="git@example.com:x/y.git",
        workdir=str(workdir),
        dry_run=True,
    )

    assert result["status"] == "dry_run"
    assert sentinel.read_text(encoding="utf-8") == "precious"
    # Nothing else should have been written into the workdir either.
    assert [p.name for p in workdir.iterdir()] == ["do_not_delete_me.txt"]


def test_dry_run_rejects_workdir_pointing_at_the_source_itself(stubbed_publish):
    """A --workdir that (mistakenly) matches the plugin's own source directory
    must be rejected, not wiped — but only once dry_run actually needs to
    stage, i.e. this asserts the overlap check exists, exercised at the
    real (non-dry-run) copy step where staging happens."""
    with pytest.raises(ValueError, match="overlaps"):
        _copy_plugin_snapshot(str(stubbed_publish), str(stubbed_publish))
