"""Descriptor-anchored O_NOFOLLOW path confinement and permission setup for var_dir."""

from __future__ import annotations

import contextlib
import os
import pwd
import stat
from collections.abc import Sequence
from pathlib import Path


class FsConfinementError(RuntimeError):
    """Raised when a persistent path escapes var_dir or traverses a symlink."""


def _resolve_clean_abs(label: str, raw_path: Path) -> Path:
    if not raw_path.is_absolute() or ".." in raw_path.parts or "." in raw_path.parts[1:]:
        raise FsConfinementError(f"{label} must be a clean absolute path without '..', got {raw_path!r}.")
    if raw_path.is_symlink():
        raise FsConfinementError(f"{label} must not be a symlink: {raw_path}")
    resolved = raw_path.resolve(strict=False)
    if resolved.is_symlink():
        raise FsConfinementError(f"Resolved {label} must not be a symlink: {resolved}")
    return resolved


def _trees_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def validate_disjoint_roots(
    app_root: Path,
    var_dir: Path,
    static_web_root: Path,
    *,
    etc_env: Path | None = None,
) -> tuple[Path, Path]:
    """Ensure app_root, var_dir, and static_web_root are strictly disjoint before any filesystem mutation."""
    r_app = _resolve_clean_abs("app_root", app_root)
    r_var = _resolve_clean_abs("var_dir", var_dir)
    r_web = _resolve_clean_abs("static_web_root", static_web_root)
    for left_name, left_p, right_name, right_p in (
        ("var_dir", r_var, "app_root", r_app),
        ("var_dir", r_var, "static_web_root", r_web),
        ("app_root", r_app, "static_web_root", r_web),
    ):
        if _trees_overlap(left_p, right_p):
            raise FsConfinementError(
                f"{left_name} ({left_p}) and {right_name} ({right_p}) must be disjoint directory trees."
            )
    if etc_env is not None:
        r_env = _resolve_clean_abs("etc_env", etc_env)
        for root_name, root_p in (("app_root", r_app), ("var_dir", r_var), ("static_web_root", r_web)):
            if _trees_overlap(r_env, root_p):
                raise FsConfinementError(f"etc_env ({r_env}) must not reside inside {root_name} ({root_p}).")
    return r_app, r_var


def anchor_var_root(var_dir: Path) -> Path:
    anchored = _resolve_clean_abs("var_dir", var_dir)
    anchored.parent.mkdir(parents=True, exist_ok=True)
    if anchored.is_symlink():
        raise FsConfinementError(f"Anchored var_dir must not be a symlink: {anchored}")
    return anchored


def extract_var_rel_parts(
    name: str, raw_value: str, *, var_dir: Path, anchored_var: Path
) -> tuple[Path, tuple[str, ...]]:
    if not raw_value or raw_value == ":memory:":
        raise FsConfinementError(f"{name} must not be empty or ':memory:' in server deployment.")
    candidate = Path(raw_value)
    if not candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts[1:]:
        raise FsConfinementError(f"{name} must be a normalized absolute path without '..', got {raw_value!r}.")

    rel_parts: tuple[str, ...] | None = None
    for prefix in (var_dir, anchored_var):
        try:
            rel = candidate.relative_to(prefix)
        except ValueError:
            continue
        rel_parts = rel.parts
        break

    if rel_parts is None or len(rel_parts) == 0:
        raise FsConfinementError(f"{name} ({raw_value}) must reside strictly inside var_dir ({anchored_var}).")
    if rel_parts[0] == "backups":
        raise FsConfinementError(
            f"{name} ({raw_value}) must not reside inside retention-managed backups/ directory."
        )
    if name == "SQLITE_PATH" and rel_parts[0] in {"cache", "mail"}:
        raise FsConfinementError(f"SQLITE_PATH ({raw_value}) must not reside inside {rel_parts[0]}/ directory.")
    return anchored_var.joinpath(*rel_parts), rel_parts


