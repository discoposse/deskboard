"""In-memory flash messages for the kiosk.

A flash is a short plain-text notice that covers most of the screen and then
goes away. Nothing here is written to disk. A repeat of the same text inside
a short window does not create a second flash.
"""

from __future__ import annotations

import secrets
import threading
import time

LEVELS = ("info", "warning", "urgent")
TITLE_MAX = 80
BODY_MAX = 400
BODY_LINES = 6
SOURCE_MAX = 24
DURATION_DEFAULT = 30
DURATION_MIN = 5
DURATION_MAX = 120
DEDUPE_SEC = 60
HOLD_SEC = 120
QUEUE_MAX = 6
_FIELDS = {"title", "body", "level", "duration", "source"}


class FlashError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class FlashQueue:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: list[dict] = []
        self._recent: dict[tuple, tuple[float, dict]] = {}

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._recent.clear()

    def post(self, data: dict, now: float | None = None) -> dict:
        if not isinstance(data, dict):
            raise FlashError("body must be an object")
        extra = sorted(set(data) - _FIELDS)
        if extra:
            raise FlashError("unknown fields: " + ", ".join(extra))
        moment = time.time() if now is None else float(now)
        title = _line(data.get("title"), "title", TITLE_MAX)
        body = _block(data.get("body"), "body", BODY_MAX, BODY_LINES)
        source = _line(data.get("source"), "source", SOURCE_MAX)
        level = _level(data)
        duration = _duration(data)
        fingerprint = (title, body, level, source)
        with self._lock:
            self._drop_locked(moment)
            previous = self._recent.get(fingerprint)
            if previous is not None and moment - previous[0] < DEDUPE_SEC:
                replay = dict(previous[1])
                replay["deduped"] = True
                return replay
            waiting = [item for item in self._items if item["expires"] > moment]
            if len(waiting) >= QUEUE_MAX:
                raise FlashError("the board already has a full queue of flashes", 409)
            item = {
                "id": secrets.token_hex(4),
                "title": title,
                "body": body,
                "level": level,
                "duration": duration,
                "source": source,
                "created": int(moment),
                "expires": int(moment) + duration + HOLD_SEC,
            }
            self._items.append(item)
            self._recent[fingerprint] = (moment, dict(item))
            shown = dict(item)
            shown["deduped"] = False
            return shown

    def active(self, now: float | None = None) -> list[dict]:
        moment = time.time() if now is None else float(now)
        with self._lock:
            self._drop_locked(moment)
            return [_public(item) for item in self._items if item["expires"] > moment]

    def _drop_locked(self, moment: float) -> None:
        self._items = [item for item in self._items if item["expires"] > moment]
        self._recent = {key: value for key, value in self._recent.items() if moment - value[0] < DEDUPE_SEC}


_queue = FlashQueue()


def post_flash(data: dict, now: float | None = None) -> dict:
    return _queue.post(data, now)


def list_flashes(now: float | None = None) -> dict:
    return {"flashes": _queue.active(now)}


def reset_flashes() -> None:
    _queue.clear()


def _public(item: dict) -> dict:
    return {key: item[key] for key in ("id", "title", "body", "level", "duration", "source", "created", "expires")}


def _level(data: dict) -> str:
    if "level" not in data:
        return "info"
    value = data["level"]
    if not isinstance(value, str) or value not in LEVELS:
        raise FlashError("level must be info, warning, or urgent")
    return value


def _duration(data: dict) -> int:
    if "duration" not in data:
        return DURATION_DEFAULT
    value = data["duration"]
    if isinstance(value, bool) or not isinstance(value, int):
        raise FlashError("duration must be a whole number of seconds")
    if value < DURATION_MIN:
        return DURATION_MIN
    if value > DURATION_MAX:
        return DURATION_MAX
    return value


def _line(value, field: str, limit: int) -> str:
    if not isinstance(value, str):
        raise FlashError(f"{field} must be text")
    if _bad_controls(value, newlines=False):
        raise FlashError(f"{field} must be one plain line")
    text = " ".join(value.split())
    if not text:
        raise FlashError(f"{field} must not be empty")
    if len(text) > limit:
        raise FlashError(f"{field} is limited to {limit} characters")
    return text


def _block(value, field: str, limit: int, max_lines: int) -> str:
    if not isinstance(value, str):
        raise FlashError(f"{field} must be text")
    if _bad_controls(value, newlines=True):
        raise FlashError(f"{field} must be plain text")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    lines = [" ".join(line.split()) for line in text.split("\n")]
    lines = [line for line in lines if line]
    if not lines:
        raise FlashError(f"{field} must not be empty")
    if len(lines) > max_lines:
        raise FlashError(f"{field} is limited to {max_lines} lines")
    joined = "\n".join(lines)
    if len(joined) > limit:
        raise FlashError(f"{field} is limited to {limit} characters")
    return joined


def _bad_controls(value: str, newlines: bool) -> bool:
    for ch in value:
        code = ord(ch)
        if code == 10 and newlines:
            continue
        if code == 13 and newlines:
            continue
        if code < 32 or code == 127:
            return True
    return False
