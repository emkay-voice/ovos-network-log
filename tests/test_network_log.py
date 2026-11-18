"""The network log: requests through http.client (urllib, requests) are written as
Emkay's network log lines, with who asked and the service, never the path."""
import http.server
import json
import threading
import time
import urllib.request

import pytest

import ovos_network_log as nl


@pytest.fixture
def log(tmp_path, monkeypatch):
    path = tmp_path / "network.jsonl"
    monkeypatch.setenv("OVOS_NETWORK_LOG_FILE", str(path))
    monkeypatch.setenv("OVOS_NETWORK_LOG_BUS", "0")
    # this machine's addresses are left out; for the test, a local server must count
    monkeypatch.setattr(nl, "LOCAL", __import__("re").compile(r"^$never"))
    nl.install()
    return path


@pytest.fixture
def server():
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"hello"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def entries(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_a_request_is_logged_without_its_path(log, server):
    urllib.request.urlopen(f"http://{server}/secret/what-you-said?q=hello").read()
    [e] = entries(log)
    assert e["host"] == server and e["method"] == "GET" and e["status"] == 200 and e["bytes"] == 5
    assert e["kind"] == "other" and e["service"] == server
    assert "secret" not in json.dumps(e) and "hello" not in json.dumps(e)
    assert abs(e["t"] / 1000 - time.time()) < 5


def test_requests_is_seen_too(log, server):
    requests = pytest.importorskip("requests")
    requests.get(f"http://{server}/x", timeout=5)
    assert entries(log)[-1]["host"] == server


def test_a_refused_request_is_logged_with_status_0(log):
    with pytest.raises(OSError):
        urllib.request.urlopen("http://127.0.0.1:9/", timeout=2)
    e = entries(log)[-1]
    assert e["status"] == 0 and e["host"] == "127.0.0.1:9"


def test_this_machine_is_not_sent_out(tmp_path, monkeypatch):
    monkeypatch.setenv("OVOS_NETWORK_LOG_FILE", str(tmp_path / "n.jsonl"))
    monkeypatch.setenv("OVOS_NETWORK_LOG_BUS", "0")
    assert nl.record("localhost:8181", "GET", 200, 1, "ovos") is None
    assert nl.record("127.0.0.1", "GET", 200, 1, "ovos") is None
    assert not (tmp_path / "n.jsonl").exists()


def test_known_services():
    assert nl.service("stt.openvoiceos.pt") == ("stt", "speech recognition (OpenVoiceOS server)")
    assert nl.service("da.wikipedia.org")[0] == "wikipedia"
    assert nl.service("air-quality-api.open-meteo.com")[0] == "weather"
    assert nl.service("example.com") == ("other", "example.com")


def test_who_asked():
    assert nl.caller(1) in ("tests", "test-network-log", "ovos")


def test_only_ovos_programs(monkeypatch):
    monkeypatch.delenv("OVOS_NETWORK_LOG", raising=False)
    for program, on in (("/usr/bin/ovos-core", True), ("ovos-audio", True), ("mycroft-skills", True),
                        ("/usr/bin/pip", False), ("python3", False)):
        monkeypatch.setattr("sys.argv", [program])
        assert nl.wanted() is on, program
    monkeypatch.setenv("OVOS_NETWORK_LOG", "1")
    assert nl.wanted()
    monkeypatch.setenv("OVOS_NETWORK_LOG", "0")
    monkeypatch.setattr("sys.argv", ["ovos-core"])
    assert not nl.wanted()


def test_old_entries_are_pruned(tmp_path):
    path = tmp_path / "n.jsonl"
    now = int(time.time() * 1000)
    path.write_text(json.dumps({"t": now - 9 * 86400 * 1000}) + "\n" + json.dumps({"t": now}) + "\n")
    nl.prune(str(path))
    assert [e["t"] for e in entries(path)] == [now]
