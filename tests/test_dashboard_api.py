"""Integration tests for Dashboard HTTP endpoints and static assets."""

import json
import socket
import threading
import time
import urllib.request
import pytest
from http.server import ThreadingHTTPServer

from applypilot.dashboard.server import DashboardHandler
from applypilot.database import init_db


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def dashboard_server(tmp_path_factory):
    port = find_free_port()
    db_file = tmp_path_factory.mktemp("db") / "test_dash.db"
    init_db(db_file)

    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.5)

    yield f"http://127.0.0.1:{port}"

    server.shutdown()


def test_dashboard_static_assets_and_routes(dashboard_server):
    """Assert HTTP 200 and valid responses for core dashboard routes."""
    # 1. Root HTML
    with urllib.request.urlopen(f"{dashboard_server}/") as resp:
        assert resp.status == 200
        assert "text/html" in resp.headers.get("Content-Type", "")
        content = resp.read().decode("utf-8")
        assert "/static/styles.css" in content
        assert "/static/app.js" in content

    # 2. Static CSS
    with urllib.request.urlopen(f"{dashboard_server}/static/styles.css") as resp:
        assert resp.status == 200
        assert "text/css" in resp.headers.get("Content-Type", "")

    # 3. Static JS
    with urllib.request.urlopen(f"{dashboard_server}/static/app.js") as resp:
        assert resp.status == 200
        assert "javascript" in resp.headers.get("Content-Type", "")

    # 4. Jobs API
    with urllib.request.urlopen(f"{dashboard_server}/api/jobs") as resp:
        assert resp.status == 200
        assert "application/json" in resp.headers.get("Content-Type", "")
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, list)

    # 5. Followups Due API
    with urllib.request.urlopen(f"{dashboard_server}/api/followups/due") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, (list, dict))

    # 5b. Stats API
    with urllib.request.urlopen(f"{dashboard_server}/api/stats") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, dict)
        assert "total" in data

    # 6. Skills Demand API
    with urllib.request.urlopen(f"{dashboard_server}/api/skills/demand") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, list)

    # 7. Funding Leads API
    with urllib.request.urlopen(f"{dashboard_server}/api/funding-leads") as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        assert isinstance(data, list)
