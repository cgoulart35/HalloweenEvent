"""Guards for vendored front-end assets that aren't exercised by Python at runtime.

The live in-app QR scanner falls back to jsQR on browsers without a native
BarcodeDetector (notably iOS Safari). jsQR is vendored as a static file rather
than pulled from a CDN at runtime, so this checks the asset is actually committed,
non-trivial, and exposes the global the page relies on -- catching an empty/corrupt
or accidentally-removed vendor file before it ships.
"""
import os

_STATIC_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "src", "app", "static"
)


def test_vendored_jsqr_present_and_sane():
    path = os.path.join(_STATIC_DIR, "jsQR.js")
    assert os.path.isfile(path), "vendored jsQR.js is missing from src/app/static"

    contents = open(path, encoding="utf-8").read()
    # The UMD build is well over 100 KB; anything tiny means a truncated/empty file.
    assert len(contents) > 50_000, "jsQR.js looks truncated"
    # The plain-<script> branch of the UMD wrapper assigns the global the page uses.
    assert 'root["jsQR"]' in contents, "jsQR.js does not expose the global jsQR"
