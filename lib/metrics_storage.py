"""SQLite-backed monthly metrics storage and cross-month query helpers."""
import csv
import os
import re
import sqlite3
from datetime import date, datetime
from io import StringIO
from typing import Dict, List, Optional, Sequence, Tuple

from .config import config

EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    badge_id TEXT,
    status TEXT NOT NULL,
    raw_message TEXT NOT NULL,
    imported_file TEXT,
    imported_line_number INTEGER
);
"""

EVENTS_INDEX_SQL = (
    "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);",
    "CREATE INDEX IF NOT EXISTS idx_events_event_type ON events(event_type);",
    "CREATE INDEX IF NOT EXISTS idx_events_badge_id ON events(badge_id);",
    # Prevent importing the same source line twice
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_imported_file_line ON events(imported_file, imported_line_number);",
)

_ACTION_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) - [^-]+ - [A-Z]+ - (?P<message>.*)$"
)
_BADGE_PART = " - Badge: "
_STATUS_PART = " - Status: "


def get_metrics_base_path() -> str:
    """Return configured base path for metrics db files."""
    return str(config.get("METRICS_DB_PATH", "logs/metrics"))


def normalize_status(status: Optional[str]) -> str:
    """Return a lowercase normalized status token, fallback to 'unknown'."""
    if status is None:
        return "unknown"
    s = str(status).strip()
    return s.lower() if s else "unknown"


def normalize_event_type(raw_event: Optional[str]) -> str:
    """Normalize a raw event description into a simplified token.

    Examples:
      - "Badge Scan" -> "scan"
      - "Door OPEN/UNLOCKED" -> "open"
      - "Manual Unlock (1 hour)" -> "manual_unlock"
      - "Some Other Event" -> "some_other_event"
    """
    if raw_event is None:
        return "unknown"
    et = str(raw_event).lower()
    # remove parenthetical notes like "(1 hour)"
    et = re.sub(r"\(.*\)", "", et).strip()
    # normalize whitespace
    et = re.sub(r"\s+", " ", et)

    if not et:
        return "unknown"

    if "manual lock" in et:
        return "manual_lock"
    if "manual unlock" in et:
        return "manual_unlock"
    if "scan" in et or "badge" in et:
        return "scan"
    if "open" in et or "unlocked" in et:
        return "open"
    if "close" in et or "closed" in et or "locked" in et:
        return "close"

    # fallback: convert to snake_case-like token
    key = re.sub(r"\W+", "_", et).strip("_")
    return key or et


def _month_key_for_datetime(ts: datetime) -> str:
    return ts.strftime("%Y-%m")


def get_month_db_path(month_key: str, base_path: Optional[str] = None) -> str:
    """Return monthly db path in year/year-month.db format."""
    base = base_path or get_metrics_base_path()
    year = month_key.split("-")[0]
    return os.path.join(base, year, "{0}.db".format(month_key))


def ensure_month_db(month_key: str, base_path: Optional[str] = None) -> str:
    """Create month db/schema if missing and return its path."""
    db_path = get_month_db_path(month_key, base_path=base_path)
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(EVENTS_TABLE_SQL)
        for stmt in EVENTS_INDEX_SQL:
            conn.execute(stmt)
        conn.commit()
    finally:
        conn.close()
    return db_path


def _parse_action_message(message: str) -> Optional[Dict[str, str]]:
    badge_id = None
    event_type = None
    status = "Unknown"

    raw_event = None
    if _BADGE_PART in message and _STATUS_PART in message:
        left, right = message.split(_BADGE_PART, 1)
        badge_part, status_part = right.rsplit(_STATUS_PART, 1)
        raw_event = left.strip()
        badge_id = badge_part.strip() or None
        status = normalize_status(status_part)
    elif _STATUS_PART in message:
        left, status_part = message.rsplit(_STATUS_PART, 1)
        raw_event = left.strip()
        status = normalize_status(status_part)
    else:
        # Message didn't match expected patterns
        return None

    if not raw_event:
        return None

    # Normalize event type using helper
    event_type = normalize_event_type(raw_event)

    return {"event_type": event_type, "badge_id": badge_id, "status": status}


def parse_action_log_line(line: str) -> Optional[Dict[str, str]]:
    """Parse action log line into normalized event dict."""
    raw = line.strip()
    if not raw:
        return None

    match = _ACTION_LINE_RE.match(raw)
    if not match:
        return None

    parsed = _parse_action_message(match.group("message"))
    if parsed is None:
        return None

    parsed["ts"] = match.group("ts")
    parsed["raw_message"] = raw
    return parsed


def ingest_action_log_file(path: str, base_path: Optional[str] = None, delete_file: bool = True) -> int:
    """
    Parse a dated action log file and persist events into monthly sqlite dbs using bulk inserts.

    Args:
        path: Path to the action log file.
        base_path: Base path for metrics db files.
        delete_file: If True, remove parsed action lines from the log file (defaults to True).

    Returns:
        Number of inserted records.
    """
    if not os.path.exists(path):
        return 0

    events_to_insert = []
    kept_lines = []

    # Read and parse lines (capture source file and line number)
    basename = os.path.basename(path)
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, start=1):
            parsed = parse_action_log_line(line)
            if parsed is None:
                kept_lines.append(line)
                continue
            parsed["imported_file"] = basename
            parsed["imported_line_number"] = lineno
            events_to_insert.append(parsed)

    if not events_to_insert:
        # Nothing to insert; if delete_file True and file only had non-action lines, leave it alone
        return 0

    # Group events by month_key for bulk insert
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for ev in events_to_insert:
        try:
            ts = datetime.strptime(ev["ts"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            # skip malformed
            continue
        month_key = _month_key_for_datetime(ts)
        grouped.setdefault(month_key, []).append(ev)

    inserted = 0
    for month_key, rows in grouped.items():
        db_path = ensure_month_db(month_key, base_path=base_path)
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=OFF;")
            cur = conn.cursor()
            cur.execute("BEGIN")
            before_changes = conn.total_changes
            cur.executemany(
                "INSERT OR IGNORE INTO events (ts, event_type, badge_id, status, raw_message, imported_file, imported_line_number) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        r["ts"],
                        r.get("event_type"),
                        r.get("badge_id"),
                        r.get("status"),
                        r.get("raw_message"),
                        r.get("imported_file"),
                        r.get("imported_line_number"),
                    )
                    for r in rows
                ],
            )
            conn.commit()
            # Compute how many rows were actually inserted in this connection
            after_changes = conn.total_changes
            inserted += (after_changes - before_changes)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # If requested, write back kept_lines (non-action lines) atomically; otherwise leave file as-is
    if delete_file:
        import tempfile
        import shutil
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path) or '.')
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as outfh:
                outfh.writelines(kept_lines)
            shutil.move(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass

    return inserted


def month_keys_in_range(start_date: date, end_date: date) -> List[str]:
    """Return inclusive YYYY-MM keys spanning start_date..end_date."""
    if end_date < start_date:
        return []
    months: List[str] = []
    cur = date(start_date.year, start_date.month, 1)
    final = date(end_date.year, end_date.month, 1)
    while cur <= final:
        months.append("{0:04d}-{1:02d}".format(cur.year, cur.month))
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    return months


def db_paths_in_range(start_date: date, end_date: date, base_path: Optional[str] = None) -> List[str]:
    """Return existing db paths in range; create current-month db when missing."""
    paths: List[str] = []
    now_key = datetime.now().strftime("%Y-%m")
    for month_key in month_keys_in_range(start_date, end_date):
        db_path = get_month_db_path(month_key, base_path=base_path)
        if os.path.exists(db_path):
            paths.append(db_path)
            continue
        if month_key == now_key:
            ensure_month_db(month_key, base_path=base_path)
            paths.append(db_path)
    return paths


def attach_databases(conn: sqlite3.Connection, db_paths: Sequence[str]) -> List[str]:
    """Attach db files and return aliases in attachment order."""
    aliases: List[str] = []
    for idx, path in enumerate(db_paths):
        alias = "m{0}".format(idx)
        conn.execute("ATTACH DATABASE ? AS {0}".format(alias), (path,))
        aliases.append(alias)
    return aliases


def build_union_all_query(aliases: Sequence[str], where_clause: str = "") -> str:
    """Build SELECT ... UNION ALL query body over attached monthly db aliases."""
    if not aliases:
        return (
            "SELECT ts, event_type, badge_id, status, raw_message "
            "FROM (SELECT 1 AS x) WHERE 1=0"
        )
    select_parts = [
        "SELECT ts, event_type, badge_id, status, raw_message FROM {0}.events {1}".format(
            alias, where_clause
        )
        for alias in aliases
    ]
    return " UNION ALL ".join(select_parts)


def _event_row(row: Tuple[str, str, Optional[str], str, str]) -> Dict[str, Optional[str]]:
    return {
        "ts": row[0],
        "event_type": row[1],
        "badge_id": row[2],
        "status": row[3],
        "raw_message": row[4],
    }


def query_events_range(
    start_ts: str,
    end_ts: str,
    event_types: Optional[Sequence[str]] = None,
) -> List[Dict[str, Optional[str]]]:
    """Query normalized events across monthly databases in timestamp range."""
    start_date = datetime.strptime(start_ts, "%Y-%m-%d %H:%M:%S").date()
    end_date = datetime.strptime(end_ts, "%Y-%m-%d %H:%M:%S").date()
    db_paths = db_paths_in_range(start_date, end_date)
    if not db_paths:
        return []

    conn = sqlite3.connect(":memory:")
    try:
        aliases = attach_databases(conn, db_paths)
        where = "WHERE ts >= ? AND ts <= ?"
        params: List[str] = []
        if event_types:
            placeholders = ",".join(["?"] * len(event_types))
            where += " AND event_type IN ({0})".format(placeholders)

        union_sql = build_union_all_query(aliases, where_clause=where)
        sql = "SELECT ts, event_type, badge_id, status, raw_message FROM ({0}) ORDER BY ts ASC".format(
            union_sql
        )
        for _alias in aliases:
            params.extend([start_ts, end_ts])
            if event_types:
                params.extend(event_types)

        rows = conn.execute(sql, tuple(params)).fetchall()
        return [_event_row(row) for row in rows]
    finally:
        conn.close()


def query_month_events(month_key: str) -> List[Dict[str, Optional[str]]]:
    """Return all events from a specific month db."""
    db_path = get_month_db_path(month_key)
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT ts, event_type, badge_id, status, raw_message FROM events ORDER BY ts ASC"
        ).fetchall()
        return [_event_row(row) for row in rows]
    finally:
        conn.close()


def month_events_to_csv(events: Sequence[Dict[str, Optional[str]]]) -> str:
    """Serialize event records to CSV."""
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ts", "event_type", "badge_id", "status", "raw_message"])
    for item in events:
        writer.writerow(
            [
                item.get("ts"),
                item.get("event_type"),
                item.get("badge_id"),
                item.get("status"),
                item.get("raw_message"),
            ]
        )
    return output.getvalue()


# ---------------------------------------------------------------------------
# Event pairing and latency helpers (pure-Python versions used for testing)
# ---------------------------------------------------------------------------

def _normalize_event_type_py(raw_event: Optional[str]) -> str:
    """Normalize a raw event string into a simple token (Python helper)."""
    if raw_event is None:
        return "unknown"
    et = str(raw_event).lower()
    et = re.sub(r"\(.*\)", "", et).strip()
    et = re.sub(r"\s+", " ", et)
    if not et:
        return "unknown"
    if "manual lock" in et:
        return "manual_lock"
    if "manual unlock" in et:
        return "manual_unlock"
    if "scan" in et or "badge" in et:
        return "scan"
    if "open" in et or "unlocked" in et:
        return "open"
    if "close" in et or "closed" in et or "locked" in et:
        return "close"
    key = re.sub(r"\W+", "_", et).strip("_")
    return key or et


def compute_open_durations(events: Sequence[Dict[str, Optional[str]]]) -> List[Dict[str, Optional[float]]]:
    """Compute open->close durations (seconds) by pairing chronological events.

    Returns a list of dicts: {'open_ts': str, 'close_ts': str, 'duration': float, 'badge_id': Optional[str]}

    Pairing strategy: sort 'open' events and 'close' events separately by timestamp, then for each open
    find the next close with ts > open.ts and pair them once. Unpaired opens are ignored.
    """
    opens = []
    closes = []
    for e in events:
        et = _normalize_event_type_py(e.get("event_type"))
        if et == "open":
            opens.append(e)
        elif et == "close":
            closes.append(e)
    def _to_dt(s: str) -> Optional[datetime]:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
    opens_sorted = sorted(opens, key=lambda x: _to_dt(x.get("ts") or "" ) or datetime.min)
    closes_sorted = sorted(closes, key=lambda x: _to_dt(x.get("ts") or "" ) or datetime.min)

    results: List[Dict[str, Optional[float]]] = []
    cidx = 0
    for o in opens_sorted:
        o_dt = _to_dt(o.get("ts") or "")
        if o_dt is None:
            continue
        # advance to a close strictly after open
        while cidx < len(closes_sorted):
            c_dt = _to_dt(closes_sorted[cidx].get("ts") or "")
            if c_dt is None or c_dt <= o_dt:
                cidx += 1
                continue
            # pair
            duration = (c_dt - o_dt).total_seconds()
            results.append({
                "open_ts": o.get("ts"),
                "close_ts": closes_sorted[cidx].get("ts"),
                "duration": duration,
                "badge_id": o.get("badge_id") or None,
            })
            cidx += 1
            break
    return results


def compute_scan_to_open_latencies(events: Sequence[Dict[str, Optional[str]]], max_window: int = 60) -> List[Dict[str, Optional[float]]]:
    """Compute scan->next-open latencies (seconds) pairing scans to the next open event within max_window seconds.

    Returns list of dicts: {'scan_ts', 'open_ts', 'delta', 'badge_id'}
    """
    scans = [e for e in events if _normalize_event_type_py(e.get("event_type")) == "scan"]
    opens = [e for e in events if _normalize_event_type_py(e.get("event_type")) == "open"]

    def _to_dt(s: str) -> Optional[datetime]:
        try:
            return datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    scans_sorted = sorted(scans, key=lambda x: _to_dt(x.get("ts") or "") or datetime.min)
    opens_sorted = sorted(opens, key=lambda x: _to_dt(x.get("ts") or "") or datetime.min)

    res: List[Dict[str, Optional[float]]] = []
    oidx = 0
    for s in scans_sorted:
        s_dt = _to_dt(s.get("ts") or "")
        if s_dt is None:
            continue
        while oidx < len(opens_sorted) and ( _to_dt(opens_sorted[oidx].get("ts") or "") or datetime.min ) < s_dt:
            oidx += 1
        if oidx < len(opens_sorted):
            o_dt = _to_dt(opens_sorted[oidx].get("ts") or "")
            if o_dt is None:
                continue
            delta = (o_dt - s_dt).total_seconds()
            if 0 <= delta <= max_window:
                res.append({
                    "scan_ts": s.get("ts"),
                    "open_ts": opens_sorted[oidx].get("ts"),
                    "delta": delta,
                    "badge_id": s.get("badge_id") or None,
                })
    return res


def compute_basic_stats(values: Sequence[float]) -> Dict[str, Optional[float]]:
    """Return simple stats: count, avg, median, p95 (or None for empty)."""
    import statistics
    if not values:
        return {"count": 0, "avg": None, "median": None, "p95": None}
    vals = sorted(values)
    count = len(vals)
    avg = sum(vals) / count
    median = statistics.median(vals)
    # p95 (use ceiling-based index to include high-tail values for small samples)
    import math
    idx = min(count - 1, max(0, math.ceil(0.95 * count) - 1))
    p95 = vals[idx]
    return {"count": count, "avg": avg, "median": median, "p95": p95}


def reload_action_logs(log_dir: Optional[str] = None, base_path: Optional[str] = None) -> dict:
    """Scan action log files and bulk-insert parsed events into monthly DBs WITHOUT deleting or modifying log files.

    Uses `ingest_action_log_file(..., delete_file=False)` so logs are left intact.

    Returns a dict with keys: inserted, files_processed, files_scanned.
    """
    log_dir = log_dir or os.path.dirname(config.get("LOG_FILE", "")) or "logs"
    base_path = base_path or get_metrics_base_path()

    files_scanned = 0
    files_processed = 0
    total_inserted = 0

    if not os.path.isdir(log_dir):
        return {"inserted": 0, "files_processed": 0, "files_scanned": 0}

    # Determine log extension from configured LOG_FILE (default to .txt)
    cfg_log = config.get("LOG_FILE", "") or ""
    _, ext = os.path.splitext(cfg_log)
    if not ext:
        ext = ".txt"

    for name in os.listdir(log_dir):
        # match files like *_action-YYYY-MM-DD.<ext> or *_action<ext>
        if not name.endswith(ext):
            continue
        if "_action-" not in name and not name.endswith(f"_action{ext}"):
            continue
        path = os.path.join(log_dir, name)
        files_scanned += 1
        try:
            inserted = ingest_action_log_file(path, base_path=base_path, delete_file=False)
            if inserted:
                total_inserted += inserted
                files_processed += 1
        except Exception as e:
            try:
                get_logger().error(f"Failed to process action log {path}: {e}")
            except Exception:
                pass

    return {"inserted": total_inserted, "files_processed": files_processed, "files_scanned": files_scanned}
