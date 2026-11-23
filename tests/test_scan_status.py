"""A scan left 'building' in progress.json by a server that was restarted must not read as still running."""
import json
import time

from patterns import scan


def _setup(monkeypatch, tmp_path, prog):
    f = tmp_path / "progress.json"
    f.write_text(json.dumps(prog), encoding="utf-8")
    monkeypatch.setattr(scan, "PROGRESS_FILE", str(f))
    monkeypatch.setattr(scan, "_proc", None)
    monkeypatch.setattr(scan, "_load_all", lambda: {})
    monkeypatch.setattr(scan, "universe", lambda: [])
    return f


def test_a_building_flag_with_no_recent_heartbeat_is_not_building(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"building": True, "total": 3105, "done": 1475, "updated": time.time() - 3600})
    assert scan.status()["building"] is False


def test_an_old_file_without_a_heartbeat_is_not_building(monkeypatch, tmp_path):
    f = _setup(monkeypatch, tmp_path, {"building": True, "total": 3105, "done": 1475})
    old = time.time() - 5 * 86400
    import os
    os.utime(f, (old, old))
    assert scan.status()["building"] is False


def test_a_scan_that_is_still_reporting_is_building(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"building": True, "total": 3105, "done": 1475, "updated": time.time() - 30})
    s = scan.status()
    assert s["building"] is True and s["done"] == 1475


def test_progress_writes_carry_a_heartbeat(monkeypatch, tmp_path):
    f = tmp_path / "p.json"
    monkeypatch.setattr(scan, "PROGRESS_FILE", str(f))
    monkeypatch.setattr(scan, "DATA_DIR", str(tmp_path))
    scan._write_progress(building=True, total=1, done=0)
    assert abs(json.loads(f.read_text())["updated"] - time.time()) < 5
