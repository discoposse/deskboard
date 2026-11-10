#!/usr/bin/env python3
"""Tile catalog. One folder per tile type.

    tiles/<id>/tile.json      id, name, description, spans, fields, example
    tiles/<id>/render.js      DeskboardTiles.register("<id>", { render(data, h) { ... } })
    tiles/<id>/tile.css       optional, scoped to .tile-<id>, colors from theme variables
    tiles/<id>/README.md      what the tile shows and a sample payload

Core tiles live directly under tiles/. Contributed tiles live under
tiles/community/ and stay off until their id is listed in the
enabled_community_tiles config key. The catalog is read once at startup.

Usage:
    python3 tiles.py check [folder ...]     validate every tile, or the given folders
    python3 tiles.py new <id> [--community] scaffold a tile folder that passes check
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COMMUNITY = "community"
TILE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
COMMON_FIELDS = {"id", "type", "enabled", "order", "col_span", "row_span"}
FIELD_TYPES = ("line", "text", "lines", "integer", "boolean", "choice")
FIT_MODES = ("none", "metric", "text")
SPEC_KEYS = {"id", "name", "description", "col_span", "row_span", "fit", "fields", "example"}
FIELD_KEYS = {
    "line": {"type", "label", "required", "max", "default"},
    "text": {"type", "label", "required", "max", "max_lines", "default"},
    "lines": {"type", "label", "required", "max", "max_items", "default"},
    "integer": {"type", "label", "min", "max", "default"},
    "boolean": {"type", "label", "default"},
    "choice": {"type", "label", "options", "default"},
}
MAX_FIELDS = 12
MAX_RENDER_BYTES = 32 * 1024
MAX_CSS_BYTES = 16 * 1024

# Identifiers render.js may not use. Render code turns data into markup and
# nothing else: no network, no storage, no DOM, no timers, no dynamic code.
FORBIDDEN_JS = (
    "fetch",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "sendBeacon",
    "navigator",
    "importScripts",
    "import",
    "require",
    "eval",
    "Function",
    "setTimeout",
    "setInterval",
    "requestAnimationFrame",
    "document",
    "window",
    "globalThis",
    "self",
    "location",
    "localStorage",
    "sessionStorage",
    "indexedDB",
    "caches",
    "cookie",
    "postMessage",
    "Worker",
    "innerHTML",
    "outerHTML",
    "insertAdjacentHTML",
)
FORBIDDEN_CSS = (
    (re.compile(r"@import", re.I), "@import"),
    (re.compile(r"url\s*\(", re.I), "url()"),
    (re.compile(r"expression\s*\(", re.I), "expression()"),
    (re.compile(r"#[0-9a-f]{3,8}\b", re.I), "hex colors (use theme variables like var(--ink))"),
    (re.compile(r"\b(?:rgb|rgba|hsl|hsla|hwb|lab|lch|oklab|oklch|color)\s*\(", re.I), "color functions (use theme variables)"),
)


class TileError(Exception):
    """A widget payload does not match its tile.json fields."""


class TileSpecError(Exception):
    """A tile folder is not valid."""


@dataclass
class Tile:
    id: str
    path: Path
    source: str
    spec: dict
    enabled: bool
    has_css: bool
    problems: list = field(default_factory=list)
    # render.js and tile.css as read and checked at discovery. The server
    # serves these bytes, so a later bad edit on disk never reaches the board
    # until a reload accepts it.
    render_js: bytes = b""
    tile_css: bytes | None = None

    @property
    def fields(self) -> dict:
        return self.spec["fields"]

    def meta(self) -> dict:
        return {
            "id": self.id,
            "name": self.spec["name"],
            "description": self.spec["description"],
            "source": self.source,
            "enabled": self.enabled,
            "col_span": self.spec.get("col_span", 1),
            "row_span": self.spec.get("row_span", 1),
            "fit": self.spec.get("fit", "none"),
            "fields": self.spec["fields"],
            "example": self.spec["example"],
            "has_css": self.has_css,
        }


@dataclass
class Catalog:
    tiles: dict = field(default_factory=dict)
    disabled: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)
    version: int = 0

    def get(self, tile_id: str) -> Tile | None:
        return self.tiles.get(tile_id)

    def ids(self) -> list[str]:
        return list(self.tiles)

    def meta(self) -> list[dict]:
        out = [tile.meta() for tile in self.tiles.values()]
        out.extend(tile.meta() for tile in self.disabled.values())
        return out


def tiles_dir() -> Path:
    return Path(os.environ["DESKBOARD_TILES"]) if os.environ.get("DESKBOARD_TILES") else ROOT / "tiles"


# ---------- discovery ----------


def discover(enabled_community=(), reserved=(), root: Path | None = None) -> Catalog:
    """Read every tile folder. Invalid folders are skipped and reported."""
    base = Path(root) if root else tiles_dir()
    catalog = Catalog()
    enabled_community = set(enabled_community or ())
    reserved = set(reserved or ())
    folders = []
    if base.is_dir():
        for path in sorted(base.iterdir()):
            if path.is_dir() and path.name != COMMUNITY and not path.name.startswith((".", "_")):
                folders.append((path, "core"))
        community = base / COMMUNITY
        if community.is_dir():
            for path in sorted(community.iterdir()):
                if path.is_dir() and not path.name.startswith((".", "_")):
                    folders.append((path, COMMUNITY))
    for path, source in folders:
        try:
            spec = load_spec(path)
            check_assets(path, spec["id"])
        except TileSpecError as exc:
            catalog.problems.append(f"{_rel(path)}: {exc}")
            continue
        tile_id = spec["id"]
        if tile_id in reserved:
            catalog.problems.append(f"{_rel(path)}: id {tile_id} is a built-in widget type")
            continue
        if tile_id in catalog.tiles or tile_id in catalog.disabled:
            catalog.problems.append(f"{_rel(path)}: id {tile_id} is already used by another tile")
            continue
        enabled = source == "core" or tile_id in enabled_community
        css_path = path / "tile.css"
        tile = Tile(
            tile_id,
            path,
            source,
            spec,
            enabled,
            css_path.is_file(),
            render_js=(path / "render.js").read_bytes(),
            tile_css=css_path.read_bytes() if css_path.is_file() else None,
        )
        if enabled:
            catalog.tiles[tile_id] = tile
        else:
            catalog.disabled[tile_id] = tile
    for tile_id in sorted(enabled_community - set(catalog.tiles)):
        catalog.problems.append(f"enabled_community_tiles lists {tile_id}, but no valid tiles/community/{tile_id} folder exists")
    return catalog


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_spec(path: Path) -> dict:
    manifest = path / "tile.json"
    if not manifest.is_file():
        raise TileSpecError("missing tile.json")
    for name in ("render.js", "README.md"):
        if not (path / name).is_file():
            raise TileSpecError(f"missing {name}")
    try:
        spec = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TileSpecError(f"tile.json could not be parsed: {exc}") from exc
    validate_spec(spec, folder_name=path.name)
    return spec


def validate_spec(spec, folder_name: str | None = None) -> None:
    if not isinstance(spec, dict):
        raise TileSpecError("tile.json must be an object")
    extra = sorted(set(spec) - SPEC_KEYS)
    if extra:
        raise TileSpecError("unknown tile.json keys: " + ", ".join(extra))
    tile_id = spec.get("id")
    if not isinstance(tile_id, str) or not TILE_ID_RE.match(tile_id):
        raise TileSpecError("id must be 2 to 32 characters of a-z, 0-9, and _, starting with a letter")
    if folder_name is not None and folder_name != tile_id:
        raise TileSpecError(f"id {tile_id} must match the folder name {folder_name}")
    for key, limit in (("name", 32), ("description", 160)):
        value = spec.get(key)
        if not isinstance(value, str) or not value.strip() or len(value) > limit or "\n" in value:
            raise TileSpecError(f"{key} must be one line of 1 to {limit} characters")
    for key in ("col_span", "row_span"):
        if key in spec and (isinstance(spec[key], bool) or spec[key] not in (1, 2)):
            raise TileSpecError(f"{key} must be 1 or 2")
    if "fit" in spec and spec["fit"] not in FIT_MODES:
        raise TileSpecError("fit must be one of: " + ", ".join(FIT_MODES))
    fields = spec.get("fields")
    if not isinstance(fields, dict) or not 1 <= len(fields) <= MAX_FIELDS:
        raise TileSpecError(f"fields must be an object with 1 to {MAX_FIELDS} entries")
    for name, fspec in fields.items():
        _validate_field_spec(name, fspec)
    example = spec.get("example")
    if not isinstance(example, dict):
        raise TileSpecError("example must be an object of field values")
    try:
        build_fields(spec, example, previous=None, strict=True)
    except TileError as exc:
        raise TileSpecError(f"example does not pass validation: {exc}") from exc


def _validate_field_spec(name: str, fspec) -> None:
    if not isinstance(name, str) or not FIELD_RE.match(name) or name in COMMON_FIELDS:
        raise TileSpecError(f"field name {name!r} is not allowed")
    if not isinstance(fspec, dict) or fspec.get("type") not in FIELD_TYPES:
        raise TileSpecError(f"field {name} needs a type, one of: " + ", ".join(FIELD_TYPES))
    kind = fspec["type"]
    extra = sorted(set(fspec) - FIELD_KEYS[kind])
    if extra:
        raise TileSpecError(f"field {name} has unknown keys: " + ", ".join(extra))
    if "label" in fspec and (not isinstance(fspec["label"], str) or not 1 <= len(fspec["label"]) <= 48):
        raise TileSpecError(f"field {name} label must be 1 to 48 characters")
    if "required" in fspec and not isinstance(fspec["required"], bool):
        raise TileSpecError(f"field {name} required must be true or false")

    def int_key(key, lo, hi):
        if key in fspec and (isinstance(fspec[key], bool) or not isinstance(fspec[key], int) or not lo <= fspec[key] <= hi):
            raise TileSpecError(f"field {name} {key} must be an integer from {lo} to {hi}")

    if kind == "line":
        int_key("max", 1, 500)
    elif kind == "text":
        int_key("max", 1, 2000)
        int_key("max_lines", 1, 40)
    elif kind == "lines":
        int_key("max", 1, 200)
        int_key("max_items", 1, 20)
    elif kind == "integer":
        for key in ("min", "max"):
            if key not in fspec:
                raise TileSpecError(f"field {name} needs {key}")
            int_key(key, -1000000, 1000000)
        if fspec["min"] > fspec["max"]:
            raise TileSpecError(f"field {name} min is above max")
    elif kind == "choice":
        options = fspec.get("options")
        if (
            not isinstance(options, list)
            or not 1 <= len(options) <= 12
            or any(not isinstance(o, str) or not FIELD_RE.match(o) for o in options)
            or len(set(options)) != len(options)
        ):
            raise TileSpecError(f"field {name} options must list 1 to 12 short lowercase names")
    if "default" in fspec:
        if fspec.get("required"):
            raise TileSpecError(f"field {name} is required, so it cannot have a default")
        try:
            _value(name, fspec, fspec["default"])
        except TileError as exc:
            raise TileSpecError(f"field {name} default is invalid: {exc}") from exc
    elif kind == "integer":
        raise TileSpecError(f"field {name} needs a default")


# ---------- asset checks ----------


def _strip_js(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    source = re.sub(r"(?m)//.*$", " ", source)
    source = re.sub(r"'(?:\\.|[^'\\\n])*'", "''", source)
    source = re.sub(r'"(?:\\.|[^"\\\n])*"', '""', source)
    return source


def check_render_js(source: str, tile_id: str) -> list[str]:
    problems = []
    if len(source.encode("utf-8")) > MAX_RENDER_BYTES:
        problems.append(f"render.js is over {MAX_RENDER_BYTES // 1024}KB")
    if not re.search(r"DeskboardTiles\.register\(\s*([\"'])" + re.escape(tile_id) + r"\1", source):
        problems.append(f'render.js must call DeskboardTiles.register("{tile_id}", {{ render(data, h) {{ ... }} }})')
    code = _strip_js(source)
    found = sorted({word for word in FORBIDDEN_JS if re.search(r"(?<![\w$])" + re.escape(word) + r"(?![\w$])", code)})
    if found:
        problems.append("render.js uses " + ", ".join(found) + ". Render code only turns data into markup")
    return problems


def check_tile_css(source: str, tile_id: str) -> list[str]:
    problems = []
    if len(source.encode("utf-8")) > MAX_CSS_BYTES:
        problems.append(f"tile.css is over {MAX_CSS_BYTES // 1024}KB")
    text = re.sub(r"/\*.*?\*/", " ", source, flags=re.S)
    for pattern, what in FORBIDDEN_CSS:
        if pattern.search(text):
            problems.append(f"tile.css uses {what}")
    scope = re.compile(r"^(?:\.board(?:\.[a-z0-9_-]+)*\s+)?(?:\.tile)?\.tile-" + re.escape(tile_id) + r"(?![\w-])")
    for raw in re.findall(r"([^{};]+)\{", text):
        selector_list = raw.strip()
        if selector_list.startswith("@"):
            if not selector_list.startswith("@media"):
                problems.append(f"tile.css only allows @media blocks, found {selector_list.split()[0]}")
            continue
        for selector in selector_list.split(","):
            selector = " ".join(selector.split())
            if selector and not scope.match(selector):
                problems.append(f"tile.css selector {selector!r} must start with .tile-{tile_id}")
    return problems


def check_assets(path: Path, tile_id: str) -> None:
    problems = check_render_js((path / "render.js").read_text(encoding="utf-8"), tile_id)
    css = path / "tile.css"
    if css.is_file():
        problems.extend(check_tile_css(css.read_text(encoding="utf-8"), tile_id))
    if problems:
        raise TileSpecError("; ".join(problems))


# ---------- field validation ----------


def _has_control(value: str) -> bool:
    return any(ord(char) < 32 and char != "\n" for char in value)


def _line(value, name: str, limit: int, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or "\n" in value or "\r" in value:
        raise TileError(f"{name} must be a single line")
    if _has_control(value):
        raise TileError(f"{name} has unsupported characters")
    cleaned = value.strip()
    if required and not cleaned:
        raise TileError(f"{name} is required")
    if len(cleaned) > limit:
        raise TileError(f"{name} is limited to {limit} characters")
    return cleaned


def _block(value, name: str, limit: int, max_lines: int, required: bool) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise TileError(f"{name} must be a string")
    cleaned = value.replace("\r\n", "\n").replace("\r", "\n")
    if _has_control(cleaned):
        raise TileError(f"{name} has unsupported characters")
    lines = [line.rstrip() for line in cleaned.split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not any(line.strip() for line in lines):
        if required:
            raise TileError(f"{name} is required")
        return ""
    if len(lines) > max_lines:
        raise TileError(f"{name} is limited to {max_lines} lines")
    text = "\n".join(lines)
    if len(text) > limit:
        raise TileError(f"{name} is limited to {limit} characters")
    return text


def _value(name: str, fspec: dict, value):
    kind = fspec["type"]
    required = bool(fspec.get("required"))
    if kind == "line":
        return _line(value, name, fspec.get("max", 80), required)
    if kind == "text":
        return _block(value, name, fspec.get("max", 280), fspec.get("max_lines", 4), required)
    if kind == "lines":
        max_items = fspec.get("max_items", 8)
        if not isinstance(value, list):
            raise TileError(f"{name} must be a list")
        if len(value) > max_items or (required and not value):
            raise TileError(f"{name} must contain {1 if required else 0} to {max_items} lines")
        return [_line(item, name, fspec.get("max", 80), required=True) for item in value]
    if kind == "integer":
        lo, hi = fspec["min"], fspec["max"]
        if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
            raise TileError(f"{name} must be an integer from {lo} to {hi}")
        return value
    if kind == "boolean":
        if not isinstance(value, bool):
            raise TileError(f"{name} must be true or false")
        return value
    if kind == "choice":
        options = fspec["options"]
        if not isinstance(value, str) or value not in options:
            raise TileError(f"{name} must be one of: {', '.join(options)}")
        return value
    raise TileError(f"{name} has an unknown type")


def _default(fspec: dict):
    if "default" in fspec:
        value = fspec["default"]
        return list(value) if isinstance(value, list) else value
    kind = fspec["type"]
    if kind in ("line", "text"):
        return ""
    if kind == "lines":
        return []
    if kind == "boolean":
        return False
    if kind == "choice":
        return fspec["options"][0]
    return fspec.get("min", 0)


def build_fields(spec: dict, data: dict, previous: dict | None, strict: bool = False) -> dict:
    """Validate the tile fields in data. Absent fields keep their previous
    value on update and take the default on create. Required fields with no
    value are an error. Field order follows tile.json."""
    fields = spec["fields"]
    if strict:
        extra = sorted(set(data) - set(fields))
        if extra:
            raise TileError("unknown fields: " + ", ".join(extra))
    out = {}
    for name, fspec in fields.items():
        if name in data:
            out[name] = _value(name, fspec, data[name])
        elif previous is not None and name in previous:
            out[name] = previous[name]
        elif fspec.get("required"):
            raise TileError(f"{name} is required")
        else:
            out[name] = _default(fspec)
    return out


# ---------- scaffold ----------

STUB_SPEC = """{{
  "id": "{id}",
  "name": "{name}",
  "description": "Describe what this tile shows in one line.",
  "col_span": 1,
  "row_span": 1,
  "fit": "text",
  "fields": {{
    "title": {{ "type": "line", "label": "Title", "max": 48, "default": "" }},
    "text": {{ "type": "text", "label": "Text", "required": true, "max": 200, "max_lines": 4 }}
  }},
  "example": {{
    "title": "{name}",
    "text": "Edit {folder}/render.js"
  }}
}}
"""

STUB_RENDER = """// {name} tile. Return markup built from data and escape every value with h.escape.
// Allowed tags: div p span strong em b i small ul ol li br blockquote figure figcaption.
// The board drops every attribute except class.
DeskboardTiles.register("{id}", {{
  render(data, h) {{
    const title = data.title ? '<p class="eyebrow">' + h.escape(data.title) + "</p>" : "";
    return title + '<p class="fit-text {id}-text">' + h.escape(data.text) + "</p>";
  }},
}});
"""

STUB_CSS = """/* Scope every selector to .tile-{id}. Colors come from theme variables. */
.board .tile-{id} .{id}-text {{
  white-space: pre-line;
  overflow-wrap: anywhere;
  line-height: 1.3;
  color: var(--ink);
}}
"""

STUB_README = """# {name}

