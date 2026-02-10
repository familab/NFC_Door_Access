import os
import sqlite3
from datetime import datetime
from lib.metrics_storage import reload_action_logs, get_month_db_path


def test_reload_consumes_action_logs_and_inserts(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    # prepare an action log with two events and other lines
    content = (
        "Info line\n"
        "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
        "Another line\n"
        "2026-02-15 08:30:00 - door_action - INFO - Door OPEN/UNLOCKED - Badge: abc - Status: Success\n"
        "End\n"
    )
    log_file = logs_dir / "door_controller_action-2026-02-15.txt"
    log_file.write_text(content)

    db_base = tmp_path / "metrics"
    db_base.mkdir()

    res = reload_action_logs(log_dir=str(logs_dir), base_path=str(db_base))

    assert res["inserted"] == 2
    assert res["files_processed"] == 1
    assert res["files_scanned"] == 1

    # Check month DB exists and has rows
    month_key = "2026-02"
    db_path = get_month_db_path(month_key, base_path=str(db_base))
    assert os.path.exists(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM events")
    cnt = cur.fetchone()[0]
    conn.close()
    assert cnt == 2

    # Ensure file no longer contains action lines
    txt = log_file.read_text()
    assert "Badge Scan" not in txt
    assert "Door OPEN/UNLOCKED" not in txt
