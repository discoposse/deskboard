"""Stored widgets for the desk display.

The HTTP layer decides who may call these functions. This module checks
the document shape and writes widgets.json atomically.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tiles
from deskboard_config import ROOT, load_config

PATH = Path(os.environ["DESKBOARD_WIDGETS"]) if os.environ.get("DESKBOARD_WIDGETS") else ROOT / "widgets.json"
LOCK = PATH.with_name(PATH.name + ".lock")
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
RESERVED_IDS = {"order"}
DEFAULT_MAX_WIDGETS = 16
STAT_FIELDS = ("temp", "load", "free", "up")
SPAN_VALUES = (1, 2)

# Widget types handled in this file. Tile folders under tiles/ add more
# (see tiles.py). metric lives in tiles/metric as the reference tile.
BUILTIN_TYPES = (
    "clock",
    "worldclocks",
    "stats",
    "note",
    "markdown",
    "list",
    "weather",
    "countdown",
    "calendar",
    "github",
    "embed",
    "rss",
    "image",
    "timer",
    "status",
    "theme_card",
)
SINGLETONS = {"clock", "stats", "worldclocks"}
TYPE_FIELDS = {
    "clock": {"style", "show_seconds", "show_date"},
    "worldclocks": {"cities", "style", "mark_markets"},
    "stats": {"fields"},
    "note": {"title", "text"},
    "markdown": {"title", "text"},
    "list": {"title", "items", "max_items"},
    "weather": {"latitude", "longitude", "label", "units"},
    "countdown": {"title", "target", "label"},
    "calendar": {"title", "url", "limit"},
    "github": {"repos", "title"},
    "embed": {"url", "title", "refresh_sec"},
    "rss": {"url", "title", "limit"},
    "image": {"src", "title", "fit"},
    "timer": {"title", "minutes", "mode"},
    "status": {"title", "targets"},
    "theme_card": {"image", "caption"},
}
COMMON_FIELDS = {"id", "type", "enabled", "order", "col_span", "row_span", "managed_by"}
# Fields that place a tile on the board. Everything else is content.
LAYOUT_FIELDS = {"id", "type", "enabled", "order", "col_span", "row_span", "managed_by"}
MANAGED_RE = re.compile(r"^[a-z][a-z0-9_-]{0,23}$")
POST_DEFAULT_ITEMS = 6
POST_SOURCE_MAX = 24
POST_LINE_MAX = 80
OUTPUT_KEYS = (
    "id",
    "type",
    "enabled",
    "order",
    "col_span",
    "row_span",
    "managed_by",
    "title",
    "text",
    "label",
    "value",
    "hint",
    "trend",
    "items",
    "max_items",
    "fields",
    "style",
    "show_seconds",
    "show_date",
    "cities",
    "mark_markets",
    "latitude",
    "longitude",
    "units",
    "target",
    "url",
    "limit",
    "repos",
    "refresh_sec",
    "src",
    "fit",
    "minutes",
    "mode",
    "targets",
    "image",
    "caption",
)

DEFAULT_WIDGETS = [
    {"id": "clock", "type": "clock", "enabled": True, "order": 0, "style": "digital", "show_seconds": True, "show_date": True},
    {
        "id": "stats",
        "type": "stats",
        "enabled": True,
        "order": 10,
        "fields": ["temp", "load", "free", "up"],
    },
]


# Where catalog types sit in GET /api and error messages, so the list reads
# the same as it did before metric moved into tiles/.
TYPE_ORDER = BUILTIN_TYPES[:5] + ("metric",) + BUILTIN_TYPES[5:]

_catalog: tiles.Catalog | None = None
_catalog_version = 0


class WidgetError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class StaleRevision(WidgetError):
    """The caller loaded the layout before someone else changed it."""

    def __init__(self, base: int, current: int):
        super().__init__(
            f"the board changed since you loaded it (you had revision {base}, it is now {current}). Reload and apply again.",
            409,
        )
        self.base = base
        self.current = current


def _check_base(base, meta: dict) -> None:
    """base_revision is optional. When given it must match layout_revision,
    which moves on every write except a bot filling a managed tile."""
    if base is None:
        return
    if isinstance(base, bool) or not isinstance(base, int) or base < 0:
        raise WidgetError("base_revision must be a non-negative integer")
    if base != meta["layout_revision"]:
        raise StaleRevision(base, meta["layout_revision"])


def revision() -> dict:
    """Current {"revision", "layout_revision"} without changing anything."""
    return _transaction(lambda: _read()[2])


def catalog() -> tiles.Catalog:
    """Tile catalog, read once. serve.py loads it at startup."""
    global _catalog
    if _catalog is None:
        reload_catalog()
    return _catalog


def reload_catalog() -> tiles.Catalog:
    """Rescan tiles/ and swap in the new catalog. Also rereads
    enabled_community_tiles from config.json. Each load bumps the version
    the board uses to fetch fresh render.js and tile.css."""
    global _catalog, _catalog_version
    enabled = load_config().get("enabled_community_tiles") or []
    fresh = tiles.discover(enabled_community=enabled, reserved=BUILTIN_TYPES)
    # A tile that was loaded and now fails its checks keeps its last good
    # version, so one bad edit does not take its tiles off the board.
    if _catalog is not None:
        for tile_id, old in _catalog.tiles.items():
            if tile_id in fresh.tiles or tile_id in fresh.disabled or not old.path.is_dir():
                continue
            if old.source != "core" and tile_id not in enabled:
                continue
            fresh.tiles[tile_id] = old
            fresh.problems.append(f"{tile_id}: kept the last good version until the folder passes again")
    _catalog_version += 1
    fresh.version = _catalog_version
    _catalog = fresh
    return _catalog


def _short(problem: str) -> str:
    """Show tile folders as tiles/<id> so the API never prints server paths."""
    root = str(tiles.tiles_dir())
    return "tiles" + problem[len(root):] if problem.startswith(root) else problem


def reload_summary(found: tiles.Catalog) -> dict:
    return {
        "ok": not found.problems,
        "version": found.version,
        "loaded": [{"id": t.id, "source": t.source} for t in found.tiles.values()],
        "disabled": sorted(found.disabled),
        "skipped": [_short(p) for p in found.problems],
    }


def types() -> tuple:
    extra = catalog().ids()
    ordered = [t for t in TYPE_ORDER if t in BUILTIN_TYPES or t in extra]
    ordered.extend(t for t in extra if t not in ordered)
    return tuple(ordered)


def _fields_for(widget_type: str) -> set:
    tile = catalog().get(widget_type)
    if tile is not None:
        return set(tile.fields)
    return TYPE_FIELDS[widget_type]


def _require_type(widget_type) -> None:
    if widget_type not in BUILTIN_TYPES and catalog().get(widget_type) is None:
        raise WidgetError("type must be one of: " + ", ".join(types()))


def max_widgets() -> int:
    return int(load_config().get("max_widgets") or DEFAULT_MAX_WIDGETS)


def list_widgets() -> list[dict]:
    return list_widgets_with_revision()[0]


def list_widgets_with_revision() -> tuple[list[dict], dict]:
    def run():
        widgets, dirty, meta = _read()
        widgets.sort(key=_sort_key)
        if dirty:
            meta = _save(widgets, meta)
        return widgets, meta

    return _transaction(run)


def get_widget(widget_id: str) -> dict:
    for widget in list_widgets():
        if widget["id"] == widget_id:
            return widget
    raise WidgetError("widget not found", 404)


def create_widget(data: dict, base_revision=None) -> dict:
    if not isinstance(data, dict):
        raise WidgetError("body must be an object")
    widget_type = data.get("type")
    _require_type(widget_type)
    _reject_unknown(data, _fields_for(widget_type) | COMMON_FIELDS)

    def run():
        widgets, _dirty, meta = _read()
        _check_base(base_revision, meta)
        limit = max_widgets()
        if len(widgets) >= limit:
            raise WidgetError(f"a screen holds up to {limit} widgets", 409)
        if widget_type in SINGLETONS and any(item["type"] == widget_type for item in widgets):
            raise WidgetError(f"{widget_type} already exists", 409)
        widget_id = _choose_id(data.get("id"), widgets)
        order = _order_value(data.get("order"), widgets)
        widget = _build(widget_type, data, widget_id, order, previous=None)
        widgets.append(widget)
        widgets.sort(key=_sort_key)
        _save(widgets, meta)
        return widget

    return _transaction(run)


def update_widget(widget_id: str, data: dict, base_revision=None) -> dict:
    if not isinstance(data, dict):
        raise WidgetError("body must be an object")
    if not data:
        raise WidgetError("body must change at least one field")

    def run():
        widgets, _dirty, meta = _read()
        _check_base(base_revision, meta)
        current = next((item for item in widgets if item["id"] == widget_id), None)
        if current is None:
            raise WidgetError("widget not found", 404)
        _reject_unknown(data, _fields_for(current["type"]) | {"enabled", "order", "col_span", "row_span", "managed_by"})
        order = current["order"] if "order" not in data else _require_order(data["order"])
        widget = _build(current["type"], data, widget_id, order, previous=current)
        widgets = [widget if item["id"] == widget_id else item for item in widgets]
        widgets.sort(key=_sort_key)
        # A bot refreshing the content of its own managed tile does not make
        # an open configurator stale. Its Apply keeps managed content anyway.
        content_only = bool(current.get("managed_by")) and not (set(data) & LAYOUT_FIELDS)
        _save(widgets, meta, layout=not content_only)
        return widget

    return _transaction(run)


def delete_widget(widget_id: str, base_revision=None) -> None:
    def run():
        widgets, _dirty, meta = _read()
        _check_base(base_revision, meta)
        if not any(item["id"] == widget_id for item in widgets):
            raise WidgetError("widget not found", 404)
        _save([item for item in widgets if item["id"] != widget_id], meta)

    _transaction(run)


def reorder_widgets(ids: list, base_revision=None) -> list[dict]:
    if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
        raise WidgetError("ids must be a list of widget ids")

    def run():
        widgets, _dirty, meta = _read()
        _check_base(base_revision, meta)
        current = sorted(widgets, key=_sort_key)
        current_ids = [item["id"] for item in current]
        if len(ids) != len(set(ids)) or sorted(ids) != sorted(current_ids):
            raise WidgetError("ids must list every widget once")
        by_id = {item["id"]: item for item in current}
        ordered = []
        for index, widget_id in enumerate(ids):
            widget = dict(by_id[widget_id])
            widget["order"] = index * 10
            ordered.append(_present(widget))
        _save(ordered, meta)
        return ordered

    return _transaction(run)


def replace_widgets(docs: list, base_revision=None, keep_managed: bool = False) -> list[dict]:
    """Replace the whole layout. With keep_managed, a tile that is managed on
    the server keeps its stored content and managed_by, and only its layout
    (order, spans, enabled) comes from the request. The configurator sends
    keep_managed so it never writes over what a bot posted."""
    if not isinstance(docs, list):
        raise WidgetError("widgets must be a list")
    limit = max_widgets()
    if len(docs) > limit:
        raise WidgetError(f"a screen holds up to {limit} widgets", 409)

    def run():
        stored, _dirty, meta = _read()
        _check_base(base_revision, meta)
        managed = {w["id"]: w for w in stored if w.get("managed_by")} if keep_managed else {}
        built = []
        seen = set()
        for index, item in enumerate(docs):
            if not isinstance(item, dict):
                raise WidgetError("each widget must be an object")
            widget_type = item.get("type")
            _require_type(widget_type)
            _reject_unknown(item, _fields_for(widget_type) | COMMON_FIELDS)
            widget_id = item.get("id")
            if not isinstance(widget_id, str) or widget_id in RESERVED_IDS or not ID_RE.match(widget_id):
                raise WidgetError("id must be a short lowercase name")
            if widget_id in seen:
                raise WidgetError(f"duplicate id {widget_id}", 409)
            seen.add(widget_id)
            if widget_type in SINGLETONS and any(w["type"] == widget_type for w in built):
                raise WidgetError(f"{widget_type} already exists", 409)
            order = item.get("order")
            if order is None:
                order = index * 10
            owner = managed.get(widget_id)
            if owner is not None and owner["type"] == widget_type:
                layout = {key: item[key] for key in ("enabled", "col_span", "row_span") if key in item}
                built.append(_build(widget_type, layout, widget_id, _require_order(order), previous=owner))
                continue
            built.append(_build(widget_type, item, widget_id, _require_order(order), previous=None))
        built.sort(key=_sort_key)
        _save(built, meta)
        return built

    return _transaction(run)


def post_line(widget_id: str, data: dict) -> dict:
    """Prepend "H:MM AM  Source  text" to a list tile and keep the newest
    max_items lines. Never creates a widget. A missing or hidden tile is 404."""
    if not isinstance(data, dict):
        raise WidgetError("body must be an object")
    _reject_unknown(data, {"source", "text"})
    source = data.get("source")
    text = data.get("text")
    if not isinstance(source, str) or not isinstance(text, str):
        raise WidgetError('body must be {"source": "...", "text": "..."}')
    if _has_control(source) or _has_control(text) or "\n" in source or "\n" in text or "\x7f" in source + text:
        raise WidgetError("source and text must be one plain line")
    source = " ".join(source.split())
    text = " ".join(text.split())
    if not source or not text:
        raise WidgetError("source and text must not be empty")
    if len(source) > POST_SOURCE_MAX:
        source = source[: POST_SOURCE_MAX - 1].rstrip() + "…"

    def run():
        widgets, _dirty, meta = _read()
        current = next((item for item in widgets if item["id"] == widget_id), None)
        if current is None or not current["enabled"]:
            raise WidgetError("widget not found", 404)
        if current["type"] != "list":
            raise WidgetError("only list tiles take posts", 409)
        stamp = _clock_stamp()
        head = f"{stamp}  {source}  "
        room = POST_LINE_MAX - len(head)
        body = text if len(text) <= room else text[: max(room - 1, 1)].rstrip() + "…"
        keep = current.get("max_items", POST_DEFAULT_ITEMS)
        items = ([head + body] + list(current["items"]))[:keep]
        widget = _build("list", {"items": items}, widget_id, current["order"], previous=current)
        widgets = [widget if item["id"] == widget_id else item for item in widgets]
        widgets.sort(key=_sort_key)
        # A post changes content only, so an open configurator stays current.
        _save(widgets, meta, layout=False)
        return widget

    return _transaction(run)


def _clock_stamp(now: datetime | None = None) -> str:
    try:
        zone = ZoneInfo(load_config().get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        zone = ZoneInfo("UTC")
    moment = (now or datetime.now(zone)).astimezone(zone)
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _choose_id(requested, widgets: list[dict]) -> str:
    taken = {item["id"] for item in widgets}
    if requested is None:
        for _ in range(8):
            widget_id = "w" + secrets.token_hex(3)
            if widget_id not in taken:
                return widget_id
        raise WidgetError("could not allocate an id", 500)
    if not isinstance(requested, str) or requested in RESERVED_IDS or not ID_RE.match(requested):
        raise WidgetError("id must be a short lowercase name")
    if requested in taken:
        raise WidgetError("id already exists", 409)
    return requested


def _order_value(requested, widgets: list[dict]) -> int:
    if requested is None:
        return max((item["order"] for item in widgets), default=-10) + 10
    return _require_order(requested)


def _require_order(value) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not -100000 <= value <= 100000:
        raise WidgetError("order must be an integer")
    return value


def _span(data: dict, previous: dict | None, field: str, default: int = 1) -> int:
    if field not in data:
        if previous is None:
            return default
        return int(previous.get(field, default))
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or value not in SPAN_VALUES:
        raise WidgetError(f"{field} must be 1 or 2")
    return value


def _build(widget_type: str, data: dict, widget_id: str, order: int, previous: dict | None) -> dict:
    enabled = _enabled(data, previous)
    tile = catalog().get(widget_type)
    spec = tile.spec if tile is not None else {}
    widget = {
        "id": widget_id,
        "type": widget_type,
        "enabled": enabled,
        "order": order,
        "col_span": _span(data, previous, "col_span", spec.get("col_span", 1)),
        "row_span": _span(data, previous, "row_span", spec.get("row_span", 1)),
    }
    owner = _managed_by(data, previous)
    if owner:
        widget["managed_by"] = owner
    if tile is not None:
        try:
            widget.update(tiles.build_fields(spec, data, previous))
        except tiles.TileError as exc:
            raise WidgetError(str(exc)) from exc
        return _present(widget)
    builders = {
        "clock": _build_clock,
        "worldclocks": _build_worldclocks,
        "stats": _build_stats,
        "note": _build_note,
        "markdown": _build_markdown,
        "list": _build_list,
        "weather": _build_weather,
        "countdown": _build_countdown,
        "calendar": _build_calendar,
        "github": _build_github,
        "embed": _build_embed,
        "rss": _build_rss,
        "image": _build_image,
        "timer": _build_timer,
        "status": _build_status,
        "theme_card": _build_theme_card,
    }
    builders[widget_type](widget, data, previous)
    return _present(widget)


def _build_clock(widget: dict, data: dict, previous: dict | None) -> None:
    widget["style"] = _choice(data, previous, "style", ("digital", "analog"), "digital")
    widget["show_seconds"] = _bool(data, previous, "show_seconds", True)
    widget["show_date"] = _bool(data, previous, "show_date", True)


def _build_worldclocks(widget: dict, data: dict, previous: dict | None) -> None:
    widget["style"] = _choice(data, previous, "style", ("analog", "digital", "both"), "analog")
    widget["mark_markets"] = _bool(data, previous, "mark_markets", False)
    if "cities" in data or previous is None:
        widget["cities"] = _cities(data.get("cities"))
    else:
        widget["cities"] = list(previous["cities"])


def _build_stats(widget: dict, data: dict, previous: dict | None) -> None:
    raw = data["fields"] if "fields" in data else None
    if raw is None and previous is not None:
        raw = previous["fields"]
    if raw is None:
        raw = list(STAT_FIELDS)
    widget["fields"] = _stat_fields(raw)


def _build_note(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["text"] = _required_text(data, previous, "text", 280, newlines=True)


def _build_markdown(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["text"] = _required_text(data, previous, "text", 1200, newlines=True, max_lines=40)


def _build_list(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    if "items" in data or previous is None:
        widget["items"] = _items(data.get("items"))
    else:
        widget["items"] = list(previous["items"])
    if "max_items" in data:
        if data["max_items"] is not None:
            widget["max_items"] = _int_range(data, previous, "max_items", 1, 8, POST_DEFAULT_ITEMS)
    elif previous is not None and "max_items" in previous:
        widget["max_items"] = previous["max_items"]


def _build_weather(widget: dict, data: dict, previous: dict | None) -> None:
    widget["latitude"] = _coord(data, previous, "latitude", -90, 90)
    widget["longitude"] = _coord(data, previous, "longitude", -180, 180)
    widget["label"] = _optional_text(data, previous, "label", 48)
    widget["units"] = _choice(data, previous, "units", ("metric", "imperial"), "metric")


def _build_countdown(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["label"] = _optional_text(data, previous, "label", 48)
    widget["target"] = _iso_datetime(data, previous, "target")


def _build_calendar(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["url"] = _http_url(data, previous, "url")
    widget["limit"] = _int_range(data, previous, "limit", 1, 12, 5)


def _build_github(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    if "repos" in data or previous is None:
        widget["repos"] = _repos(data.get("repos"))
    else:
        widget["repos"] = list(previous["repos"])


def _build_embed(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["url"] = _http_url(data, previous, "url")
    widget["refresh_sec"] = _int_range(data, previous, "refresh_sec", 30, 86400, 300)
    _check_embed_allowlist(widget["url"])


def _build_rss(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["url"] = _http_url(data, previous, "url")
    widget["limit"] = _int_range(data, previous, "limit", 1, 12, 6)


def _build_image(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["src"] = _image_src(data, previous, "src")
    widget["fit"] = _choice(data, previous, "fit", ("cover", "contain"), "cover")


def _build_timer(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    widget["minutes"] = _int_range(data, previous, "minutes", 1, 180, 25)
    widget["mode"] = _choice(data, previous, "mode", ("pomodoro", "countdown"), "pomodoro")


def _build_status(widget: dict, data: dict, previous: dict | None) -> None:
    widget["title"] = _optional_text(data, previous, "title", 48)
    if "targets" in data or previous is None:
        widget["targets"] = _targets(data.get("targets"))
    else:
        widget["targets"] = list(previous["targets"])


def _build_theme_card(widget: dict, data: dict, previous: dict | None) -> None:
    widget["image"] = _optional_text(data, previous, "image", 64) or "default"
    if "/" in widget["image"] or "\\" in widget["image"] or ".." in widget["image"]:
        raise WidgetError("image must be a preset name")
    widget["caption"] = _optional_text(data, previous, "caption", 64)


def _managed_by(data: dict, previous: dict | None) -> str:
    """Optional owner tag such as "bots" or "calendar". "" or null clears it."""
    if "managed_by" not in data:
        return "" if previous is None else previous.get("managed_by", "")
    value = data["managed_by"]
    if value is None or value == "":
        return ""
    if not isinstance(value, str) or not MANAGED_RE.match(value):
        raise WidgetError("managed_by must be a short lowercase name such as bots or calendar")
    return value


def _enabled(data: dict, previous: dict | None) -> bool:
    if "enabled" not in data:
        return True if previous is None else previous["enabled"]
    if not isinstance(data["enabled"], bool):
        raise WidgetError("enabled must be true or false")
    return data["enabled"]


def _bool(data: dict, previous: dict | None, field: str, default: bool) -> bool:
    if field not in data:
        if previous is None:
            return default
        return bool(previous.get(field, default))
    if not isinstance(data[field], bool):
        raise WidgetError(f"{field} must be true or false")
    return data[field]


def _choice(data: dict, previous: dict | None, field: str, allowed: tuple[str, ...], default: str) -> str:
    if field not in data:
        if previous is None:
            return default
        value = previous.get(field, default)
        return value if value in allowed else default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        raise WidgetError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def _optional_text(data: dict, previous: dict | None, field: str, limit: int) -> str:
    if field not in data:
        if previous is None:
            return ""
        return previous.get(field, "")
    return _line(data.get(field), field, limit, required=False)


def _required_text(data, previous, field: str, limit: int, newlines: bool, max_lines: int = 4) -> str:
    if field not in data:
        if previous is None:
            raise WidgetError(f"{field} is required")
        return previous[field]
    if newlines:
        return _block(data.get(field), field, limit, max_lines=max_lines)
    return _line(data.get(field), field, limit, required=True)


def _line(value, field: str, limit: int, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise WidgetError(f"{field} must be a single line")
    if _has_control(value):
        raise WidgetError(f"{field} has unsupported characters")
    cleaned = value.strip()
    if required and not cleaned:
        raise WidgetError(f"{field} is required")
    if len(cleaned) > limit:
        raise WidgetError(f"{field} is limited to {limit} characters")
    return cleaned


def _block(value, field: str, limit: int, max_lines: int = 4) -> str:
    if not isinstance(value, str):
        raise WidgetError(f"{field} must be a string")
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n")
    if _has_control(cleaned):
        raise WidgetError(f"{field} has unsupported characters")
    lines = [line.rstrip() for line in cleaned.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not any(line.strip() for line in lines):
        raise WidgetError(f"{field} is required")
    if len(lines) > max_lines:
        raise WidgetError(f"{field} is limited to {max_lines} lines")
    text = "\n".join(lines)
    if len(text) > limit:
        raise WidgetError(f"{field} is limited to {limit} characters")
    return text


def _items(value) -> list[str]:
    if not isinstance(value, list):
        raise WidgetError("items must be a list")
    if not 1 <= len(value) <= 8:
        raise WidgetError("items must contain 1 to 8 lines")
    return [_line(item, "items", 80, required=True) for item in value]


def _stat_fields(value) -> list[str]:
    if not isinstance(value, list) or not value:
        raise WidgetError("fields must list one or more of temp, load, free, up")
    if any(not isinstance(item, str) for item in value):
        raise WidgetError("fields must be strings")
    if len(value) != len(set(value)) or any(item not in STAT_FIELDS for item in value):
        raise WidgetError("fields must be temp, load, free, or up, without repeats")
    return list(value)


def _cities(value) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise WidgetError("cities must list 1 to 8 cities")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise WidgetError("each city must be an object with label and zone")
        extra = sorted(set(item) - {"label", "zone"})
        if extra:
            raise WidgetError("unknown city fields: " + ", ".join(extra))
        label = _line(item.get("label"), "label", 24, required=True)
        zone = _line(item.get("zone"), "zone", 64, required=True)
        try:
            ZoneInfo(zone)
        except ZoneInfoNotFoundError as exc:
            raise WidgetError(f"unknown timezone {zone}") from exc
        out.append({"label": label, "zone": zone})
    return out


def _coord(data: dict, previous: dict | None, field: str, lo: float, hi: float) -> float:
    if field not in data:
        if previous is None:
            raise WidgetError(f"{field} is required")
        return float(previous[field])
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise WidgetError(f"{field} must be a number")
    number = float(value)
    if not lo <= number <= hi:
        raise WidgetError(f"{field} must be between {lo} and {hi}")
    return round(number, 4)


def _iso_datetime(data: dict, previous: dict | None, field: str) -> str:
    if field not in data:
        if previous is None:
            raise WidgetError(f"{field} is required")
        return previous[field]
    value = data[field]
    if not isinstance(value, str):
        raise WidgetError(f"{field} must be an ISO date or datetime string")
    cleaned = value.strip()
    if not re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?$", cleaned):
        raise WidgetError(f"{field} must look like 2026-12-31 or 2026-12-31T18:00:00")
    if len(cleaned) > 40:
        raise WidgetError(f"{field} is too long")
    return cleaned


def _http_url(data: dict, previous: dict | None, field: str) -> str:
    if field not in data:
        if previous is None:
            raise WidgetError(f"{field} is required")
        return previous[field]
    value = data[field]
    if not isinstance(value, str):
        raise WidgetError(f"{field} must be a URL")
    cleaned = value.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WidgetError(f"{field} must be an http or https URL")
    if len(cleaned) > 500:
        raise WidgetError(f"{field} is limited to 500 characters")
    if _has_control(cleaned):
        raise WidgetError(f"{field} has unsupported characters")
    return cleaned


def _check_embed_allowlist(url: str) -> None:
    allow = load_config().get("embed_allowlist") or []
    if not allow:
        raise WidgetError("embed_allowlist is empty; add the host in config before creating an embed tile")
    host = urlparse(url).hostname or ""
    host = host.lower()
    for entry in allow:
        entry = entry.lower()
        if host == entry or host.endswith("." + entry):
            return
    raise WidgetError(f"host {host} is not on embed_allowlist")


def _repos(value) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= 6:
        raise WidgetError("repos must list 1 to 6 owner/name strings")
    out = []
    for item in value:
        if not isinstance(item, str):
            raise WidgetError("each repo must be a string like owner/name")
        cleaned = item.strip()
        if not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", cleaned):
            raise WidgetError("each repo must look like owner/name")
        out.append(cleaned)
    return out


def _image_src(data: dict, previous: dict | None, field: str) -> str:
    if field not in data:
        if previous is None:
            raise WidgetError(f"{field} is required")
        return previous[field]
    value = data[field]
    if not isinstance(value, str):
        raise WidgetError(f"{field} must be a string")
    cleaned = value.strip()
    if cleaned.startswith("/media/") or cleaned.startswith("/themes/"):
        if ".." in cleaned or len(cleaned) > 200:
            raise WidgetError(f"{field} path is invalid")
        return cleaned
    parsed = urlparse(cleaned)
    if parsed.scheme in ("http", "https") and parsed.netloc:
        if len(cleaned) > 500:
            raise WidgetError(f"{field} is limited to 500 characters")
        return cleaned
    raise WidgetError(f"{field} must be /media/..., /themes/..., or an http(s) URL")


def _targets(value) -> list[dict]:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise WidgetError("targets must list 1 to 8 entries")
    out = []
    for item in value:
        if not isinstance(item, dict):
            raise WidgetError("each target must be an object with label and url")
        extra = sorted(set(item) - {"label", "url"})
        if extra:
            raise WidgetError("unknown target fields: " + ", ".join(extra))
        label = _line(item.get("label"), "label", 24, required=True)
        url = item.get("url")
        if not isinstance(url, str):
            raise WidgetError("url must be a string")
        parsed = urlparse(url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise WidgetError("url must be an http or https URL")
        cleaned = url.strip()
        if len(cleaned) > 300:
            raise WidgetError("url is limited to 300 characters")
        out.append({"label": label, "url": cleaned})
    return out


def _int_range(data: dict, previous: dict | None, field: str, lo: int, hi: int, default: int) -> int:
    if field not in data:
        if previous is None:
            return default
        return int(previous.get(field, default))
    value = data[field]
    if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
        raise WidgetError(f"{field} must be an integer from {lo} to {hi}")
    return value


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 and char != "\n" for char in value)


def _reject_unknown(data: dict, allowed: set[str]) -> None:
    extra = sorted(set(data) - allowed)
    if extra:
        raise WidgetError("unknown fields: " + ", ".join(extra))


def _sort_key(widget: dict) -> tuple:
    return (widget["order"], widget["id"])


def _present(widget: dict) -> dict:
    tile = catalog().get(widget.get("type"))
    if tile is not None:
        keys = ("id", "type", "enabled", "order", "col_span", "row_span", "managed_by") + tuple(tile.fields)
        return {key: widget[key] for key in keys if key in widget}
    return {key: widget[key] for key in OUTPUT_KEYS if key in widget}


def _default_widgets() -> list[dict]:
    widgets = []
    for item in DEFAULT_WIDGETS:
        widgets.append(_build(item["type"], item, item["id"], item["order"], previous=None))
    return widgets


def _read() -> tuple[list[dict], bool, dict]:
    if not PATH.exists():
        return _default_widgets(), True, {"revision": 0, "layout_revision": 0}
    try:
        raw = json.loads(PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WidgetError(f"widgets.json could not be parsed: {exc}", 500) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("widgets"), list):
        raise WidgetError("widgets.json is missing a widgets list", 500)
    meta = {}
    for key in ("revision", "layout_revision"):
        value = raw.get(key, 0)
        meta[key] = value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    widgets = []
    seen = set()
    for item in raw["widgets"]:
        if not isinstance(item, dict):
            raise WidgetError("widgets.json has an invalid widget", 500)
        try:
            widget_id = item["id"]
            widget_type = item["type"]
            order = item["order"]
        except KeyError as exc:
            raise WidgetError("widgets.json has an invalid widget", 500) from exc
        if not isinstance(widget_id, str) or widget_id in seen or not ID_RE.match(widget_id):
            raise WidgetError("widgets.json has an invalid widget id", 500)
        if widget_type in catalog().disabled:
            # A community tile that is switched off. Leave it out of the board.
            continue
        if widget_type not in BUILTIN_TYPES and catalog().get(widget_type) is None:
            raise WidgetError("widgets.json has an invalid widget", 500)
        seen.add(widget_id)
        allowed = _fields_for(widget_type) | COMMON_FIELDS
        kept = {key: item[key] for key in allowed if key in item}
        try:
            widgets.append(_build(widget_type, kept, widget_id, _require_order(order), previous=None))
        except WidgetError as exc:
            raise WidgetError(f"widgets.json has an invalid widget: {exc}", 500) from exc
    return widgets, False, meta


def _save(widgets: list[dict], meta: dict, layout: bool = True) -> dict:
    """Write widgets.json and bump the revision. layout=False is for writes
    that only change a managed tile's content."""
    revision = meta["revision"] + 1
    fresh = {"revision": revision, "layout_revision": revision if layout else meta["layout_revision"]}
    payload = {**fresh, "widgets": [_present(widget) for widget in widgets]}
    temporary = PATH.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, PATH)
    return fresh


def _transaction(fn):
    LOCK.touch(exist_ok=True)
    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            return fn()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
