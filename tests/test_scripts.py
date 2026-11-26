"""rusthinq-scripts: installing the pinned release and changing to another pin, against the real daemon."""

import gzip
import io
import json
import re
import shutil
import tarfile
from pathlib import Path

import aiohttp
import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rusthinq import scripts
from custom_components.rusthinq.const import (
    CONF_HTTPS_PORT,
    CONF_MODE,
    CONF_MQTT_PORT,
    CONF_PREFIX,
    CONF_THINQ1_HTTPS_PORT,
    CONF_THINQ1_PORT,
    DOMAIN,
    MODE_EMBEDDED,
)

OLD, NEW = "a" * 40, "b" * 40
"""The commit installed before, and the one the integration pins (`scripts.COMMIT`, stubbed)."""


def tarball(files: dict[str, str]) -> bytes:
    """A GitHub-style tarball: everything under one top directory."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as archive:
        for name, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"rusthinq-scripts-{NEW[:7]}/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(buf.getvalue())


OLD_TREE = {"VERSION": f"{OLD} 2026-10-31\n", "drivers/A.rhai": "// a", "drivers/B.rhai": "// b",
            "modules/gone/x.rhai": "// x", "modules/common.rhai": "// c"}
NEW_TREE = {"VERSION": f"{NEW} 2026-11-01\n", "drivers/A.rhai": "// a", "drivers/B.rhai": "// b2",
            "drivers/C.rhai": "// c", "modules/common.rhai": "// c"}


def tree(directory: Path) -> dict[str, str]:
    return {str(p.relative_to(directory)): p.read_text() for p in sorted(directory.rglob("*"))
            if p.is_file() and p.name != scripts.RELEASE_FILES}


def test_the_first_install_moves_the_tree_in(tmp_path):
    scripts.install(tmp_path, tarball(OLD_TREE))
    assert tree(tmp_path / "scripts") == OLD_TREE
    assert [p.name for p in tmp_path.iterdir()] == ["scripts"]
    assert scripts.installed_commit(tmp_path) == OLD


def test_an_update_changes_files_inside_the_watched_directory(tmp_path):
    scripts.install(tmp_path, tarball(OLD_TREE))
    directory = tmp_path / "scripts"
    inode, unchanged = directory.stat().st_ino, (directory / "drivers/A.rhai").stat().st_ino
    scripts.install(tmp_path, tarball(NEW_TREE))
    assert tree(directory) == NEW_TREE
    assert directory.stat().st_ino == inode  # the daemon keeps watching it
    assert (directory / "drivers/A.rhai").stat().st_ino == unchanged
    assert not (directory / "modules/gone").exists()
    assert scripts.installed_commit(tmp_path) == NEW


def test_files_a_user_added_survive_an_update(tmp_path):
    """A driver override at the top of scripts/ (rusthinq picks it first) or copied into drivers/ is the user's."""
    scripts.install(tmp_path, tarball(OLD_TREE))
    directory = tmp_path / "scripts"
    (directory / "H05.rhai").write_text("// my H05")
    (directory / "drivers/X.rhai").write_text("// my X")
    scripts.install(tmp_path, tarball(NEW_TREE))
    assert tree(directory) == {**NEW_TREE, "H05.rhai": "// my H05", "drivers/X.rhai": "// my X"}
    assert not (directory / "modules/gone").exists()  # the previous release's own file still goes


def test_the_release_files_are_recorded(tmp_path):
    scripts.install(tmp_path, tarball(OLD_TREE))
    recorded = (tmp_path / "scripts" / scripts.RELEASE_FILES).read_text().splitlines()
    assert recorded == sorted(OLD_TREE)
    scripts.install(tmp_path, tarball(NEW_TREE))
    assert (tmp_path / "scripts" / scripts.RELEASE_FILES).read_text().splitlines() == sorted(NEW_TREE)


def test_an_installation_without_a_record_deletes_nothing_on_its_first_update(tmp_path):
    """Installed before the record existed, a file there may be the release's or the user's: keep both, once."""
    scripts.install(tmp_path, tarball(OLD_TREE))
    directory = tmp_path / "scripts"
    (directory / scripts.RELEASE_FILES).unlink()
    (directory / "drivers/X.rhai").write_text("// my X")
    scripts.install(tmp_path, tarball(NEW_TREE))
    assert tree(directory) == {**NEW_TREE, "modules/gone/x.rhai": "// x", "drivers/X.rhai": "// my X"}
    scripts.install(tmp_path, tarball(OLD_TREE))  # from here on the record knows the release's files
    assert not (directory / "drivers/C.rhai").exists()
    assert (directory / "drivers/X.rhai").read_text() == "// my X"


