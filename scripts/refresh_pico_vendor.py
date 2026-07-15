#!/usr/bin/env python3
"""Fetches a PicoCSS release's full CSS so a maintainer can diff it against
the hand-trimmed <style> block vendored in docs/index.html.

This is intentionally a manual, human-reviewed step, not CI-automated: the
vendored CSS is a deliberately curated subset of only the declarations
docs/index.html's markup actually uses, not a mechanically regenerated
bundle. Re-run this after bumping the pinned version or after changing which
elements/classes the page uses, then hand-update the <style> block and
spot-check the page in a browser (including dark mode) before committing.

Usage: python3 scripts/refresh_pico_vendor.py <version>
       e.g. python3 scripts/refresh_pico_vendor.py 2.2.0
"""

import sys
import urllib.request
from pathlib import Path

OUTPUT = Path("/tmp/pico-reference.css")


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(f"Usage: {sys.argv[0]} <picocss-version>")
    version = sys.argv[1]

    url = f"https://cdn.jsdelivr.net/npm/@picocss/pico@{version}/css/pico.css"
    with urllib.request.urlopen(url) as response:
        OUTPUT.write_bytes(response.read())

    print(f"Saved PicoCSS {version} reference to {OUTPUT}")
    print("Diff it against the <style> block in docs/index.html by hand,")
    print("update the vendored declarations and version comment, then")
    print("verify docs/index.html in a browser (including dark mode).")


if __name__ == "__main__":
    main()
