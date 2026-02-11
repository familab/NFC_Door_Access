# Metrics and Door Toggle API

[← Back to README](../README.md)

This project includes authenticated admin controls and a metrics dashboard:

- `POST /api/toggle` toggles the current lock state using the existing manual lock/unlock callbacks.
- `GET /metrics` renders the dashboard with date-range filtering and month pagination.
- `GET /api/metrics/*` returns JSON for charts and timeline.
- `GET /api/metrics/export?month=YYYY-MM&format=csv|json` exports monthly event data.

## Metrics Storage

Action logs are persisted to monthly SQLite databases during log cleanup before old files are deleted.

- Base path: `METRICS_DB_PATH` in config
- File structure: `year/year-month.db` (example: `2026/2026-02.db`)
- Table schema:

```sql
CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    badge_id TEXT,
    status TEXT NOT NULL,
    raw_message TEXT NOT NULL
);
CREATE INDEX idx_events_ts ON events(ts);
CREATE INDEX idx_events_event_type ON events(event_type);
CREATE INDEX idx_events_badge_id ON events(badge_id);
```

Cross-month queries use `ATTACH DATABASE` and `UNION ALL` helpers in `src_service/metrics_storage.py`.