def test_a_download_without_drivers_changes_nothing(tmp_path):
    scripts.install(tmp_path, tarball(OLD_TREE))
    with pytest.raises(scripts.ScriptsError, match="no drivers"):
        scripts.install(tmp_path, tarball({"README.md": "?"}))
    assert tree(tmp_path / "scripts") == OLD_TREE
    assert [p.name for p in tmp_path.iterdir()] == ["scripts"]


def test_an_unsubstituted_version_is_no_commit(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "VERSION").write_text("$Format:%H %cs$\n")
    assert scripts.installed_commit(tmp_path) is None
    assert scripts.installed_commit(tmp_path / "missing") is None


@pytest.fixture
def embedded_entry(hass, tmp_path, socket_enabled, enable_custom_integrations, monkeypatch):
    hass.config.config_dir = str(tmp_path)
    scripts.install(tmp_path / DOMAIN, tarball(OLD_TREE))
    downloads = []

    async def download(_http, ref=None):
        downloads.append(ref or scripts.COMMIT)
        return tarball(NEW_TREE)

    monkeypatch.setattr(scripts, "COMMIT", NEW)
    monkeypatch.setattr(scripts, "download", download)
    entry = MockConfigEntry(domain=DOMAIN, unique_id=MODE_EMBEDDED, data={
        CONF_MODE: MODE_EMBEDDED, CONF_PREFIX: "rusthinq", CONF_HTTPS_PORT: 0, CONF_MQTT_PORT: 0,
        CONF_THINQ1_HTTPS_PORT: 0, CONF_THINQ1_PORT: 0})
    entry.add_to_hass(hass)
    entry.downloads = downloads
    return entry


async def daemon_source(entry) -> dict:
    daemon = entry.runtime_data.daemon
    async with aiohttp.ClientSession() as http, http.get(f"{daemon.url}/api/diagnostics",
                                                          headers=daemon.headers) as response:
        return json.loads(await response.text())["drivers"]["source"]


async def test_a_start_installs_the_pinned_release(hass, embedded_entry):
    entry = embedded_entry
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.downloads == [NEW]
    assert (await daemon_source(entry))["commit"] == NEW
    assert await hass.config_entries.async_unload(entry.entry_id)

    assert await hass.config_entries.async_setup(entry.entry_id)
    assert entry.downloads == [NEW]  # already pinned: nothing downloaded
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_failed_download_keeps_the_installed_drivers(hass, embedded_entry, monkeypatch):
    async def offline(_http, ref=None):
        raise scripts.ScriptsError("offline")

    monkeypatch.setattr(scripts, "download", offline)
    entry = embedded_entry
    assert await hass.config_entries.async_setup(entry.entry_id)
    assert (await daemon_source(entry))["commit"] == OLD
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_without_drivers_a_failed_download_fails_the_start(hass, embedded_entry, monkeypatch, tmp_path):
    async def offline(_http, ref=None):
        raise scripts.ScriptsError("offline")

    monkeypatch.setattr(scripts, "download", offline)
    shutil.rmtree(tmp_path / DOMAIN / "scripts")
    assert not await hass.config_entries.async_setup(embedded_entry.entry_id)
    assert embedded_entry.state is ConfigEntryState.SETUP_RETRY


async def test_the_old_drivers_update_entity_is_removed(hass, embedded_entry):
    registry = er.async_get(hass)
    old = registry.async_get_or_create("update", DOMAIN, f"{embedded_entry.entry_id}-scripts",
                                       config_entry=embedded_entry)
    assert await hass.config_entries.async_setup(embedded_entry.entry_id)
    assert registry.async_get(old.entity_id) is None
    assert await hass.config_entries.async_unload(embedded_entry.entry_id)


def test_the_pin_names_a_dated_release_and_a_full_commit():
    assert re.fullmatch(r"\d{4}\.\d{2}\.\d{2}(\.[1-9]\d*)?", scripts.RELEASE)
    assert re.fullmatch(r"[0-9a-f]{40}", scripts.COMMIT)
