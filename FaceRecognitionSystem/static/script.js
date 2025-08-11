document.addEventListener("DOMContentLoaded", () => {
  // --- Dashboard Functionalities (Common to all pages) ---
  const darkToggle = document.getElementById("dark-mode-toggle");
  const languageSelect = document.getElementById("language") || document.getElementById("personnel-language");
  const timezoneSelect = document.getElementById("timezone");

  // Apply saved preferences (Dark Mode)
  if (localStorage.getItem("darkMode") === "true") {
    document.body.classList.add("dark-mode");
    if (darkToggle) darkToggle.checked = true;
  }

  if (darkToggle) {
    darkToggle.addEventListener("change", () => {
      const isDark = darkToggle.checked;
      document.body.classList.toggle("dark-mode", isDark);
      localStorage.setItem("darkMode", isDark);
    });
  }

  // Language Switching (assuming data-i18n attributes are used)
  const translations = {
    en: {
      title: "AI-BASED SURVEILLANCE SYSTEM",
      dark_mode: "Dark Mode",
      // Add other English translations here if needed for sidebar/header
    },
    fr: {
      title: "SYSTÈME DE SURVEILLANCE BASÉ SUR L'IA",
      dark_mode: "Mode Sombre",
      // Add other French translations here if needed for sidebar/header
    },
  };

  function applyLanguage(lang) {
    document.querySelectorAll("[data-i18n]").forEach(el => {
      const key = el.getAttribute("data-i18n");
      if (translations[lang] && translations[lang][key]) {
        el.textContent = translations[lang][key];
      }
    });
    // Update dark mode label if it's data-i18n
    if (darkToggle && darkToggle.nextElementSibling && translations[lang] && translations[lang].dark_mode) {
        darkToggle.nextElementSibling.textContent = translations[lang].dark_mode;
    }
  }

  const currentLang = localStorage.getItem("language") || "en";
  applyLanguage(currentLang);
  if (languageSelect) languageSelect.value = currentLang;

  if (languageSelect) {
    languageSelect.addEventListener("change", () => {
      const newLang = languageSelect.value;
      localStorage.setItem("language", newLang);
      applyLanguage(newLang);
    });
  }

  if (timezoneSelect) {
    timezoneSelect.value = localStorage.getItem("timezone") || "Africa/Lagos";
    timezoneSelect.addEventListener("change", () => {
      localStorage.setItem("timezone", timezoneSelect.value);
    });
  }

  function updateTime() {
    const now = new Date();
    const time = now.toLocaleTimeString("en-US", {
      timeZone: localStorage.getItem("timezone") || "Africa/Lagos"
    });
    const clock = document.getElementById("current-time"); // Assuming you have an element with this ID
    if (clock) clock.textContent = time;
  }
  setInterval(updateTime, 1000);
  updateTime();

  // --- Real-time Webcam Access and Face Recognition (Core Logic - only on overview pages) ---
  const video = document.getElementById('video');
  const canvas = document.getElementById('canvas');
  const context = canvas.getContext('2d');
  const detectionOverlay = document.getElementById('detection-overlay');
  const systemStatus = document.getElementById('system-status');
  const alarmStatus = document.getElementById('alarm-status');
  const alertSound = document.getElementById('alert-sound');
  const alertsList = document.getElementById('alerts-list'); // Assuming this ID exists in your HTML

  let isCameraReady = false;
  let processingInterval = null;
  const FRAME_INTERVAL_MS = 200; // Process frame every 200ms (5 FPS)

  // --- Webcam Setup ---
  async function setupCamera() {
    // Only attempt camera setup if the video element exists on the page
    if (!video) {
        console.info("Video element not found. Skipping camera setup (likely on a non-camera page).");
        return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true });
      video.srcObject = stream;
      video.onloadedmetadata = () => {
        video.play();
        // Adjust canvas size to match video stream
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        // Position canvas over video (these styles are critical for overlay)
        canvas.style.position = 'absolute';
        canvas.style.top = video.offsetTop + 'px';
        canvas.style.left = video.offsetLeft + 'px';
        canvas.style.display = 'block'; // Make canvas visible
        video.style.opacity = 0; // Hide video element, show only canvas with drawings
        isCameraReady = true;
        systemStatus.textContent = "Camera Ready. Processing frames...";
        startProcessing();
      };
    } catch (err) {
      console.error("Error accessing camera: ", err);
      systemStatus.textContent = "Error: Could not access camera.";
    }
  }

  // --- Frame Processing and Sending to Flask ---
  function startProcessing() {
    if (processingInterval) {
      clearInterval(processingInterval);
    }

    processingInterval = setInterval(() => {
      if (!isCameraReady || video.paused || video.ended) {
        return;
      }

      // Draw video frame onto canvas
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.drawImage(video, 0, 0, canvas.width, canvas.height);

      // Get image data from canvas
      const imageData = canvas.toDataURL('image/jpeg', 0.8); // JPEG for smaller size

      // Send to Flask backend
      fetch('/process_frame', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ image: imageData }),
      })
      .then(response => {
        if (response.redirected) {
            // If Flask redirects (e.g., to login page due to session expiry)
            window.location.href = response.url;
            return; // Stop further processing
        }
        return response.json();
      })
      .then(data => {
        // If data is undefined, it means we redirected
        if (!data) return;

        // Clear previous bounding boxes
        detectionOverlay.innerHTML = '';

        if (data.error) {
          console.error("Flask error:", data.error);
          systemStatus.textContent = `System Error: ${data.error}`;
          return;
        }

        // Display recognition results
        if (data.results && data.results.length > 0) {
          data.results.forEach(face => {
            const [x1, y1, x2, y2] = face.box;
            const name = face.name;
            const distance = face.distance !== null ? face.distance.toFixed(2) : '';

            // Create bounding box element
            const bboxDiv = document.createElement('div');
            bboxDiv.classList.add('bounding-box');
            bboxDiv.classList.add(name === 'Unknown' ? 'unknown' : 'known');
            // Position bounding box relative to the video/canvas
            bboxDiv.style.left = `${(x1 / video.videoWidth) * 100}%`;
            bboxDiv.style.top = `${(y1 / video.videoHeight) * 100}%`;
            bboxDiv.style.width = `${((x2 - x1) / video.videoWidth) * 100}%`;
            bboxDiv.style.height = `${((y2 - y1) / video.videoHeight) * 100}%`;

            // Add text (name and distance)
            const textSpan = document.createElement('span');
            textSpan.textContent = `${name} ${distance}`;
            bboxDiv.appendChild(textSpan);

            detectionOverlay.appendChild(bboxDiv);
          });
        } else {
          systemStatus.textContent = "No faces detected.";
        }

        // Handle alarm
        if (data.alarm) {
          alarmStatus.style.display = 'block';
          if (alertSound && alertSound.paused) { // Check if alertSound exists before playing
            alertSound.play().catch(e => console.error("Error playing sound:", e));
          }
          addAlert('danger', 'Unknown person detected!');
        } else {
          alarmStatus.style.display = 'none';
          if (alertSound) { // Check if alertSound exists before pausing/resetting
            alertSound.pause();
            alertSound.currentTime = 0; // Reset sound for next play
          }
        }
      })
      .catch(error => {
        console.error("Fetch error:", error);
        systemStatus.textContent = `Network Error: ${error.message}`;
        alarmStatus.style.display = 'none';
        if (alertSound) {
            alertSound.pause();
            alertSound.currentTime = 0;
        }
      });
    }, FRAME_INTERVAL_MS);
  }

  // --- Alert List Management ---
  function addAlert(type, message) {
    // Ensure alertsList exists before trying to add alerts
    if (!alertsList) {
        console.warn("Alerts list element not found. Cannot add alert.");
        return;
    }
    const timestamp = new Date().toLocaleTimeString();
    const newAlert = document.createElement('li');
    newAlert.classList.add(type); // 'danger', 'info', 'success'
    newAlert.innerHTML = `<span>[${timestamp}] ${message}</span>`;
    alertsList.prepend(newAlert); // Add to the top
    // Keep only the latest 5 alerts
    if (alertsList.children.length > 5) {
      alertsList.removeChild(alertsList.lastChild);
    }
  }

  // Initialize camera when the DOM is fully loaded, but only if video element exists
  // This ensures camera setup only runs on pages that have the video feed
  if (video) {
    setupCamera();
  }
});