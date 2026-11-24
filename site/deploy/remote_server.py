#!/usr/bin/env python3
"""Atomic release deployment, SQLite hot backup, health probe, and auto-rollback CLI for site/server."""

from __future__ import annotations

import argparse
import dataclasses
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path

if not __package__:
    _SELF_DIR = str(Path(__file__).resolve().parent)
    if _SELF_DIR not in sys.path:
        sys.path.insert(0, _SELF_DIR)
    import history as _hist  # type: ignore[import-not-found]
    import runtime as _rt  # type: ignore[import-not-found]
    import sqlite_ops  # type: ignore[no-redef]
else:
    from . import history as _hist
    from . import runtime as _rt
    from . import sqlite_ops

DEFAULT_APP_ROOT = _rt.DEFAULT_APP_ROOT
DEFAULT_ETC_ENV = _rt.DEFAULT_ETC_ENV
DEFAULT_VAR_DIR = _rt.DEFAULT_VAR_DIR
DEFAULT_LOCK_FILE = _rt.DEFAULT_LOCK_FILE
DEFAULT_SERVICE_NAME = _rt.DEFAULT_SERVICE_NAME
DEFAULT_SERVICE_USER = _rt.DEFAULT_SERVICE_USER
DEFAULT_SYSTEMCTL_BIN = _rt.DEFAULT_SYSTEMCTL_BIN
DEFAULT_HEALTH_URL = _rt.DEFAULT_HEALTH_URL
DEFAULT_KEEP_RELEASES = _rt.DEFAULT_KEEP_RELEASES
DEFAULT_KEEP_BACKUPS = _rt.DEFAULT_KEEP_BACKUPS
DEFAULT_HEALTH_RETRIES = _rt.DEFAULT_HEALTH_RETRIES
DEFAULT_HEALTH_INTERVAL = _rt.DEFAULT_HEALTH_INTERVAL
DEFAULT_HEALTH_TIMEOUT = _rt.DEFAULT_HEALTH_TIMEOUT
DeployConfig = _rt.DeployConfig
DeployError = _rt.DeployError
activate_venv_for_release = _rt.activate_venv_for_release
atomic_switch_symlink = _rt.atomic_switch_symlink
build_runtime_env = _rt.build_runtime_env
ensure_release_venv = _rt.ensure_release_venv
exclusive_lock = _rt.exclusive_lock
is_healthy_payload = _rt.is_healthy_payload
load_and_validate_env_file = _rt.load_and_validate_env_file
normalize_tree_permissions = _rt.normalize_tree_permissions
prepare_var_dirs = _rt.prepare_var_dirs
run_checked = _rt.run_checked
stage_release = _rt.stage_release
validate_release_id = _rt.validate_release_id
wait_for_healthy = _rt.wait_for_healthy


def _install_sqlite_ops_helper(app_root: Path) -> Path:
    shared_dir = app_root / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(app_root, 0o755)
    os.chmod(shared_dir, 0o755)
    src = Path(sqlite_ops.__file__).resolve()
    dst = shared_dir / "sqlite_ops.py"
    if src != dst:
        tmp = shared_dir / f".sqlite_ops.py.tmp.{os.getpid()}"
        shutil.copyfile(src, tmp)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    else:
        os.chmod(dst, 0o644)
    return dst


def _run_sqlite_op(
    action: str, src: Path, dst: Path, *, helper_py: Path, python_bin: str, cwd: Path, as_user: str | None
) -> None:
    run_checked([python_bin, str(helper_py), action, str(src), str(dst)], cwd=cwd, as_user=as_user)


def _run_verify_schema(
    server_dir: Path, *, helper_py: Path, python_bin: str, env: Mapping[str, str], as_user: str | None, allow_newer: bool = False
) -> None:
    flags = ["--allow-newer-migrations"] if allow_newer else []
    run_checked([python_bin, str(helper_py), "verify-schema", *flags, str(server_dir)], cwd=server_dir, env=env, as_user=as_user)


def _safe_prune_backups_on_error(
    var_dir: Path, *, keep: int, protected: set[Path], errors: list[str] | None = None
) -> None:
    try:
        _hist.prune_old_backups(var_dir, keep=keep, protected=protected)
    except DeployError as exc:
        if errors is not None:
            errors.append(f"backup prune aborted: {exc}")


