function openSidebar() {
  document.getElementById("mySidebar").style.display = "flex";
}

function closeSidebar() {
  document.getElementById("mySidebar").style.display = "none";
}

function showLoading() {
  document.getElementById("loaderElement").style.display = "block";
}

function hideloading() {
  document.getElementById("loaderElement").style.display = "none";
}

function getCameraInputElement() {
  return document.getElementById("cameraFileInput");
}

// ----- shared navigation guard -----
// The QR encodes this app's own absolute "/fight/?scannedUserKey=..." URL, and a
// successful scan just navigates there. Only follow a decoded value that resolves
// to a same-origin /fight/ URL, so a bogus or foreign QR can't redirect a player
// off the app. Returns the safe href, or null. No side effects.
function resolveFightUrl(text) {
  if (text === null || typeof text !== "string" || text.length === 0) {
    return null;
  }
  var target;
  try {
    target = new URL(text, location.href);
  } catch (error) {
    return null;
  }
  if (target.origin !== location.origin || !target.pathname.startsWith("/fight/")) {
    return null;
  }
  return target.href;
}

// Navigate to a decoded QR (photo-upload path). Toasts on a bad code.
function navigateToFightUrl(text) {
  var href = resolveFightUrl(text);
  if (href === null) {
    toastr.error("Not a valid game QR code.");
    return false;
  }
  showLoading();
  location = href;
  return true;
}

// ----- photo-upload fallback (the native file input: camera on mobile, file
// picker on desktop). Used when live scanning is unavailable/denied, or via the
// scanner overlay's "Use photo instead" button. Decodes server-side at /scan/. -----
function openCamera() {
  getCameraInputElement().click();
  closeSidebar();
}

function uploadPicture() {
  try {
    showLoading();
    var picture = getCameraInputElement().files[0];
    var formData = new FormData();
    formData.set('file', picture);

    fetch(getCameraInputElement().getAttribute("scanURL"), {
      method: 'POST',
      body: formData
    })
    .then(response => {
      if (!response.ok) {
        return Promise.reject(response);
      } else {
        return response.text();
      }
    })
    .then(text => {
      // navigateToFightUrl keeps the loader up while it navigates; only drop it
      // here if the decoded value was rejected.
      if (!navigateToFightUrl(text)) {
        hideloading();
      }
    })
    .catch(response => {
      hideloading();
      response.text().then(text => {
        if (text !== null && typeof text === "string" && text.length !== 0) {
          toastr.error(text);
        } else {
          toastr.error("Error scanning QR code.");
        }
      });
    });
  } catch (error) {
    hideloading();
    toastr.error("Error sending QR code.");
  }
}

// ----- live in-app scanner: getUserMedia preview + continuous client-side decode
// (native BarcodeDetector when available, vendored jsQR otherwise). The camera
// preview and decoding stay inside the page, so the user never leaves the app and
// the server does no image processing on this path. -----
var scannerStream = null;
var scannerRaf = null;
var scannerActive = false;
var barcodeDetector = null;

function getScannerOverlay() { return document.getElementById("scannerOverlay"); }
function getScannerVideo() { return document.getElementById("scannerVideo"); }
function getScannerCanvas() { return document.getElementById("scannerCanvas"); }

function openScanner() {
  closeSidebar();
  // No live camera API (older browsers / desktop without it) -> photo upload.
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    openCamera();
    return;
  }
  startCamera();
}

function startCamera() {
  var overlay = getScannerOverlay();
  var video = getScannerVideo();
  overlay.style.display = "flex";
  scannerActive = true;

  navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false })
    .then(function (stream) {
      if (!scannerActive) {           // user closed before the camera resolved
        stopStream(stream);
        return null;
      }
      scannerStream = stream;
      video.srcObject = stream;
      video.setAttribute("playsinline", "true");
      return video.play();
    })
    .then(function () {
      if (!scannerActive) return null;
      return setupDetectorThenScan();
    })
    .catch(function () {
      // permission denied / no camera -> fall back to the photo upload path
      closeScanner();
      toastr.info("Camera unavailable — using photo upload.");
      openCamera();
    });
}

