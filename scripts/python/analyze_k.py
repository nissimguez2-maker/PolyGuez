#!/usr/bin/env python3
"""Re-fit the logistic-model coefficient `k` against settled shadow trades.

Production PolyGuez uses `k = 0.035 / sqrt(seconds_remaining/60)` in
`agents/strategies/polyguez_strategy.py`. This script pulls every settled
shadow trade from Supabase, computes the effective feature
`x = |strike_delta| / sqrt((300 - elapsed_seconds)/60)`, and fits the
maximum-likelihood `k` for `P(win) = 1/(1+exp(-k*x))`.

Output: fitted k per era (V4, V4.1, V5, combined), 95% bootstrap CI,
reliability diagram as a PNG, and a JSON summary.

Usage:
    export SUPABASE_SERVICE_KEY='eyJ...'   # NEVER commit this
    python3 scripts/python/analyze_k.py [--out-dir docs]

The key is read from the environment only. It is never written to disk.
Rotate after use via Supabase → Project Settings → API.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL", "https://rapmxqnxsobvxqtfnwqh.supabase.co"
)
TABLE = "shadow_trade_log"
ERAS = ("V4", "V4.1", "V5")


def fetch_all(key: str) -> list[dict]:
    """Page through shadow_trade_log and return all settled rows for ERAS."""
    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    in_list = ",".join(ERAS)
    rows: list[dict] = []
    last_id = 0
    while True:
        q = (
            f"{url}?select=id,session_tag,direction,entry_price,strike_delta,"
            f"elapsed_seconds,terminal_probability,outcome,pnl"
            f"&session_tag=in.({in_list})"
            f"&id=gt.{last_id}&order=id.asc&limit=5000"
        )
        req = urllib.request.Request(q, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            batch = json.loads(resp.read())
        if not batch:
            break
        rows.extend(batch)
        last_id = batch[-1]["id"]
        print(f"  fetched {len(rows):>6} rows (last_id={last_id})", file=sys.stderr)
    return rows


def build_features(rows: list[dict], tags: set[str]) -> tuple[np.ndarray, np.ndarray]:
    X: list[float] = []
    y: list[int] = []
    for r in rows:
        if r["session_tag"] not in tags:
            continue
        sd = r["strike_delta"]
        el = r["elapsed_seconds"]
        oc = r["outcome"]
        if sd is None or el is None or oc not in ("win", "loss"):
            continue
        t_rem = max(1.0, 300.0 - el)
        X.append(abs(sd) / math.sqrt(t_rem / 60.0))
        y.append(1 if oc == "win" else 0)
    return np.asarray(X), np.asarray(y)


def nll(k: float, X: np.ndarray, y: np.ndarray) -> float:
    p = 1.0 / (1.0 + np.exp(np.clip(-k * X, -500, 500)))
    return float(-np.mean(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12)))


def fit_k(X: np.ndarray, y: np.ndarray) -> float:
    return float(
        minimize_scalar(
            lambda k: nll(k, X, y), bounds=(1e-4, 0.5), method="bounded"
        ).x
    )


def bootstrap_ci(
    X: np.ndarray, y: np.ndarray, n_boots: int = 200, seed: int = 42
) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    n = len(X)
    ks = []
    for _ in range(n_boots):
        idx = rng.integers(0, n, n)
        ks.append(fit_k(X[idx], y[idx]))
    arr = np.asarray(ks)
    return float(np.quantile(arr, 0.025)), float(np.quantile(arr, 0.975))


def calibration(
    X: np.ndarray, y: np.ndarray, k: float, nbins: int = 10
) -> list[dict]:
    p = 1 / (1 + np.exp(np.clip(-k * X, -500, 500)))
    bins = np.quantile(p, np.linspace(0, 1, nbins + 1))
    bins[0] -= 1e-9
    bins[-1] += 1e-9
    out = []
    for i in range(nbins):
        m = (p >= bins[i]) & (p < bins[i + 1])
        if m.sum() == 0:
            continue
        out.append(
            {
                "bin": i + 1,
                "n": int(m.sum()),
                "predicted": float(p[m].mean()),
                "actual": float(y[m].mean()),
            }
        )
    return out


def save_chart(rows, results, out_path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 3, figsize=(15, 5))
    for ax, (label, tags) in zip(
        axes,
        [
            ("V5", {"V5"}),
            ("V4.1", {"V4.1"}),
            ("V4+V4.1+V5", {"V4", "V4.1", "V5"}),
        ],
    ):
        X, y = build_features(rows, tags)
        k_hat = results[label if label != "V4+V4.1+V5" else "combined"]["k_hat"]
        c1 = calibration(X, y, 0.035)
        c2 = calibration(X, y, k_hat)
        ax.plot([0, 1], [0, 1], "k--", alpha=0.3)
        ax.plot(
            [b["predicted"] for b in c1],
            [b["actual"] for b in c1],
            "o-",
            color="crimson",
            label="current k=0.035",
            markersize=8,
        )
        ax.plot(
            [b["predicted"] for b in c2],
            [b["actual"] for b in c2],
            "s-",
            color="seagreen",
            label=f"fitted k={k_hat:.4f}",
            markersize=8,
        )
        ax.set_xlabel("Predicted P(win)")
        ax.set_ylabel("Actual win rate")
        ax.set_title(f"{label}  (n={len(X):,}  wr={y.mean():.3f})")
        ax.legend(loc="upper left")
        ax.grid(alpha=0.3)
        ax.set_xlim(0.4, 1.0)
        ax.set_ylim(0.2, 1.0)
    plt.tight_layout()
    plt.savefig(out_path, dpi=120, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="docs", help="where to write outputs")
    ap.add_argument(
        "--no-chart", action="store_true", help="skip the calibration plot"
    )
    ap.add_argument("--boots", type=int, default=200, help="bootstrap samples")
    args = ap.parse_args()

    key = os.environ.get("SUPABASE_SERVICE_KEY")
    if not key:
        print(
            "error: SUPABASE_SERVICE_KEY env var is required (service_role).",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("fetching shadow_trade_log...", file=sys.stderr)
    rows = fetch_all(key)
    print(f"total fetched: {len(rows)}", file=sys.stderr)

    results: dict[str, dict] = {}
    for label, tags in [
        ("V5", {"V5"}),
        ("V4.1", {"V4.1"}),
        ("combined", {"V4", "V4.1", "V5"}),
    ]:
        X, y = build_features(rows, tags)
        k_hat = fit_k(X, y)
        ci = bootstrap_ci(X, y, n_boots=args.boots)
        results[label] = {
            "n": int(len(X)),
            "win_rate": float(y.mean()),
            "k_hat": k_hat,
            "k_ci_95": list(ci),
            "nll_at_0.035": nll(0.035, X, y),
            "nll_at_k_hat": nll(k_hat, X, y),
        }
        print(
            f"{label:>10}: n={len(X):>6}  win_rate={y.mean():.4f}  "
            f"k_hat={k_hat:.4f}  CI=[{ci[0]:.4f}, {ci[1]:.4f}]",
            file=sys.stderr,
        )

    summary_path = out_dir / "k_fit_summary.json"
    summary_path.write_text(json.dumps(results, indent=2))
    print(f"wrote {summary_path}", file=sys.stderr)

    if not args.no_chart:
        chart_path = out_dir / "k_calibration.png"
        save_chart(rows, results, chart_path)
        print(f"wrote {chart_path}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
