#!/usr/bin/env python3
"""Apply SQL migrations from supabase/migrations/ in filename order.

Usage:
  # List what would be applied
  python scripts/ops/sb_migrate.py --dry-run

  # Actually apply
  python scripts/ops/sb_migrate.py --confirm CONFIRM_SCHEMA

Rules:
- Refuses to run without `--confirm CONFIRM_SCHEMA` (unless --dry-run).
- Applies migrations in sorted filename order.
- Assumes migrations are idempotent (CREATE ... IF NOT EXISTS,
  ALTER TABLE ADD COLUMN IF NOT EXISTS, etc.). Re-running is a no-op.
- Logs filenames applied (or the first one that failed) to ops_log.jsonl.

Pre-requisites (one-time):
  - `python3 -m pip install --break-system-packages psycopg2-binary` on the VPS.
  - `SUPABASE_DB_DSN` added to /etc/polyguez.env. Get this from:
    Supabase -> Project Settings -> Database -> Connection string (URI).
    Use the Transaction pooler or direct connection, either works.
  - Note: this is DIFFERENT from SUPABASE_SERVICE_KEY. The DSN is a full
    postgres connection string; the service_key is a JWT for the REST API.

Why psycopg2 and not the supabase client? The Supabase Python client goes
through PostgREST, which does NOT accept arbitrary DDL (CREATE VIEW, ALTER
TABLE, etc.). Direct psycopg2 is the only clean path for running migration
files from this host.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# sibling-import helper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_utils import write_ops_log  # noqa: E402

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def _connect():
    dsn = os.environ.get("SUPABASE_DB_DSN", "")
    if not dsn:
        raise RuntimeError(
            "SUPABASE_DB_DSN not set. Add to /etc/polyguez.env:\n"
            "  SUPABASE_DB_DSN=postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres"
        )
    try:
        import psycopg2  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "psycopg2 not installed. Run once on this host:\n"
            "  python3 -m pip install --break-system-packages --user psycopg2-binary"
        ) from e
    import psycopg2
    return psycopg2.connect(dsn)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirm",
        default="",
        help="Must equal CONFIRM_SCHEMA to actually apply (ignored if --dry-run).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List migration filenames in order without applying.",
    )
    args = parser.parse_args()

    if not MIGRATIONS_DIR.exists():
        write_ops_log("sb_migrate", "error", {"reason": "missing_migrations_dir"})
        print(f"Migrations dir not found: {MIGRATIONS_DIR}", file=sys.stderr)
        return 1

    migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not migration_files:
        write_ops_log("sb_migrate", "ok", {"applied": [], "note": "no migrations found"})
        print("No *.sql files in supabase/migrations/; nothing to do.")
        return 0

    # Connect early so dry-run can also show what's pending vs applied.
    try:
        conn = _connect()
        conn.autocommit = True
        cur = conn.cursor()
    except Exception as exc:
        print(f"sb_migrate connection failed: {exc}", file=sys.stderr)
        write_ops_log("sb_migrate", "error", {"reason": "connect_failed", "error": str(exc)})
        return 1

    # Ensure tracking table exists (defensive — the seeding migration should
    # have created it, but we self-heal if someone deploys a fresh DB).
    cur.execute(
        "CREATE TABLE IF NOT EXISTS _sb_migrate_applied ("
        "  filename TEXT PRIMARY KEY,"
        "  applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  applied_by TEXT NOT NULL DEFAULT current_user"
        ")"
    )

    cur.execute("SELECT filename FROM _sb_migrate_applied")
    already_applied = {row[0] for row in cur.fetchall()}

    pending = [p for p in migration_files if p.name not in already_applied]
    skipped = [p.name for p in migration_files if p.name in already_applied]

    if args.dry_run:
        print(f"Already applied ({len(skipped)}):")
        for name in skipped:
            print(f"  - {name}")
        print(f"\nWould apply in order ({len(pending)}):")
        for p in pending:
            print(f"  + {p.name}")
        write_ops_log("sb_migrate", "dry_run", {
            "pending": [p.name for p in pending],
            "already_applied": skipped,
        })
        cur.close()
        conn.close()
        return 0

    if args.confirm != "CONFIRM_SCHEMA":
        write_ops_log("sb_migrate", "error", {"reason": "missing_confirm"})
        print("Refusing to apply without --confirm CONFIRM_SCHEMA", file=sys.stderr)
        cur.close()
        conn.close()
        return 1

    if not pending:
        write_ops_log("sb_migrate", "ok", {
            "applied": [],
            "skipped": skipped,
            "note": "all migrations already applied",
        })
        print(f"All {len(skipped)} migration(s) already applied; nothing to do.")
        cur.close()
        conn.close()
        return 0

    applied: list[str] = []
    try:
        for path in pending:
            sql = path.read_text(encoding="utf-8")
            try:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO _sb_migrate_applied (filename) VALUES (%s)",
                    (path.name,),
                )
                applied.append(path.name)
                print(f"applied: {path.name}")
            except Exception as exc:
                write_ops_log("sb_migrate", "error", {
                    "applied_so_far": applied,
                    "failed_on": path.name,
                    "error": str(exc),
                })
                raise

        cur.close()
        conn.close()

        write_ops_log("sb_migrate", "ok", {
            "applied": applied,
            "skipped": skipped,
        })
        print(f"\nDone. Applied {len(applied)} new migration(s); skipped {len(skipped)} already-applied.")
        return 0

    except Exception as exc:
        try:
            cur.close()
            conn.close()
        except Exception:
            pass
        print(f"sb_migrate failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
