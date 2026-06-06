"""End-to-end canary for the QR-scan path in src/app/views.py::scan.

views.scan() can't be imported directly (its module runs property/Firebase init
at import time), so this test reproduces exactly the pipeline it performs:

    nparr = numpy.frombuffer(file, numpy.uint8)
    imageNp = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    decodedText, points, _ = cv2.QRCodeDetector().detectAndDecode(imageNp)

This validates the torch-free detector (OpenCV's built-in QRCodeDetector, which
replaced qreader/torch) and catches the realistic breakages on Python 3.12:
  - numpy 2.x altering numpy.frombuffer, and
  - an opencv/numpy ABI mismatch ("numpy.core.multiarray failed to import").

Fast and fully offline (no model weights / network).
"""
from io import BytesIO

import cv2
import numpy
import qrcode


def _png_bytes(payload):
    img = qrcode.make(payload).get_image()  # underlying PIL image
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_views_scan_decodes_qr():
    payload = "halloween-2026"
    file = _png_bytes(payload)

    # Mirror views.scan() exactly.
    nparr = numpy.frombuffer(file, numpy.uint8)
    imageNp = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    assert imageNp is not None, "cv2.imdecode returned None -- opencv/numpy ABI break"

    detector = cv2.QRCodeDetector()
    decodedText, points, _ = detector.detectAndDecode(imageNp)

    assert decodedText == payload, f"QR round-trip failed: got {decodedText!r}"
