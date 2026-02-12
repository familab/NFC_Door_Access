"""Login/logout routes with basic auth and Google OAuth2."""
import html as html_stdlib
import os
from urllib.parse import parse_qs, quote

from ..config import config
from ..logging_utils import get_logger
from .helpers import get_host_header
from .auth import (
    create_session,
    set_session_cookie,
    clear_session,
    clear_session_cookie,
    is_email_whitelisted,
    save_oauth_state,
    pop_oauth_state,
)

# Allow OAuth over HTTP for local development/tunnels (configure via GOOGLE_OAUTH_ALLOW_HTTP)
if config.get("GOOGLE_OAUTH_ALLOW_HTTP"):
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

GOOGLE_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _get_query_param(raw_query: str, key: str, default: str = "") -> str:
    query = parse_qs(raw_query or "", keep_blank_values=False)
    return query.get(key, [default])[0]


def _get_next_path(raw_query: str) -> str:
    next_path = _get_query_param(raw_query, "next", "/admin")
    if not next_path.startswith("/") or next_path.startswith("//"):
        return "/admin"
    return next_path


def _normalize_scopes(value) -> list:
    if value is None:
        return ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    if isinstance(value, list):
        return value
    raw = str(value).strip()
    if not raw:
        return ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    return [p.strip() for p in raw.replace(",", " ").split() if p.strip()]


