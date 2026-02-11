import os
import sqlite3
from datetime import datetime
from src_service.metrics_storage import reload_action_logs, get_month_db_path


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

    # Ensure file still contains action lines (reload should not delete logs)
    txt = log_file.read_text()
    assert "Badge Scan" in txt
    assert "Door OPEN/UNLOCKED" in txt


def test_ingest_records_import_metadata_and_prevents_duplicates(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    content = (
        "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
        "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
    )
    log_file = logs_dir / "door_controller_action-2026-02-01.txt"
    log_file.write_text(content)

    db_base = tmp_path / "metrics"
    db_base.mkdir()

    # ingest twice without deleting source lines to simulate repeated reloads
    inserted1 = ingest_action_log_file(str(log_file), base_path=str(db_base), delete_file=False)
    inserted2 = ingest_action_log_file(str(log_file), base_path=str(db_base), delete_file=False)

    assert inserted1 == 2
    # second ingest should not duplicate same source lines
    assert inserted2 == 0

    # verify metadata recorded
    db_path = get_month_db_path("2026-02", base_path=str(db_base))
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT imported_file, imported_line_number FROM events ORDER BY imported_line_number ASC")
    rows = cur.fetchall()
    conn.close()
    assert rows == [("door_controller_action-2026-02-01.txt", 1), ("door_controller_action-2026-02-01.txt", 2)]


def test_ingest_action_log_file_deletes_by_default(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    content = (
        "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
        "Some comment\n"
    )
    log_file = logs_dir / "door_controller_action-2026-02-01.txt"
    log_file.write_text(content)

    db_base = tmp_path / "metrics"
    db_base.mkdir()

    inserted = ingest_action_log_file(str(log_file), base_path=str(db_base))
    assert inserted == 1

    # file should have comments preserved but action line removed
    txt = log_file.read_text()
    assert "Badge Scan" not in txt
    assert "Some comment" in txt


def test_ingest_action_log_file_preserves_when_delete_false(tmp_path):
    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    content = (
        "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
        "Another comment\n"
    )
    log_file = logs_dir / "door_controller_action-2026-02-01.txt"
    log_file.write_text(content)

    db_base = tmp_path / "metrics"
    db_base.mkdir()

    inserted = ingest_action_log_file(str(log_file), base_path=str(db_base), delete_file=False)
    assert inserted == 1

    # file should still contain the action line
    txt = log_file.read_text()
    assert "Badge Scan" in txt
    assert "Another comment" in txt
