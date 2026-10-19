import json
import runpy
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/deploy_dokploy.py"))
deploy = module["deploy"]
NoRedirects = module["NoRedirects"]

CONFIG = {
    "DOKPLOY_URL": "https://deploy.example.com/",
    "DOKPLOY_API_KEY": "private-deployment-token",
    "DOKPLOY_COMPOSE_ID": "scraper-compose-id",
    "GITHUB_SHA": "a" * 40,
}


class Opener:
    def __init__(self, error=None, status=200):
        self.error, self.status, self.calls = error, status, []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def test_deploy_request_auth_payload_and_timeout(capsys):
    opener = Opener()
    assert deploy(CONFIG, opener=opener)
    request, timeout = opener.calls[0]
    assert timeout == 30 and request.method == "POST"
    assert request.full_url == "https://deploy.example.com/api/compose.deploy"
    assert request.get_header("X-api-key") == CONFIG["DOKPLOY_API_KEY"]
    payload = json.loads(request.data)
    assert payload["composeId"] == "scraper-compose-id"
    assert payload["title"].endswith("a" * 12)
    assert "freshVolumes" not in payload
    assert CONFIG["DOKPLOY_API_KEY"] not in capsys.readouterr().out


def test_absent_deployment_settings_skip_without_request(capsys):
    opener = Opener()
    assert not deploy({}, opener=opener)
    assert opener.calls == []
    assert "skipped" in capsys.readouterr().out


@pytest.mark.parametrize("missing", ["DOKPLOY_URL", "DOKPLOY_API_KEY", "DOKPLOY_COMPOSE_ID"])
def test_partial_configuration_fails_without_request(missing):
    config = {key: value for key, value in CONFIG.items() if key != missing}
    opener = Opener()
    with pytest.raises(RuntimeError, match="all three"):
        deploy(config, opener=opener)
    assert opener.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "http://deploy.example.com",
        "https://user:secret@deploy.example.com",
        "https://deploy.example.com/api",
        "https://deploy.example.com/?token=secret",
        "https://deploy.example.com/#secret",
    ],
)
def test_invalid_or_credential_bearing_origin_never_sends_request(url):
    opener = Opener()
    with pytest.raises(RuntimeError, match="HTTPS origin") as error:
        deploy({**CONFIG, "DOKPLOY_URL": url}, opener=opener)
    assert "secret" not in str(error.value) and opener.calls == []


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://private.example.com", 401, "private-deployment-token", {}, None),
        HTTPError("https://private.example.com", 302, "private-deployment-token", {}, None),
        URLError("private-deployment-token"),
        TimeoutError("private-deployment-token"),
    ],
)
def test_failure_does_not_leak_credentials_or_retry(failure, capsys):
    opener = Opener(error=failure)
    with pytest.raises(RuntimeError) as error:
        deploy(CONFIG, opener=opener)
    assert "private-deployment-token" not in str(error.value)
    assert "private-deployment-token" not in capsys.readouterr().out
    assert len(opener.calls) == 1


def test_redirects_do_not_forward_api_key():
    assert (
        NoRedirects().redirect_request(None, None, 302, "", {}, "https://other.example.com") is None
    )
