"""Release activation history stack, maintenance barrier, and retention pruning."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

if not __package__:
    _SELF_DIR = str(Path(__file__).resolve().parent)
    if _SELF_DIR not in sys.path:
        sys.path.insert(0, _SELF_DIR)
    import runtime as _rt  # type: ignore[import-not-found]
else:
    from . import runtime as _rt

DeployError = _rt.DeployError
requirements_venv_id = _rt.requirements_venv_id
validate_release_id = _rt.validate_release_id


def enter_maintenance(app_root: Path) -> Path:
    shared_dir = app_root / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(app_root, 0o755)
    os.chmod(shared_dir, 0o755)
    maint = shared_dir / ".maintenance"
    maint.write_text(f"{datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
    os.chmod(maint, 0o644)
    return maint


def exit_maintenance(app_root: Path) -> None:
    (app_root / "shared" / ".maintenance").unlink(missing_ok=True)


def current_release_target(current_link: Path) -> Path | None:
    if not current_link.is_symlink() and not current_link.exists():
        return None
    resolved = current_link.resolve()
    return resolved if resolved.is_dir() else None


def is_activated_release(release_dir: Path) -> bool:
    return (
        release_dir.is_dir()
        and not release_dir.is_symlink()
        and (release_dir / ".activated").is_file()
        and (release_dir / "server" / "manage.py").is_file()
    )


def read_release_history(app_root: Path) -> list[str]:
    history_file = app_root / ".release-history"
    releases_dir = app_root / "releases"
    if not history_file.is_file():
        if not releases_dir.is_dir():
            return []
        seeded = sorted(
            (d for d in releases_dir.iterdir() if is_activated_release(d)),
            key=lambda d: (d.stat().st_mtime_ns, d.name),
        )
        return [d.name for d in seeded]
    valid: list[str] = []
    for raw in history_file.read_text(encoding="utf-8").splitlines():
        rid = raw.strip()
        if (
            rid
            and rid not in {".", ".."}
            and _rt.SAFE_RELEASE_ID_RE.fullmatch(rid)
            and rid not in valid
            and is_activated_release(releases_dir / rid)
        ):
            valid.append(rid)
    return valid


def write_release_history(app_root: Path, history: Sequence[str]) -> None:
    history_file = app_root / ".release-history"
    tmp_file = app_root / f".release-history.tmp.{os.getpid()}"
    tmp_file.write_text("".join(f"{item}\n" for item in history), encoding="utf-8")
    os.chmod(tmp_file, 0o644)
    os.replace(tmp_file, history_file)


def record_activated_release(app_root: Path, release_dir: Path) -> None:
    marker = release_dir / ".activated"
    marker.write_text(f"{datetime.now(timezone.utc).isoformat()}\n", encoding="utf-8")
    os.chmod(marker, 0o644)
    history = [rid for rid in read_release_history(app_root) if rid != release_dir.name]
    history.append(release_dir.name)
    write_release_history(app_root, history)


def select_rollback_target(
    app_root: Path, prior_target: Path | None, to_release: str | None
) -> tuple[Path, list[str]]:
    releases_dir = app_root / "releases"
    history = read_release_history(app_root)
    if to_release:
        clean_to = validate_release_id(to_release, label="--to")
        target_dir = releases_dir / clean_to
        if not is_activated_release(target_dir):
            raise DeployError(f"Target activated release {clean_to!r} does not exist under {releases_dir}")
        next_history = [rid for rid in history if rid != clean_to] + [clean_to]
        return target_dir, next_history

    prior_name = prior_target.name if prior_target is not None else None
    if prior_name in history:
        idx = history.index(prior_name)
        if idx == 0:
            raise DeployError("No earlier activated release in history to roll back to.")
        next_history = history[:idx]
        return releases_dir / next_history[-1], next_history

    candidates = [rid for rid in history if rid != prior_name]
    if not candidates:
        raise DeployError("No historical activated release available in releases/ to roll back to.")
    return releases_dir / candidates[-1], candidates


def _prune_entries(entries: list[Path], *, keep: int, protected: set[Path], is_dir: bool) -> None:
    resolved_protected = {p.resolve() for p in protected}
    ordered = sorted(entries, key=lambda p: (p.stat().st_mtime_ns, p.name), reverse=True)
    for old_item in ordered[max(1, keep) :]:
        if old_item.resolve() not in resolved_protected:
            if is_dir:
                shutil.rmtree(old_item)
            else:
                old_item.unlink()


def prune_old_releases_and_venvs(
    app_root: Path, *, keep: int, protected: set[Path], clean_legacy_stash: bool = False
) -> None:
    releases_dir = app_root / "releases"
    if releases_dir.is_dir():
        candidates = [d for d in releases_dir.iterdir() if d.is_dir() and not d.is_symlink()]
        _prune_entries(candidates, keep=keep, protected=protected, is_dir=True)
        write_release_history(app_root, read_release_history(app_root))

    shared_dir = app_root / "shared"
    if clean_legacy_stash and shared_dir.is_dir():
        for legacy_dir in shared_dir.glob(".venv.legacy*"):
            shutil.rmtree(legacy_dir, ignore_errors=True)

    venvs_root = shared_dir / "venvs"
    if not venvs_root.is_dir():
        return
    referenced_ids: set[str] = set()
    if releases_dir.is_dir():
        for rel_dir in releases_dir.iterdir():
            req_file = rel_dir / "server" / "requirements.txt"
            if req_file.is_file():
                referenced_ids.add(requirements_venv_id(req_file))
    active_venv = shared_dir / "venv"
    if active_venv.exists() or active_venv.is_symlink():
        referenced_ids.add(active_venv.resolve().name)
    for entry in venvs_root.iterdir():
        if entry.name not in referenced_ids:
            if entry.is_symlink():
                entry.unlink()
            elif entry.is_dir():
                shutil.rmtree(entry)


def prune_old_backups(var_dir: Path, *, keep: int, protected: set[Path]) -> None:
    _rt._confinement_to_deploy_error(
        _rt._fs.prune_backups_nofollow,
        var_dir,
        keep=keep,
        protected_names={p.name for p in protected},
    )
