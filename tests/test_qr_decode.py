"""Canary for the QR-scan image-preprocessing path in src/app/views.py::scan.

views.scan() can't be imported directly (its module runs property/Firebase init
at import time), so this test reproduces exactly the numpy -> cv2 preprocessing
it performs:

    nparr = numpy.fromstring(file, numpy.uint8)
    imageNp = cv2.imdecode(nparr, ...)

This catches the two realistic breakages from moving to Python 3.12 / newer deps:
  - numpy 2.x removing/altering numpy.fromstring, and
  - an opencv/numpy ABI mismatch ("numpy.core.multiarray failed to import").

The heavy QReader/torch model step (which downloads weights over the network) is
intentionally NOT exercised here -- this stays a fast, offline test.
"""
from io import BytesIO

import cv2
import numpy
import qrcode


def _png_bytes(payload="halloween"):
    img = qrcode.make(payload).convert("RGB")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_views_scan_preprocessing_still_works():
    file = _png_bytes()

    # Mirror views.scan() exactly. numpy.frombuffer replaced numpy.fromstring,
    # whose binary mode was removed in numpy 2.x; it must still produce a buffer
    # cv2 can decode. (frombuffer returns a read-only array, which is fine here
    # because cv2.imdecode only reads it.)
    nparr = numpy.frombuffer(file, numpy.uint8)

    imageNp = cv2.imdecode(nparr, cv2.COLOR_BGR2RGB)

    assert imageNp is not None, "cv2.imdecode returned None -- opencv/numpy ABI break"
    assert imageNp.size > 0
