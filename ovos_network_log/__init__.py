"""A network log for OpenVoiceOS: what the assistant sent out, and who asked.

Installed next to OVOS (pip install ovos-network-log), it logs every HTTP
request an OVOS service makes – ovos-core and its skills, the listener, the
audio service, PHAL – in the format Emkay keeps and
ovos-skill-guardian reads ("what did you send out today?", "what just
happened?"):

    {"t": 1794863530091, "host": "stt.openvoiceos.pt", "method": "POST",
     "status": 200, "bytes": 52, "who": "ovos-stt-plugin-server",
     "kind": "stt", "service": "speech recognition (OpenVoiceOS server)"}

when, the host, the method, the status, the size of the answer, which
package asked (from the call stack) and the service in words. Never the
path, the query or the body: some services carry what you said in the
address, and the log must not become the thing it is there to show.
https://github.com/emkay-voice/emkay/blob/main/docs/network-log.md

How: a .pth file (ovos_network_log.pth) that Python reads at start-up in
every process of this environment imports ovos_network_log._startup, which
switches the log on in OVOS' own processes only (ovos-core, ovos-audio,
ovos-dinkum-listener, ovos-phal …; OVOS_NETWORK_LOG=1 forces it on,
=0 off). It wraps http.client – under urllib, urllib3 and requests, which
nearly all of OVOS uses. Requests made with httpx or aiohttp are not seen.

Where: each entry is appended to ~/.local/state/emkay/network.jsonl
(OVOS_NETWORK_LOG_FILE changes it) and, unless OVOS_NETWORK_LOG_BUS=0, sent
on the messagebus as ovos.network.request – so a skill in another process or
container hears it too (in Docker, where each OVOS service has its own file
system, install the package in each image; the bus is what they share).
Entries older than seven days are dropped when a service starts.
"""
import json
import os
import re
import sys
import threading
import time
from functools import lru_cache

__version__ = "0.1.0a1"

DEFAULT_FILE = "~/.local/state/emkay/network.jsonl"
BUS_MESSAGE = "ovos.network.request"
KEEP_DAYS = 7

#: OVOS' own processes, by the program's name: the log is on in these
OVOS_PROGRAMS = re.compile(r"^(ovos|mycroft|hivemind|neon)[-_]")

#: known services, by host: (pattern, kind, words) – the same as Emkay's
#: web/netlog.js; `kind` is a fixed id that ovos-skill-guardian translates
SERVICES = [
    (r"(^|\.)stt\.openvoiceos\.pt$|(^|\.)stt\.smartgic\.io$", "stt", "speech recognition (OpenVoiceOS server)"),
    (r"(^|\.)tts\.openvoiceos\.pt$|(^|\.)tts\.smartgic\.io$", "tts", "voice (OpenVoiceOS server)"),
    (r"nllb|translat", "translate", "translation (OpenVoiceOS server)"),
    (r"(^|\.)wikipedia\.org$|(^|\.)wikimedia\.org$|(^|\.)wikidata\.org$", "wikipedia", "Wikipedia"),
    (r"(^|\.)huggingface\.co$|(^|\.)hf\.co$|xethub", "models", "model downloads (Hugging Face)"),
    (r"(^|\.)store\.emkay\.ai$", "store", "Emkay skill store"),
    (r"(^|\.)pypi\.org$|(^|\.)pythonhosted\.org$", "packages", "package installs (PyPI)"),
    (r"(^|\.)githubusercontent\.com$|(^|\.)github\.com$", "github", "GitHub"),
    (r"(^|\.)open-meteo\.com$|weather", "weather", "weather"),
    (r"radio-browser|somafm|(^|\.)dr\.dk$|stream", "radio", "radio and news"),
]
_SERVICES = [(re.compile(p), k, w) for p, k, w in SERVICES]

#: hosts that are this machine: not "sent out"
LOCAL = re.compile(r"^(localhost|127\.|\[?::1\]?|0\.0\.0\.0)")

#: packages on the way to the network that are not the one asking
MACHINERY = {
    "requests", "urllib3", "httpx", "httpcore", "certifi", "charset_normalizer", "idna",
    "ovos_network_log", "ovos_utils", "ovos_bus_client", "ovos_workshop", "ovos_plugin_manager",
    "ovos_config", "ovos_core", "concurrent", "contextlib", "functools", "threading", "importlib",
}


def service(host: str):
    """(kind, words) for a host: a known service, or the host itself."""
    name = host.split(":")[0].lower()
    for pattern, kind, words in _SERVICES:
        if pattern.search(name):
            return kind, words
    return "other", host


@lru_cache(maxsize=None)
def _distribution(top: str) -> str:
    name = top
    try:
        from importlib.metadata import packages_distributions
        name = (packages_distributions().get(top) or [top])[0]
    except Exception:
        pass
    return re.sub(r"[-_.]+", "-", name).lower()


