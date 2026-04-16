#!/usr/bin/env python3
"""One-off migration: add hot-path timing columns to trade_log."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("ERROR: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set")
    sys.exit(1)

SQL = """
ALTER TABLE trade_log
  ADD COLUMN IF NOT EXISTS llm_response_ms  FLOAT,
  ADD COLUMN IF NOT EXISTS signal_eval_ms   FLOAT,
  ADD COLUMN IF NOT EXISTS order_submit_ms  FLOAT,
  ADD COLUMN IF NOT EXISTS total_latency_ms FLOAT;
"""

print("Running migration...")
print(SQL)

try:
    import re
    match = re.search(r"https://([^.]+)\.supabase\.co", SUPABASE_URL)
    if match:
        project_ref = match.group(1)
        db_host = f"db.{project_ref}.supabase.co"
        import psycopg2
        conn = psycopg2.connect(
            host=db_host,
            port=5432,
            dbname="postgres",
            user="postgres",
            password=SUPABASE_SERVICE_KEY,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.close()
        print("Migration applied successfully via psycopg2")
    else:
        print("Could not parse project ref from SUPABASE_URL")
        print("Run this SQL manually in Supabase SQL editor")
except ImportError:
    print("psycopg2 not installed — run migration manually in Supabase SQL editor")
except Exception as e:
    print(f"psycopg2 migration failed: {e}")
    print("Run this SQL manually in Supabase SQL editor")
