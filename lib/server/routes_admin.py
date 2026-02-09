"""Admin routes: /admin page and actions (auth required), rate-limited refresh, log downloads."""
import html as html_stdlib
import json
from ..config import config
from ..version import __version__
from ..logging_utils import (
    get_last_google_log_success,
    get_last_badge_download,
    get_last_data_connection,
    get_last_google_error,
    get_log_file_size,
    get_current_log_file_path,
    get_current_action_log_file_path,
    update_last_badge_download,
    record_action,
    get_logger,
    _parse_log_base,
)
from ..server import state as server_state
from ..door_control import get_door_status, get_door_status_updated
from .state import (
    TEXT_HTML,
    APPLICATION_JSON,
    format_timestamp,
    get_local_ips,
    get_uptime,
    get_disk_space,
    get_pn532_status,
    get_badge_refresh_callback,
    check_rate_limit_badge_refresh,
    read_log_tail,
    read_log_full,
)
from datetime import datetime
import socket
import os
import re
from io import BytesIO
from zipfile import ZipFile


def send_admin_page(handler):
    """Send admin dashboard: health data + last 50 system log lines + last 50 action log lines + refresh buttons."""
    door_status = "OPEN/UNLOCKED" if get_door_status() else "CLOSED/LOCKED"
    door_updated = format_timestamp(get_door_status_updated())
    last_google_log = format_timestamp(get_last_google_log_success())
    last_data_conn = format_timestamp(get_last_data_connection())
    last_badge_dl = format_timestamp(get_last_badge_download())
    google_error = get_last_google_error() or "None"
    pn532_status = get_pn532_status()
    pn532_success = format_timestamp(pn532_status["last_success"])
    pn532_error = pn532_status["last_error"] or "None"
    uptime = get_uptime()
    disk = get_disk_space()
    try:
        current_log_file = get_current_log_file_path()
    except Exception:
        current_log_file = config.get("LOG_FILE", "")
    try:
        current_action_log_file = get_current_action_log_file_path()
    except Exception:
        current_action_log_file = ""
    log_size_bytes = get_log_file_size()
    log_size_mb = log_size_bytes / (1024 * 1024)

    last_system_log = html_stdlib.escape(read_log_tail(current_log_file, 50))
    last_action_log = html_stdlib.escape(
        read_log_tail(current_action_log_file, 50) if current_action_log_file else ""
    )

    # Time until next rate-limited actions (seconds)
    badge_wait = server_state.get_seconds_until_next_badge_refresh()

    def _format_hms(seconds):
        try:
            s = int(seconds)
        except Exception:
            s = 0
        h = s // 3600
        m = (s % 3600) // 60
        sec = s % 60
        return f"{h:02d}:{m:02d}:{sec:02d}"

    badge_hms = _format_hms(badge_wait)

    # Health refresh interval (for shows/how often system state is auto-refreshed) - reuse HEALTH_REFRESH_INTERVAL
    refresh_interval = int(config.get("HEALTH_REFRESH_INTERVAL", 0) or 0)

    # Optional meta refresh tag for auto-reloading the page
    refresh_meta = f'<meta http-equiv="refresh" content="{refresh_interval}">' if refresh_interval > 0 else ''

    page = f"""<!DOCTYPE html>
<html>
<head>
    {refresh_meta}
    <title>Admin - Door Controller</title>
    <link rel="icon" href="https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w">
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
        h1 {{ color: #4ec9b0; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
        th, td {{ border: 1px solid #555; padding: 10px; text-align: left; }}
        th {{ background: #2d2d30; color: #4ec9b0; }}
        tr:nth-child(even) {{ background: #252526; }}
        .status-ok {{ color: #4ec9b0; font-weight: bold; }}
        .status-warning {{ color: #dcdcaa; font-weight: bold; }}
        .status-error {{ color: #f48771; font-weight: bold; }}
        .timestamp {{ color: #9cdcfe; }}
        .toast {{ position: fixed; right: 20px; bottom: 20px; padding: 10px 14px; border-radius: 6px; display: none; z-index: 9999; }}
        .toast.success {{ background: #4ec9b0; color: #1e1e1e; }}
        .toast.error {{ background: #f48771; color: #fff; }}
        pre {{ white-space: pre-wrap; max-height: 240px; overflow: auto; margin: 0; font-size: 0.9em; }}
        a {{ color: #9cdcfe; }}
    </style>
</head>
<body>
    <h1>Admin Dashboard</h1>
    <p class="timestamp">Version: {__version__} &nbsp;|&nbsp; <a href="/health">Health</a> &nbsp;|&nbsp; <a href="/docs">Docs</a></p>
    <p class="timestamp">Machine: {socket.gethostname()} &nbsp; Local IPs: {', '.join(get_local_ips()) or 'None'}</p>
    <p class="timestamp">
        Auto-refresh: {refresh_interval}s &nbsp; Next refresh in <span id="adminRefreshCountdown">{refresh_interval}</span>s
    </p>
    <p class="timestamp">
        <button id="refreshBadgeBtn" style="background:#4ec9b0;color:#1e1e1e;padding:6px;border:none;border-radius:4px;cursor:pointer;">Refresh Badge List</button>
        Next badge refresh in <span id="badgeRefreshCountdown">{badge_hms}</span>
    </p>
    <div id="toast" class="toast"></div>
    <table>
        <tr><th>Metric</th><th>Value</th></tr>
        <tr>
            <td>Door Status</td>
            <td class="{'status-warning' if get_door_status() else 'status-ok'}">{door_status}</td>
        </tr>
        <tr><td>Door Status Updated</td><td>{door_updated}</td></tr>
        <tr><td>Application Uptime</td><td class="status-ok">{uptime}</td></tr>
        <tr><td>Last Google Sheets Log</td><td>{last_google_log}</td></tr>
        <tr><td>Last Data Connection</td><td>{last_data_conn}</td></tr>
        <tr><td>Last Badge Download</td><td>{last_badge_dl}</td></tr>
        <tr>
            <td>Google Sheets Last Error</td>
            <td class="{'status-ok' if google_error == 'None' else 'status-error'}">{google_error}</td>
        </tr>
        <tr><td>PN532 Last Success</td><td>{pn532_success}</td></tr>
        <tr>
            <td>PN532 Last Error</td>
            <td class="{'status-ok' if pn532_error == 'None' else 'status-error'}">{pn532_error}</td>
        </tr>
        <tr><td>Log File Size</td><td>{log_size_mb:.2f} MB</td></tr>
        <tr><td>Current Log File</td><td style="font-size:0.9em; word-break:break-all;">{current_log_file}</td></tr>
        <tr><td>Disk Free Space</td><td>{disk['free_mb']:.2f} MB / {disk['total_mb']:.2f} MB ({disk['percent_used']:.1f}% used)</td></tr>
        <tr>
            <td>Last 50 System Log Lines</td>
            <td><pre>{last_system_log or '(empty)'}</pre></td>
        </tr>
        <tr>
            <td>Last 50 Action Log Lines</td>
            <td><pre>{last_action_log or '(empty)'}</pre></td>
        </tr>
    </table>
    <p class="timestamp" style="margin-top:16px;">
        Downloads: <a href="/admin/download/system-current">system-current</a> &nbsp;
        <a href="/admin/download/action-current">action-current</a> &nbsp;
        <a href="/admin/download/system-all">system-all</a> &nbsp;
        <a href="/admin/download/action-all">action-all</a>
    </p>
    <script>
    (function() {{
        const toastEl = document.getElementById('toast');
        function showToast(msg, kind, timeout) {{ toastEl.textContent = msg; toastEl.className = 'toast ' + (kind || 'success'); toastEl.style.display = 'block'; setTimeout(function() {{ toastEl.style.display = 'none'; }}, timeout || 4000); }}
        async function post(url) {{
            const r = await fetch(url, {{ method: 'POST', redirect: 'manual' }});
            const ct = r.headers.get('Content-Type') || '';
            if (ct.includes('application/json')) {{
                const j = await r.json();
                return {{ ok: r.ok, msg: j.message || (r.ok ? 'OK' : 'Error') }};
            }}
            return {{ ok: r.ok, msg: r.ok ? 'OK' : ('Error ' + r.status) }};
        }}
        document.getElementById('refreshBadgeBtn').addEventListener('click', async function() {{
            const btn = this;
            btn.disabled = true;
            const res = await post('/api/refresh_badges');
            showToast(res.msg, res.ok ? 'success' : 'error');
            btn.disabled = false;
            if (res.msg.indexOf('Rate limited') === -1) location.reload();
        }});
        // Countdown timer for admin page refresh (reload page when it reaches 0)
        (function() {{
            const adminEl = document.getElementById('adminRefreshCountdown');
            let adminCountdown = {refresh_interval};
            function adminTick() {{
                if (adminEl) adminEl.textContent = String(Math.max(0, adminCountdown));
                if (adminCountdown <= 0) {{
                    location.reload();
                    return;
                }}
                adminCountdown -= 1;
                setTimeout(adminTick, 1000);
            }}
            if ({refresh_interval} > 0) adminTick();
        }})();

        // Countdown timer for badge refresh (reload page when it reaches 0) and display HH:MM:SS
        (function() {{
            const badgeEl = document.getElementById('badgeRefreshCountdown');
            let badgeCountdown = {badge_wait};
            function formatTime(s) {{
                const h = Math.floor(s / 3600);
                const m = Math.floor((s % 3600) / 60);
                const sec = s % 60;
                const hh = String(h).padStart(2, '0');
                const mm = String(m).padStart(2, '0');
                const ss = String(sec).padStart(2, '0');
                return `${{hh}}:${{mm}}:${{ss}}`;
            }}
            function tick() {{
                if (badgeEl) badgeEl.textContent = formatTime(Math.max(0, badgeCountdown));
                if (badgeCountdown <= 0) {{
                    // refresh the page so server can recompute remaining time
                    location.reload();
                    return;
                }}
                badgeCountdown -= 1;
                setTimeout(tick, 1000);
            }}
            tick();
        }})();

    }})();
    </script>
</body>
</html>"""
    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(page.encode("utf-8"))


