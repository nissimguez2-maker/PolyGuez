#!/usr/bin/env python3
"""One-off migration: add bid_yes, bid_no, complete_set_edge columns to signal_log."""

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
ALTER TABLE signal_log
  ADD COLUMN IF NOT EXISTS bid_yes FLOAT,
  ADD COLUMN IF NOT EXISTS bid_no  FLOAT,
  ADD COLUMN IF NOT EXISTS complete_set_edge FLOAT;
"""

try:
    from supabase import create_client
    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    resp = client.rpc("exec_sql", {"query": SQL}).execute()
    print(f"Migration response: {resp}")
except Exception as e:
    print(f"supabase rpc failed ({e}), trying postgrest...")

# Fallback: use psycopg2 if available
try:
    import re
    # Extract host from SUPABASE_URL (e.g. https://xxx.supabase.co)
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
except ImportError:
    print("psycopg2 not installed — run migration manually in Supabase SQL editor:")
    print(SQL)
except Exception as e:
    print(f"psycopg2 migration failed: {e}")
    print("Run this SQL manually in Supabase SQL editor:")
    print(SQL)
