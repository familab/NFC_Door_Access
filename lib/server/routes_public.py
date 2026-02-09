"""Public routes: /health (no auth), /docs (no auth)."""
from ..config import config
from ..version import __version__
from ..logging_utils import (
    get_last_google_log_success,
    get_last_badge_download,
    get_last_data_connection,
    get_last_google_error,
    get_log_file_size,
    get_current_log_file_path,
)
from ..door_control import get_door_status, get_door_status_updated
from .state import (
    TEXT_HTML,
    format_timestamp,
    get_local_ips,
    get_uptime,
    get_disk_space,
    get_pn532_status,
)
from datetime import datetime
import socket


def send_health_page(handler):
    """Send public health page: door status, timestamps, uptime, disk. No auth, no refresh, no logs."""
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
    log_size_bytes = get_log_file_size()
    log_size_mb = log_size_bytes / (1024 * 1024)

    refresh_interval = int(config.get("HEALTH_REFRESH_INTERVAL", 0) or 0)
    meta_refresh = f'<meta http-equiv="refresh" content="{refresh_interval}">' if refresh_interval > 0 else ""
    refresh_display = f"{refresh_interval}s" if refresh_interval > 0 else "Off"
    if refresh_interval > 0:
        refresh_html = f'Auto-refresh: {refresh_display} &nbsp; Next refresh in <span id="refreshCountdown">{refresh_interval}</span>s'
    else:
        refresh_html = "Auto-refresh: Off"

    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Door Controller Health</title>
    {meta_refresh}
    <link rel="icon" href="https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w">
    <style>
        body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
        h1 {{ color: #4ec9b0; }}
        table {{ border-collapse: collapse; width: 100%; max-width: 800px; }}
        th, td {{ border: 1px solid #555; padding: 10px; text-align: left; }}
        th {{ background: #2d2d30; color: #4ec9b0; }}
        tr:nth-child(even) {{ background: #252526; }}
        .status-ok {{ color: #4ec9b0; font-weight: bold; }}
        .status-warning {{ color: #dcdcaa; font-weight: bold; }}
        .status-error {{ color: #f48771; font-weight: bold; }}
        .timestamp {{ color: #9cdcfe; }}
    </style>
</head>
<body>
    <h1>Door Controller Health Status</h1>
    <p class="timestamp">Version: {__version__}</p>
    <p class="timestamp">Current Date: {format_timestamp(datetime.now())}</p>
    <p class="timestamp">{refresh_html}</p>
    <p class="timestamp">Machine: {socket.gethostname()}</p>
    <p class="timestamp">Local IPs: {', '.join(get_local_ips()) or 'None'}</p>
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
        <tr><td>Disk Free Space</td><td>{disk['free_mb']:.2f} MB / {disk['total_mb']:.2f} MB ({disk['percent_used']:.1f}% used)</td></tr>
    </table>
    <script>
    (function() {{
        const interval = {refresh_interval};
        if (interval > 0) {{
            let countdown = interval;
            const el = document.getElementById('refreshCountdown');
            if (el) el.textContent = countdown;
            setInterval(function() {{
                countdown -= 1;
                if (el) el.textContent = countdown;
                if (countdown <= 0) location.reload();
            }}, 1000);
        }}
    }})();
    </script>
</body>
</html>"""
    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(html.encode("utf-8"))


def send_docs_page(handler):
    """Send Swagger UI docs page (public)."""
    html = """<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Door Controller API Docs</title>
    <link rel="icon" href="https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w">
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@4/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@4/swagger-ui-bundle.js"></script>
    <script>
      window.onload = function() {
        const ui = SwaggerUIBundle({
          url: '/openapi.json',
          dom_id: '#swagger-ui',
          presets: [SwaggerUIBundle.presets.apis],
          layout: 'BaseLayout'
        });
      };
    </script>
  </body>
</html>"""
    handler.send_response(200)
    handler.send_header("Content-type", TEXT_HTML)
    handler.end_headers()
    handler.wfile.write(html.encode("utf-8"))
