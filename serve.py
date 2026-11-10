#!/usr/bin/env python3
"""Desk page and widget API.

Always listens on loopback. Optional Tailscale and extra_bind addresses
come from config. LAN and public catch-all binds are never used.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from deskboard_config import load_config, public_config, update_config
from fetches import (
    calendar_payload,
    github_payload,
    rss_payload,
    status_payload,
    weather_payload,
)
from widgets import (
    ID_RE,
    SINGLETONS,
    WidgetError,
    catalog,
    create_widget,
    delete_widget,
    get_widget,
    list_widgets,
    max_widgets,
    reload_catalog,
    reload_summary,
    reorder_widgets,
    replace_widgets,
    types,
    update_widget,
)

WEB = Path(__file__).resolve().parent / "web"
TAILSCALE_V4 = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE_V6 = ipaddress.ip_network("fd7a:115c:a1e0::/48")
MAX_BODY = 65536
TYPES_BY_EXT = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}


def _parse_ip(value: str):
    host = value.split("%", 1)[0].strip().strip("[]")
    return ipaddress.ip_address(host)


def is_tailscale_addr(address) -> bool:
    if address.version == 4:
        return address in TAILSCALE_V4
    return address in TAILSCALE_V6


def ip_allowed(value: str) -> bool:
    try:
        address = _parse_ip(value)
    except ValueError:
        return False
    if address.is_loopback:
        return True
    cfg = load_config()
    if cfg.get("bind_tailscale") and is_tailscale_addr(address):
        return True
    for item in cfg.get("extra_bind") or []:
        try:
            if address == _parse_ip(item):
                return True
        except ValueError:
            continue
    return False


def tailscale_addrs() -> list[str]:
    try:
        result = subprocess.run(
            ["tailscale", "ip"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    found = []
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        try:
            address = _parse_ip(candidate)
        except ValueError:
            continue
        if address.is_loopback or not is_tailscale_addr(address):
            continue
        found.append(candidate)
    return found


def bind_hosts() -> list[str]:
    hosts = ["127.0.0.1", "::1"]
    cfg = load_config()
    if cfg.get("bind_tailscale"):
        for host in tailscale_addrs():
            if host not in hosts:
                hosts.append(host)
    for item in cfg.get("extra_bind") or []:
        candidate = item.strip()
        if not candidate or candidate in ("0.0.0.0", "::"):
            continue
        if candidate not in hosts:
            hosts.append(candidate)
    return hosts


def status() -> dict:
    try:
        mem_total, mem_available = _read_mem()
    except (OSError, KeyError, ValueError, IndexError):
        mem_total, mem_available = 0, 0
    try:
        load1 = float(Path("/proc/loadavg").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        load1 = 0.0
    try:
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (OSError, ValueError, IndexError):
        uptime = 0.0
    cfg = load_config()
    return {
        "mark": cfg["mark"],
        "timezone": cfg["timezone"],
        "night_dim": cfg["night_dim"],
        "night_start": cfg["night_start"],
        "night_end": cfg["night_end"],
        "theme": cfg["theme"],
        "hostname": os.environ.get("DESKBOARD_HOSTNAME") or os.uname().nodename,
        "uptime_sec": uptime,
        "load1": load1,
        "mem_total": mem_total,
        "mem_available": mem_available,
        "temp_c": _read_temp(),
        "tiles_version": catalog().version,
    }


def _read_mem() -> tuple[int, int]:
    info = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        key, _, rest = line.partition(":")
        info[key] = int(rest.split()[0])
    return info["MemTotal"] * 1024, info["MemAvailable"] * 1024


def _read_temp() -> float | None:
    base = Path("/sys/class/thermal")
    for zone in sorted(base.glob("thermal_zone*")):
        try:
            if (zone / "type").read_text(encoding="utf-8").strip() == "x86_pkg_temp":
                return int((zone / "temp").read_text(encoding="utf-8")) / 1000
        except OSError:
            continue
    return None


def list_themes() -> dict:
    themes_dir = WEB / "themes"
    themes = []
    if themes_dir.is_dir():
        for path in sorted(themes_dir.iterdir()):
            if not path.is_dir() or path.name.startswith(".") or path.name == "presets":
                continue
            entry = {"id": path.name}
            manifest = path / "theme.json"
            if manifest.is_file():
                try:
                    data = json.loads(manifest.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = None
                if isinstance(data, dict):
                    for key in ("name", "label", "description", "fonts", "images"):
                        if key in data:
                            entry[key] = data[key]
            css = path / "theme.css"
            entry["has_css"] = css.is_file()
            themes.append(entry)
    return {"themes": themes, "current": load_config().get("theme")}


def widget_live_data(widget: dict) -> dict:
    widget_type = widget["type"]
    if widget_type == "weather":
        return weather_payload(widget["latitude"], widget["longitude"], widget.get("units", "metric"))
    if widget_type == "github":
        return github_payload(list(widget.get("repos") or []))
    if widget_type == "rss":
        return rss_payload(widget["url"], int(widget.get("limit") or 6))
    if widget_type == "calendar":
        return calendar_payload(widget["url"], int(widget.get("limit") or 5), load_config()["timezone"])
    if widget_type == "status":
        return status_payload(list(widget.get("targets") or []))
    raise WidgetError(f"{widget_type} has no live data endpoint", 404)


def bulk_github() -> dict:
    repos = []
    seen = set()
    for widget in list_widgets():
        if widget.get("type") != "github":
            continue
        for repo in widget.get("repos") or []:
            if repo not in seen:
                seen.add(repo)
                repos.append(repo)
    if not repos:
        return {"ok": True, "repos": []}
    return github_payload(repos)


def api_index() -> dict:
    return {
        "service": "deskboard",
        "widgets": {
            "types": list(types()),
            "limit": max_widgets(),
            "singleton": sorted(SINGLETONS),
        },
        "routes": [
            "GET /api/widgets",
            "POST /api/widgets",
            "GET /api/widgets/{id}",
            "PATCH /api/widgets/{id}",
            "DELETE /api/widgets/{id}",
            "PUT /api/widgets/order",
            "PUT /api/widgets/import",
            "GET /api/config",
            "PATCH /api/config",
            "GET /api/status",
            "GET /api/themes",
            "GET /api/tiles",
            "POST /api/reload",
            "GET /api/widget-data/{id}",
            "GET /api/github",
        ],
    }


def list_tiles() -> dict:
    current = catalog()
    return {"version": current.version, "tiles": current.meta()}


def reload_tiles(data: dict) -> dict:
    if data:
        raise WidgetError("body must be {}")
    found = reload_catalog()
    for problem in found.problems:
        print(f"deskboard tiles: {problem}", flush=True)
    print(f"deskboard tiles reloaded (v{found.version}): {', '.join(found.ids()) or 'none'}", flush=True)
    return reload_summary(found)


def tile_asset(url_path: str) -> tuple[bytes, str] | None:
    """/tiles/<id>/render.js or /tiles/<id>/tile.css for an enabled tile,
    as checked when the catalog was last loaded."""
    parts = url_path.strip("/").split("/")
    if len(parts) != 3 or parts[0] != "tiles":
        return None
    tile = catalog().get(parts[1])
    if tile is None:
        return None
    if parts[2] == "render.js":
        return tile.render_js, TYPES_BY_EXT[".js"]
    if parts[2] == "tile.css" and tile.tile_css is not None:
        return tile.tile_css, TYPES_BY_EXT[".css"]
    return None


def clean_path(raw: str) -> str | None:
    path = unquote(urlparse(raw).path)
    if not path.startswith("/"):
        return None
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            return None
        parts.append(part)
    return "/" + "/".join(parts)


def safe_file(url_path: str) -> Path | None:
    rel = url_path.lstrip("/")
    if not rel:
        rel = "index.html"
    candidate = (WEB / rel).resolve()
    try:
        candidate.relative_to(WEB.resolve())
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


class Handler(BaseHTTPRequestHandler):
    server_version = "deskboard"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self._dispatch("GET", head=False)

    def do_HEAD(self) -> None:
        self._dispatch("GET", head=True)

    def do_POST(self) -> None:
        self._dispatch("POST", head=False)

    def do_PATCH(self) -> None:
        self._dispatch("PATCH", head=False)

    def do_PUT(self) -> None:
        self._dispatch("PUT", head=False)

    def do_DELETE(self) -> None:
        self._dispatch("DELETE", head=False)

    def do_OPTIONS(self) -> None:
        self._error(405, "method not allowed")

    def _dispatch(self, method: str, head: bool) -> None:
        if not ip_allowed(self.client_address[0]):
            self._error(403, "forbidden")
            return
        path = clean_path(self.path)
        if path is None:
            self._error(400, "bad path")
            return
        try:
            self._handle(method, path, head)
        except WidgetError as exc:
            self._error(exc.status, str(exc))
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:
            print(f"deskboard error: {exc}", flush=True)
            self._error(500, "internal error")

    def _handle(self, method: str, path: str, head: bool) -> None:
        if path == "/api" and method == "GET":
            self._json(200, api_index(), head=head)
            return
        if path == "/api/status" and method == "GET":
            self._json(200, status(), head=head)
            return
        if path == "/api/config" and method == "GET":
            self._json(200, public_config(), head=head)
            return
        if path == "/api/config" and method == "PATCH":
            self._mutate(method, path, lambda data: update_config(data))
            return
        if path == "/api/themes" and method == "GET":
            self._json(200, list_themes(), head=head)
            return
        if path == "/api/tiles" and method == "GET":
            self._json(200, list_tiles(), head=head)
            return
        if path == "/api/reload" and method == "POST":
            self._mutate(method, path, reload_tiles)
            return
        if path == "/api/github" and method == "GET":
            self._json(200, bulk_github(), head=head)
            return
        if path == "/api/widgets" and method == "GET":
            self._json(200, {"widgets": list_widgets()}, head=head)
            return
        if path == "/api/widgets" and method == "POST":
            self._mutate(method, path, create_widget, created=True)
            return
        if path == "/api/widgets/order" and method == "PUT":
            def reorder(data):
                if set(data) != {"ids"}:
                    raise WidgetError('body must be {"ids": [...]}')
                return {"widgets": reorder_widgets(data["ids"])}

            self._mutate(method, path, reorder)
            return
        if path == "/api/widgets/import" and method == "PUT":
            def import_layout(data):
                if "widgets" not in data or set(data) - {"widgets"}:
                    raise WidgetError('body must be {"widgets": [...]}')
                return {"widgets": replace_widgets(data["widgets"])}

            self._mutate(method, path, import_layout)
            return
        if path.startswith("/api/widget-data/"):
            widget_id = path.removeprefix("/api/widget-data/")
            if "/" in widget_id or not ID_RE.match(widget_id):
                self._error(404, "widget not found")
                return
            if method != "GET":
                self._error(405, "method not allowed")
                return
            self._json(200, widget_live_data(get_widget(widget_id)), head=head)
            return
        if path.startswith("/api/widgets/"):
            widget_id = path.removeprefix("/api/widgets/")
            if "/" in widget_id or not ID_RE.match(widget_id):
                self._error(404, "widget not found")
                return
            if method == "GET":
                self._json(200, get_widget(widget_id), head=head)
                return
            if method == "PATCH":
                self._mutate(method, path, lambda data: update_widget(widget_id, data))
                return
            if method == "DELETE":
                delete_widget(widget_id)
                self._empty(204)
                self._access(method, path, 204)
                return
            self._error(405, "method not allowed")
            return
        if path.startswith("/api"):
            if method != "GET":
                self._error(405, "method not allowed")
            else:
                self._error(404, "not found")
            return
        if method != "GET":
            self._error(405, "method not allowed")
            return
        if path.startswith("/tiles/"):
            asset = tile_asset(path)
            if asset is None:
                self._send(404, "text/plain; charset=utf-8", b"not found\n", head, cache=False)
            else:
                self._send(200, asset[1], asset[0], head, cache=False)
            return
        if path in ("/", "/config"):
            file_path = safe_file("/index.html")
        else:
            file_path = safe_file(path)
        if file_path is None:
            self._send(404, "text/plain; charset=utf-8", b"not found\n", head, cache=False)
            return
        cache = file_path.suffix in (".woff2", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg")
        content_type = TYPES_BY_EXT.get(file_path.suffix, "application/octet-stream")
        self._send(200, content_type, file_path.read_bytes(), head, cache)

    def _mutate(self, method: str, path: str, fn, created: bool = False) -> None:
        data, error, code = self._body()
        if error:
            self._error(code, error)
            return
        payload = fn(data)
        if created:
            self._json(201, payload, location=f"/api/widgets/{payload['id']}")
            self._access(method, path, 201)
            return
        self._json(200, payload)
        self._access(method, path, 200)

    def _body(self) -> tuple[dict | None, str | None, int]:
        raw_length = self.headers.get("Content-Length", "")
        try:
            length = int(raw_length) if raw_length else 0
        except ValueError:
            return None, "invalid content length", 400
        if length < 0 or length > MAX_BODY:
            return None, "body is limited to 64KB", 413
        mime = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if mime != "application/json":
            return None, "content type must be application/json", 415
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None, "body must be JSON", 400
        if not isinstance(data, dict):
            return None, "body must be a JSON object", 400
        return data, None, 0

    def _json(self, code: int, payload, head: bool = False, location: str | None = None) -> None:
        body = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if location:
            self.send_header("Location", location)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _empty(self, code: int) -> None:
        self.send_response(code)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _error(self, code: int, message: str) -> None:
        self._access(self.command, urlparse(self.path).path, code)
        self._json(code, {"error": message})

    def _send(self, code: int, content_type: str, body: bytes, head: bool, cache: bool) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=31536000, immutable")
        else:
            self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if content_type.startswith("text/html"):
            # Page scripts, tile render code included, may only call this server.
            self.send_header("Content-Security-Policy", "connect-src 'self'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _access(self, method: str, path: str, code: int) -> None:
        if method == "GET" and code < 400:
            return
        peer = self.client_address[0]
        print(f"deskboard {peer} {method} {path} {code}", flush=True)


class Server4(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET


class Server6(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = socket.AF_INET6

    def server_bind(self) -> None:
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
        super().server_bind()


def listen(host: str, port: int) -> ThreadingHTTPServer:
    family = ipaddress.ip_address(host.split("%", 1)[0].strip("[]"))
    server_cls = Server6 if family.version == 6 else Server4
    server = server_cls((host, port), Handler)
    threading.Thread(target=server.serve_forever, name=f"deskboard-{host}", daemon=True).start()
    return server


def ensure_bound(port: int, bound: dict, lock: threading.Lock) -> None:
    hosts = bind_hosts()
    with lock:
        for host in hosts:
            if host in bound:
                continue
            try:
                bound[host] = listen(host, port)
            except OSError as exc:
                print(f"deskboard: {host}:{port} unavailable ({exc})", flush=True)
                continue
            shown = f"[{host}]" if ":" in host else host
            print(f"deskboard listening on http://{shown}:{port}", flush=True)


def main() -> None:
    port = load_config()["port"]
    found = reload_catalog()
    for problem in found.problems:
        print(f"deskboard tiles: {problem}", flush=True)
    print(f"deskboard tiles: {', '.join(found.ids()) or 'none'}", flush=True)
    bound: dict = {}
    lock = threading.Lock()
    ensure_bound(port, bound, lock)
    if "127.0.0.1" not in bound:
        raise SystemExit("deskboard could not listen on 127.0.0.1")

    def refresh() -> None:
        while True:
            time.sleep(15)
            ensure_bound(port, bound, lock)

    threading.Thread(target=refresh, name="deskboard-bind", daemon=True).start()
    threading.Event().wait()


if __name__ == "__main__":
    main()