// Prefer the native BarcodeDetector, but only when it actually supports QR codes;
// otherwise decode with jsQR. Returns a promise so the scan loop starts after this
// resolves.
function setupDetectorThenScan() {
  barcodeDetector = null;
  if ("BarcodeDetector" in window && typeof BarcodeDetector.getSupportedFormats === "function") {
    return BarcodeDetector.getSupportedFormats()
      .then(function (formats) {
        if (formats.indexOf("qr_code") !== -1) {
          barcodeDetector = new BarcodeDetector({ formats: ["qr_code"] });
        }
        startScanLoop();
      })
      .catch(function () {
        barcodeDetector = null;
        startScanLoop();
      });
  }
  startScanLoop();
  return null;
}

function startScanLoop() {
  if (scannerActive) {
    scannerRaf = requestAnimationFrame(scanTick);
  }
}

function scanTick() {
  if (!scannerActive) return;
  var video = getScannerVideo();
  if (video.readyState !== video.HAVE_ENOUGH_DATA) {
    scannerRaf = requestAnimationFrame(scanTick);
    return;
  }

  if (barcodeDetector) {
    barcodeDetector.detect(video)
      .then(function (codes) {
        if (codes && codes.length > 0) {
          handleDecoded(codes[0].rawValue);
        } else if (scannerActive) {
          scannerRaf = requestAnimationFrame(scanTick);
        }
      })
      .catch(function () {
        // a per-frame detector hiccup -> drop to jsQR for the rest of the session
        barcodeDetector = null;
        if (scannerActive) {
          scannerRaf = requestAnimationFrame(scanTick);
        }
      });
    return;
  }

  var result = decodeWithJsQR(video);
  if (result !== null) {
    handleDecoded(result);
  } else if (scannerActive) {
    scannerRaf = requestAnimationFrame(scanTick);
  }
}

function decodeWithJsQR(video) {
  if (typeof jsQR !== "function") return null;
  var width = video.videoWidth;
  var height = video.videoHeight;
  if (!width || !height) return null;
  var canvas = getScannerCanvas();
  canvas.width = width;
  canvas.height = height;
  var ctx = canvas.getContext("2d");
  ctx.drawImage(video, 0, 0, width, height);
  var imageData = ctx.getImageData(0, 0, width, height);
  var code = jsQR(imageData.data, width, height, { inversionAttempts: "dontInvert" });
  return code ? code.data : null;
}

// A QR was decoded. If it's one of our /fight/ codes, stop + navigate; otherwise
// keep scanning silently (don't toast every frame on an unrelated QR).
function handleDecoded(text) {
  var href = resolveFightUrl(text);
  if (href === null) {
    if (scannerActive) {
      scannerRaf = requestAnimationFrame(scanTick);
    }
    return;
  }
  scannerActive = false;
  stopCamera();
  getScannerOverlay().style.display = "none";
  showLoading();
  location = href;
}

function stopStream(stream) {
  if (stream) {
    stream.getTracks().forEach(function (track) { track.stop(); });
  }
}

function stopCamera() {
  if (scannerRaf !== null) {
    cancelAnimationFrame(scannerRaf);
    scannerRaf = null;
  }
  stopStream(scannerStream);
  scannerStream = null;
  var video = getScannerVideo();
  if (video) {
    video.pause();
    video.srcObject = null;
  }
}

function closeScanner() {
  scannerActive = false;
  stopCamera();
  getScannerOverlay().style.display = "none";
}

// Release the camera if the page is hidden/backgrounded or navigated away from.
document.addEventListener("visibilitychange", function () {
  if (document.hidden) {
    closeScanner();
  }
});
window.addEventListener("pagehide", closeScanner);

closeSidebar();
hideloading();
getCameraInputElement().addEventListener('change', uploadPicture, false)
