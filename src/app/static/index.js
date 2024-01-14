function openSidebar() {
  document.getElementById("mySidebar").style.display = "block";
}

function closeSidebar() {
  document.getElementById("mySidebar").style.display = "none";
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
      location.replace(text);
    })
    .catch(response => {
      response.text().then(text => {
        if (text !== null && typeof text === "string" && text.length !== 0) {
          toastr.error(text);
        } else {
          toastr.error("Error scanning QR code.");
        }
      });
    });
  } catch (error) {
    toastr.error("Error sending QR code.");
  }
}

closeSidebar();
getCameraInputElement().addEventListener('change', uploadPicture, false)