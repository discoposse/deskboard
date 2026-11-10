#!/usr/bin/env python3
"""Block until the local desk page responds."""

import sys
import time
import urllib.error
import urllib.request

from deskboard_config import load_config


def main() -> int:
    url = f"http://127.0.0.1:{load_config()['port']}/"
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if 200 <= response.status < 500:
                    return 0
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            time.sleep(0.25)
    print("deskboard page did not come up", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
