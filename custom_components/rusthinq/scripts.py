"""rusthinq-scripts (the Rhai drivers) in `<config>/rusthinq/scripts`: which commit is there and how the pinned one
gets in.

The integration pins one dated rusthinq-scripts release (`RELEASE`, by its commit `COMMIT`), so drivers change only with
an integration release. A start whose installed commit differs from the pin installs the pinned one.

A GitHub tarball carries its commit in `VERSION` (`export-subst`: `<sha> <date>`). The daemon watches the directory it
canonicalized at start (`driver_watch.rs`, inotify, recursive), so an update changes files inside `scripts/` (each
replaced atomically, removed ones deleted), as a `git pull` would, and the daemon reloads the drivers by itself;
replacing the directory itself would leave the daemon watching the old one. The first install, with no daemon running,
moves the unpacked tree in whole.

Only files the previous release installed are deleted, so a driver a user added (a `<model>.rhai` at the top of
`scripts/`, which rusthinq picks before `drivers/<model>.rhai`, or one copied into `drivers/`) survives an update.
`RELEASE_FILES` lists what the installed release put there; an installation from before it existed has none, and that
update deletes nothing. A user's edit of a file the release ships is still replaced.
"""

from __future__ import annotations

import io
import os
import shutil
import tarfile
from pathlib import Path

import aiohttp

REPOSITORY = "3735943886/rusthinq-scripts"
RELEASE = "2026.11.25"
"""The pinned dated release of rusthinq-scripts; move it together with `COMMIT`."""
COMMIT = "89712e52d3c3569ac805cb28df31995508c5c384"
"""The commit `RELEASE` tags. Downloads are by commit, so a moved tag cannot change what is installed."""
DOWNLOAD_TIMEOUT = aiohttp.ClientTimeout(total=120)
RELEASE_FILES = ".release-files"
"""In `scripts/`: the files the installed release put there, one relative path per line."""


class ScriptsError(Exception):
    """rusthinq-scripts could not be checked, downloaded or installed."""


def tarball_url(ref: str) -> str:
    return f"https://codeload.github.com/{REPOSITORY}/tar.gz/{ref}"


def installed_commit(directory: Path) -> str | None:
    """The commit `scripts/VERSION` names, or None (no scripts, or a checkout whose VERSION was not substituted)."""
    try:
        sha = (directory / "scripts" / "VERSION").read_text().split()[0]
    except (OSError, IndexError):
        return None
    return sha if len(sha) == 40 and all(c in "0123456789abcdef" for c in sha) else None


async def download(http: aiohttp.ClientSession, ref: str = COMMIT) -> bytes:
    try:
        async with http.get(tarball_url(ref), timeout=DOWNLOAD_TIMEOUT) as response:
            response.raise_for_status()
            return await response.read()
    except (aiohttp.ClientError, TimeoutError) as err:
        raise ScriptsError(f"could not download rusthinq-scripts: {err}") from err


def install(directory: Path, tarball: bytes) -> None:
    """Put a rusthinq-scripts tarball into `directory/scripts`: whole on the first install, file by file after."""
    staging = directory / ".scripts.new"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(tarball), mode="r:gz") as archive:
            archive.extractall(staging, filter="data")
        roots = [p for p in staging.iterdir() if p.is_dir()]
        if len(roots) != 1 or not (roots[0] / "drivers").is_dir():
            raise ScriptsError("the rusthinq-scripts download has no drivers directory")
        target = directory / "scripts"
        if target.is_dir():
            _sync(roots[0], target)
        else:
            _write_release_files(roots[0], _files(roots[0]))
            roots[0].rename(target)
    except (OSError, tarfile.TarError) as err:
        raise ScriptsError(f"could not install rusthinq-scripts: {err}") from err
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def _files(root: Path) -> set[Path]:
    return {p.relative_to(root) for p in root.rglob("*") if p.is_file()} - {Path(RELEASE_FILES)}


def _release_files(target: Path) -> set[Path] | None:
    """What the installed release put into `target`, or None when it was installed before this was recorded."""
    try:
        return {Path(line) for line in (target / RELEASE_FILES).read_text().splitlines() if line}
    except OSError:
        return None


def _write_release_files(target: Path, files: set[Path]) -> None:
    tmp = target / f".{RELEASE_FILES}.tmp"
    tmp.write_text("".join(f"{rel.as_posix()}\n" for rel in sorted(files)))
    os.replace(tmp, target / RELEASE_FILES)


def _sync(source: Path, target: Path) -> None:
    """Make `target` hold what `source` holds, touching only what differs, and delete what the previous release
    installed and this one does not; files a user added stay. `VERSION` last, so it names the commit only once every
    file of it is in place."""
    wanted = _files(source)
    previous = _release_files(target)
    for rel in sorted(wanted - {Path("VERSION")}):
        _copy(source / rel, target / rel)
    for rel in sorted((previous or set()) - wanted, reverse=True):
        old = target / rel
        if old.is_file():
            old.unlink()
        parent = old.parent
        while parent != target and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent
    _write_release_files(target, wanted)
    if Path("VERSION") in wanted:
        _copy(source / "VERSION", target / "VERSION")


def _copy(new: Path, old: Path) -> None:
    if old.is_file() and old.read_bytes() == new.read_bytes():
        return
    old.parent.mkdir(parents=True, exist_ok=True)
    tmp = old.with_name(f".{old.name}.tmp")
    shutil.copyfile(new, tmp)
    os.replace(tmp, old)