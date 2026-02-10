"""Unit tests for metrics pairing and latency helpers."""
import unittest
from lib import metrics_storage as ms


class TestMetricsCalculations(unittest.TestCase):
    def test_open_close_pairing_simple(self):
        events = [
            {"ts": "2026-02-01 10:00:00", "event_type": "Door OPEN/UNLOCKED", "badge_id": "1"},
            {"ts": "2026-02-01 10:05:00", "event_type": "Door CLOSED/LOCKED", "badge_id": "1"},
        ]
        res = ms.compute_open_durations(events)
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["duration"], 300)

    def test_open_close_pairing_multiple(self):
        events = [
            {"ts": "2026-02-01 10:00:00", "event_type": "Door OPEN/UNLOCKED", "badge_id": "1"},
            {"ts": "2026-02-01 11:00:00", "event_type": "Door OPEN/UNLOCKED", "badge_id": "2"},
            {"ts": "2026-02-01 10:05:00", "event_type": "Door CLOSED/LOCKED", "badge_id": "1"},
            {"ts": "2026-02-01 12:00:00", "event_type": "Door CLOSED/LOCKED", "badge_id": "2"},
        ]
        res = ms.compute_open_durations(events)
        self.assertEqual(len(res), 2)
        self.assertAlmostEqual(res[0]["duration"], 300)
        self.assertAlmostEqual(res[1]["duration"], 3600)

    def test_unpaired_open_ignored(self):
        events = [
            {"ts": "2026-02-01 10:00:00", "event_type": "Door OPEN/UNLOCKED", "badge_id": "1"},
        ]
        res = ms.compute_open_durations(events)
        self.assertEqual(len(res), 0)

    def test_scan_to_open_latency_simple(self):
        events = [
            {"ts": "2026-02-01 10:00:00", "event_type": "Badge Scan", "badge_id": "1"},
            {"ts": "2026-02-01 10:00:10", "event_type": "Door OPEN/UNLOCKED", "badge_id": "1"},
        ]
        res = ms.compute_scan_to_open_latencies(events, max_window=60)
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["delta"], 10)

    def test_scan_to_open_latency_out_of_window(self):
        events = [
            {"ts": "2026-02-01 10:00:00", "event_type": "Badge Scan", "badge_id": "1"},
            {"ts": "2026-02-01 10:05:10", "event_type": "Door OPEN/UNLOCKED", "badge_id": "1"},
        ]
        res = ms.compute_scan_to_open_latencies(events, max_window=60)
        self.assertEqual(len(res), 0)

    def test_compute_basic_stats(self):
        vals = [1, 2, 3, 4, 100]
        s = ms.compute_basic_stats(vals)
        self.assertEqual(s["count"], 5)
        self.assertAlmostEqual(s["avg"], 22)
        self.assertEqual(s["median"], 3)
        self.assertEqual(s["p95"], 100)


if __name__ == '__main__':
    unittest.main()