def _open_dir_nofollow(name: str, *, dir_fd: int | None, display_path: Path) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    try:
        fd = os.open(name, flags, dir_fd=dir_fd)
    except OSError as exc:
        raise FsConfinementError(f"Refusing to traverse symlink or non-directory at {display_path}: {exc}") from exc
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) and stat.S_ISDIR(st.st_mode):
            return fd
        os.close(fd)
        raise FsConfinementError(f"Expected directory at {display_path}, got mode {oct(st.st_mode)}.")
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        raise


def _ensure_subdir_chain_fd(
    var_fd: int,
    anchored_var: Path,
    rel_parts: Sequence[str],
    *,
    leaf_mode: int,
    owner_ids: tuple[int, int] | None,
) -> int:
    cur_fd = os.dup(var_fd)
    cur_path = anchored_var
    try:
        for idx, part in enumerate(rel_parts):
            cur_path = cur_path / part
            mode = leaf_mode if idx == len(rel_parts) - 1 else 0o750
            try:
                os.mkdir(part, mode, dir_fd=cur_fd)
            except FileExistsError:
                pass
            except OSError as exc:
                raise FsConfinementError(f"Failed to create directory {cur_path}: {exc}") from exc
            next_fd = _open_dir_nofollow(part, dir_fd=cur_fd, display_path=cur_path)
            os.close(cur_fd)
            cur_fd = next_fd
            os.fchmod(cur_fd, mode)
            if owner_ids is not None:
                os.fchown(cur_fd, *owner_ids)
        return cur_fd
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(cur_fd)
        raise


