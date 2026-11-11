"""Shared settings for the desk display."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = Path(os.environ["DESKBOARD_CONFIG"]) if os.environ.get("DESKBOARD_CONFIG") else ROOT / "config.json"
CONFIG_LOCK = CONFIG_PATH.with_name(CONFIG_PATH.name + ".lock")

PUBLIC_KEYS = (
    "mark",
    "timezone",
    "port",
    "night_dim",
    "night_start",
    "night_end",
    "theme",
    "max_widgets",
    "embed_allowlist",
    "bind_tailscale",
    "extra_bind",
    "grid_cols",
    "grid_rows",
    "enabled_community_tiles",
)
# enabled_community_tiles is read from config.json only. Community tiles run
# code in the board page, so turning one on takes an edit on the box and a restart.
EDITABLE_KEYS = (
    "mark",
    "timezone",
    "night_dim",
    "night_start",
    "night_end",
    "theme",
    "max_widgets",
    "embed_allowlist",
    "bind_tailscale",
    "extra_bind",
    "grid_cols",
    "grid_rows",
)

DEFAULTS = {
    "mark": "DESK",
    "timezone": "auto",
    "port": 8730,
    "night_dim": True,
    "night_start": 22,
    "night_end": 7,
    "theme": "warm-dark",
    "max_widgets": 16,
    "embed_allowlist": [],
    "bind_tailscale": False,
    "extra_bind": [],
    "grid_cols": 4,
    "grid_rows": 3,
    "enabled_community_tiles": [],
}



# Sentinel so detect_host_timezone can tell "use the process env" from "TZ is unset".
_TZ_ENV_UNSET = object()
_SKIP_ZONE_NAMES = {
    "auto",
    "localtime",
    "posixrules",
    "leapseconds",
    "iso3166.tab",
    "zone.tab",
    "zone1970.tab",
    "tzdata.zi",
    "leap-seconds.list",
}


def _valid_zone(name: str | None) -> str | None:
    if not isinstance(name, str):
        return None
    cleaned = name.strip().strip("/")
    if not cleaned or len(cleaned) > 64:
        return None
    if any(ch.isspace() or ch in "\\" for ch in cleaned) or ".." in cleaned:
        return None
    if cleaned.lower() in _SKIP_ZONE_NAMES:
        return None
    try:
        ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return None
    return cleaned


def _zone_from_zoneinfo_path(target: str) -> str | None:
    text = target.replace("\\", "/")
    marker = "/zoneinfo/"
    if marker not in text:
        return None
    return _valid_zone(text.split(marker, 1)[1])


def _zone_from_tz_value(value: str | None) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith(":"):
        text = text[1:].strip()
    if not text:
        return None
    normalized = text.replace("\\", "/")
    if normalized.startswith("/") or "/zoneinfo/" in normalized:
        return _zone_from_zoneinfo_path(normalized)
    return _valid_zone(text)


def _zone_from_timezone_file(path: Path) -> str | None:
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    if not raw:
        return None
    return _valid_zone(raw[0])


def _zone_from_localtime(path: Path) -> str | None:
    try:
        if not path.is_symlink():
            return None
        target = os.path.realpath(path)
    except OSError:
        return None
    return _zone_from_zoneinfo_path(target)


def _zone_from_timedatectl() -> str | None:
    try:
        result = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return _valid_zone((result.stdout or "").strip())


def detect_host_timezone(
    *,
    tz_env=_TZ_ENV_UNSET,
    timezone_path: Path | None = None,
    localtime_path: Path | None = None,
    run_timedatectl: bool = True,
) -> str:
    """Return the host IANA timezone, or UTC when it cannot be read."""
    env = os.environ.get("TZ") if tz_env is _TZ_ENV_UNSET else tz_env
    zone = _zone_from_tz_value(env)
    if zone:
        return zone

    zone_file = Path("/etc/timezone") if timezone_path is None else timezone_path
    zone = _zone_from_timezone_file(zone_file)
    if zone:
        return zone

    link = Path("/etc/localtime") if localtime_path is None else localtime_path
    zone = _zone_from_localtime(link)
    if zone:
        return zone

    if run_timedatectl:
        zone = _zone_from_timedatectl()
        if zone:
            return zone

    # On macOS, /etc/localtime is usually a symlink into
    # /var/db/timezone/zoneinfo. The localtime read above already covers
    # that path, so a second pass would not find a different name.
    if sys.platform == "darwin" and localtime_path is None:
        zone = _zone_from_localtime(Path("/etc/localtime"))
        if zone:
            return zone

    return "UTC"


def resolved_timezone(cfg: dict | None = None) -> str:
    """IANA zone the clock, calendar, and bot stamps should use."""
    settings = cfg if cfg is not None else load_config()
    name = settings.get("timezone")
    if not isinstance(name, str) or not name.strip() or name.strip().lower() == "auto":
        return detect_host_timezone()
    name = name.strip()
    valid = _valid_zone(name)
    if valid:
        return valid
    print(
        f"deskboard config: invalid timezone {name!r}, falling back to auto",
        file=sys.stderr,
    )
    return detect_host_timezone()


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    cfg["embed_allowlist"] = list(DEFAULTS["embed_allowlist"])
    cfg["extra_bind"] = list(DEFAULTS["extra_bind"])
    cfg["enabled_community_tiles"] = []
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except json.JSONDecodeError as exc:
        print(f"deskboard config: {exc}", file=sys.stderr)
        return cfg
    if not isinstance(data, dict):
        return cfg

    mark = data.get("mark")
    if isinstance(mark, str) and mark.strip():
        cfg["mark"] = mark.strip()[:24]

    timezone = data.get("timezone")
    if isinstance(timezone, str) and timezone.strip():
        cfg["timezone"] = timezone.strip()

    port = data.get("port")
    if isinstance(port, int) and not isinstance(port, bool) and 1 <= port <= 65535:
        cfg["port"] = port

    if isinstance(data.get("night_dim"), bool):
        cfg["night_dim"] = data["night_dim"]

    for key in ("night_start", "night_end"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 23:
            cfg[key] = value

    theme = data.get("theme")
    if isinstance(theme, str) and theme.strip():
        cfg["theme"] = theme.strip()[:48]

    max_widgets = data.get("max_widgets")
    if isinstance(max_widgets, int) and not isinstance(max_widgets, bool) and 1 <= max_widgets <= 48:
        cfg["max_widgets"] = max_widgets

    allow = data.get("embed_allowlist")
    if isinstance(allow, list) and all(isinstance(item, str) for item in allow):
        cfg["embed_allowlist"] = [item.strip()[:200] for item in allow if item.strip()][:64]

    if isinstance(data.get("bind_tailscale"), bool):
        cfg["bind_tailscale"] = data["bind_tailscale"]

    extra = data.get("extra_bind")
    if isinstance(extra, list):
        cleaned = []
        for item in extra:
            if isinstance(item, str) and item.strip() and item.strip() != "0.0.0.0":
                cleaned.append(item.strip()[:64])
        cfg["extra_bind"] = cleaned[:8]

    for key in ("grid_cols", "grid_rows"):
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 8:
            cfg[key] = value

    community = data.get("enabled_community_tiles")
    if isinstance(community, list):
        cfg["enabled_community_tiles"] = [
            item for item in community if isinstance(item, str) and re.match(r"^[a-z][a-z0-9_]{1,31}$", item)
        ][:32]

    return cfg


def public_config() -> dict:
    cfg = load_config()
    out = {key: cfg[key] for key in PUBLIC_KEYS}
    out["timezone_resolved"] = resolved_timezone(cfg)
    return out


def update_config(patch: dict) -> dict:
    if not isinstance(patch, dict) or not patch:
        raise ValueError("body must change at least one field")
    extra = sorted(set(patch) - set(EDITABLE_KEYS))
    if extra:
        raise ValueError("unknown fields: " + ", ".join(extra))

    def run():
        cfg = load_config()
        if "mark" in patch:
            cfg["mark"] = _mark(patch["mark"])
        if "timezone" in patch:
            cfg["timezone"] = _timezone(patch["timezone"])
        if "night_dim" in patch:
            if not isinstance(patch["night_dim"], bool):
                raise ValueError("night_dim must be true or false")
            cfg["night_dim"] = patch["night_dim"]
        for key in ("night_start", "night_end"):
            if key in patch:
                cfg[key] = _hour(patch[key], key)
        if "theme" in patch:
            cfg["theme"] = _theme(patch["theme"])
        if "max_widgets" in patch:
            cfg["max_widgets"] = _max_widgets(patch["max_widgets"])
        if "embed_allowlist" in patch:
            cfg["embed_allowlist"] = _allowlist(patch["embed_allowlist"])
        if "bind_tailscale" in patch:
            if not isinstance(patch["bind_tailscale"], bool):
                raise ValueError("bind_tailscale must be true or false")
            cfg["bind_tailscale"] = patch["bind_tailscale"]
        if "extra_bind" in patch:
            cfg["extra_bind"] = _extra_bind(patch["extra_bind"])
        for key in ("grid_cols", "grid_rows"):
            if key in patch:
                cfg[key] = _grid(patch[key], key)
        _write_config(cfg)
        out = {item: cfg[item] for item in PUBLIC_KEYS}
        out["timezone_resolved"] = resolved_timezone(cfg)
        return out

    return _locked(run)


def _mark(value) -> str:
    if not isinstance(value, str):
        raise ValueError("mark must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 24 or any(ord(char) < 32 for char in cleaned):
        raise ValueError("mark must be 1 to 24 visible characters")
    return cleaned


def _timezone(value) -> str:
    if not isinstance(value, str):
        raise ValueError("timezone must be auto or an IANA name, such as America/Toronto")
    name = value.strip()
    if name.lower() == "auto":
        return "auto"
    if not name or len(name) > 64 or any(char.isspace() for char in name):
        raise ValueError("timezone must be auto or an IANA name, such as America/Toronto")
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("timezone must be auto or an IANA name, such as America/Toronto") from exc
    return name


def _theme(value) -> str:
    if not isinstance(value, str):
        raise ValueError("theme must be a string")
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 48 or any(ord(char) < 32 for char in cleaned):
        raise ValueError("theme must be 1 to 48 visible characters")
    if any(ch in cleaned for ch in ("/", "\\", "..")):
        raise ValueError("theme name is invalid")
    return cleaned


def _max_widgets(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 48:
        raise ValueError("max_widgets must be an integer from 1 to 48")
    return value


def _allowlist(value) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("embed_allowlist must be a list of hostnames")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("embed_allowlist entries must be strings")
        cleaned = item.strip().lower()
        if not cleaned or len(cleaned) > 200 or any(ord(ch) < 32 for ch in cleaned):
            raise ValueError("embed_allowlist entry is invalid")
        if "://" in cleaned or "/" in cleaned or " " in cleaned:
            raise ValueError("embed_allowlist entries are hostnames only, like example.com")
        out.append(cleaned)
        if len(out) > 64:
            raise ValueError("embed_allowlist is limited to 64 hosts")
    return out


def _extra_bind(value) -> list[str]:
    if not isinstance(value, list):
        raise ValueError("extra_bind must be a list of addresses")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("extra_bind entries must be strings")
        cleaned = item.strip()
        if not cleaned or cleaned == "0.0.0.0" or cleaned == "::":
            raise ValueError("extra_bind cannot include 0.0.0.0 or ::")
        if len(cleaned) > 64 or any(ord(ch) < 32 for ch in cleaned):
            raise ValueError("extra_bind entry is invalid")
        out.append(cleaned)
        if len(out) > 8:
            raise ValueError("extra_bind is limited to 8 addresses")
    return out


def _grid(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8:
        raise ValueError(f"{field} must be an integer from 1 to 8")
    return value


def _hour(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 23:
        raise ValueError(f"{field} must be an hour from 0 to 23")
    return value


def _write_config(cfg: dict) -> None:
    temporary = CONFIG_PATH.with_suffix(".json.tmp")
    data = {key: cfg[key] for key in PUBLIC_KEYS}
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, CONFIG_PATH)


def _locked(fn):
    CONFIG_LOCK.touch(exist_ok=True)
    with CONFIG_LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