def _restore_release_state(
    cfg: DeployConfig,
    *,
    runtime_env: Mapping[str, str],
    sqlite_path: Path,
    helper_py: Path,
    python_bin: str,
    run_user: str | None,
    db_mutated: bool,
    restore_backup: Path | None,
    remove_new_db: bool,
    restore_target: Path | None,
) -> list[str]:
    errors: list[str] = []
    stopped_ok = True
    try:
        run_checked([cfg.systemctl_bin, "stop", cfg.service_name])
    except BaseException as exc:
        stopped_ok = False
        errors.append(f"service stop failed: {exc}")

    db_restored_ok = not db_mutated
    if db_mutated and stopped_ok:
        if remove_new_db:
            try:
                _rt._confinement_to_deploy_error(_rt._fs.unlink_sqlite_files_nofollow, cfg.var_dir, sqlite_path)
                db_restored_ok = True
            except (DeployError, OSError) as exc:
                errors.append(f"new DB cleanup failed: {exc}")
        elif restore_backup is None or restore_backup.is_symlink() or not restore_backup.is_file():
            errors.append(f"DB restore failed: expected backup snapshot missing or invalid ({restore_backup})")
        else:
            try:
                _run_sqlite_op(
                    "restore", restore_backup, sqlite_path, helper_py=helper_py, python_bin=python_bin, cwd=cfg.var_dir, as_user=run_user
                )
                db_restored_ok = True
            except BaseException as exc:
                errors.append(f"DB restore failed: {exc}")
    elif db_mutated and not stopped_ok:
        errors.append("skipped DB restore/cleanup because service stop failed")

    current_link = cfg.app_root / "current"
    if stopped_ok and db_restored_ok:
        if restore_target is not None and restore_target.is_dir():
            try:
                if not _rt.restore_stashed_legacy_dir(cfg.app_root / "shared" / "venv"):
                    activate_venv_for_release(cfg.app_root, restore_target)
                atomic_switch_symlink(current_link, restore_target)
                run_checked([cfg.systemctl_bin, "restart", cfg.service_name])
                wait_for_healthy(cfg, runtime_env)
            except BaseException as exc:
                errors.append(f"service recovery failed: {exc}")
        elif current_link.is_symlink():
            current_link.unlink(missing_ok=True)
            _rt.restore_stashed_legacy_dir(cfg.app_root / "shared" / "venv")
    return errors