def caller(depth: int = 2) -> str:
    """The package making the current call (its pip name), or "ovos" for OVOS itself."""
    stdlib = getattr(sys, "stdlib_module_names", ())
    frame = sys._getframe(depth)
    while frame:
        top = (frame.f_globals.get("__name__") or "").split(".")[0]
        if top and top not in MACHINERY and top not in stdlib and top != "__main__":
            return _distribution(top)
        frame = frame.f_back
    return "ovos"


def log_file() -> str:
    return os.path.expanduser(os.environ.get("OVOS_NETWORK_LOG_FILE") or DEFAULT_FILE)


_lock = threading.Lock()


def write(entry: dict, path: str = None):
    """Append one entry to the log file (one short line: an append is atomic)."""
    path = path or log_file()
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    with _lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)


def prune(path: str = None, days: int = KEEP_DAYS):
    """Drop the entries older than `days` (when a service starts)."""
    path = path or log_file()
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return
    since = (time.time() - days * 86400) * 1000
    keep = []
    for line in lines:
        try:
            if json.loads(line).get("t", 0) >= since:
                keep.append(line)
        except ValueError:
            pass
    if len(keep) != len(lines):
        with _lock:
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(keep)
            os.replace(tmp, path)


# -- the bus -------------------------------------------------------------------

_queue = []
_wake = threading.Event()
_bus_thread = None


def _bus_sender():
    """Send queued entries on the messagebus from a thread of its own, so a
    request never waits for the bus. The bus client talks over a websocket,
    not http.client, so it is not logged itself."""
    client = None
    while True:
        _wake.wait(5)
        _wake.clear()
        if not _queue:
            continue
        try:
            if client is None:
                from ovos_bus_client import MessageBusClient
                client = MessageBusClient()
                client.run_in_thread()
                client.connected_event.wait(5)
            from ovos_bus_client.message import Message
            while _queue:
                client.emit(Message(BUS_MESSAGE, _queue.pop(0)))
        except Exception:
            time.sleep(10)          # no bus yet (still starting): later


def send_on_bus(entry: dict):
    global _bus_thread
    _queue.append(entry)
    del _queue[:-500]               # never more than this waiting
    if _bus_thread is None:
        _bus_thread = threading.Thread(target=_bus_sender, name="ovos-network-log", daemon=True)
        _bus_thread.start()
    _wake.set()


# -- the hook ------------------------------------------------------------------

def record(host: str, method: str, status: int, size, who: str):
    """Log one request; None for this machine's own addresses."""
    if not host or LOCAL.match(host):
        return None
    kind, words = service(host)
    entry = {"t": int(time.time() * 1000), "host": host, "method": method or "GET", "status": status,
             "bytes": size, "who": who, "kind": kind, "service": words}
    try:
        write(entry)
    except OSError:
        pass
    if os.environ.get("OVOS_NETWORK_LOG_BUS", "1") != "0":
        send_on_bus(entry)
    return entry


def install():
    """Wrap http.client so every request this process makes is logged. Once."""
    import http.client as hc
    if getattr(hc.HTTPConnection.getresponse, "_ovos_network_log", False):
        return
    plain_request, plain_getresponse = hc.HTTPConnection.request, hc.HTTPConnection.getresponse

    def _host(conn):
        default = 443 if isinstance(conn, getattr(hc, "HTTPSConnection", ())) else 80
        host = getattr(conn, "_tunnel_host", None) or conn.host
        port = getattr(conn, "_tunnel_port", None) or conn.port
        return host if not port or port == default else f"{host}:{port}"

    def request(self, method, url, *args, **kwargs):
        self._ovos_net = (method, caller(2))
        try:
            return plain_request(self, method, url, *args, **kwargs)
        except Exception:            # refused, offline, no name: it never got an answer
            record(_host(self), method, 0, None, self._ovos_net[1])
            raise

    def getresponse(self, *args, **kwargs):
        method, who = getattr(self, "_ovos_net", ("GET", "ovos"))
        try:
            resp = plain_getresponse(self, *args, **kwargs)
        except Exception:
            record(_host(self), method, 0, None, who)
            raise
        size = resp.getheader("Content-Length")
        record(_host(self), method, resp.status, int(size) if size and size.isdigit() else None, who)
        return resp

    getresponse._ovos_network_log = True
    hc.HTTPConnection.request = request
    hc.HTTPConnection.getresponse = getresponse


def wanted() -> bool:
    """Is this one of OVOS' own processes (or forced on/off)?"""
    forced = os.environ.get("OVOS_NETWORK_LOG")
    if forced in ("0", "1"):
        return forced == "1"
    program = os.path.basename(sys.argv[0] if sys.argv and sys.argv[0] else "")
    return bool(OVOS_PROGRAMS.match(program))
