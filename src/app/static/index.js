function openSidebar() {
  document.getElementById("mySidebar").style.display = "block";
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
      hideloading();
      location = text;
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

closeSidebar();
hideloading();
getCameraInputElement().addEventListener('change', uploadPicture, false)