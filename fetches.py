"""Server-side fetches for network-backed widgets.

Results are cached in memory. Failures return soft empty payloads so the
board keeps painting. Tokens never leave this module into widget JSON.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

USER_AGENT = "deskboard/1.0 (+https://github.com/deskboard/deskboard)"
_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(key: str, ttl: float):
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
    return None


def _set_cached(key: str, value: Any) -> Any:
    with _lock:
        _cache[key] = (time.time(), value)
    return value


def _http_get(url: str, headers: dict | None = None, timeout: float = 8.0) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def weather_payload(latitude: float, longitude: float, units: str = "metric") -> dict:
    key = f"weather:{latitude}:{longitude}:{units}"
    cached = _get_cached(key, 600)
    if cached is not None:
        return cached
    temp_unit = "fahrenheit" if units == "imperial" else "celsius"
    wind_unit = "mph" if units == "imperial" else "kmh"
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={latitude}&longitude={longitude}"
        f"&current=temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m"
        f"&daily=temperature_2m_max,temperature_2m_min"
        f"&temperature_unit={temp_unit}&wind_speed_unit={wind_unit}"
        "&timezone=auto&forecast_days=1"
    )
    try:
        raw = json.loads(_http_get(url).decode("utf-8"))
        current = raw.get("current") or {}
        daily = raw.get("daily") or {}
        payload = {
            "ok": True,
            "temperature": current.get("temperature_2m"),
            "weather_code": current.get("weather_code"),
            "wind": current.get("wind_speed_10m"),
            "humidity": current.get("relative_humidity_2m"),
            "high": (daily.get("temperature_2m_max") or [None])[0],
            "low": (daily.get("temperature_2m_min") or [None])[0],
            "units": units,
        }
    except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError):
        payload = {"ok": False}
    return _set_cached(key, payload)


def github_payload(repos: list[str]) -> dict:
    key = "github:" + ",".join(repos)
    cached = _get_cached(key, 300)
    if cached is not None:
        return cached
    token = os.environ.get("DESKBOARD_GITHUB_TOKEN", "").strip()
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    items = []
    for repo in repos:
        try:
            raw = json.loads(_http_get(f"https://api.github.com/repos/{repo}", headers=headers).decode("utf-8"))
            stars = int(raw.get("stargazers_count") or 0)
            history_key = f"github-hist:{repo}"
            with _lock:
                hist = _cache.get(history_key)
                series = list(hist[1]) if hist else []
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if not series or series[-1][0] != today:
                series.append([today, stars])
            else:
                series[-1][1] = stars
            series = series[-14:]
            _set_cached(history_key, series)
            week_ago = series[0][1] if series else stars
            day_ago = series[-2][1] if len(series) > 1 else stars
            items.append(
                {
                    "repo": repo,
                    "stars": stars,
                    "change_today": stars - day_ago,
                    "change_week": stars - week_ago,
                    "sparkline": [point[1] for point in series],
                }
            )
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError, TypeError):
            items.append({"repo": repo, "ok": False})
    return _set_cached(key, {"ok": True, "repos": items})


def rss_payload(url: str, limit: int = 6) -> dict:
    key = f"rss:{url}:{limit}"
    cached = _get_cached(key, 600)
    if cached is not None:
        return cached
    try:
        raw = _http_get(url)
        root = ET.fromstring(raw)
        items = []
        for node in root.iter():
            tag = node.tag.split("}")[-1].lower()
            if tag == "item":
                title = ""
                for child in node:
                    ctag = child.tag.split("}")[-1].lower()
                    if ctag == "title" and child.text:
                        title = re.sub(r"\s+", " ", child.text).strip()
                        break
                if title:
                    items.append(title[:120])
            elif tag == "entry":
                title = ""
                for child in node:
                    ctag = child.tag.split("}")[-1].lower()
                    if ctag == "title" and (child.text or "").strip():
                        title = re.sub(r"\s+", " ", child.text).strip()
                        break
                if title:
                    items.append(title[:120])
            if len(items) >= limit:
                break
        payload = {"ok": True, "items": items[:limit]}
    except (OSError, urllib.error.URLError, TimeoutError, ET.ParseError):
        payload = {"ok": False, "items": []}
    return _set_cached(key, payload)


def calendar_payload(url: str, limit: int = 5, board_tz: str = "UTC") -> dict:
    key = f"cal:{url}:{limit}:{board_tz}"
    cached = _get_cached(key, 300)
    if cached is not None:
        return cached
    try:
        text = _http_get(url, timeout=10.0).decode("utf-8", errors="replace")
        items = _parse_ics_upcoming(text, limit=limit, board_tz=board_tz)
        payload = {"ok": True, "items": items}
    except (OSError, urllib.error.URLError, TimeoutError, UnicodeError):
        payload = {"ok": False, "items": []}
    return _set_cached(key, payload)


def status_payload(targets: list[dict]) -> dict:
    key = "status:" + ",".join(t["url"] for t in targets)
    cached = _get_cached(key, 30)
    if cached is not None:
        return cached
    results = []
    for target in targets:
        url = target["url"]
        label = target["label"]
        started = time.monotonic()
        ok = False
        code = 0
        try:
            req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                code = getattr(resp, "status", 200) or 200
                ok = 200 <= int(code) < 400
        except Exception:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    code = getattr(resp, "status", 200) or 200
                    ok = 200 <= int(code) < 400
            except Exception:
                ok = False
                code = 0
        ms = int((time.monotonic() - started) * 1000)
        results.append({"label": label, "url": url, "ok": ok, "ms": ms, "code": code})
    return _set_cached(key, {"ok": True, "targets": results})


def _parse_ics_upcoming(text: str, limit: int, board_tz: str) -> list[str]:
    # Lightweight ICS reader for VEVENT summaries in the next 14 days.
    unfolded = text.replace("\r\n", "\n").replace("\r", "\n")
    unfolded = re.sub(r"\n[ \t]", "", unfolded)
    events = []
    cur = None
    for line in unfolded.split("\n"):
        if line == "BEGIN:VEVENT":
            cur = {}
            continue
        if line == "END:VEVENT":
            if cur and "DTSTART" in cur and "SUMMARY" in cur:
                events.append(cur)
            cur = None
            continue
        if cur is None or ":" not in line:
            continue
        left, value = line.split(":", 1)
        prop = left.split(";", 1)[0].upper()
        if prop == "DTSTART":
            cur["DTSTART"] = value
        elif prop == "SUMMARY":
            cur["SUMMARY"] = value.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";").strip()
        elif prop == "STATUS":
            cur["STATUS"] = value.upper()
    now = datetime.now(timezone.utc)
    horizon = now.timestamp() + 14 * 86400
    items = []
    for ev in events:
        if ev.get("STATUS") == "CANCELLED":
            continue
        stamp = _ics_to_epoch(ev["DTSTART"])
        if stamp is None or stamp > horizon or stamp + 86400 < now.timestamp():
            continue
        when = datetime.fromtimestamp(stamp, tz=timezone.utc).strftime("%a %H:%M")
        items.append(f"{when}  {ev['SUMMARY'][:60]}")
    items.sort()
    if not items:
        return ["Nothing on the calendar"]
    return items[:limit]


def _ics_to_epoch(value: str) -> float | None:
    m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(\d{2})?(Z)?)?$", value)
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    hh = int(m.group(4) or 0)
    mm = int(m.group(5) or 0)
    ss = int(m.group(6) or 0)
    if m.group(7):
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
    else:
        dt = datetime(y, mo, d, hh, mm, ss, tzinfo=timezone.utc)
    return dt.timestamp()


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower()
