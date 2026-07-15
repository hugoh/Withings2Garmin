#!/usr/bin/env python3
"""Regenerates the PicoCSS <link integrity="..."> hash in docs/index.html to
match whatever @picocss/pico@<version> is currently pinned in that file.

Run this after Renovate (or anyone) bumps the version string, so the SRI
hash never drifts out of sync with the pinned version.

The hash comes from jsDelivr's package metadata API rather than being
computed locally from a downloaded copy of the file - that API is jsDelivr's
own authoritative record of the file's content, generated independently of
whatever a CDN edge node serves for the <link> URL.
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

PAGE = Path("docs/index.html")
PACKAGE = "@picocss/pico"
CSS_FILE = "/css/pico.min.css"


def main() -> None:
    html = PAGE.read_text()

    match = re.search(rf"{re.escape(PACKAGE)}@([0-9.]+)/css/pico\.min\.css", html)
    if not match:
        sys.exit(f"Could not find a pinned {PACKAGE} version in {PAGE}")
    version = match.group(1)

    url = (
        f"https://data.jsdelivr.com/v1/packages/npm/{PACKAGE}@{version}?structure=flat"
    )
    with urllib.request.urlopen(url) as response:
        metadata = json.load(response)

    file_entry = next(f for f in metadata["files"] if f["name"] == CSS_FILE)
    integrity = f"sha256-{file_entry['hash']}"

    updated_html = re.sub(
        r'integrity="sha[0-9]+-[^"]*"', f'integrity="{integrity}"', html
    )
    PAGE.write_text(updated_html)

    print(f"Updated integrity hash for {PACKAGE}@{version} in {PAGE}")


if __name__ == "__main__":
    main()
