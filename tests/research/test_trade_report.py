import sys
from pathlib import Path
import json

sys.path.append(".")

from tools.research import trade_report as tr


def test_parse_and_metrics(tmp_path):
    fixtures = Path("tests/research/fixtures")
    files = tr.find_trade_files([str(fixtures)], ["**/*.jsonl"])
    assert files, "fixtures not found"
    all_trades = []
    for f in files:
        recs = tr.read_trades(f)
        for r in recs:
            all_trades.append(tr.normalize_trade(r, str(f)))

    # total 10 in fixture
    assert len(all_trades) == 10

    # compute all metrics
    metrics = tr.compute_metrics(all_trades)
    assert metrics["total_trades"] == 10
    assert metrics["closed_trades"] == 10
    # wins: count positive pnls excluding smoke (two smoke with one win, one loss)
    assert metrics["wins"] >= 6

    # only real filter
    real_trades = [t for t in all_trades if not (t["is_smoke"] or t["is_test"] or t["is_paper"])]
    real_metrics = tr.compute_metrics(real_trades)
    assert real_metrics["total_trades"] == len(real_trades)
    assert real_metrics["wins"] == sum(1 for t in real_trades if t.get("pnl") and t["pnl"] > 0)

    # rolling last_n
    sorted_closed, info = tr.filter_recent(all_trades, last_n=5, since_hours=None, tz=tr.timezone.utc)
    assert len(info["last_n"]) == 5

    # markdown generation contains sections
    md = tr.generate_markdown({"all": metrics, "real": real_metrics}, "UTC")
    assert "Trade Performance Report" in md
    assert "Only real trades" in md

