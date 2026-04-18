#!/usr/bin/env python3
"""Inspect and repair Railway service environment variables for PolyGuez.

Usage:
  # List current vars and report missing/suspicious ones
  python3 scripts/ops/fix_railway_env.py

  # Set a single variable (requires --confirm)
  python3 scripts/ops/fix_railway_env.py --set SUPABASE_SERVICE_KEY=<value> --confirm FIX_RAILWAY_ENV

Reads from env (add to .env or export before running):
  RAILWAY_TOKEN         Railway API token  (Settings > Tokens in Railway UI)
  RAILWAY_PROJECT_ID    Railway project UUID
  RAILWAY_SERVICE_ID    Railway service UUID

Key vars checked:
  SUPABASE_URL, SUPABASE_SERVICE_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_ALERT_CHAT_ID,
  POLYGON_WALLET_PRIVATE_KEY, OPENAI_API_KEY, SESSION_TAG, DASHBOARD_SECRET
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_utils import write_ops_log  # noqa: E402

RAILWAY_API = "https://backboard.railway.app/graphql/v2"

_CRITICAL_VARS = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "POLYGON_WALLET_PRIVATE_KEY",
    "OPENAI_API_KEY",
    "DASHBOARD_SECRET",
    "SESSION_TAG",
]
_ALERTER_VARS = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALERT_CHAT_ID",
]
_EXPECTED_SUPABASE_URL = "https://rapmxqnxsobvxqtfnwqh.supabase.co"


def _gql(token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    import urllib.request
    import urllib.parse
    import json

    payload = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(
        RAILWAY_API,
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


_LIST_ENVIRONMENTS = """
query Envs($projectId: String!) {
  project(id: $projectId) {
    environments { edges { node { id name } } }
  }
}
"""

_LIST_VARIABLES = """
query Vars($projectId: String!, $environmentId: String!, $serviceId: String!) {
  variables(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId)
}
"""

_UPSERT_VARIABLE = """
mutation VarUpsert($input: VariableUpsertInput!) {
  variableUpsert(input: $input)
}
"""


def _get_prod_environment_id(token: str, project_id: str) -> str:
    data = _gql(token, _LIST_ENVIRONMENTS, {"projectId": project_id})
    envs = data["project"]["environments"]["edges"]
    # Prefer "production" by name, fall back to first
    for edge in envs:
        if edge["node"]["name"].lower() in ("production", "prod"):
            return edge["node"]["id"]
    if envs:
        return envs[0]["node"]["id"]
    raise RuntimeError("No environments found in Railway project")


def _get_variables(token: str, project_id: str, environment_id: str, service_id: str) -> Dict[str, str]:
    data = _gql(
        token,
        _LIST_VARIABLES,
        {"projectId": project_id, "environmentId": environment_id, "serviceId": service_id},
    )
    return data.get("variables") or {}


def _upsert_variable(
    token: str, project_id: str, environment_id: str, service_id: str, name: str, value: str
) -> None:
    _gql(
        token,
        _UPSERT_VARIABLE,
        {
            "input": {
                "projectId": project_id,
                "environmentId": environment_id,
                "serviceId": service_id,
                "name": name,
                "value": value,
            }
        },
    )


def _audit(current_vars: Dict[str, str]) -> List[str]:
    issues = []
    for v in _CRITICAL_VARS:
        if not current_vars.get(v):
            issues.append(f"MISSING  {v}")
    for v in _ALERTER_VARS:
        if not current_vars.get(v):
            issues.append(f"WARNING  {v} (alerts degrade to Railway logs only)")
    sb_url = current_vars.get("SUPABASE_URL", "")
    if sb_url and sb_url != _EXPECTED_SUPABASE_URL:
        issues.append(f"MISMATCH SUPABASE_URL={sb_url!r}  expected={_EXPECTED_SUPABASE_URL!r}")
    sb_key = current_vars.get("SUPABASE_SERVICE_KEY", "")
    if sb_key:
        # Anon key payload contains "role":"anon"; service_role contains "role":"service_role"
        import base64
        try:
            parts = sb_key.split(".")
            if len(parts) == 3:
                padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
                import json
                payload = json.loads(base64.urlsafe_b64decode(padded))
                role = payload.get("role", "unknown")
                if role != "service_role":
                    issues.append(
                        f"WRONG_KEY SUPABASE_SERVICE_KEY has JWT role={role!r} — "
                        "must be service_role. Get it from Supabase > Settings > API."
                    )
        except Exception:
            pass
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect/fix Railway env vars for PolyGuez.")
    parser.add_argument("--set", metavar="KEY=VALUE", help="Set a single variable (requires --confirm)")
    parser.add_argument("--confirm", default="", help="Must equal FIX_RAILWAY_ENV to write")
    args = parser.parse_args()

    token = os.environ.get("RAILWAY_TOKEN", "")
    project_id = os.environ.get("RAILWAY_PROJECT_ID", "")
    service_id = os.environ.get("RAILWAY_SERVICE_ID", "")

    missing_creds = [n for n, v in [
        ("RAILWAY_TOKEN", token), ("RAILWAY_PROJECT_ID", project_id), ("RAILWAY_SERVICE_ID", service_id)
    ] if not v]
    if missing_creds:
        print(f"ERROR: missing env vars: {', '.join(missing_creds)}", file=sys.stderr)
        print("Add them to .env (see .env.example), then re-run.", file=sys.stderr)
        return 1

    try:
        env_id = _get_prod_environment_id(token, project_id)
        current = _get_variables(token, project_id, env_id, service_id)
    except Exception as exc:
        print(f"Railway API error: {exc}", file=sys.stderr)
        write_ops_log("fix_railway_env", "error", {"error": str(exc)})
        return 1

    print(f"\n=== Railway Variables (environment: production, {len(current)} set) ===")
    for k in sorted(current):
        # Redact secrets in output
        v = current[k]
        if any(s in k.upper() for s in ("KEY", "SECRET", "TOKEN", "PASSWORD", "PRIVATE")):
            display = v[:8] + "..." + v[-4:] if len(v) > 12 else "***"
        else:
            display = v
        print(f"  {k}={display}")

    issues = _audit(current)
    if issues:
        print("\n=== Issues ===")
        for issue in issues:
            print(f"  {issue}")
    else:
        print("\n=== All critical vars look OK ===")

    if args.set:
        if args.confirm != "FIX_RAILWAY_ENV":
            print("\nERROR: --set requires --confirm FIX_RAILWAY_ENV", file=sys.stderr)
            return 1
        if "=" not in args.set:
            print(f"ERROR: --set value must be KEY=VALUE, got: {args.set!r}", file=sys.stderr)
            return 1
        key, _, value = args.set.partition("=")
        key = key.strip()
        value = value.strip()
        try:
            _upsert_variable(token, project_id, env_id, service_id, key, value)
            print(f"\nSet {key} on Railway (redeploy to pick up).")
            write_ops_log("fix_railway_env", "set", {"key": key})
        except Exception as exc:
            print(f"ERROR setting {key}: {exc}", file=sys.stderr)
            write_ops_log("fix_railway_env", "error", {"key": key, "error": str(exc)})
            return 1

    write_ops_log("fix_railway_env", "ok", {"issues": issues})
    return 0


if __name__ == "__main__":
    sys.exit(main())