def _login_page_html(error_message: str = "", next_path: str = "/admin") -> str:
    error_html = ""
    if error_message:
        safe_error = html_stdlib.escape(error_message)
        error_html = f"<div class=\"error\">{safe_error}</div>"

    google_ready = bool(config.get("GOOGLE_OAUTH_ENABLED")) and bool(
        config.get("GOOGLE_OAUTH_CLIENT_ID")
    ) and bool(config.get("GOOGLE_OAUTH_CLIENT_SECRET"))
    google_next = quote(next_path)
    google_button = (
        f"<a class=\"btn google\" href=\"/login/google?next={google_next}\">Sign in with Google</a>"
        if google_ready
        else "<div class=\"note\">Google Sign-In is not configured.</div>"
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>Door Controller Login</title>
  <link rel=\"icon\" href=\"https://images.squarespace-cdn.com/content/v1/65fbda49f5eb7e7df1ae5f87/1711004274233-C9RL74H38DXHYWBDMLSS/favicon.ico?format=100w\">
  <style>
    body {{ font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; }}
    h1 {{ color: #4ec9b0; }}
    .card {{ max-width: 420px; background: #252526; border: 1px solid #555; border-radius: 8px; padding: 16px; }}
    label {{ display: block; margin-top: 10px; }}
    input {{ width: 100%; background: #1e1e1e; color: #d4d4d4; border: 1px solid #555; padding: 8px; border-radius: 4px; }}
    .btn {{ display: inline-block; margin-top: 12px; background:#4ec9b0; color:#1e1e1e; padding:8px 12px; border:none; border-radius:4px; cursor:pointer; text-decoration: none; }}
    .btn.google {{ background: #9cdcfe; }}
    .error {{ margin-top: 10px; padding: 8px; background: #4a2d2d; color: #f48771; border-radius: 4px; }}
    .note {{ margin-top: 12px; color: #c9c9c9; }}
  </style>
</head>
<body>
  <h1>Login</h1>
  <div class=\"card\">
    {error_html}
    <form method=\"POST\" action=\"/login\">
      <input type=\"hidden\" name=\"next\" value=\"{html_stdlib.escape(next_path)}\">
      <label>Username</label>
      <input name=\"username\" autocomplete=\"username\" required />
      <label>Password</label>
      <input name=\"password\" type=\"password\" autocomplete=\"current-password\" required />
      <button class=\"btn\" type=\"submit\">Sign in</button>
    </form>
    <div style=\"margin-top:14px;\">{google_button}</div>
  </div>
</body>
</html>"""


def send_login_page(handler, raw_query: str, error_message: str = "") -> None:
    next_path = _get_next_path(raw_query)
    html = _login_page_html(error_message=error_message, next_path=next_path)
    handler.send_response(200)
    handler.send_header("Content-type", "text/html; charset=utf-8")
    handler.end_headers()
    handler.wfile.write(html.encode("utf-8"))


def handle_login_post(handler) -> None:
    length = int(handler.headers.get("Content-Length", 0) or 0)
    body = handler.rfile.read(length) if length > 0 else b""
    raw = body.decode("utf-8", errors="ignore")
    data = parse_qs(raw, keep_blank_values=True)
    username = data.get("username", [""])[0]
    password = data.get("password", [""])[0]
    next_path = data.get("next", ["/admin"])[0] or "/admin"
    if not next_path.startswith("/") or next_path.startswith("//"):
        next_path = "/admin"

    if username == config.get("HEALTH_SERVER_USERNAME") and password == config.get(
        "HEALTH_SERVER_PASSWORD"
    ):
        session_id = create_session(username)
        handler.send_response(302)
        set_session_cookie(handler, session_id)
        handler.send_header("Location", next_path)
        handler.end_headers()
        return

    send_login_page(handler, raw_query=f"next={next_path}", error_message="Invalid username or password")


def handle_logout(handler) -> None:
    clear_session(handler)

    # If OAuth is disabled, we're using Basic Auth - use a more reliable logout approach
    if not config.get("GOOGLE_OAUTH_ENABLED"):
        handler.send_response(200)
        clear_session_cookie(handler)
        handler.send_header("Content-type", "text/html; charset=utf-8")
        handler.end_headers()
        # Use XMLHttpRequest with invalid credentials to overwrite cached Basic Auth
        html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>Logging Out...</title>
  <style>
    body { font-family: monospace; margin: 20px; background: #1e1e1e; color: #d4d4d4; text-align: center; padding-top: 100px; }
    h1 { color: #4ec9b0; }
    .spinner { border: 4px solid #555; border-top: 4px solid #4ec9b0; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; margin: 20px auto; }
    @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
  </style>
  <script>
    (function() {
      // Clear Basic Auth by sending request with invalid credentials
      var xhr = new XMLHttpRequest();
      xhr.open('GET', '/admin', true, 'logout', 'logout');
      xhr.onreadystatechange = function() {
        if (xhr.readyState === 4) {
          // After clearing credentials, redirect to login
          setTimeout(function() {
            window.location.href = '/login';
          }, 500);
        }
      };
      xhr.onerror = function() {
        // On error, still redirect to login
        setTimeout(function() {
          window.location.href = '/login';
        }, 500);
      };
      xhr.send();
    })();
  </script>
</head>
<body>
  <h1>Logging Out...</h1>
  <div class="spinner"></div>
  <p>Clearing credentials...</p>
</body>
</html>"""
        handler.wfile.write(html.encode("utf-8"))
    else:
        # OAuth mode: clear session cookie and redirect to login
        handler.send_response(302)
        clear_session_cookie(handler)
        handler.send_header("Location", "/login")
        handler.end_headers()


def handle_google_login_start(handler, raw_query: str) -> None:
    next_path = _get_next_path(raw_query)
    if not config.get("GOOGLE_OAUTH_ENABLED"):
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth is not enabled")
        return
    client_id = config.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth is not configured")
        return

    try:
        from google_auth_oauthlib.flow import Flow
    except Exception as exc:
        get_logger().warning(f"Google OAuth library missing: {exc}")
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth libraries missing")
        return

    host = get_host_header(handler) or "localhost"
    scheme = "https" if config.get("HEALTH_SERVER_TLS") else "http"
    redirect_uri = config.get("GOOGLE_OAUTH_REDIRECT_URI") or f"{scheme}://{host}/login/google/callback"

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
        }
    }

    scopes = _normalize_scopes(config.get("GOOGLE_OAUTH_SCOPES"))
    flow = Flow.from_client_config(client_config, scopes=scopes)
    flow.redirect_uri = redirect_uri
    auth_url, state = flow.authorization_url(
        access_type="online",
        include_granted_scopes="true",
        prompt="select_account",
    )

    save_oauth_state(state, next_path)
    handler.send_response(302)
    handler.send_header("Location", auth_url)
    handler.end_headers()


def handle_google_callback(handler, raw_query: str) -> None:
    query = parse_qs(raw_query or "", keep_blank_values=True)
    state = query.get("state", [""])[0]
    code = query.get("code", [""])[0]
    next_path = pop_oauth_state(state) or "/admin"

    if not config.get("GOOGLE_OAUTH_ENABLED"):
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth is not enabled")
        return

    if not state or not code:
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Invalid OAuth response")
        return

    client_id = config.get("GOOGLE_OAUTH_CLIENT_ID")
    client_secret = config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    if not client_id or not client_secret:
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth is not configured")
        return

    try:
        from google_auth_oauthlib.flow import Flow
        from google.auth.transport.requests import Request
        from google.oauth2 import id_token
    except Exception as exc:
        get_logger().warning(f"Google OAuth library missing: {exc}")
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google OAuth libraries missing")
        return

    host = get_host_header(handler) or "localhost"
    scheme = "https" if config.get("HEALTH_SERVER_TLS") else "http"
    redirect_uri = config.get("GOOGLE_OAUTH_REDIRECT_URI") or f"{scheme}://{host}/login/google/callback"

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": GOOGLE_AUTH_URI,
            "token_uri": GOOGLE_TOKEN_URI,
        }
    }

    scopes = _normalize_scopes(config.get("GOOGLE_OAUTH_SCOPES"))
    flow = Flow.from_client_config(client_config, scopes=scopes)
    flow.redirect_uri = redirect_uri

    try:
        full_url = handler.path
        if not full_url.startswith("http"):
            full_url = f"{scheme}://{host}{handler.path}"
        flow.fetch_token(authorization_response=full_url)
        credentials = flow.credentials
        info = id_token.verify_oauth2_token(credentials.id_token, Request(), client_id)
        email = info.get("email")
        email_verified = info.get("email_verified")
        if not email or not email_verified:
            send_login_page(handler, raw_query=f"next={next_path}", error_message="Google account not verified")
            return
        if not is_email_whitelisted(email):
            send_login_page(handler, raw_query=f"next={next_path}", error_message="Email not allowed")
            return
        session_id = create_session(email)
        handler.send_response(302)
        set_session_cookie(handler, session_id)
        handler.send_header("Location", next_path)
        handler.end_headers()
    except Exception as exc:
        get_logger().warning(f"Google OAuth callback failed: {exc}")
        send_login_page(handler, raw_query=f"next={next_path}", error_message="Google sign-in failed")