Describe what this tile shows and where its data comes from.

## Fields

| Field | Type | Notes |
| --- | --- | --- |
| `title` | line | Optional, up to 48 characters |
| `text` | text | Required, up to 200 characters and 4 lines |

## Sample payload

```bash
curl -s http://127.0.0.1:8730/api/widgets \\\\
  -X POST -H 'Content-Type: application/json' \\\\
  -d '{{"type":"{id}","title":"{name}","text":"Edit {folder}/render.js"}}'
```

Preview it at `http://127.0.0.1:8730/?tilepreview={id}`.
"""


def scaffold(tile_id: str, community: bool = False, root: Path | None = None, reserved=()) -> Path:
    base = Path(root) if root else tiles_dir()
    if not TILE_ID_RE.match(tile_id or ""):
        raise TileSpecError("id must be 2 to 32 characters of a-z, 0-9, and _, starting with a letter")
    if tile_id in set(reserved) or tile_id == COMMUNITY:
        raise TileSpecError(f"{tile_id} is a built-in widget type")
    if (base / tile_id).exists() or (base / COMMUNITY / tile_id).exists():
        raise TileSpecError(f"a tile folder named {tile_id} already exists")
    folder = base / COMMUNITY / tile_id if community else base / tile_id
    folder.mkdir(parents=True)
    shown = f"tiles/{COMMUNITY}/{tile_id}" if community else f"tiles/{tile_id}"
    values = {"id": tile_id, "name": tile_id.replace("_", " ").title(), "folder": shown}
    (folder / "tile.json").write_text(STUB_SPEC.format(**values), encoding="utf-8")
    (folder / "render.js").write_text(STUB_RENDER.format(**values), encoding="utf-8")
    (folder / "tile.css").write_text(STUB_CSS.format(**values), encoding="utf-8")
    (folder / "README.md").write_text(STUB_README.format(**values).replace("\\\\", "\\"), encoding="utf-8")
    return folder


# ---------- CLI ----------


def _builtin_types() -> tuple:
    from widgets import BUILTIN_TYPES

    return BUILTIN_TYPES


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "new":
        community = "--community" in argv[2:]
        try:
            folder = scaffold(argv[1], community=community, reserved=_builtin_types())
        except TileSpecError as exc:
            print(f"new_tile: {exc}", file=sys.stderr)
            return 1
        catalog = discover(enabled_community=[argv[1]] if community else [], reserved=_builtin_types())
        mine = [p for p in catalog.problems if f"/{argv[1]}:" in p or f"/{argv[1]} " in p]
        if mine:
            print("\n".join(mine), file=sys.stderr)
            return 1
        print(f"Created {_rel(folder)}")
        return 0
    if argv and argv[0] == "check":
        names = {Path(p).resolve().name for p in argv[1:]}
        everything = discover(enabled_community=(), reserved=_builtin_types())
        tiles = list(everything.tiles.values()) + list(everything.disabled.values())
        problems = [p for p in everything.problems if not names or any(f"/{n}:" in p or p.startswith(f"{n}:") for n in names)]
        checked = [t for t in tiles if not names or t.id in names]
        for tile in checked:
            print(f"ok    {_rel(tile.path)} ({tile.source})")
        for problem in problems:
            print(f"FAIL  {problem}")
        if names and not checked and not problems:
            print("no tile folders matched", file=sys.stderr)
            return 1
        return 1 if problems else 0
    print(__doc__.strip().split("Usage:")[1].strip(), file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