def handle_post_refresh_badges(handler) -> bool:
    """Handle POST /api/refresh_badges (rate-limited). Returns True if handled."""
    allowed, err_msg = check_rate_limit_badge_refresh()
    if not allowed:
        handler.send_response(429)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "message": err_msg}).encode("utf-8"))
        return True

    fn = get_badge_refresh_callback()
    if fn is None:
        try:
            update_last_badge_download(success=False)
        except Exception:
            pass
        handler.send_response(503)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(
            json.dumps({"success": False, "message": "Badge refresh not available"}).encode("utf-8")
        )
        return True

    try:
        result = fn()
        if isinstance(result, tuple):
            success = bool(result[0])
            info = str(result[1]) if len(result) > 1 else ""
        else:
            success = bool(result)
            info = ""
        update_last_badge_download(success=success)
        record_action("Manual Badge Refresh", status="Success" if success else "Failure")
        status_code = 200 if success else 500
        handler.send_response(status_code)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": success, "message": info}).encode("utf-8"))
        return True
    except Exception as e:
        get_logger().error(f"Badge refresh failed: {e}")
        try:
            update_last_badge_download(success=False)
        except Exception:
            pass
        handler.send_response(500)
        handler.send_header("Content-type", APPLICATION_JSON)
        handler.end_headers()
        handler.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))
        return True





