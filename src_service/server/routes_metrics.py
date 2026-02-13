"""Metrics routes - unified API with IndexedDB caching frontend."""
import json
import math
from datetime import date, datetime
from urllib.parse import parse_qs

from ..metrics_storage import query_events_range, month_events_to_csv
from .state import APPLICATION_JSON, check_rate_limit_metrics_reload, get_seconds_until_next_metrics_reload
from ..logging_utils import get_logger
from .auth import login_required, get_current_user


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


@login_required
def send_metrics_page(handler, raw_query: str):
    """Metrics dashboard with IndexedDB caching and client-side graphing."""

    # Get current user for display
    user_info = get_current_user(handler)
    user_display = ""
    if user_info and user_info.get("email"):
        auth_method = user_info.get("auth_method", "")
        if auth_method == "google_oauth":
            user_display = f" ({user_info['email']})"

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
  <link rel="icon" href="https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w">
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
    /* Timeline inner scroll */
    .timeline-scroll {{ max-height: 360px; overflow: auto; }}
    /* Hourly heatmap should span full width and allow inner scroll/pagination */
    .card.full-row {{ grid-column: 1 / -1; }}
    .hourly-heatmap-scroll {{ max-height: 520px; overflow: auto; }}
    .heatmap-controls {{ margin-bottom: 6px; display:flex; gap:8px; align-items:center; }}

    /* Modal for heatmap cell details */
    .modal-overlay {{ position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: none; align-items: center; justify-content: center; z-index: 9999; }}
    .modal-overlay.show {{ display: flex; }}
    .modal-content {{ background: #252526; color: #d4d4d4; padding: 16px; border-radius: 8px; max-width: 900px; width: 95%; max-height: 80vh; overflow: auto; border:1px solid #555; position: relative; }}
    .modal-close {{ position: absolute; right: 12px; top: 12px; background: #4ec9b0; border: none; padding:4px 8px; cursor:pointer; border-radius:4px; color:#1e1e1e; }}
    .heatmap-cell {{ cursor: pointer; }}
    .heatmap-cell:hover {{ outline: 2px solid rgba(78,201,176,0.25); }}
  </style>
</head>
<body>
  <h1>Door Metrics</h1>
  <p><a href="/admin">← Admin</a> | <a href="/docs">API Docs</a> | <a href="/logout">Logout</a>{user_display}</p>

  <div id="status" class="status loading">Initializing...</div>

  <div class="toolbar">
    <label>Start: <input type="date" id="startDate" value="{start_date.isoformat()}"></label>
    <label>End: <input type="date" id="endDate" value="{end_date.isoformat()}"></label>
    <button id="btnLoad">Load/Refresh</button>
    <button id="btnClearCache">Clear Cache</button>
    <button id="btnExportCSV">Export CSV</button>
    <button id="btnExportAlerts">Export Alerts CSV</button>
    <label><input type="checkbox" id="chkIncludeNoBadge"> Include No Badge</label>
    <span id="unitTestFilterWrapper" style="display:none; margin-left:8px;"><label><input type="checkbox" id="chkExcludeUnitTest"> Exclude 'unit_test' badges</label></span>
    <label>Open threshold (s): <input type="number" id="openThreshold" value="300" min="10" style="width:80px;"></label>
    <span id="excludedCount" style="margin-left:8px;color:#c9c9c9;">0 events without badge</span>
    <button id="btnReload" {reload_disabled}>{reload_text}</button>
  </div>

  <div class="grid" id="chartsGrid"></div>

  <div class="card">
    <h2>Event Timeline (Latest 100)</h2>
    <div class="timeline-scroll">
      <table id="timelineTable">
        <thead><tr><th>Time</th><th>Event</th><th>Badge</th><th>Status</th></tr></thead>
        <tbody id="timelineBody"></tbody>
      </table>
    </div>
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

// Show/hide the unit_test filter checkbox based on presence of 'unit_test' badge events
function updateUnitTestFilterVisibility(events) {{
  const wrapper = document.getElementById('unitTestFilterWrapper');
  const chk = document.getElementById('chkExcludeUnitTest');
  if (!wrapper || !chk) return;
  const hasUnitTest = events && events.some(e => ((e.badge_id || '') === 'unit_test'));
  if (hasUnitTest) {{
    wrapper.style.display = '';
    chk.checked = true; // default: exclude unit_test
  }} else {{
    wrapper.style.display = 'none';
    chk.checked = false;
  }}
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

// Helper: turn IDBRequest into a Promise that resolves with request.result
function idbRequestToPromise(req) {{
  return new Promise((resolve, reject) => {{
    if (req && typeof req.then === 'function') {{
      // Already a promise (some browsers/polyfills)
      req.then(resolve).catch(reject);
      return;
    }}
    try {{
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    }} catch (e) {{
      // Not an IDBRequest; resolve with value directly
      resolve(req);
    }}
  }});
}}

// Get cached data (exact key)
async function getCached(start, end) {{
  const key = `${{start}}_${{end}}`;
  const tx = db.transaction([STORE_NAME], 'readonly');
  const req = tx.objectStore(STORE_NAME).get(key);
  const cached = await idbRequestToPromise(req);
  return cached ? cached.events : null;
}}

// Get all cached segments overlapping [start, end]
async function getCachedSegments(start, end) {{
  const tx = db.transaction([STORE_NAME], 'readonly');
  const req = tx.objectStore(STORE_NAME).getAll();
  let all = await idbRequestToPromise(req);
  if (!Array.isArray(all)) all = [];
  // Filter entries that overlap the requested range (inclusive)
  return all.filter(e => !(e.end < start || e.start > end));
}}

// Normalize a stored 'events' value into an array
function normalizeEventsValue(v) {{
  if (!v) return [];
  if (Array.isArray(v)) return v;
  if (typeof v === 'string') {{
    try {{
      const parsed = JSON.parse(v);
      if (Array.isArray(parsed)) return parsed;
    }} catch (e) {{ /* ignore parsing errors */ }}
    return [];
  }}
  if (typeof v === 'object' && Array.isArray(v.events)) return v.events;
  // Fallback: wrap single object into array
  return [v];
}}

// Merge multiple event arrays, sort by ts and remove duplicate events (by ts+event_type+badge_id+status)
function mergeAndDedupEventLists(lists) {{
  const normalized = lists.map(normalizeEventsValue);
  const all = [].concat(...normalized);
  all.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  const seen = new Set();
  const out = [];
  all.forEach(e => {{
    const key = `${{e.ts}}|${{e.event_type}}|${{(e.badge_id || '')}}|${{e.status}}`;
    if (!seen.has(key)) {{
      seen.add(key);
      out.push(e);
    }}
  }});
  return out;
}}

// Compute gaps within [start,end] not covered by provided segments
function computeMissingRanges(start, end, segments) {{
  // segments: array of {{start, end}}
  function toDate(s) {{ return new Date(s + 'T00:00:00'); }}
  function toISO(d) {{ return d.toISOString().slice(0,10); }}

  const s = toDate(start);
  const e = toDate(end);
  if (s > e) return [];

  const ints = segments.map(x => ({{ s: toDate(x.start), e: toDate(x.end) }}))
    .sort((a,b) => a.s - b.s);

  const gaps = [];
  let cur = new Date(s);

  for (const it of ints) {{
    if (it.e < s || it.s > e) continue;
    const segStart = new Date(Math.max(it.s, s));
    const segEnd = new Date(Math.min(it.e, e));
    if (segStart > cur) {{
      // gap from cur to segStart - 1 day
      const gapEnd = new Date(segStart);
      gapEnd.setDate(gapEnd.getDate() - 1);
      gaps.push({{ start: toISO(cur), end: toISO(gapEnd) }});
    }}
    if (segEnd > cur) {{
      cur = new Date(segEnd);
      cur.setDate(cur.getDate() + 1);
    }}
    if (cur > e) break;
  }}

  if (cur <= e) gaps.push({{ start: toISO(cur), end: toISO(e) }});
  return gaps;
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

// Fetch for a potentially large date range by splitting into <=365-day chunks
async function fetchMetricsRange(start, end) {{
  const maxDays = 365;
  const s = new Date(start + 'T00:00:00');
  const e = new Date(end + 'T00:00:00');
  const msPerDay = 24 * 60 * 60 * 1000;
  const diffDays = Math.ceil((e - s) / msPerDay) + 1; // inclusive

  if (diffDays <= maxDays) {{
    return await fetchMetrics(start, end);
  }}

  const parts = [];
  let curStart = new Date(s);
  while (curStart <= e) {{
    const curEnd = new Date(Math.min(e.getTime(), curStart.getTime() + (maxDays - 1) * msPerDay));
    const partStart = curStart.toISOString().slice(0, 10);
    const partEnd = curEnd.toISOString().slice(0, 10);
    parts.push({{ start: partStart, end: partEnd }});
    curStart = new Date(curEnd.getTime() + msPerDay);
  }}

  // Make requests sequentially and concatenate results
  let combined = [];
  for (const p of parts) {{
    const chunk = await fetchMetrics(p.start, p.end);
    combined = combined.concat(chunk);
  }}

  // Ensure globally sorted by ts
  combined.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : 0));
  return combined;
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
    debugger
    // Try cache first
    let events = await getCached(start, end);
    debugger;
    // Try to use cached segments covering requested range
    const cachedSegments = await getCachedSegments(start, end);
    if (cachedSegments && cachedSegments.length) {{
      // Compute missing ranges
      const gaps = computeMissingRanges(start, end, cachedSegments);
      if (!gaps.length) {{
        // Full coverage — merge cached entries
        const lists = cachedSegments.map(s => s.events);
        events = mergeAndDedupEventLists(lists);
        updateStatus(`Loaded ${{events.length}} events from cache`, 'cached');
      }} else {{
        // Persist selected date range in URL so refresh keeps it
        try {{
          const params = new URLSearchParams(window.location.search);
          params.set('start', start);
          params.set('end', end);
          const newUrl = window.location.pathname + '?' + params.toString();
          window.history.replaceState(null, '', newUrl);
        }} catch (e) {{ /* ignore */ }}

        // Fetch only missing gaps and save each to cache
        let fetchedLists = [];
        for (const g of gaps) {{
          const chunk = await fetchMetricsRange(g.start, g.end);
          fetchedLists.push(chunk);
          try {{ await saveCache(g.start, g.end, chunk); }} catch (e) {{ /* ignore */ }}
        }}
        // Combine cached + fetched
        const lists = cachedSegments.map(s => s.events).concat(fetchedLists);
        events = mergeAndDedupEventLists(lists);
        updateStatus(`Loaded ${{events.length}} events (cache+server)`, 'loading');
      }}
    }} else {{
      // No cached segments at all — persist URL and fetch full range
      try {{
        const params = new URLSearchParams(window.location.search);
        params.set('start', start);
        params.set('end', end);
        const newUrl = window.location.pathname + '?' + params.toString();
        window.history.replaceState(null, '', newUrl);
      }} catch (e) {{ /* ignore */ }}

      events = await fetchMetricsRange(start, end);
      await saveCache(start, end, events);
      updateStatus(`Loaded ${{events.length}} events from server`, 'loading');
    }}

    latestEvents = events;
    updateExcludedCount(events);
    updateUnitTestFilterVisibility(events);
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
  renderDoorOpenDurationsOverTime(events);
  renderDurationHistogram(events);
  renderScanToOpenLatency(events);
  renderLatencyHistogram(events);
  renderDoorLeftOpenTooLong(events);
  renderHourlyHeatmap(events);
  renderTimeline(events);
}}

// Badge scans per hour
function renderBadgeScansPerHour(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const data = new Array(24).fill(0);
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if (et === 'scan' || et === 'badge scan' || et.includes('scan')) {{
      const badge = e.badge_id || '';
      if (excludeUnitTest && badge === 'unit_test') return;
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
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if ((et === 'scan' || et.includes('scan') || et === 'badge scan') && e.status?.toLowerCase() === 'granted') {{
      const badge = e.badge_id || '';
      if (excludeUnitTest && badge === 'unit_test') return;
      if (!badge && !includeNoBadge) return;
      const label = badge || '(no badge)';
      counts[label] = (counts[label] || 0) + 1;
    }}
  }});

  const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const labels = sorted.map(x => x[0]);
  const data = sorted.map(x => x[1]);

  // Create chart as before
  createChart('top-users', 'Top 10 Badge Users', 'bar', labels, data);

  // Make bars/labels clickable so user can copy badge id to clipboard
  try {{
    const canvas = document.getElementById('chart-top-users');
    const chartObj = charts['top-users'];
    if (canvas && chartObj) {{
      canvas.style.cursor = 'pointer';
      canvas.onclick = async (evt) => {{
        try {{
          // Use Chart.js helper to find the nearest item under the click
          const items = chartObj.getElementsAtEventForMode(evt, 'nearest', {{ intersect: true }}, true);
          if (!items || !items.length) return;
          const idx = items[0].index;
          const label = chartObj.data.labels[idx];
          if (!label) return;
          // Try clipboard API, fall back to prompt for older browsers
          try {{
            await navigator.clipboard.writeText(label);
            updateStatus(`Copied "${{label}}" to clipboard`, 'cached');
          }} catch (e) {{
            // Fallback: show the value in a prompt so user can copy manually
            prompt('Badge ID (copy from here):', label);
          }}
        }} catch (e) {{ console.error('copy-on-click failed', e); }}
      }};
    }}
  }} catch (e) {{ /* ignore errors */ }}
}}

// Door cycles per day
function renderDoorCyclesPerDay(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if (et === 'open' || et.includes('open') || et.includes('unlocked')) {{
      const badge = e.badge_id || '';
      if (excludeUnitTest && badge === 'unit_test') return;
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
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const counts = {{}};
  events.forEach(e => {{
    const et = (e.event_type || '').toString().toLowerCase();
    if ((et === 'scan' || et.includes('scan') || et === 'badge scan') && e.status?.toLowerCase() === 'denied') {{
      const badge = e.badge_id || '';
      if (excludeUnitTest && badge === 'unit_test') return;
      if (!badge && !includeNoBadge) return;
      const day = e.ts.split(' ')[0];
      counts[day] = (counts[day] || 0) + 1;
    }}
  }});

  const labels = Object.keys(counts).sort();
  const data = labels.map(d => counts[d]);

  createChart('denied-scans', 'Denied Badge Scans Per Day', 'line', labels, data);
}}

// Compute open durations by pairing open->close chronologically
function computeOpenDurations(events) {{
  const opens = events.filter(e => {{ const et = (e.event_type||'').toString().toLowerCase(); return et === 'open' || et.includes('open') || et.includes('unlocked'); }}).sort((a,b)=> new Date(a.ts)-new Date(b.ts));
  const closes = events.filter(e => {{ const et = (e.event_type||'').toString().toLowerCase(); return et === 'close' || et.includes('close') || et.includes('locked') || et.includes('closed'); }}).sort((a,b)=> new Date(a.ts)-new Date(b.ts));
  const results = [];
  let cidx = 0;
  for (const o of opens) {{
    while (cidx < closes.length && new Date(closes[cidx].ts) <= new Date(o.ts)) cidx++;
    if (cidx < closes.length) {{
      const cl = closes[cidx++];
      const duration = (new Date(cl.ts) - new Date(o.ts)) / 1000; // seconds
      results.push({{open_ts: o.ts, close_ts: cl.ts, duration, badge_id: o.badge_id || null}});
    }}
  }}
  return results;
}}

// Render average door open duration per day
function renderDoorOpenDurationsOverTime(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const durations = computeOpenDurations(events).filter(d => (includeNoBadge || d.badge_id) && !(excludeUnitTest && d.badge_id === 'unit_test'));
  const byDay = {{}};
  durations.forEach(d => {{
    const day = d.open_ts.split(' ')[0];
    byDay[day] = byDay[day] || {{total:0, count:0}};
    byDay[day].total += d.duration;
    byDay[day].count += 1;
  }});
  const labels = Object.keys(byDay).sort();
  const data = labels.map(l => byDay[l].count ? Math.round((byDay[l].total/byDay[l].count)/60) : 0); // minutes
  createChart('open-durations', 'Avg Door Open Duration (min)', 'line', labels, data);
}}

// Compute scan -> next open latency (seconds)
function computeScanToOpenLatencies(events, maxWindow=60) {{
  const scans = events.filter(e => (e.event_type||'').toString().toLowerCase().includes('scan')).sort((a,b)=> new Date(a.ts)-new Date(b.ts));
  const opens = events.filter(e => (e.event_type||'').toString().toLowerCase().includes('open')).sort((a,b)=> new Date(a.ts)-new Date(b.ts));
  const res = [];
  let oidx = 0;
  for (const s of scans) {{
    while (oidx < opens.length && new Date(opens[oidx].ts) < new Date(s.ts)) oidx++;
    if (oidx < opens.length) {{
      const o = opens[oidx];
      const delta = (new Date(o.ts) - new Date(s.ts)) / 1000;
      if (delta >= 0 && delta <= maxWindow) res.push({{scan_ts: s.ts, open_ts: o.ts, delta, badge_id: s.badge_id || null}});
    }}
  }}
  return res;
}}

// Render average scan->open latency per day
function renderScanToOpenLatency(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const latencies = computeScanToOpenLatencies(events).filter(l => (includeNoBadge || l.badge_id) && !(excludeUnitTest && l.badge_id === 'unit_test'));
  const byDay = {{}};
  latencies.forEach(l => {{
    const day = l.scan_ts.split(' ')[0];
    byDay[day] = byDay[day] || {{total:0, count:0}};
    byDay[day].total += l.delta;
    byDay[day].count += 1;
  }});
  const labels = Object.keys(byDay).sort();
  const data = labels.map(l => byDay[l].count ? Math.round(byDay[l].total/byDay[l].count) : 0); // seconds
  createChart('scan-latency', 'Avg Scan→Open Latency (s)', 'line', labels, data);
}}

// Find door left open too long and render a small table
function renderDoorLeftOpenTooLong(events) {{
  const threshold = parseInt(document.getElementById('openThreshold')?.value || '300', 10);
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const durations = computeOpenDurations(events).filter(d => (includeNoBadge || d.badge_id) && !(excludeUnitTest && d.badge_id === 'unit_test'));
  const tooLong = durations.filter(d => d.duration > threshold);
  // Create/Update card
  const id = 'door-left-open';
  let card = document.getElementById('card-'+id);
  if (!card) {{
    card = document.createElement('div'); card.className = 'card'; card.id = 'card-'+id; document.getElementById('chartsGrid').appendChild(card);
  }}
  let html = `<h2>Door Left Open Too Long (&gt; ${{threshold}}s)</h2>`;
  html += `<p>${{tooLong.length}} instances</p>`;
  if (tooLong.length) {{
    html += `<table><thead><tr><th>Open Time</th><th>Duration (s)</th><th>Badge</th></tr></thead><tbody>`;
    tooLong.slice(0,10).forEach(t => {{ html += `<tr><td>${{t.open_ts}}</td><td>${{Math.round(t.duration)}}</td><td>${{t.badge_id || ''}}</td></tr>`; }});
    html += `</tbody></table>`;
  }}
  card.innerHTML = html;
}}

// Hourly activity heatmap (days x 24 hours) — full-width card, single continuous scroll (no pagination)
function renderHourlyHeatmap(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const byDayHour = {{}}; // day->{{hour:count}}
  events.forEach(e => {{
    const day = e.ts.split(' ')[0];
    const hour = new Date(e.ts).getHours();
    if (excludeUnitTest && (e.badge_id || '') === 'unit_test') return;
    if (!includeNoBadge && !e.badge_id && (e.event_type||'').toLowerCase().includes('scan')) return;
    byDayHour[day] = byDayHour[day] || {{}};
    byDayHour[day][hour] = (byDayHour[day][hour] || 0) + 1;
  }});
  const days = Object.keys(byDayHour).sort();
  const id = 'hourly-heatmap';
  let card = document.getElementById('card-'+id);
  if (!card) {{
    card = document.createElement('div'); card.className = 'card full-row'; card.id = 'card-'+id; document.getElementById('chartsGrid').appendChild(card);
  }}

  // Build scroll container with full table (no pagination)
  let html = `<h2>Hourly Activity Heatmap</h2>`;
  html += `<div class="hourly-heatmap-scroll" id="heat-scroll-${{id}}"><table><thead><tr><th>Day</th>`;
  for (let h=0; h<24; h++) html += `<th>${{h}}</th>`;
  html += `</tr></thead><tbody id="heat-body-${{id}}"></tbody></table></div>`;

  card.innerHTML = html;

  const maxCount = days.reduce((m, d) => Math.max(m, ...(Object.values(byDayHour[d] || {{}}))), 0);
  const tbody = document.getElementById(`heat-body-${{id}}`);
  tbody.innerHTML = '';
  days.forEach(d => {{
    let row = `<tr><td>${{d}}</td>`;
    for (let h=0; h<24; h++) {{
      const v = byDayHour[d][h] || 0;
      const intensity = maxCount ? Math.round((v/maxCount)*200) : 0;
      const color = `rgba(78,201,176,${{0.05 + (intensity/255)}})`;
      const cls = v ? 'heatmap-cell' : '';
      row += `<td class="${{cls}}" data-day="${{d}}" data-hour="${{h}}" title="${{v}} event${{v === 1 ? '' : 's'}}" style="background:${{color}}; text-align:center; cursor:${{v ? 'pointer' : 'default'}};">${{v || ''}}</td>`;
    }}
    row += `</tr>`;
    tbody.innerHTML += row;
  }});

  // Attach click handlers for cells (delegation could be used but table is rebuilt each render)
  tbody.querySelectorAll('td.heatmap-cell').forEach(td => {{
    td.addEventListener('click', (ev) => {{
      const day = td.getAttribute('data-day');
      const hour = parseInt(td.getAttribute('data-hour'), 10);
      openHeatmapModal(day, hour);
    }});
  }});

  // Ensure scroll container scrolls to top
  const scroller = document.getElementById(`heat-scroll-${{id}}`);
  if (scroller) scroller.scrollTop = 0;
}}

// Create modal overlay (lazy)
function createHeatmapModal() {{
  if (document.getElementById('heatmapModal')) return;
  const overlay = document.createElement('div');
  overlay.id = 'heatmapModal';
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `<div class="modal-content"><button class="modal-close" id="heatmapModalClose">Close</button><div id="heatmapModalBody"></div></div>`;
  overlay.addEventListener('click', (e) => {{ if (e.target === overlay) closeHeatmapModal(); }});
  document.body.appendChild(overlay);
  document.getElementById('heatmapModalClose').addEventListener('click', closeHeatmapModal);
}}

// Open modal and populate with events for the selected day/hour
function openHeatmapModal(day, hour) {{
  createHeatmapModal();
  const overlay = document.getElementById('heatmapModal');
  const body = document.getElementById('heatmapModalBody');
  const evs = (latestEvents || []).filter(e => e.ts.startsWith(day) && new Date(e.ts).getHours() === hour);
  let html = `<h3>Events for ${{day}} @ ${{hour}}:00 (${{evs.length}})</h3>`;
  if (!evs.length) {{ html += `<p>No events</p>`; }} else {{
    html += `<table><thead><tr><th>Time</th><th>Event</th><th>Badge</th><th>Status</th></tr></thead><tbody>`;
    evs.forEach(e => {{
      const badge = e.badge_id || '';
      const badgeDisplay = badge ? `<span class="badge-copy" data-badge="${{badge}}" style="color:#9cdcfe;cursor:pointer;">${{badge}}</span>` : '';
      html += `<tr><td>${{e.ts.split(' ')[1]}}</td><td>${{e.event_type}}</td><td>${{badgeDisplay}}</td><td>${{e.status || ''}}</td></tr>`;
    }});
    html += `</tbody></table>`;
    html += `<p style="margin-top:8px;"><small>Click a badge to copy its id</small></p>`;
  }}
  body.innerHTML = html;

  // attach copy handlers
  const clips = body.querySelectorAll('.badge-copy');
  clips.forEach(el => {{
    el.addEventListener('click', async (ev) => {{
      const b = el.getAttribute('data-badge');
      try {{ await navigator.clipboard.writeText(b); updateStatus(`Copied "${{b}}" to clipboard`, 'cached'); }} catch (err) {{ prompt('Badge ID (copy):', b); }}
    }});
  }});

  overlay.classList.add('show');
}}

function closeHeatmapModal() {{
  const overlay = document.getElementById('heatmapModal');
  if (overlay) overlay.classList.remove('show');
}}

// Histogram helper (bins numeric array into N bins)
function histogramBins(values, bins=10) {{
  if (!values || !values.length) return {{labels: [], data: []}};
  const min = Math.min(...values);
  const max = Math.max(...values);
  const width = (max - min) / bins || 1;
  const bcounts = new Array(bins).fill(0);
  const blabels = new Array(bins).fill(0).map((_,i) => `${{Math.round(min + i*width)}}-${{Math.round(min + (i+1)*width)}}`);
  values.forEach(v => {{
    const idx = Math.min(bins-1, Math.floor((v - min)/width));
    bcounts[idx]++;
  }});
  return {{labels: blabels, data: bcounts}};
}}

// Render histogram for durations (minutes)
function renderDurationHistogram(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const filtered = computeOpenDurations(events).filter(d => (includeNoBadge || d.badge_id) && !(excludeUnitTest && d.badge_id === 'unit_test')).map(d => Math.round(d.duration/60)); // minutes
  const hist = histogramBins(filtered, 12);
  createChart('duration-hist', 'Open Duration Histogram (min)', 'bar', hist.labels, hist.data);
  // Percentiles
  if (filtered.length) {{
    filtered.sort((a,b) => a-b);
    const p50 = filtered[Math.floor(0.5*(filtered.length-1))];
    const p95 = filtered[Math.floor(0.95*(filtered.length-1))];
    const id = 'duration-stats';
    let card = document.getElementById('card-'+id);
    if (!card) {{ card = document.createElement('div'); card.className = 'card'; card.id = 'card-'+id; document.getElementById('chartsGrid').appendChild(card); }}
    card.innerHTML = `<h2>Duration Percentiles</h2><p>p50: ${{p50}} min, p95: ${{p95}} min</p>`;
  }}
}}

// Render histogram for scan->open latency (s)
function renderLatencyHistogram(events) {{
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const lat = computeScanToOpenLatencies(events).filter(l => (includeNoBadge || l.badge_id) && !(excludeUnitTest && l.badge_id === 'unit_test'));
  const vals = lat.map(l => Math.round(l.delta));
  const hist = histogramBins(vals, 12);
  createChart('latency-hist', 'Scan→Open Latency Histogram (s)', 'bar', hist.labels, hist.data);
  if (vals.length) {{
    vals.sort((a,b)=>a-b);
    const p50 = vals[Math.floor(0.5*(vals.length-1))];
    const p95 = vals[Math.floor(0.95*(vals.length-1))];
    const id = 'latency-stats';
    let card = document.getElementById('card-'+id);
    if (!card) {{ card = document.createElement('div'); card.className = 'card'; card.id = 'card-'+id; document.getElementById('chartsGrid').appendChild(card); }}
    card.innerHTML = `<h2>Latency Percentiles</h2><p>p50: ${{p50}}s, p95: ${{p95}}s</p>`;
  }}
}}

// Export too-long-open list as CSV
function exportTooLongCSV(events) {{
  const threshold = parseInt(document.getElementById('openThreshold')?.value || '300', 10);
  const durations = computeOpenDurations(events).filter(d => d.duration > threshold);
  if (!durations.length) {{ alert('No items exceed threshold'); return; }}
  let csv = 'open_ts,close_ts,duration_s,badge_id\\n';
  durations.forEach(d => {{ csv += `${{d.open_ts}},${{d.close_ts}},${{Math.round(d.duration)}},"${{d.badge_id || ''}}"\\n`; }});
}}

// Reusable chart creation helper
function createChart(id, title, type, labels, data) {{
  const cardId = 'card-'+id;
  let card = document.getElementById(cardId);
  if (!card) {{
    card = document.createElement('div');
    card.className = 'card';
    card.id = cardId;
    document.getElementById('chartsGrid').appendChild(card);
  }}

  // Insert header and canvas
  card.innerHTML = `<h2>${{title}}</h2><canvas id="chart-${{id}}"></canvas>`;

  // Destroy existing chart if present
  try {{
    if (charts[id] && typeof charts[id].destroy === 'function') {{
      charts[id].destroy();
      charts[id] = undefined;
    }}
  }} catch (e) {{ /* ignore */ }}

  const canvas = document.getElementById('chart-'+id);
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

  const excludeUnitTest = document.getElementById('chkExcludeUnitTest')?.checked || false;
  const includeNoBadge = document.getElementById('chkIncludeNoBadge')?.checked || false;
  const filtered = (events || []).filter(e => {{
    if (excludeUnitTest && (e.badge_id || '') === 'unit_test') return false;
    if (!includeNoBadge && !(e.badge_id)) return false;
    return true;
  }});
  const latest = filtered.slice(-100).reverse();
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
  const btnExportAlerts = document.getElementById('btnExportAlerts');
  if (btnExportAlerts) {{ btnExportAlerts.addEventListener('click', () => exportTooLongCSV(latestEvents)); }}

  const chkInclude = document.getElementById('chkIncludeNoBadge');
  if (chkInclude) {{
    // default: unchecked
    chkInclude.checked = false;
    chkInclude.addEventListener('change', () => {{ renderDashboard(latestEvents); updateExcludedCount(latestEvents); }});
  }}

  const chkUnitTest = document.getElementById('chkExcludeUnitTest');
  if (chkUnitTest) {{
    chkUnitTest.addEventListener('change', () => {{ renderDashboard(latestEvents); updateExcludedCount(latestEvents); }});
  }}

  const openThreshold = document.getElementById('openThreshold');
  if (openThreshold) {{
    openThreshold.addEventListener('input', () => {{ renderDashboard(latestEvents); }});
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

    # Fill Python placeholders used in the HTML (keeps the inline JS simple and avoids f-string escaping issues)
    html = html.replace("{start_date.isoformat()}", start_date.isoformat()).replace("{end_date.isoformat()}", end_date.isoformat())
    html = html.replace("{reload_disabled}", reload_disabled).replace("{reload_text}", reload_text)

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
