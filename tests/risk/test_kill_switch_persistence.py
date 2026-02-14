import json
import time
from pathlib import Path

from src.config.settings import get_settings
from agents.application.risk_manager import RiskManager


def write_paper_log(path: Path, pnls):
    lines = []
    for i, pnl in enumerate(pnls):
        lines.append(json.dumps({"trade_id": f"t{i}", "realized_pnl": pnl, "exit_time_utc": f"2026-01-01T0{i}:00:00Z"}))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_kill_switch_blocks_during_cooldown(tmp_path):
    settings = get_settings()
    paper = tmp_path / "paper_trades.jsonl"
    # create 3 losing trades totaling -6
    write_paper_log(paper, [-2.0, -2.0, -2.0])
    settings.PAPER_LOG_PATH = str(paper)
    settings.RISK_STATE_PATH = str(tmp_path / "risk_state.json")
    settings.KILL_SWITCH_LOOKBACK_CLOSED = 3
    settings.KILL_SWITCH_MAX_REALIZED_LOSS = -5.0
    settings.KILL_SWITCH_MIN_WINRATE = 0.25
    settings.KILL_SWITCH_COOLDOWN_SECONDS = 60

    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    allowed, reason, details = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=None)
    assert not allowed
    assert reason in ("kill_switch", "kill_switch_cooldown")
    # subsequent call should be in cooldown
    allowed2, reason2, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=None)
    assert not allowed2
    assert reason2 == "kill_switch_cooldown"


def test_kill_switch_persists_and_survives_restart(tmp_path):
    settings = get_settings()
    paper = tmp_path / "paper_trades.jsonl"
    write_paper_log(paper, [-2.0, -2.0, -2.0])
    settings.PAPER_LOG_PATH = str(paper)
    state = tmp_path / "risk_state.json"
    settings.RISK_STATE_PATH = str(state)
    settings.KILL_SWITCH_LOOKBACK_CLOSED = 3
    settings.KILL_SWITCH_MAX_REALIZED_LOSS = -5.0
    settings.KILL_SWITCH_MIN_WINRATE = 0.25
    settings.KILL_SWITCH_COOLDOWN_SECONDS = 60

    rm1 = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    a, r, d = rm1.check_entry_allowed(token_id="t1", confidence=5, adapter=None)
    assert not a
    # state file should exist
    assert state.exists()
    # new instance should load state and block
    rm2 = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    allowed, reason, _ = rm2.check_entry_allowed(token_id="t1", confidence=5, adapter=None)
    assert not allowed
    assert reason == "kill_switch_cooldown"


def test_kill_switch_expires_and_clears_state(tmp_path):
    settings = get_settings()
    # create explicit state file with past until
    state = tmp_path / "risk_state.json"
    data = {"kill_switch_until_ts": time.time() - 10.0, "kill_switch_reason": "test", "kill_switch_last_trigger_ts": time.time() - 100}
    state.write_text(json.dumps(data), encoding="utf-8")
    settings.RISK_STATE_PATH = str(state)
    # ensure other gates won't block
    settings.ENTRY_REQUIRE_FRESH_BOOK = False
    # ensure no legacy closed trades influence kill-switch recompute
    paper = tmp_path / "paper_trades.jsonl"
    paper.write_text("", encoding="utf-8")
    settings.PAPER_LOG_PATH = str(paper)
    rm = RiskManager(settings.INITIAL_EQUITY, settings.MAX_EXPOSURE_PCT, settings.BASE_RISK_PCT)
    # expired -> should allow (subject to other gates, which we disabled)
    allowed, reason, _ = rm.check_entry_allowed(token_id="t1", confidence=5, adapter=None)
    assert allowed
    # ensure state has been cleared
    assert not state.exists()