def handle_download(handler, path: str) -> bool:
    """Handle GET /admin/download/<kind>. Returns True if handled."""
    # path is e.g. /admin/download/system-current
    parts = path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "admin" or parts[1] != "download":
        return False
    kind = parts[2]
    if kind == "system-current":
        log_path = get_current_log_file_path()
        content = read_log_tail(log_path, 50)
        filename = "system-current.txt"
    elif kind == "action-current":
        log_path = get_current_action_log_file_path()
        content = read_log_tail(log_path, 50)
        filename = "action-current.txt"
    elif kind == "system-all":
        # Package all dated system log files into a zip archive
        log_file = config.get("LOG_FILE")
        log_dir, base_name, ext = _parse_log_base(log_file)
        pattern = re.compile(rf"^{re.escape(base_name)}-(\d{{4}}-\d{{2}}-\d{{2}}){re.escape(ext)}$")
        file_list = [n for n in sorted(os.listdir(log_dir)) if pattern.match(n)] if os.path.exists(log_dir) else []
        filename = "system-all.zip"
        bio = BytesIO()
        with ZipFile(bio, 'w') as zf:
            for fname in file_list:
                path = os.path.join(log_dir, fname)
                try:
                    zf.write(path, arcname=fname)
                except Exception:
                    pass
        content = bio.getvalue()
    elif kind == "action-all":
        # Package all dated action log files into a zip archive
        action_file_cfg = config.get("ACTION_LOG_FILE")
        if action_file_cfg:
            action_file = action_file_cfg
        else:
            # Derive action file name from LOG_FILE but keep the same directory
            system_log_file = config.get("LOG_FILE")
            log_dir, base_name, ext = _parse_log_base(system_log_file)
            action_file = os.path.join(log_dir, f"{base_name}_action{ext}")

        log_dir, base_name_action, ext = _parse_log_base(action_file)
        pattern = re.compile(rf"^{re.escape(base_name_action)}-(\d{{4}}-\d{{2}}-\d{{2}}){re.escape(ext)}$")
        file_list = [n for n in sorted(os.listdir(log_dir)) if pattern.match(n)] if os.path.exists(log_dir) else []
        filename = "action-all.zip"
        bio = BytesIO()
        with ZipFile(bio, 'w') as zf:
            for fname in file_list:
                path = os.path.join(log_dir, fname)
                try:
                    zf.write(path, arcname=fname)
                except Exception:
                    pass
        content = bio.getvalue()
    else:
        return False

    handler.send_response(200)
    # Choose content-type based on content
    if isinstance(content, bytes):
        handler.send_header("Content-type", "application/zip")
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.end_headers()
        handler.wfile.write(content)
    else:
        handler.send_header("Content-type", "text/plain; charset=utf-8")
        handler.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        handler.end_headers()
        handler.wfile.write(content.encode("utf-8"))
    return True