def prepare_var_dirs_nofollow(
    var_dir: Path,
    *,
    sqlite_path: Path,
    cache_path: Path,
    email_file_path: Path,
    service_user: str,
) -> tuple[str | None, tuple[int, int] | None]:
    anchored_var = anchor_var_root(var_dir)
    _, sqlite_rel = extract_var_rel_parts("SQLITE_PATH", str(sqlite_path), var_dir=var_dir, anchored_var=anchored_var)
    _, cache_rel = extract_var_rel_parts(
        "DJANGO_CACHE_PATH", str(cache_path), var_dir=var_dir, anchored_var=anchored_var
    )
    _, mail_rel = extract_var_rel_parts(
        "EMAIL_FILE_PATH", str(email_file_path), var_dir=var_dir, anchored_var=anchored_var
    )

    cleaned_user: str | None = None
    owner_ids: tuple[int, int] | None = None
    if os.geteuid() == 0:
        candidate_user = service_user.strip()
        if not candidate_user:
            raise FsConfinementError("service_user must be non-empty when running as root.")
        try:
            account = pwd.getpwnam(candidate_user)
        except KeyError as exc:
            raise FsConfinementError(f"Configured service_user {candidate_user!r} does not exist on host.") from exc
        cleaned_user = candidate_user
        owner_ids = (account.pw_uid, account.pw_gid)

    parent_fd = _open_dir_nofollow(str(anchored_var.parent), dir_fd=None, display_path=anchored_var.parent)
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(anchored_var.name, 0o750, dir_fd=parent_fd)
        var_fd = _open_dir_nofollow(anchored_var.name, dir_fd=parent_fd, display_path=anchored_var)
    finally:
        os.close(parent_fd)

    try:
        os.fchmod(var_fd, 0o750)
        if owner_ids is not None:
            os.fchown(var_fd, *owner_ids)

        for rel_parts, mode in (
            (("backups",), 0o750),
            (("cache",), 0o700),
            (("mail",), 0o700),
            (cache_rel, 0o700),
            (mail_rel, 0o700),
        ):
            sub_fd = _ensure_subdir_chain_fd(var_fd, anchored_var, rel_parts, leaf_mode=mode, owner_ids=owner_ids)
            os.close(sub_fd)

        db_parent_parts = sqlite_rel[:-1]
        db_parent_fd = (
            _ensure_subdir_chain_fd(var_fd, anchored_var, db_parent_parts, leaf_mode=0o750, owner_ids=owner_ids)
            if db_parent_parts
            else os.dup(var_fd)
        )
        try:
            db_parent_display = anchored_var.joinpath(*db_parent_parts)
            for suffix in ("", "-wal", "-shm"):
                fname = f"{sqlite_rel[-1]}{suffix}"
                fdisplay = db_parent_display / fname
                try:
                    file_fd = os.open(fname, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=db_parent_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    raise FsConfinementError(f"Refusing symlink or unsafe SQLite file at {fdisplay}: {exc}") from exc
                try:
                    st = os.fstat(file_fd)
                    if not stat.S_ISREG(st.st_mode):
                        raise FsConfinementError(f"SQLite file must be a regular file at {fdisplay}.")
                    if owner_ids is not None:
                        os.fchown(file_fd, *owner_ids)
                finally:
                    os.close(file_fd)
        finally:
            os.close(db_parent_fd)
    finally:
        os.close(var_fd)

    return cleaned_user, owner_ids


def prune_backups_nofollow(
    var_dir: Path, *, keep: int, protected_names: set[str]
) -> None:
    """Prune historical SQLite snapshots strictly via dir_fd + O_NOFOLLOW."""
    anchored_var = anchor_var_root(var_dir)
    dir_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    try:
        var_fd = os.open(str(anchored_var), dir_flags)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise FsConfinementError(f"Refusing unsafe var_dir {anchored_var}: {exc}") from exc

    try:
        if not stat.S_ISDIR(os.fstat(var_fd).st_mode):
            raise FsConfinementError(f"Expected directory at {anchored_var}.")
        try:
            bk_fd = os.open("backups", dir_flags, dir_fd=var_fd)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise FsConfinementError(
                f"Refusing symlink or unsafe backups directory at {anchored_var / 'backups'}: {exc}"
            ) from exc

        try:
            if not stat.S_ISDIR(os.fstat(bk_fd).st_mode):
                raise FsConfinementError(f"Expected directory at {anchored_var / 'backups'}.")
            scan_fd = os.dup(bk_fd)
            candidates: list[tuple[int, str]] = []
            try:
                with os.scandir(scan_fd) as entries:
                    for entry in entries:
                        name = entry.name
                        if not (
                            (name.startswith("db-") or name.startswith("pre-rollback-"))
                            and name.endswith(".sqlite3")
                        ):
                            continue
                        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                            continue
                        st = entry.stat(follow_symlinks=False)
                        if stat.S_ISREG(st.st_mode):
                            candidates.append((st.st_mtime_ns, name))
            finally:
                os.close(scan_fd)

            candidates.sort(reverse=True)
            for _, old_name in candidates[max(1, keep) :]:
                if old_name in protected_names:
                    continue
                st = os.stat(old_name, dir_fd=bk_fd, follow_symlinks=False)
                if stat.S_ISREG(st.st_mode):
                    os.unlink(old_name, dir_fd=bk_fd)
        finally:
            os.close(bk_fd)
    finally:
        os.close(var_fd)


def prepare_temp_writable_dir_nofollow(
    parent_dir: Path, name: str, *, owner_ids: tuple[int, int] | None
) -> Path:
    """Create `<parent_dir>/<name>` via dir_fd + O_NOFOLLOW and grant temporary `owner_ids`."""
    parent_fd = _open_dir_nofollow(str(parent_dir), dir_fd=None, display_path=parent_dir)
    target_path = parent_dir / name
    try:
        with contextlib.suppress(FileExistsError):
            os.mkdir(name, 0o755, dir_fd=parent_fd)
        dir_fd = _open_dir_nofollow(name, dir_fd=parent_fd, display_path=target_path)
        try:
            os.fchmod(dir_fd, 0o755)
            if owner_ids is not None:
                os.fchown(dir_fd, *owner_ids)
        finally:
            os.close(dir_fd)
    finally:
        os.close(parent_fd)
    return target_path


def _reclaim_dir_fd_to_root(dir_fd: int, display_path: Path, *, reclaim_owner: bool) -> None:
    # Lock parent directory to root:root 0755 BEFORE inspecting children so service_user
    # can no longer create, rename, or swap entries inside it.
    if reclaim_owner:
        os.fchown(dir_fd, 0, 0)
    os.fchmod(dir_fd, 0o755)

    scan_fd = os.dup(dir_fd)
    child_names: list[str] = []
    try:
        with os.scandir(scan_fd) as it:
            for entry in it:
                child_names.append(entry.name)
    finally:
        os.close(scan_fd)

    for name in child_names:
        child_display = display_path / name
        st = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if stat.S_ISLNK(st.st_mode):
            raise FsConfinementError(f"Symlink not permitted in collected staticfiles: {child_display}")
        if stat.S_ISDIR(st.st_mode):
            sub_fd = _open_dir_nofollow(name, dir_fd=dir_fd, display_path=child_display)
            try:
                _reclaim_dir_fd_to_root(sub_fd, child_display, reclaim_owner=reclaim_owner)
            finally:
                os.close(sub_fd)
        elif stat.S_ISREG(st.st_mode):
            if st.st_nlink != 1:
                raise FsConfinementError(
                    f"Hardlinked file (nlink={st.st_nlink}) not permitted in staticfiles: {child_display}"
                )
            try:
                file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
            except OSError as exc:
                raise FsConfinementError(f"Unsafe static asset at {child_display}: {exc}") from exc
            try:
                fst = os.fstat(file_fd)
                if not stat.S_ISREG(fst.st_mode) or fst.st_nlink != 1:
                    raise FsConfinementError(f"Static asset changed to non-unique/non-regular file: {child_display}")
                if reclaim_owner:
                    os.fchown(file_fd, 0, 0)
                os.fchmod(file_fd, 0o644)
            finally:
                os.close(file_fd)
        else:
            raise FsConfinementError(f"Unsupported special file in staticfiles: {child_display}")


def reclaim_tree_to_root_nofollow(target_dir: Path, *, reclaim_owner: bool) -> None:
    """Reclaim `target_dir` tree back to root:root (0755/0644) strictly via dir_fd + O_NOFOLLOW."""
    dir_fd = _open_dir_nofollow(str(target_dir), dir_fd=None, display_path=target_dir)
    try:
        _reclaim_dir_fd_to_root(dir_fd, target_dir, reclaim_owner=reclaim_owner)
    finally:
        os.close(dir_fd)


def unlink_sqlite_files_nofollow(var_dir: Path, sqlite_path: Path) -> None:
    """Unlink newly created SQLite file and WAL/SHM sidecars strictly via dir_fd + O_NOFOLLOW."""
    anchored_var = anchor_var_root(var_dir)
    _, sqlite_rel = extract_var_rel_parts("SQLITE_PATH", str(sqlite_path), var_dir=var_dir, anchored_var=anchored_var)
    try:
        cur_fd = _open_dir_nofollow(str(anchored_var), dir_fd=None, display_path=anchored_var)
    except FsConfinementError:
        if not anchored_var.exists() and not anchored_var.is_symlink():
            return
        raise
    cur_display = anchored_var
    try:
        for part in sqlite_rel[:-1]:
            cur_display = cur_display / part
            try:
                next_fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0), dir_fd=cur_fd)
            except FileNotFoundError:
                return
            except OSError as exc:
                raise FsConfinementError(f"Refusing symlink or unsafe SQLite parent at {cur_display}: {exc}") from exc
            if not stat.S_ISDIR(os.fstat(next_fd).st_mode):
                os.close(next_fd)
                raise FsConfinementError(f"Expected directory for SQLite parent at {cur_display}.")
            os.close(cur_fd)
            cur_fd = next_fd

        for suffix in ("", "-wal", "-shm"):
            fname = f"{sqlite_rel[-1]}{suffix}"
            try:
                st = os.stat(fname, dir_fd=cur_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue
            if stat.S_ISDIR(st.st_mode):
                raise FsConfinementError(f"Refusing directory at SQLite file path {cur_display / fname}.")
            os.unlink(fname, dir_fd=cur_fd)
    finally:
        os.close(cur_fd)
