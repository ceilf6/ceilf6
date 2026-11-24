#!/usr/bin/env python3
"""Consistent online SQLite WAL backup, integrity verification, and restore helpers."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from collections.abc import Sequence
from pathlib import Path

SQLITE_CONNECT_TIMEOUT = 30.0


class SqliteOpError(RuntimeError):
    """Raised when SQLite verification, backup, or restore fails."""


def verify_sqlite_integrity(db_path: Path) -> None:
    """Verify that `db_path` is a regular non-symlink SQLite database passing integrity_check."""
    try:
        st = db_path.lstat()
    except FileNotFoundError as exc:
        raise SqliteOpError(f"SQLite file does not exist: {db_path}") from exc

    if not stat.S_ISREG(st.st_mode):
        raise SqliteOpError(f"SQLite path must be a regular file (not symlink/dir): {db_path}")

    if st.st_size == 0:
        raise SqliteOpError(f"SQLite file is empty: {db_path}")

    try:
        ro_uri = f"file:{urllib.parse.quote(str(db_path.resolve()))}?mode=ro"
        with contextlib.closing(sqlite3.connect(ro_uri, uri=True, timeout=SQLITE_CONNECT_TIMEOUT)) as conn:
            rows = conn.execute("PRAGMA integrity_check").fetchall()
    except sqlite3.Error as exc:
        raise SqliteOpError(f"SQLite integrity query failed for {db_path}: {exc}") from exc

    if rows != [("ok",)]:
        raise SqliteOpError(f"SQLite integrity_check failed for {db_path}: {rows!r}")


def backup_sqlite_file(src_db: Path, dst_backup: Path) -> None:
    """Create a standalone single-file (`journal_mode=DELETE`) online backup at `dst_backup` (0600)."""
    verify_sqlite_integrity(src_db)
    dst_backup.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dst_backup.parent / f".{dst_backup.name}.tmp.{os.getpid()}"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{tmp_path}{suffix}").unlink(missing_ok=True)

    try:
        with contextlib.closing(sqlite3.connect(str(src_db), timeout=SQLITE_CONNECT_TIMEOUT)) as src_conn:
            with contextlib.closing(sqlite3.connect(str(tmp_path), timeout=SQLITE_CONNECT_TIMEOUT)) as dst_conn:
                src_conn.backup(dst_conn)
                dst_conn.execute("PRAGMA journal_mode=DELETE")
        for suffix in ("-wal", "-shm"):
            Path(f"{tmp_path}{suffix}").unlink(missing_ok=True)
        os.chmod(tmp_path, 0o600)
        verify_sqlite_integrity(tmp_path)
        os.replace(tmp_path, dst_backup)
    except BaseException as exc:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{tmp_path}{suffix}").unlink(missing_ok=True)
        if isinstance(exc, SqliteOpError):
            raise
        raise SqliteOpError(f"Online SQLite backup from {src_db} to {dst_backup} failed: {exc}") from exc


def restore_sqlite_file(backup_file: Path, dst_db: Path) -> None:
    """Stage verified restore in a temp sibling and atomically replace `dst_db` without destructive retry."""
    verify_sqlite_integrity(backup_file)
    dst_db.parent.mkdir(parents=True, exist_ok=True)
    tmp_restore = dst_db.parent / f".{dst_db.name}.restore.{os.getpid()}"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{tmp_restore}{suffix}").unlink(missing_ok=True)

    try:
        with contextlib.closing(sqlite3.connect(str(backup_file), timeout=SQLITE_CONNECT_TIMEOUT)) as src_conn:
            with contextlib.closing(sqlite3.connect(str(tmp_restore), timeout=SQLITE_CONNECT_TIMEOUT)) as tmp_conn:
                src_conn.backup(tmp_conn)
                tmp_conn.execute("PRAGMA journal_mode=DELETE")
        for suffix in ("-wal", "-shm"):
            Path(f"{tmp_restore}{suffix}").unlink(missing_ok=True)
        os.chmod(tmp_restore, 0o640)
        verify_sqlite_integrity(tmp_restore)
        os.replace(tmp_restore, dst_db)
        for suffix in ("-wal", "-shm"):
            Path(f"{dst_db}{suffix}").unlink(missing_ok=True)
        verify_sqlite_integrity(dst_db)
    except BaseException as exc:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{tmp_restore}{suffix}").unlink(missing_ok=True)
        if isinstance(exc, SqliteOpError):
            raise
        raise SqliteOpError(f"SQLite restore from {backup_file} into {dst_db} failed: {exc}") from exc


def _collapse_ws_outside_quotes(sql: str) -> str:
    out: list[str] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        if ch in {"'", '"', "`"}:
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                out.append(sql[i])
                if sql[i] == quote:
                    if i + 1 < n and sql[i + 1] == quote:
                        out.append(sql[i + 1])
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
        elif ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out).strip()


def _extract_check_clauses(create_sql: str) -> list[str]:
    clauses: list[str] = []
    i, n = 0, len(create_sql)
    while i < n:
        ch = create_sql[i]
        if ch in {"'", '"', "`"}:
            quote = ch
            i += 1
            while i < n:
                if create_sql[i] == quote:
                    if i + 1 < n and create_sql[i + 1] == quote:
                        i += 2
                        continue
                    i += 1
                    break
                i += 1
            continue
        prev_ok = i == 0 or not (create_sql[i - 1].isalnum() or create_sql[i - 1] == "_")
        next_ok = i + 5 >= n or not (create_sql[i + 5].isalnum() or create_sql[i + 5] == "_")
        if prev_ok and next_ok and create_sql[i : i + 5].upper() == "CHECK":
            j = i + 5
            while j < n and create_sql[j].isspace():
                j += 1
            if j < n and create_sql[j] == "(":
                k, depth = j, 0
                while k < n:
                    kc = create_sql[k]
                    if kc in {"'", '"', "`"}:
                        q = kc
                        k += 1
                        while k < n:
                            if create_sql[k] == q:
                                if k + 1 < n and create_sql[k + 1] == q:
                                    k += 2
                                    continue
                                break
                            k += 1
                    elif kc == "(":
                        depth += 1
                    elif kc == ")":
                        depth -= 1
                        if depth == 0:
                            clauses.append(_collapse_ws_outside_quotes(create_sql[j : k + 1]))
                            i = k + 1
                            break
                    k += 1
                else:
                    i = j + 1
                continue
        i += 1
    return sorted(clauses)


def _table_write_signature(cursor, quote_fn, table: str) -> dict[str, object]:
    ddl_row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", [table]).fetchone()
    q_tbl = quote_fn(table)
    cols = {
        r[1]: [(r[2] or "").upper(), int(r[3]), r[4], int(r[5])]
        for r in cursor.execute(f"PRAGMA table_info({q_tbl})").fetchall()
    }
    fks = sorted(
        [r[2], r[3], r[4], (r[5] or "NO ACTION").upper(), (r[6] or "NO ACTION").upper()]
        for r in cursor.execute(f"PRAGMA foreign_key_list({q_tbl})").fetchall()
    )
    uniques: list[list[object]] = []
    for _, idx_name, is_uniq, _, _ in cursor.execute(f"PRAGMA index_list({q_tbl})").fetchall():
        if not is_uniq:
            continue
        xinfo_keys = [
            [ir[2] or "", int(ir[3]), (ir[4] or "BINARY").upper()]
            for ir in cursor.execute(f"PRAGMA index_xinfo({quote_fn(idx_name)})").fetchall()
            if int(ir[5]) == 1
        ]
        sql_row = cursor.execute("SELECT sql FROM sqlite_master WHERE type='index' AND name=?", [idx_name]).fetchone()
        raw_idx_sql = _collapse_ws_outside_quotes((sql_row[0] if sql_row else "") or "")
        up_sql = raw_idx_sql.upper()
        on_pos = up_sql.find(" ON ")
        on_clause = raw_idx_sql[on_pos + 4 :] if on_pos >= 0 else raw_idx_sql
        uniques.append([xinfo_keys, on_clause])
    triggers = sorted(
        _collapse_ws_outside_quotes(r[0] or "")
        for r in cursor.execute("SELECT sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?", [table]).fetchall()
    )
    return {
        "cols": cols,
        "checks": _extract_check_clauses((ddl_row[0] if ddl_row else "") or ""),
        "fks": fks,
        "uniques": sorted(uniques),
        "triggers": triggers,
    }


def _list_user_tables(cursor) -> set[str]:
    return {
        r[0]
        for r in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
    }


def dump_canonical_schema(server_dir: Path) -> dict[str, dict[str, object]]:
    """Build canonical schema in an isolated process whose `default` DB is `:memory:`."""
    resolved_server = server_dir.resolve()
    if str(resolved_server) not in sys.path:
        sys.path.insert(0, str(resolved_server))
    os.environ["SQLITE_PATH"] = ":memory:"
    os.environ["DJANGO_CACHE_PATH"] = ":memory:"
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    with contextlib.redirect_stdout(sys.stderr):
        import django

        django.setup()
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        conn = connections["default"]
        try:
            executor = MigrationExecutor(conn)
            executor.migrate(executor.loader.graph.leaf_nodes())
            with conn.cursor() as cur:
                return {
                    tbl: _table_write_signature(cur, conn.ops.quote_name, tbl)
                    for tbl in sorted(_list_user_tables(cur))
                }
        finally:
            conn.close()


def _load_canonical_schema_isolated(resolved_server: Path) -> dict[str, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="schema-ref-tmp-") as tmp_dir:
        out_json = Path(tmp_dir) / "schema.json"
        mail_dir = Path(tmp_dir) / "mail"
        mail_dir.mkdir(mode=0o700)
        iso_env = {
            **os.environ,
            "SQLITE_PATH": ":memory:",
            "DJANGO_CACHE_PATH": ":memory:",
            "EMAIL_FILE_PATH": str(mail_dir),
        }
        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "dump-canonical-schema",
                str(resolved_server),
                str(out_json),
            ],
            cwd=str(resolved_server),
            env=iso_env,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0 or not out_json.is_file():
            detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
            raise SqliteOpError(f"Canonical reference migration failed for {resolved_server.parent.name}: {detail}")
        return json.loads(out_json.read_text(encoding="utf-8"))


def _verify_against_canonical_schema(
    conn, ref_sigs: dict[str, dict[str, object]], *, rel_name: str, allow_additive: bool
) -> None:
    with conn.cursor() as live_cur:
        live_tables = _list_user_tables(live_cur)
        ref_tables = set(ref_sigs)
        missing_tables = sorted(ref_tables - live_tables)
        if missing_tables:
            raise SqliteOpError(f"Database is missing tables required by {rel_name}: {missing_tables!r}")

        for tbl in sorted(ref_tables):
            live_sig = _table_write_signature(live_cur, conn.ops.quote_name, tbl)
            ref_sig = ref_sigs[tbl]
            live_cols = live_sig["cols"]
            ref_cols = ref_sig["cols"]
            assert isinstance(live_cols, dict) and isinstance(ref_cols, dict)
            missing_cols = sorted(set(ref_cols) - set(live_cols))
            if missing_cols:
                raise SqliteOpError(f"Table {tbl} missing columns {missing_cols!r} for {rel_name}.")
            for col_name, (r_type, r_notnull, _, r_pk) in ref_cols.items():
                l_type, l_notnull, _, l_pk = live_cols[col_name]
                if [l_type, l_notnull, l_pk] != [r_type, r_notnull, r_pk]:
                    raise SqliteOpError(
                        f"Column {tbl}.{col_name} definition {(l_type, l_notnull, l_pk)} incompatible with "
                        f"{rel_name} {(r_type, r_notnull, r_pk)}; pass --restore-db."
                    )
            for extra_col in sorted(set(live_cols) - set(ref_cols)):
                if not allow_additive:
                    raise SqliteOpError(f"Unexpected extra column {tbl}.{extra_col} for {rel_name}.")
                _, e_notnull, e_dflt, e_pk = live_cols[extra_col]
                if e_notnull and e_dflt is None and not e_pk:
                    raise SqliteOpError(
                        f"Extra column {tbl}.{extra_col} is NOT NULL without default; incompatible with {rel_name}."
                    )
            for kind in ("checks", "uniques", "fks", "triggers"):
                if live_sig[kind] != ref_sig[kind]:
                    raise SqliteOpError(
                        f"Table {tbl} {kind} constraints differ from {rel_name}; pass --restore-db."
                    )

        for extra_tbl in sorted(live_tables - ref_tables):
            if not allow_additive:
                raise SqliteOpError(f"Unexpected extra table {extra_tbl!r} for {rel_name}.")
            q_extra = conn.ops.quote_name(extra_tbl)
            for r in live_cur.execute(f"PRAGMA foreign_key_list({q_extra})").fetchall():
                target_tbl, on_del = r[2], (r[6] or "NO ACTION").upper()
                if target_tbl in ref_tables and on_del not in {"CASCADE", "SET NULL"}:
                    raise SqliteOpError(
                        f"Extra table {extra_tbl} has {on_del} FK referencing {target_tbl}; incompatible with {rel_name}."
                    )


def verify_django_schema(server_dir: Path, *, allow_newer_migrations: bool = False) -> None:
    """Read-only verification of live SQLite DB against isolated canonical schema of `server_dir`."""
    resolved_server = server_dir.resolve()
    ref_sigs = _load_canonical_schema_isolated(resolved_server)
    if str(resolved_server) not in sys.path:
        sys.path.insert(0, str(resolved_server))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        import django

        django.setup()
        from django.apps import apps
        from django.conf import settings
        from django.db import connections
        from django.db.migrations.executor import MigrationExecutor

        verify_sqlite_integrity(Path(settings.DATABASES["default"]["NAME"]))
        conn = connections["default"]
        conn.ensure_connection()
        assert conn.connection is not None
        conn.connection.execute("PRAGMA query_only=ON;")
        try:
            executor = MigrationExecutor(conn)
            targets = executor.loader.graph.leaf_nodes()
            if executor.migration_plan(targets):
                raise SqliteOpError(f"Database is missing forward migrations required by {resolved_server.parent.name}.")
            known_nodes = set(executor.loader.disk_migrations.keys())
            applied_nodes = set(executor.recorder.applied_migrations())
            unknown_newer = sorted(applied_nodes - known_nodes)
            if unknown_newer and not allow_newer_migrations:
                raise SqliteOpError(
                    f"Restored DB contains newer migrations unknown to {resolved_server.parent.name}: {unknown_newer!r}"
                )
            _verify_against_canonical_schema(
                conn, ref_sigs, rel_name=resolved_server.parent.name, allow_additive=allow_newer_migrations
            )
            for model in apps.get_models(include_auto_created=True):
                if model._meta.managed and not model._meta.proxy:
                    list(model._default_manager.all()[:1])
        finally:
            conn.close()
    except SqliteOpError:
        raise
    except Exception as exc:
        raise SqliteOpError(
            f"Target release {resolved_server.parent.name} is incompatible with current database "
            f"(pass matching --restore-db snapshot if rolling back destructive schema changes): {exc}"
        ) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_p = subparsers.add_parser("verify", help="Verify SQLite database integrity")
    verify_p.add_argument("db_path", type=Path)

    schema_p = subparsers.add_parser("verify-schema", help="Verify SQLite DB matches release Django schema")
    schema_p.add_argument("server_dir", type=Path)
    schema_p.add_argument("--allow-newer-migrations", action="store_true")

    dump_p = subparsers.add_parser("dump-canonical-schema", help="Internal: emit canonical :memory: schema JSON")
    dump_p.add_argument("server_dir", type=Path)
    dump_p.add_argument("out_json", type=Path)

    backup_p = subparsers.add_parser("backup", help="Create online SQLite backup")
    backup_p.add_argument("src_db", type=Path)
    backup_p.add_argument("dst_backup", type=Path)

    restore_p = subparsers.add_parser("restore", help="Restore SQLite database from backup")
    restore_p.add_argument("backup_file", type=Path)
    restore_p.add_argument("dst_db", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "verify":
            verify_sqlite_integrity(args.db_path)
        elif args.command == "verify-schema":
            verify_django_schema(args.server_dir, allow_newer_migrations=args.allow_newer_migrations)
        elif args.command == "dump-canonical-schema":
            args.out_json.write_text(json.dumps(dump_canonical_schema(args.server_dir)), encoding="utf-8")
        elif args.command == "backup":
            backup_sqlite_file(args.src_db, args.dst_backup)
        else:
            restore_sqlite_file(args.backup_file, args.dst_db)
    except (SqliteOpError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
