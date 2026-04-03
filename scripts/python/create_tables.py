"""Create missing Supabase tables for PolyGuez signal/trade logging."""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    print("Error: SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
    print("Export them and re-run:")
    print("  export SUPABASE_URL='https://xxx.supabase.co'")
    print("  export SUPABASE_SERVICE_KEY='eyJ...'")
    print("  PYTHONPATH=. python scripts/python/create_tables.py")
    sys.exit(1)

SQL = """
CREATE TABLE IF NOT EXISTS signal_log (
  id bigint generated always as identity primary key,
  ts timestamptz not null default now(),
  market_id text, market_question text, elapsed_seconds float,
  btc_price float, chainlink_price float, strike_delta float,
  terminal_probability float, terminal_edge float, entry_side text,
  yes_price float, no_price float, spread float,
  conditions_met int, all_conditions_met boolean, trade_fired boolean, mode text
);

CREATE TABLE IF NOT EXISTS trade_log (
  id bigint generated always as identity primary key,
  ts timestamptz not null default now(),
  market_id text, market_question text, side text,
  entry_price float, exit_price float, pnl float, size_usdc float,
  outcome text, reason text, llm_verdict text, llm_provider text, mode text
);

CREATE TABLE IF NOT EXISTS trade_archive (
  id bigint generated always as identity primary key,
  ts timestamptz, data jsonb
);
"""

try:
    from supabase import create_client

    client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    # Execute via PostgREST RPC or direct SQL
    result = client.postgrest.rpc("exec_sql", {"query": SQL}).execute()
    print("Tables created successfully via RPC.")
except Exception as e:
    # Fallback: try using psycopg2 with the database URL
    print(f"RPC method failed ({e}), trying direct connection...")
    try:
        import httpx

        headers = {
            "apikey": SUPABASE_SERVICE_KEY,
            "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
            "Content-Type": "application/json",
        }
        # Use the Supabase SQL endpoint
        url = f"{SUPABASE_URL}/rest/v1/rpc/exec_sql"
        resp = httpx.post(url, json={"query": SQL}, headers=headers, timeout=30)
        if resp.status_code < 300:
            print("Tables created successfully via REST.")
        else:
            print(f"REST call returned {resp.status_code}: {resp.text}")
            print("You may need to run the SQL manually in the Supabase SQL Editor:")
            print(SQL)
    except Exception as e2:
        print(f"Direct connection also failed: {e2}")
        print("Run this SQL manually in the Supabase SQL Editor:")
        print(SQL)
