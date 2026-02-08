"""OpenAPI (Swagger) spec generator for the Door Controller API."""
from typing import Dict, Optional
from .config import config
from .logging_utils import logger
from .version import __version__


def get_openapi_spec(host: Optional[str] = None) -> Dict:
    """Return an OpenAPI 3.0 spec as a Python dict.

    If `host` is provided (for example the HTTP Host header from the request), it
    will be used to construct the `servers` URL. `host` may be a hostname, hostname:port,
    or a full URL (including scheme). When not provided, falls back to configuration
    or localhost.
    """
    port = config.get("HEALTH_SERVER_PORT", 8080)

    logger.debug(f"get_openapi_spec called with host={host!r}, port={port}")

    if host:
        # If a full URL is provided, use it directly
        if host.startswith('http://') or host.startswith('https://'):
            server_url = host
        else:
            # If host already includes a port, don't append one
            if ':' in host:
                server_url = f"http://{host}"
            else:
                server_url = f"http://{host}:{port}"
    else:
        cfg_host = config.get("HEALTH_SERVER_HOST", "localhost")
        server_url = f"http://{cfg_host}:{port}"

    logger.debug(f"Calculated server_url={server_url!r}")

    spec = {
        "openapi": "3.0.0",
        "info": {
            "title": "Door Controller API",
            "version": __version__,
            "description": "API endpoints for managing and inspecting the Door Controller"
        },
        "servers": [{"url": server_url}],
        "components": {
            "securitySchemes": {
                "basicAuth": {
                    "type": "http",
                    "scheme": "basic"
                }
            }
        },
        "security": [{"basicAuth": []}],
        "paths": {
            "/api/refresh_badges": {
                "post": {
                    "summary": "Trigger a manual badge list refresh from Google Sheets",
                    "description": "Manually refresh the badge list. Requires Basic Auth.",
                    "responses": {
                        "200": {"description": "Refresh completed (JSON)"},
                        "500": {"description": "Internal server error"},
                        "503": {"description": "Service unavailable (no refresh callback)"}
                    },
                    "security": [{"basicAuth": []}]
                }
            }
        }
    }

    return spec
