#!/usr/bin/env python3
"""One undecorated WebKit window. Cage fullscreen's it on the HDMI output."""

import os
import sys

os.environ.setdefault("GDK_BACKEND", "wayland")
os.environ.setdefault("WEBKIT_DISABLE_DMABUF_RENDERER", "1")
os.environ.setdefault("WEBKIT_DISABLE_COMPOSITING_MODE", "1")

import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gdk, GLib, Gtk, WebKit2

from deskboard_config import load_config

BG = "#10110e"


def page_url() -> str:
    override = os.environ.get("DESKBOARD_URL", "").strip()
    if override:
        return override
    return f"http://127.0.0.1:{load_config()['port']}/"


def paint_background() -> None:
    provider = Gtk.CssProvider()
    provider.load_from_data(f"window, * {{ background-color: {BG}; }}".encode())
    screen = Gdk.Screen.get_default()
    if screen is None:
        return
    Gtk.StyleContext.add_provider_for_screen(
        screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )


def hide_cursor(widget) -> None:
    window = widget.get_window()
    if window is None:
        return
    blank = Gdk.Cursor.new_for_display(widget.get_display(), Gdk.CursorType.BLANK_CURSOR)
    window.set_cursor(blank)


def main() -> None:
    url = page_url()
    Gtk.init(sys.argv)
    paint_background()

    rgba = Gdk.RGBA()
    rgba.parse(BG)

    context = WebKit2.WebContext.new_ephemeral()
    view = WebKit2.WebView.new_with_context(context)
    settings = view.get_settings()
    settings.set_enable_javascript(True)
    settings.set_enable_write_console_messages_to_stdout(True)
    settings.set_media_playback_requires_user_gesture(True)
    policy = getattr(WebKit2, "HardwareAccelerationPolicy", None)
    if policy is not None:
        settings.set_hardware_acceleration_policy(policy.NEVER)
    if hasattr(view, "set_background_color"):
        view.set_background_color(rgba)

    win = Gtk.Window()
    win.set_title("deskboard")
    win.set_decorated(False)
    win.override_background_color(Gtk.StateFlags.NORMAL, rgba)
    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.connect("realize", hide_cursor)
    view.connect("realize", hide_cursor)

    def reload() -> bool:
        view.load_uri(url)
        return False

    def retry(*_args) -> bool:
        print("deskboard view retrying", url, flush=True)
        GLib.timeout_add_seconds(2, reload)
        return True

    for signal in ("load-failed", "web-process-terminated"):
        try:
            view.connect(signal, retry)
        except TypeError:
            pass
    try:
        view.connect("context-menu", lambda *_args: True)
    except TypeError:
        pass

    def on_load(_view, event) -> None:
        if event == WebKit2.LoadEvent.FINISHED:
            print("deskboard view ready", url, flush=True)

    try:
        view.connect("load-changed", on_load)
    except TypeError:
        pass

    win.show_all()
    win.fullscreen()
    GLib.idle_add(win.fullscreen)
    view.load_uri(url)
    print("deskboard view opening", url, flush=True)
    Gtk.main()


if __name__ == "__main__":
    main()
