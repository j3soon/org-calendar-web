"""Verify bundled bytes offline, with an explicit opt-in for upstream checks."""

import base64
import hashlib
import json
import os
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "static" / "vendor"
MANIFEST = json.loads((VENDOR / "manifest.json").read_text())


@pytest.mark.parametrize("name, entry", MANIFEST.items())
def test_bundled_asset_matches_pinned_hash(name, entry):
    digest = hashlib.sha256((VENDOR / name).read_bytes()).hexdigest()
    assert digest == entry["sha256"], f"Bundled asset changed: {name}"


@pytest.mark.skipif(
    os.environ.get("CHECK_VENDOR_UPSTREAM") != "1",
    reason="Set CHECK_VENDOR_UPSTREAM=1 to compare with the upstream CDN.",
)
@pytest.mark.parametrize("name, entry", MANIFEST.items())
def test_upstream_matches_pinned_and_bundled_bytes(name, entry):
    local = (VENDOR / name).read_bytes()
    with urlopen(entry["url"], timeout=30) as response:
        upstream = response.read()
    assert hashlib.sha256(local).hexdigest() == entry["sha256"], name
    assert hashlib.sha256(upstream).hexdigest() == entry["sha256"], entry["url"]


class ScriptTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.scripts.append(dict(attrs))


def test_browser_scripts_are_local_with_matching_integrity():
    parser = ScriptTags()
    parser.feed((ROOT / "static" / "index.html").read_text())
    for script in parser.scripts:
        assert script["src"].startswith("/static/"), "Scripts must load locally."
    bundled = [script for script in parser.scripts if script["src"].startswith("/static/vendor/")]
    assert {script["src"] for script in bundled} == {
        f"/static/vendor/{name}" for name in MANIFEST if name.endswith(".js")
    }
    for script in bundled:
        digest = MANIFEST[Path(script["src"]).name]["sha256"]
        integrity = "sha256-" + base64.b64encode(bytes.fromhex(digest)).decode()
        assert script.get("integrity") == integrity, script["src"]
