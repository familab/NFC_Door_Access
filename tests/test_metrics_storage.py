"""Tests for sqlite metrics ingestion and cross-db helpers."""
import os
import sqlite3
import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from src_service.metrics_storage import (
    attach_databases,
    build_union_all_query,
    db_paths_in_range,
    ensure_month_db,
    get_month_db_path,
    ingest_action_log_file,
    month_keys_in_range,
    query_events_range,
)


class TestMetricsStorage(unittest.TestCase):
    def test_ingest_action_log_file_creates_month_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = os.path.join(tmpdir, "door_controller_action-2026-02-01.txt")
            with open(log_path, "w", encoding="utf-8") as handle:
                handle.write(
                    "2026-02-01 10:00:00 - door_action - INFO - Badge Scan - Badge: abc - Status: Granted\n"
                )
                handle.write(
                    "2026-02-01 10:00:02 - door_action - INFO - Door OPEN/UNLOCKED - Badge: abc - Status: Success\n"
                )

            with patch("src_service.metrics_storage.config.get", side_effect=lambda key, default=None: tmpdir if key == "METRICS_DB_PATH" else default):
                inserted = ingest_action_log_file(log_path)
                self.assertEqual(inserted, 2)
                db_path = get_month_db_path("2026-02", base_path=tmpdir)
                self.assertTrue(os.path.exists(db_path))
                conn = sqlite3.connect(db_path)
                try:
                    rows = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
                    self.assertEqual(rows, 2)
                finally:
                    conn.close()

    def test_month_helpers_and_cross_db_union(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ensure_month_db("2026-01", base_path=tmpdir)
            ensure_month_db("2026-02", base_path=tmpdir)
            jan = get_month_db_path("2026-01", base_path=tmpdir)
            feb = get_month_db_path("2026-02", base_path=tmpdir)

            conn = sqlite3.connect(jan)
            conn.execute(
                "INSERT INTO events (ts, event_type, badge_id, status, raw_message) VALUES (?, ?, ?, ?, ?)",
                ("2026-01-10 08:00:00", "Manual Lock", None, "Success", "x"),
            )
            conn.commit()
            conn.close()

            conn = sqlite3.connect(feb)
            conn.execute(
                "INSERT INTO events (ts, event_type, badge_id, status, raw_message) VALUES (?, ?, ?, ?, ?)",
                ("2026-02-10 09:00:00", "Manual Unlock (1 hour)", None, "Success", "y"),
            )
            conn.commit()
            conn.close()

            with patch("src_service.metrics_storage.config.get", side_effect=lambda key, default=None: tmpdir if key == "METRICS_DB_PATH" else default):
                self.assertEqual(month_keys_in_range(date(2026, 1, 1), date(2026, 2, 28)), ["2026-01", "2026-02"])
                paths = db_paths_in_range(date(2026, 1, 1), date(2026, 2, 28), base_path=tmpdir)
                self.assertEqual(paths, [jan, feb])

                mem = sqlite3.connect(":memory:")
                try:
                    aliases = attach_databases(mem, paths)
                    union_sql = build_union_all_query(aliases, where_clause="WHERE ts >= ? AND ts <= ?")
                    params = []
                    for _ in aliases:
                        params.extend(["2026-01-01 00:00:00", "2026-12-31 23:59:59"])
                    rows = mem.execute(
                        "SELECT COUNT(*) FROM ({0})".format(union_sql),
                        tuple(params),
                    ).fetchone()[0]
                    self.assertEqual(rows, 2)
                finally:
                    mem.close()

                events = query_events_range("2026-01-01 00:00:00", "2026-12-31 23:59:59")
                self.assertEqual(len(events), 2)

    def test_parse_action_message_normalization(self):
        from src_service.metrics_storage import parse_action_log_line
        cases = [
            ("2026-02-09 12:00:00 - foo - INFO - Badge Scan - Badge: 12345 - Status: OK", "scan", "12345", "ok"),
            ("2026-02-09 12:01:00 - foo - INFO - Door CLOSED - Status: LOCKED", "close", None, "locked"),
            ("2026-02-09 12:02:00 - foo - INFO - Door OPEN - Status: UNLOCKED", "open", None, "unlocked"),
            ("2026-02-09 12:03:00 - foo - INFO - Manual Lock - Status: OK", "manual_lock", None, "ok"),
            ("2026-02-09 12:04:00 - foo - INFO - Manual Unlock (1 hour) - Status: OK", "manual_unlock", None, "ok"),
            ("2026-02-09 12:05:00 - foo - INFO - Some Other Event - Status: YEP", "some_other_event", None, "yep"),
        ]
        for line, expect_type, expect_badge, expect_status in cases:
            parsed = parse_action_log_line(line)
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["event_type"], expect_type)
            self.assertEqual(parsed.get("badge_id"), expect_badge)
            self.assertEqual(parsed.get("status"), expect_status)

    def test_normalize_status_helper(self):
        from src_service.metrics_storage import normalize_status
        self.assertEqual(normalize_status("OK"), "ok")
        self.assertEqual(normalize_status(" Locked "), "locked")
        self.assertEqual(normalize_status(""), "unknown")
        self.assertEqual(normalize_status(None), "unknown")

    def test_normalize_event_type_helper(self):
        from src_service.metrics_storage import normalize_event_type
        cases = [
            ("Badge Scan", "scan"),
            ("Badge: 12345", "scan"),
            ("Door CLOSED/LOCKED", "close"),
            ("Door OPEN/UNLOCKED", "open"),
            ("Manual Lock", "manual_lock"),
            ("Manual Unlock (1 hour)", "manual_unlock"),
            ("Some Other Event", "some_other_event"),
            ("", "unknown"),
            (None, "unknown"),
        ]
        for raw, expect in cases:
            self.assertEqual(normalize_event_type(raw), expect)


if __name__ == "__main__":
    unittest.main()
