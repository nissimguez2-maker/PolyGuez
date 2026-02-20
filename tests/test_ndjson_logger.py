import os, json, tempfile

def test_ndjson_logger_writes(tmp_path, monkeypatch):
    fp = tmp_path / "dbg.log"
    monkeypatch.setenv("DEBUG_NDJSON_LOG", "1")
    monkeypatch.setenv("DEBUG_NDJSON_LOG_PATH", str(fp))
    from src.debug.ndjson_logger import dbg_log, is_enabled
    assert is_enabled() is True
    dbg_log("T1", "test.location", "test msg", {"k": "v"}, run_id="r1")
    dbg_log("T2", "test.location2", "test msg2", {"k2": 2}, run_id="r1")
    txt = fp.read_text(encoding="utf-8").strip().splitlines()
    assert len(txt) == 2
    for line in txt:
        obj = json.loads(line)
        assert "id" in obj and "ts_iso" in obj and "ts_ms" in obj
