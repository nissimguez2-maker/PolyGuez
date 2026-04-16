#!/usr/bin/env python3
"""Trigger a Railway deploy for the PolyGuez production service.

Usage:
  python scripts/ops/deploy_prod.py --confirm CONFIRM_DEPLOY

Rules:
- Refuses to run without `--confirm CONFIRM_DEPLOY`.
- Reads `RAILWAY_TOKEN`, `RAILWAY_PROJECT_ID`, `RAILWAY_SERVICE_ID` from env
  (or /etc/polyguez.env if you source that first).
- Every outcome logs to scripts/ops/ops_log.jsonl.

Note on triggering mechanism:
  Railway normally auto-deploys on push to main. This script exists so an
  OpenClaw operator agent can force a redeploy of the CURRENT main commit
  without pushing anything (e.g. to recover from a failed deploy). It uses
  the Railway GraphQL API.

Pre-requisites (one-time, manual):
  - Nessim creates a Railway API token scoped to the PolyGuez project:
    Railway -> Account -> Tokens -> Create
  - Add to /etc/polyguez.env (0640 root:thiago):
      RAILWAY_TOKEN=<token>
      RAILWAY_PROJECT_ID=<project-uuid>
      RAILWAY_SERVICE_ID=<service-uuid>
  - Project/service UUIDs are visible in the Railway UI under the service's
    URL, or queryable via the Railway CLI (`railway status --json`).

If Railway's GraphQL mutation shape changes (they occasionally do), update
the `_TRIGGER_DEPLOY_MUTATION` constant below.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any, Dict

# sibling-import helper
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from log_utils import write_ops_log  # noqa: E402

RAILWAY_API = "https://backboard.railway.app/graphql/v2"
_TRIGGER_DEPLOY_MUTATION = """
mutation TriggerDeploy($projectId: String!, $serviceId: String!) {
  serviceInstanceDeploy(input: {projectId: $projectId, serviceId: $serviceId}) {
    id
  }
}
"""


def _railway_request(token: str, query: str, variables: Dict[str, Any]) -> Dict[str, Any]:
    import requests  # lazy import so --help works without requests
    resp = requests.post(
        RAILWAY_API,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if "errors" in data:
        raise RuntimeError(data["errors"])
    return data["data"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Trigger a Railway deploy (confirmed).")
    parser.add_argument(
        "--confirm",
        required=True,
        help="Must equal CONFIRM_DEPLOY to proceed",
    )
    args = parser.parse_args()

    if args.confirm != "CONFIRM_DEPLOY":
        write_ops_log("deploy_prod", "error", {"reason": "missing_or_wrong_confirm"})
        print("Refusing to deploy without --confirm CONFIRM_DEPLOY", file=sys.stderr)
        return 1

    token = os.environ.get("RAILWAY_TOKEN", "")
    project_id = os.environ.get("RAILWAY_PROJECT_ID", "")
    service_id = os.environ.get("RAILWAY_SERVICE_ID", "")

    missing = [
        name for name, val in (
            ("RAILWAY_TOKEN", token),
            ("RAILWAY_PROJECT_ID", project_id),
            ("RAILWAY_SERVICE_ID", service_id),
        ) if not val
    ]
    if missing:
        write_ops_log("deploy_prod", "error", {
            "reason": "missing_env_vars",
            "missing": missing,
        })
        print(
            f"Missing env vars: {', '.join(missing)}. Source /etc/polyguez.env first.",
            file=sys.stderr,
        )
        return 1

    write_ops_log("deploy_prod", "start", {"project_id": project_id, "service_id": service_id})

    try:
        data = _railway_request(
            token,
            _TRIGGER_DEPLOY_MUTATION,
            {"projectId": project_id, "serviceId": service_id},
        )
        deploy_id = data["serviceInstanceDeploy"]["id"]

        # Let the API settle before returning — Railway usually takes ~10-30s
        # to start a new container. We don't poll status to keep the script
        # simple; the operator is expected to tail `/health` after this.
        time.sleep(5)

        write_ops_log("deploy_prod", "ok", {"deploy_id": deploy_id})
        print(f"Triggered Railway deploy id={deploy_id}")
        return 0

    except Exception as exc:
        write_ops_log("deploy_prod", "error", {"error": str(exc)})
        print(f"deploy_prod failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
