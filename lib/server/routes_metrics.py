"""Metrics routes - unified API with IndexedDB caching frontend."""
import json
import math
from datetime import date, datetime
from urllib.parse import parse_qs

from ..metrics_storage import query_events_range, month_events_to_csv
from .state import APPLICATION_JSON, check_rate_limit_metrics_reload, get_seconds_until_next_metrics_reload
from ..logging_utils import get_logger


def _parse_date(value: str, default_value: date) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return default_value


def _parse_int(value: str, default_value: int, minimum: int = 1, maximum: int = 10000) -> int:
    try:
        val = int(value)
        return max(minimum, min(maximum, val))
    except Exception:
        return default_value


def _query_parts(raw_query: str):
    return parse_qs(raw_query or "", keep_blank_values=False)


def _write_json(handler, payload, status_code=200):
    handler.send_response(status_code)
    handler.send_header("Content-type", APPLICATION_JSON)
    handler.end_headers()
    handler.wfile.write(json.dumps(payload).encode("utf-8"))


def handle_unified_metrics_api(handler, raw_query: str) -> bool:
    """Unified GET /api/metrics endpoint.

    Returns all structured metrics data.
    - Defaults: start=Jan 1 of current year, end=today
    - Max range: 365 days
    - Pagination supported
    - NO raw_message field (for efficiency)
    """
    query = _query_parts(raw_query)

    # Defaults
    now = datetime.now()
    default_start = date(now.year, 1, 1)
    default_end = date(now.year, now.month, now.day)

    start_date = _parse_date(query.get("start", [default_start.isoformat()])[0], default_start)
    end_date = _parse_date(query.get("end", [default_end.isoformat()])[0], default_end)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    # Validate 365-day max
    date_range_days = (end_date - start_date).days
    if date_range_days > 365:
        _write_json(handler, {
            "error": "Date range exceeds maximum of 365 days",
            "requested_days": date_range_days,
            "max_days": 365
        }, status_code=400)
        return True

    # Pagination
    page = _parse_int(query.get("page", ["1"])[0], 1)
    page_size = _parse_int(query.get("page_size", ["5000"])[0], 5000, minimum=100, maximum=10000)

    # Query
    start_ts = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end_ts = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59)

    try:
        all_events = query_events_range(
            start_ts.strftime("%Y-%m-%d %H:%M:%S"),
            end_ts.strftime("%Y-%m-%d %H:%M:%S"),
        )

        # Strip raw_message
        clean_events = [
            {k: v for k, v in event.items() if k != "raw_message"}
            for event in all_events
        ]

        # Handle CSV export if requested (returns full range as CSV)
        fmt = query.get("format", ["json"])[0].lower()
        if fmt == "csv":
            payload = month_events_to_csv(clean_events)
            handler.send_response(200)
            handler.send_header("Content-type", "text/csv; charset=utf-8")
            handler.send_header("Content-Disposition", f'attachment; filename="metrics-{start_date.isoformat()}_{end_date.isoformat()}.csv"')
            handler.end_headers()
            handler.wfile.write(payload.encode("utf-8"))
            return True

        # Paginate
        total = len(clean_events)
        total_pages = max(1, math.ceil(total / page_size)) if total else 1
        page = min(page, total_pages)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        _write_json(handler, {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "page": page,
            "page_size": page_size,
            "total_events": total,
            "total_pages": total_pages,
            "events": clean_events[start_idx:end_idx]
        })
        return True

    except Exception as e:
        get_logger().error(f"Metrics query failed: {e}")
        _write_json(handler, {"error": str(e)}, status_code=500)
        return True


