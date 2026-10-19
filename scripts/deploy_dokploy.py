"""Trigger Compose deployment after publication; never print deployment credentials."""

import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

SETTINGS = ("DOKPLOY_URL", "DOKPLOY_API_KEY", "DOKPLOY_COMPOSE_ID")


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Do not forward the API key to a login page or another host.
        return None


def deploy(environ=None, *, opener=None):
    environ = os.environ if environ is None else environ
    values = {name: environ.get(name, "").strip() for name in SETTINGS}
    if not any(values.values()):
        print(
            "Dokploy deployment skipped: configure DOKPLOY_URL, DOKPLOY_API_KEY, DOKPLOY_COMPOSE_ID"
        )
        return False
    if not all(values.values()):
        raise RuntimeError("Configure all three Dokploy secrets before enabling deployment")
    parts = urlsplit(values["DOKPLOY_URL"])
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise RuntimeError("DOKPLOY_URL must be the HTTPS origin of your Dokploy dashboard")
    payload = {
        "composeId": values["DOKPLOY_COMPOSE_ID"],
        "title": "Published scraper image " + environ.get("GITHUB_SHA", "")[:12],
    }
    request = Request(
        values["DOKPLOY_URL"].rstrip("/") + "/api/compose.deploy",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "x-api-key": values["DOKPLOY_API_KEY"],
        },
        method="POST",
    )
    opener = build_opener(NoRedirects()) if opener is None else opener
    try:
        with opener.open(request, timeout=30) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"Dokploy rejected deployment (HTTP {response.status})")
    except HTTPError as exc:
        raise RuntimeError(f"Dokploy rejected deployment (HTTP {exc.code})") from None
    except (URLError, TimeoutError, OSError, ValueError):
        raise RuntimeError(
            "Cannot reach Dokploy API; check URL, certificate and connectivity"
        ) from None
    print("Dokploy accepted deployment after image publication; check its deployment logs")
    return True


if __name__ == "__main__":
    try:
        deploy()
    except RuntimeError as error:
        raise SystemExit(str(error)) from None