def _warn_post_commit_prune(label: str, fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except (DeployError, OSError) as exc:
        print(f"warning: post-commit {label} cleanup failed (active release unaffected): {exc}", file=sys.stderr)


def deploy_release(cfg: DeployConfig, *, staged_server: Path, release_id: str) -> Path:
    clean_id = validate_release_id(release_id)
    _rt._confinement_to_deploy_error(
        _rt._fs.validate_disjoint_roots, cfg.app_root, cfg.var_dir, _rt.DEFAULT_STATIC_WEB_ROOT, etc_env=cfg.etc_env
    )
    with exclusive_lock(cfg.lock_file):
        parsed_env = load_and_validate_env_file(cfg.etc_env)
        runtime_env, sqlite_path, cache_path, mail_path = build_runtime_env(
            parsed_env, var_dir=cfg.var_dir, app_root=cfg.app_root
        )
        run_user, owner_ids = prepare_var_dirs(
            cfg.var_dir, sqlite_path=sqlite_path, cache_path=cache_path, email_file_path=mail_path, service_user=cfg.service_user
        )
        helper_py = _install_sqlite_ops_helper(cfg.app_root)
        current_link = cfg.app_root / "current"
        previous_target = _hist.current_release_target(current_link)
        prior_history = _hist.read_release_history(cfg.app_root)

        release_dir = stage_release(staged_server, cfg.app_root, clean_id, previous_target)
        server_dir = release_dir / "server"
        backup_path: Path | None = None
        had_existing_db = sqlite_path.exists()
        has_pending_migrations = True
        try:
            new_venv_dir = ensure_release_venv(cfg.app_root, server_dir / "requirements.txt")
            venv_python = new_venv_dir / "bin" / "python"
            staticfiles_dir = _rt._confinement_to_deploy_error(
                _rt._fs.prepare_temp_writable_dir_nofollow, server_dir, "staticfiles", owner_ids=owner_ids
            )
            run_checked(
                [str(venv_python), "manage.py", "collectstatic", "--noinput"],
                cwd=server_dir,
                env=runtime_env,
                as_user=run_user,
            )
            _rt._confinement_to_deploy_error(
                _rt._fs.reclaim_tree_to_root_nofollow, staticfiles_dir, reclaim_owner=(owner_ids is not None)
            )
            if not any(staticfiles_dir.iterdir()):
                raise DeployError("collectstatic produced an empty staticfiles/ directory.")
            run_checked([str(venv_python), "manage.py", "check", "--deploy"], cwd=server_dir, env=runtime_env, as_user=run_user)
            if had_existing_db:
                mig_cmd = ["runuser", "-u", run_user, "--"] if run_user else []
                mig_cmd.extend([str(venv_python), "manage.py", "migrate", "--check", "--noinput"])
                mig_probe = subprocess.run(mig_cmd, cwd=str(server_dir), env=runtime_env, capture_output=True, text=True)
                has_pending_migrations = mig_probe.returncode != 0
                if not has_pending_migrations:
                    _run_verify_schema(
                        server_dir, helper_py=helper_py, python_bin=str(venv_python), env=runtime_env, as_user=run_user
                    )
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
                    backup_path = cfg.var_dir / "backups" / f"db-{ts}-{clean_id}.sqlite3"
                    _run_sqlite_op(
                        "backup", sqlite_path, backup_path, helper_py=helper_py, python_bin=str(venv_python), cwd=cfg.var_dir, as_user=run_user
                    )
        except BaseException:
            shutil.rmtree(release_dir, ignore_errors=True)
            _hist.prune_old_releases_and_venvs(
                cfg.app_root, keep=cfg.keep_releases, protected={previous_target} if previous_target else set()
            )
            _safe_prune_backups_on_error(
                cfg.var_dir, keep=cfg.keep_backups, protected={backup_path} if backup_path else set()
            )
            raise

        db_mutated = False
        try:
            if has_pending_migrations:
                _hist.enter_maintenance(cfg.app_root)
                run_checked([cfg.systemctl_bin, "stop", cfg.service_name])
                if had_existing_db:
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
                    backup_path = cfg.var_dir / "backups" / f"db-{ts}-{clean_id}.sqlite3"
                    _run_sqlite_op(
                        "backup", sqlite_path, backup_path, helper_py=helper_py, python_bin=str(venv_python), cwd=cfg.var_dir, as_user=run_user
                    )
                db_mutated = True
                run_checked([str(venv_python), "manage.py", "migrate", "--noinput"], cwd=server_dir, env=runtime_env, as_user=run_user)
                _run_verify_schema(
                    server_dir, helper_py=helper_py, python_bin=str(venv_python), env=runtime_env, as_user=run_user
                )
            atomic_switch_symlink(cfg.app_root / "shared" / "venv", new_venv_dir)
            atomic_switch_symlink(current_link, release_dir)
            run_checked([cfg.systemctl_bin, "restart", cfg.service_name])
            wait_for_healthy(cfg, runtime_env)
            _hist.record_activated_release(cfg.app_root, release_dir)
            _hist.exit_maintenance(cfg.app_root)
        except BaseException as deploy_exc:
            try:
                (release_dir / ".activated").unlink(missing_ok=True)
            except OSError:
                pass
            rb_errors = _restore_release_state(
                cfg,
                runtime_env=runtime_env,
                sqlite_path=sqlite_path,
                helper_py=helper_py,
                python_bin=str(venv_python),
                run_user=run_user,
                db_mutated=db_mutated,
                restore_backup=backup_path if had_existing_db else None,
                remove_new_db=not had_existing_db,
                restore_target=previous_target,
            )
            try:
                _hist.write_release_history(cfg.app_root, prior_history)
            except OSError as hist_exc:
                rb_errors.append(f"release history restore failed: {hist_exc}")
            if not rb_errors:
                _hist.exit_maintenance(cfg.app_root)
            if _hist.current_release_target(current_link) != release_dir.resolve():
                shutil.rmtree(release_dir, ignore_errors=True)
            _hist.prune_old_releases_and_venvs(
                cfg.app_root, keep=cfg.keep_releases, protected={previous_target} if previous_target else set()
            )
            _safe_prune_backups_on_error(
                cfg.var_dir, keep=cfg.keep_backups, protected={backup_path} if backup_path else set(), errors=rb_errors
            )
            extra = f" | rollback errors: {'; '.join(rb_errors)}" if rb_errors else ""
            raise DeployError(f"Deploy {clean_id} failed and rolled back: {deploy_exc}{extra}") from deploy_exc

        protected = {release_dir} | ({previous_target} if previous_target else set())
        _warn_post_commit_prune(
            "release/venv",
            _hist.prune_old_releases_and_venvs,
            cfg.app_root,
            keep=cfg.keep_releases,
            protected=protected,
            clean_legacy_stash=True,
        )
        _warn_post_commit_prune(
            "backup",
            _hist.prune_old_backups,
            cfg.var_dir,
            keep=cfg.keep_backups,
            protected={backup_path} if backup_path else set(),
        )
        return release_dir


def _resolve_validated_backup(
    var_dir: Path,
    restore_db: str,
    *,
    helper_py: Path,
    python_bin: str,
    run_user: str | None,
) -> Path:
    if "/" in restore_db or "\\" in restore_db:
        raise DeployError(f"--restore-db must be a backup filename inside backups/, got {restore_db!r}.")
    clean_name = validate_release_id(restore_db, label="--restore-db")
    anchored_var = _rt._confinement_to_deploy_error(_rt._fs.anchor_var_root, var_dir)
    backups_root = anchored_var / "backups"
    candidate = backups_root / clean_name
    dir_flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_DIRECTORY", 0)
    try:
        var_fd = os.open(str(anchored_var), dir_flags)
    except OSError as exc:
        raise DeployError(f"Unsafe var_dir {anchored_var}: {exc}") from exc
    try:
        try:
            bk_dir_fd = os.open("backups", dir_flags, dir_fd=var_fd)
        except OSError as exc:
            raise DeployError(f"Unsafe backups directory {backups_root}: {exc}") from exc
        try:
            try:
                file_fd = os.open(clean_name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=bk_dir_fd)
            except FileNotFoundError as exc:
                raise DeployError(f"Requested --restore-db backup not found: {candidate}") from exc
            except OSError as exc:
                raise DeployError(f"Requested --restore-db must not be a symlink: {candidate}") from exc
            try:
                if not stat.S_ISREG(os.fstat(file_fd).st_mode):
                    raise DeployError(f"Requested --restore-db must be a regular file: {candidate}")
            finally:
                os.close(file_fd)
        finally:
            os.close(bk_dir_fd)
    finally:
        os.close(var_fd)
    run_checked([python_bin, str(helper_py), "verify", str(candidate)], cwd=anchored_var, as_user=run_user)
    return candidate


def rollback_release(cfg: DeployConfig, *, to_release: str | None = None, restore_db: str | None = None) -> Path:
    _rt._confinement_to_deploy_error(
        _rt._fs.validate_disjoint_roots, cfg.app_root, cfg.var_dir, _rt.DEFAULT_STATIC_WEB_ROOT, etc_env=cfg.etc_env
    )
    with exclusive_lock(cfg.lock_file):
        parsed_env = load_and_validate_env_file(cfg.etc_env)
        runtime_env, sqlite_path, cache_path, mail_path = build_runtime_env(
            parsed_env, var_dir=cfg.var_dir, app_root=cfg.app_root
        )
        run_user, _ = prepare_var_dirs(
            cfg.var_dir, sqlite_path=sqlite_path, cache_path=cache_path, email_file_path=mail_path, service_user=cfg.service_user
        )
        helper_py = _install_sqlite_ops_helper(cfg.app_root)
        current_link = cfg.app_root / "current"
        prior_target = _hist.current_release_target(current_link)
        prior_history = _hist.read_release_history(cfg.app_root)
        target_dir, next_history = _hist.select_rollback_target(cfg.app_root, prior_target, to_release)

        target_venv = ensure_release_venv(cfg.app_root, target_dir / "server" / "requirements.txt")
        py_bin = str(target_venv / "bin" / "python")
        backup_candidate = (
            _resolve_validated_backup(cfg.var_dir, restore_db, helper_py=helper_py, python_bin=py_bin, run_user=run_user)
            if restore_db
            else None
        )
        safety_backup: Path | None = None
        had_existing_db = sqlite_path.exists() or sqlite_path.is_symlink()
        if backup_candidate is None:
            if sqlite_path.is_symlink() or not sqlite_path.is_file():
                raise DeployError(
                    f"Cannot run code-only rollback without live SQLite database at {sqlite_path}; pass --restore-db."
                )
            _run_verify_schema(
                target_dir / "server", helper_py=helper_py, python_bin=py_bin, env=runtime_env, as_user=run_user, allow_newer=True
            )
        db_mutated = False

        try:
            if backup_candidate is not None:
                _hist.enter_maintenance(cfg.app_root)
                run_checked([cfg.systemctl_bin, "stop", cfg.service_name])
                if sqlite_path.is_symlink():
                    raise DeployError(f"Refusing symlink at SQLITE_PATH: {sqlite_path}")
                if had_existing_db:
                    verify_cmd = ["runuser", "-u", run_user, "--"] if run_user else []
                    verify_cmd.extend([py_bin, str(helper_py), "verify", str(sqlite_path)])
                    verify_live = subprocess.run(verify_cmd, cwd=str(cfg.var_dir), capture_output=True, text=True)
                    if verify_live.returncode == 0:
                        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
                        safety_backup = cfg.var_dir / "backups" / f"pre-rollback-{ts}-{target_dir.name}.sqlite3"
                        _run_sqlite_op("backup", sqlite_path, safety_backup, helper_py=helper_py, python_bin=py_bin, cwd=cfg.var_dir, as_user=run_user)
                db_mutated = True
                _run_sqlite_op("restore", backup_candidate, sqlite_path, helper_py=helper_py, python_bin=py_bin, cwd=cfg.var_dir, as_user=run_user)
                _run_verify_schema(
                    target_dir / "server", helper_py=helper_py, python_bin=py_bin, env=runtime_env, as_user=run_user
                )
            atomic_switch_symlink(cfg.app_root / "shared" / "venv", target_venv)
            atomic_switch_symlink(current_link, target_dir)
            run_checked([cfg.systemctl_bin, "restart", cfg.service_name])
            wait_for_healthy(cfg, runtime_env)
            _hist.write_release_history(cfg.app_root, next_history)
            _hist.exit_maintenance(cfg.app_root)
        except BaseException as exc:
            rb_errors = _restore_release_state(
                cfg,
                runtime_env=runtime_env,
                sqlite_path=sqlite_path,
                helper_py=helper_py,
                python_bin=py_bin,
                run_user=run_user,
                db_mutated=db_mutated,
                restore_backup=safety_backup,
                remove_new_db=not had_existing_db,
                restore_target=prior_target,
            )
            try:
                _hist.write_release_history(cfg.app_root, prior_history)
            except OSError as hist_exc:
                rb_errors.append(f"release history restore failed: {hist_exc}")
            if not rb_errors:
                _hist.exit_maintenance(cfg.app_root)
            _safe_prune_backups_on_error(
                cfg.var_dir, keep=cfg.keep_backups, protected={safety_backup} if safety_backup else set(), errors=rb_errors
            )
            extra = f" | recovery errors: {'; '.join(rb_errors)}" if rb_errors else ""
            raise DeployError(f"Rollback to {target_dir.name} failed: {exc}{extra}") from exc

        _warn_post_commit_prune(
            "backup",
            _hist.prune_old_backups,
            cfg.var_dir,
            keep=cfg.keep_backups,
            protected={safety_backup} if safety_backup else set(),
        )
        return target_dir


_COMMON_CLI_SPECS: tuple[tuple[str, type, object], ...] = (
    ("--app-root", Path, DEFAULT_APP_ROOT),
    ("--etc-env", Path, DEFAULT_ETC_ENV),
    ("--var-dir", Path, DEFAULT_VAR_DIR),
    ("--lock-file", Path, DEFAULT_LOCK_FILE),
    ("--service-name", str, DEFAULT_SERVICE_NAME),
    ("--service-user", str, DEFAULT_SERVICE_USER),
    ("--systemctl-bin", str, DEFAULT_SYSTEMCTL_BIN),
    ("--health-url", str, DEFAULT_HEALTH_URL),
    ("--keep-releases", int, DEFAULT_KEEP_RELEASES),
    ("--keep-backups", int, DEFAULT_KEEP_BACKUPS),
    ("--health-retries", int, DEFAULT_HEALTH_RETRIES),
    ("--health-interval", float, DEFAULT_HEALTH_INTERVAL),
    ("--health-timeout", float, DEFAULT_HEALTH_TIMEOUT),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    deploy_p = subparsers.add_parser("deploy", help="Deploy a staged site/server release")
    deploy_p.add_argument("--staged-server", type=Path, required=True)
    deploy_p.add_argument("--release-id", required=True)
    rb_p = subparsers.add_parser("rollback", help="Roll back to a previous release")
    rb_p.add_argument("--to", dest="to_release", help="Specific release_id to activate")
    rb_p.add_argument("--restore-db", help="Backup filename inside backups/ to restore into SQLITE_PATH")
    for sub in (deploy_p, rb_p):
        for flag, typ, default in _COMMON_CLI_SPECS:
            sub.add_argument(flag, type=typ, default=default)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = DeployConfig(**{f.name: getattr(args, f.name) for f in dataclasses.fields(DeployConfig)})
    try:
        if args.command == "deploy":
            active = deploy_release(cfg, staged_server=args.staged_server, release_id=args.release_id)
            print(f"deployed release {active.name} -> {active}")
        else:
            restored = rollback_release(cfg, to_release=args.to_release, restore_db=args.restore_db)
            print(f"rolled back current -> {restored}")
    except (DeployError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
