"""Dependency smoke + security-floor tests.

Purpose:
1. Prove every top-level dependency actually imports on the target runtime
   (Python 3.12 on aarch64) -- a canary for the native/opencv/firebase-admin
   chain that can be fragile on the Pi4.
2. Lock in the security bumps: VERSION_FLOORS asserts a minimum installed
   version for packages that were bumped to clear an advisory, so a future
   downgrade to a vulnerable version fails the suite.

VERSION_FLOORS is finalized from the `pip-audit` output for this branch.
"""
import importlib
import importlib.metadata as md

import pytest
from packaging.version import Version

# import name -> pip distribution name (only where they differ)
TOP_LEVEL_IMPORTS = [
    "apscheduler",
    "bcrypt",
    "debugpy",
    "flask",
    "flask_cors",
    "flask_restful",
    "flask_toastr",
    "firebase_admin",   # replaces Pyrebase4
    "qrcode",
    # runtime deps the app imports directly
    "cv2",              # opencv-python (QR detection)
    "numpy",
    "requests",
]

# distribution name -> minimum required (security-patched) version.
# Derived from pip-audit on the modernization-2026 branch.
VERSION_FLOORS = {
    "flask": "3.1.3",        # CVE-2026-27205
    "flask-cors": "6.0.0",   # CVE-2024-6839 / 6844 / 6866 (+ PYSEC-2024-71/260)
    "requests": "2.33.0",    # CVE-2024-35195 / 47081 / 2026-25645 / PYSEC-2023-74
    "urllib3": "2.5.0",      # CVE-2025-50181 / 66418 / 66471 / 2026-21441 (freed by dropping Pyrebase4)
}


@pytest.mark.parametrize("module", TOP_LEVEL_IMPORTS)
def test_dependency_imports(module):
    """Each dependency imports cleanly on this interpreter/platform."""
    importlib.import_module(module)


@pytest.mark.parametrize("dist,minimum", sorted(VERSION_FLOORS.items()))
def test_security_floor(dist, minimum):
    """Installed version is at or above the patched floor (no regressions)."""
    installed = md.version(dist)
    assert Version(installed) >= Version(minimum), (
        f"{dist} {installed} is below the security floor {minimum}"
    )