def send_metrics_page(handler, raw_query: str):
    """Metrics dashboard with IndexedDB caching and client-side graphing."""

    # Parse URL params for initial date range
    query = _query_parts(raw_query)
    now = datetime.now()
    default_start = date(now.year, 1, 1)
    default_end = date(now.year, now.month, now.day)

    start_date = _parse_date(query.get("start", [default_start.isoformat()])[0], default_start)
    end_date = _parse_date(query.get("end", [default_end.isoformat()])[0], default_end)

    # Compute reload button state
    # Use the module-level helper (patchable in tests)
    try:
        metrics_reload_wait = get_seconds_until_next_metrics_reload()
    except Exception:
        metrics_reload_wait = 0
    reload_disabled = "disabled" if metrics_reload_wait > 0 else ""
    reload_text = f"Manual Load Data ({metrics_reload_wait}s)" if metrics_reload_wait > 0 else "Manual Load Data"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Door Metrics</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <style>
    body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
    h1, h2 {{ color: #4ec9b0; }}
    a {{ color: #9cdcfe; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .status {{ padding: 8px; margin-bottom: 16px; border-radius: 4px; }}
    .status.loading {{ background: #2d2d30; color: #4ec9b0; }}
    .status.cached {{ background: #2d4a2d; color: #6cc96c; }}
    .status.error {{ background: #4a2d2d; color: #c96c6c; }}
    .toolbar {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(420px, 1fr)); gap: 16px; }}
    .card {{ background: #252526; border: 1px solid #555; border-radius: 8px; padding: 12px; }}
    /* Ensure canvases have a fixed height so Chart.js responsive resizing doesn't expand vertically */
    .card {{ min-height: 260px; }}
    .card canvas {{ display: block; width: 100%; height: 260px !important; }}
    .controls {{ margin-top: 8px; display: flex; gap: 8px; flex-wrap: wrap; }}
    button {{ background:#4ec9b0; color:#1e1e1e; padding:6px 10px; border:none; border-radius:4px; cursor:pointer; }}
    button:disabled {{ opacity:0.5; cursor:not-allowed; }}
    select, input {{ background:#1e1e1e; color:#d4d4d4; border:1px solid #555; padding:6px; border-radius:4px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 11px; }}
    th, td {{ border: 1px solid #555; padding: 4px; text-align: left; }}
    th {{ background: #2d2d30; color: #4ec9b0; }}
  </style>
</head>
<body>
  <h1>Door Metrics</h1>
  <p><a href="/admin">← Admin</a> | <a href="/docs">API Docs</a></p>

  <div id="status" class="status loading">Initializing...</div>

  <div class="toolbar">
    <label>Start: <input type="date" id="startDate" value="{start_date.isoformat()}"></label>
    <label>End: <input type="date" id="endDate" value="{end_date.isoformat()}"></label>
    <button id="btnLoad">Load/Refresh</button>
    <button id="btnClearCache">Clear Cache</button>
    <button id="btnExportCSV">Export CSV</button>
    <label><input type="checkbox" id="chkIncludeNoBadge"> Include No Badge</label>
    <span id="excludedCount" style="margin-left:8px;color:#c9c9c9;">0 events without badge</span>
    <button id="btnReload" {reload_disabled}>{reload_text}</button>
  </div>

  <div class="grid" id="chartsGrid"></div>

  <div class="card">
    <h2>Event Timeline (Latest 100)</h2>
    <table id="timelineTable">
      <thead><tr><th>Time</th><th>Event</th><th>Badge</th><th>Status</th></tr></thead>
      <tbody id="timelineBody"></tbody>
    </table>
  </div>

  <script>
// IndexedDB setup
const DB_NAME = 'DoorMetrics';
const DB_VERSION = 1;
const STORE_NAME = 'events';

let db = null;
let charts = {{}};
let latestEvents = []; // most recently loaded events for re-rendering on filter changes

function updateExcludedCount(events) {{
  const el = document.getElementById('excludedCount');
  if (!el) return;
  if (!events || !events.length) {{
    el.textContent = '0 events without badge';
    el.style.display = 'none';
    return;
  }}
  const cnt = events.filter(e => !e.badge_id).length;
  el.textContent = `${{cnt}} event${{cnt === 1 ? '' : 's'}} without badge`;
  el.style.display = cnt ? 'inline' : 'none';
}}

// Open IndexedDB
async function openDB() {{
  return new Promise((resolve, reject) => {{
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
    request.onupgradeneeded = (e) => {{
      const db = e.target.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {{
        const store = db.createObjectStore(STORE_NAME, {{ keyPath: 'cacheKey' }});
        store.createIndex('timestamp', 'timestamp');
      }}
    }};
  }});
}}

// Clear auth-dependent cache (called on logout or error 401)
async function clearCache() {{
  const tx = db.transaction([STORE_NAME], 'readwrite');
  await tx.objectStore(STORE_NAME).clear();
  updateStatus('Cache cleared', 'cached');
}}

// Get cached data
async function getCached(start, end) {{
  const key = `${{start}}_${{end}}`;
  const tx = db.transaction([STORE_NAME], 'readonly');
  const cached = await tx.objectStore(STORE_NAME).get(key);
  return cached ? cached.events : null;
}}

// Save to cache
async function saveCache(start, end, events) {{
  const key = `${{start}}_${{end}}`;
  const tx = db.transaction([STORE_NAME], 'readwrite');
  await tx.objectStore(STORE_NAME).put({{
    cacheKey: key,
    start,
    end,
    events,
    timestamp: Date.now()
  }});
}}

// Fetch from API (with pagination handling)
async function fetchMetrics(start, end) {{
  let allEvents = [];
  let page = 1;
  let totalPages = 1;

  while (page <= totalPages) {{
    const url = `/api/metrics?start=${{start}}&end=${{end}}&page=${{page}}&page_size=5000`;
    const res = await fetch(url, {{ credentials: 'same-origin' }});

    if (res.status === 401) {{
      await clearCache();
      throw new Error('Not authenticated. Please log in.');
    }}

    if (!res.ok) {{
      const err = await res.json();
      throw new Error(err.error || 'API error');
    }}

    const data = await res.json();
    allEvents = allEvents.concat(data.events);
    totalPages = data.total_pages;
    page++;
  }}

  return allEvents;
}}

// Load metrics (cache-first)
async function loadMetrics() {{
  const start = document.getElementById('startDate').value;
  const end = document.getElementById('endDate').value;

  if (!start || !end) {{
    updateStatus('Please select start and end dates', 'error');
    return;
  }}

  updateStatus('Loading...', 'loading');

  try {{
    // Try cache first
    let events = await getCached(start, end);

    if (events) {{
      updateStatus(`Loaded ${{events.length}} events from cache`, 'cached');
    }} else {{
      // Fetch from API
      events = await fetchMetrics(start, end);
      await saveCache(start, end, events);
      updateStatus(`Loaded ${{events.length}} events from server`, 'loading');
    }}

    latestEvents = events;
    updateExcludedCount(events);
    renderDashboard(events);

  }} catch (err) {{
    updateStatus(`Error: ${{err.message}}`, 'error');
    console.error(err);
  }}
}}

// Update status message
function updateStatus(msg, type) {{
  const el = document.getElementById('status');
  el.textContent = msg;
  el.className = `status ${{type}}`;
}}

// Render all charts and timeline
function renderDashboard(events) {{
  renderBadgeScansPerHour(events);
  renderTopBadgeUsers(events);
  renderDoorCyclesPerDay(events);
  renderDeniedScans(events);
  renderTimeline(events);
}}

// Badge scans per hour
function renderBadgeScansPerHour(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const data = new Array(24).fill(0);
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if (et === 'scan' || et === 'badge scan' || et.includes('scan')) {{
      const badge = e.badge_id || '';
      if (!badge && !includeNoBadge) return; // skip events without badge_id unless included
      const hour = new Date(e.ts).getHours();
      data[hour]++;
    }}
  }});

  const labels = Array.from({{length: 24}}, (_, i) => i.toString().padStart(2, '0'));
  createChart('badge-scans', 'Badge Scans Per Hour', 'bar', labels, data);
}}

// Top badge users
function renderTopBadgeUsers(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if ((et === 'scan' || et.includes('scan') || et === 'badge scan') && e.status?.toLowerCase() === 'granted') {{
      const badge = e.badge_id || '';
      if (!badge && !includeNoBadge) return;
      const label = badge || '(no badge)';
      counts[label] = (counts[label] || 0) + 1;
    }}
  }});

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const labels = sorted.map(x => x[0]);
  const data = sorted.map(x => x[1]);

  createChart('top-users', 'Top 10 Badge Users', 'bar', labels, data);
}}

// Door cycles per day
function renderDoorCyclesPerDay(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if (et === 'open' || et.includes('open') || et.includes('unlocked')) {{
      const badge = e.badge_id || '';
      if (!badge && !includeNoBadge) return;
      const day = e.ts.split(' ')[0];
      counts[day] = (counts[day] || 0) + 1;
    }}
  }});

  const labels = Object.keys(counts).sort();
  const data = labels.map(d => counts[d]);

  createChart('door-cycles', 'Door Cycles Per Day', 'line', labels, data);
}}

// Denied scans
function renderDeniedScans(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if ((et === 'scan' || et.includes('scan') || et === 'badge scan') && e.status?.toLowerCase() === 'denied') {{
      const badge = e.badge_id || '';
      if (!badge && !includeNoBadge) return;
      const day = e.ts.split(' ')[0];
      counts[day] = (counts[day] || 0) + 1;
    }}
  }});

  const labels = Object.keys(counts).sort();
  const data = labels.map(d => counts[d]);

  createChart('denied-scans', 'Denied Badge Scans Per Day', 'line', labels, data);
}}

// Generic chart creator
function createChart(id, title, type, labels, data) {{
  const cardId = `card-${{id}}`;
  const canvasId = `chart-${{id}}`;

  let card = document.getElementById(cardId);
  if (!card) {{
    card = document.createElement('div');
    card.className = 'card';
    card.id = cardId;
    card.innerHTML = `<h2>${{title}}</h2><canvas id="${{canvasId}}"></canvas>`;
    document.getElementById('chartsGrid').appendChild(card);
  }} else {{
    // Update title
    const h2 = card.querySelector('h2');
    if (h2) h2.textContent = title;
  }}

  // Replace existing canvas to clear inline size attributes and avoid cumulative scaling
  const oldCanvas = document.getElementById(canvasId);
  if (oldCanvas) {{
    try {{ if (charts[id]) {{ charts[id].destroy(); }} }} catch (e) {{ /* ignore */ }}
    const newCanvas = document.createElement('canvas');
    newCanvas.id = canvasId;
    newCanvas.style.width = '100%';
    newCanvas.style.height = '260px';
    oldCanvas.parentNode.replaceChild(newCanvas, oldCanvas);
  }} else {{
    const c = document.getElementById(canvasId);
    if (c) {{ c.style.width = '100%'; c.style.height = '260px'; }}
  }}

  const canvas = document.getElementById(canvasId);
  try {{ if (charts[id]) {{ charts[id].destroy(); delete charts[id]; }} }} catch (e) {{ /* ignore */ }}

  charts[id] = new Chart(canvas, {{
    type,
    data: {{ labels, datasets: [{{ label: title, data, borderColor: '#4ec9b0', backgroundColor: 'rgba(78,201,176,0.3)' }}] }},
    options: {{ responsive: true, maintainAspectRatio: false }}
  }});

  // Enforce CSS height after Chart.js applies inline styles
  try {{ canvas.style.height = '260px'; }} catch (e) {{ /* ignore */ }}
}}

// Timeline table
function renderTimeline(events) {{
  const tbody = document.getElementById('timelineBody');
  tbody.innerHTML = '';

  const latest = events.slice(-100).reverse();
  latest.forEach(e => {{
    const tr = tbody.insertRow();
    tr.insertCell().textContent = e.ts;
    tr.insertCell().textContent = e.event_type;
    tr.insertCell().textContent = e.badge_id || '';
    tr.insertCell().textContent = e.status;
  }});
}}

// Export CSV
function exportCSV() {{
  const start = document.getElementById('startDate').value;
  const end = document.getElementById('endDate').value;
  window.location.href = `/api/metrics?start=${{start}}&end=${{end}}&format=csv`;
}}

// Init
(async () => {{
  db = await openDB();
  document.getElementById('btnLoad').addEventListener('click', loadMetrics);
  document.getElementById('btnClearCache').addEventListener('click', clearCache);
  document.getElementById('btnExportCSV').addEventListener('click', exportCSV);

  const chkInclude = document.getElementById('chkIncludeNoBadge');
  if (chkInclude) {{
    // default: unchecked
    chkInclude.checked = false;
    chkInclude.addEventListener('change', () => {{ renderDashboard(latestEvents); updateExcludedCount(latestEvents); }});
  }}

  const btnReload = document.getElementById('btnReload');
  if (btnReload) {{
    btnReload.addEventListener('click', async function() {{
      const btn = this;
      if (btn.disabled) return;
      if (!confirm('Load metrics from action logs now? This will ingest any _action log entries and may change metrics DBs.')) return;
      btn.disabled = true;
      const prevText = btn.textContent;
      btn.textContent = 'Reloading...';
      try {{
        const res = await fetch('/api/metrics/reload', {{ method: 'POST', credentials: 'same-origin' }});
        const result = await res.json();
        if (!res.ok) {{
          alert(result.error || 'Reload failed');
          // If rate limited, try to extract seconds
          const m = (result.error || '').match(/(\d+) seconds?/);
          if (m) {{
            let wait = parseInt(m[1], 10);
            btn.textContent = `Manual Load Data (${{wait}}s)`;
            const iv = setInterval(() => {{
              wait -= 1;
              if (wait <= 0) {{ clearInterval(iv); btn.textContent = prevText; btn.disabled = false; }}
              else {{ btn.textContent = `Manual Load Data (${{wait}}s)`; }}
            }}, 1000);
          }} else {{
            btn.textContent = prevText;
            btn.disabled = false;
          }}
          return;
        }}
        alert(result.message || 'Reload completed');
        // Refresh metrics from server
        await loadMetrics();
        // Disable for default rate limit period (approximate)
        const RATE_MS = 1000 * 300; // 5 minutes
        btn.textContent = prevText;
        btn.disabled = true;
        setTimeout(() => {{ btn.disabled = false; btn.textContent = prevText; }}, RATE_MS);
      }} catch (e) {{
        alert('Error reloading metrics: ' + e.message);
        btn.textContent = prevText;
        btn.disabled = false;
      }}
    }});
  }}

  await loadMetrics();
}})();
  </script>
</body>
</html>"""

    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(html.encode("utf-8"))


def handle_metrics_reload_post(handler) -> bool:
    """POST /api/metrics/reload - reload metrics by consuming all action logs (rate limited)."""
    allowed, error_msg = check_rate_limit_metrics_reload()
    if not allowed:
        _write_json(handler, {"error": error_msg}, status_code=429)
        return True

    try:
        from ..metrics_storage import reload_action_logs

        res = reload_action_logs()
        get_logger().info(f"Metrics reload completed: {res}")
        _write_json(handler, {"success": True, "message": f"Reloaded {res.get('inserted',0)} events from {res.get('files_processed',0)} files."})
        return True
    except Exception as e:
        get_logger().error(f"Failed to reload metrics: {e}")
        _write_json(handler, {"error": f"Failed to reload metrics: {str(e)}"}, status_code=500)
        return True
