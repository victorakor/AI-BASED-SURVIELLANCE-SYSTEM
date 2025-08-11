// Enhanced surveillance system script with complete functionality
// Combines all system functionalities including Firebase authentication,
// camera feed, sidebar, dark mode, user settings, and real-time updates.

// --- Firebase Imports ---
import { initializeApp } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-app.js";
import { getAuth, createUserWithEmailAndPassword, signInWithEmailAndPassword, onAuthStateChanged, signInWithCustomToken, signInAnonymously, updatePassword, signOut } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-auth.js";
import { getFirestore, setDoc, doc, collection, onSnapshot, addDoc, deleteDoc, updateDoc, getDoc, query, where, orderBy } from "https://www.gstatic.com/firebasejs/11.6.1/firebase-firestore.js";

// --- Firebase Configuration and Initialization ---
const appId = typeof __app_id !== 'undefined' ? __app_id : 'default-app-id';
const firebaseConfig = typeof __firebase_config !== 'undefined' ? JSON.parse(__firebase_config) : {};

let app;
let auth;
let db;

if (Object.keys(firebaseConfig).length > 0) {
    try {
        app = initializeApp(firebaseConfig);
        auth = getAuth(app);
        db = getFirestore(app);
    } catch (error) {
        console.error("Error initializing Firebase:", error);
    }
} else {
    console.error("Firebase configuration is missing. Cannot initialize Firebase.");
}

// --- Global Variables ---
let userId;
let userRole = 'anonymous';
let previousAlerts = [];
let systemData = {
    status: 'offline',
    threatLevel: 'Low',
    alertsToday: 0,
    camerasActive: '0/0'
};

// --- Utility Functions ---
const logout = async () => {
    try {
        await signOut(auth);
        console.log("User signed out.");
        window.location.href = "index.html";
    } catch (error) {
        console.error("Error signing out:", error);
    }
};

// Enhanced modal display function
function showModal(title, message, type, onConfirm = null) {
    const modal = document.createElement('div');
    modal.className = 'custom-modal';
    let modalContent = `
        <div class="modal-content">
            <span class="close-modal-btn">&times;</span>
            <div class="modal-header">
                <h2>${title}</h2>
            </div>
            <div class="modal-body">
                <p>${message}</p>
            </div>
    `;
    if (type === 'confirm') {
        modalContent += `
            <div class="modal-footer">
                <button class="modal-btn confirm-btn">Yes</button>
                <button class="modal-btn cancel-btn">No</button>
            </div>
        `;
    } else {
        modalContent += `
            <div class="modal-footer">
                <button class="modal-btn ok-btn">OK</button>
            </div>
        `;
    }
    modalContent += `</div>`;
    modal.innerHTML = modalContent;
    document.body.appendChild(modal);

    modal.querySelector('.close-modal-btn').addEventListener('click', () => {
        modal.remove();
    });

    if (type === 'confirm' && onConfirm) {
        modal.querySelector('.confirm-btn').addEventListener('click', () => {
            onConfirm(true);
            modal.remove();
        });
        modal.querySelector('.cancel-btn').addEventListener('click', () => {
            onConfirm(false);
            modal.remove();
        });
    } else {
        const okBtn = modal.querySelector('.ok-btn');
        if (okBtn) {
            okBtn.addEventListener('click', () => {
                modal.remove();
            });
        }
    }
}

// Helper function to show messages
function showMessage(message, divId) {
    var messageDiv = document.getElementById(divId);
    if (messageDiv) {
        messageDiv.style.display = "block";
        messageDiv.innerHTML = message;
        messageDiv.style.opacity = 1;
        setTimeout(() => {
            messageDiv.style.opacity = 0;
        }, 5000);
    }
}

// Enhanced API call function with error handling
async function apiCall(endpoint, method = 'GET', data = null) {
    try {
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            }
        };
        
        if (data) {
            options.body = JSON.stringify(data);
        }
        
        const response = await fetch(endpoint, options);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        return await response.json();
    } catch (error) {
        console.error(`API call failed for ${endpoint}:`, error);
        throw error;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    // --- Authentication State Listener ---
    if (auth) {
        onAuthStateChanged(auth, async (user) => {
            if (user) {
                console.log("User is signed in:", user.uid);
                userId = user.uid;

                // Fetch user role from Firestore
                const userDocRef = doc(db, 'artifacts', appId, 'public', 'data', 'users', userId);
                try {
                    const userDocSnap = await getDoc(userDocRef);
                    if (userDocSnap.exists()) {
                        userRole = userDocSnap.data().role;
                        console.log("User role:", userRole);
                    }
                    initializePageSpecificFunctions();
                } catch (error) {
                    console.error("Error fetching user role:", error);
                    window.location.href = "index.html";
                }
            } else {
                console.log("No user is signed in. Attempting to sign in with token or anonymously.");
                const currentPath = window.location.pathname;
                if (currentPath.endsWith('/index.html') || currentPath === '/') {
                    try {
                        if (typeof __initial_auth_token !== 'undefined' && __initial_auth_token) {
                            await signInWithCustomToken(auth, __initial_auth_token);
                        } else {
                            await signInAnonymously(auth);
                        }
                    } catch (error) {
                        console.error("Error signing in anonymously or with custom token:", error);
                    }
                } else {
                    window.location.href = "index.html";
                }
            }
        });
    }

    // --- Login/Signup Form Handling ---
    const signInForm = document.getElementById('signIn');
    const signUpForm = document.getElementById('signup');
    const signUpButton = document.getElementById('signUpButton');
    const signInButton = document.getElementById('signInButton');
    const logoutButton = document.getElementById('logout-button');

    if (signUpButton && signInForm && signUpForm) {
        signUpButton.addEventListener('click', () => {
            signInForm.style.display = "none";
            signUpForm.style.display = "block";
        });
    }

    if (signInButton && signInForm && signUpForm) {
        signInButton.addEventListener('click', () => {
            signInForm.style.display = "block";
            signUpForm.style.display = "none";
        });
    }

    if (logoutButton) {
        logoutButton.addEventListener('click', logout);
    }

    // Handle Signup
    const submitSignUp = document.getElementById('submitSignUp');
    if (submitSignUp) {
        submitSignUp.addEventListener('click', async (event) => {
            event.preventDefault();
            const email = document.getElementById('rEmail').value;
            const password = document.getElementById('rPassword').value;
            const firstName = document.getElementById('fName').value;
            const lastName = document.getElementById('lName').value;

            try {
                const userCredential = await createUserWithEmailAndPassword(auth, email, password);
                showMessage('Account Created Successfully', 'signUpMessage');
                const user = userCredential.user;
                const userDocRef = doc(db, 'artifacts', appId, 'public', 'data', 'users', user.uid);
                const userData = {
                    firstName: firstName,
                    lastName: lastName,
                    email: email,
                    role: 'personnel'
                };
                await setDoc(userDocRef, userData);
                window.location.href = '/personnel_overview.html';
            } catch (error) {
                const errorCode = error.code;
                console.error("Error during signup:", errorCode, error.message);
                if (errorCode === 'auth/email-already-in-use') {
                    showMessage('Email Address Already Exists !!!', 'signUpMessage');
                } else {
                    showMessage('Unable to create User', 'signUpMessage');
                }
            }
        });
    }

    // Handle Signin
    const submitSignIn = document.getElementById('submitSignIn');
    if (submitSignIn) {
        submitSignIn.addEventListener('click', async (event) => {
            event.preventDefault();
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            try {
                const userCredential = await signInWithEmailAndPassword(auth, email, password);
                const user = userCredential.user;
                const idToken = await user.getIdToken();

                const response = await fetch('/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ idToken: idToken })
                });

                if (!response.ok) {
                    throw new Error('Authentication failed on server.');
                }

                const data = await response.json();
                showMessage('Login successful', 'signInMessage');
                window.location.href = data.redirect_url;
            } catch (error) {
                console.error("Error during signin:", error);
                const errorCode = error.code;
                if (errorCode === 'auth/invalid-credential') {
                    showMessage('Incorrect Email or Password', 'signInMessage');
                } else {
                    showMessage('Account does not Exist', 'signInMessage');
                }
            }
        });
    }
});

// This function initializes page-specific functionality after authentication
function initializePageSpecificFunctions() {
    // --- Dark Mode Toggle ---
    const darkModeToggle = document.getElementById('dark-mode-toggle');
    const body = document.body;
    
    function applyTheme(theme) {
        if (theme === 'dark-mode') {
            body.classList.add('dark-mode');
            if (darkModeToggle) darkModeToggle.checked = true;
        } else {
            body.classList.remove('dark-mode');
            if (darkModeToggle) darkModeToggle.checked = false;
        }
    }
    
    const currentTheme = localStorage.getItem('theme');
    applyTheme(currentTheme);

    if (darkModeToggle) {
        darkModeToggle.addEventListener('change', () => {
            const newTheme = darkModeToggle.checked ? 'dark-mode' : 'light-mode';
            localStorage.setItem('theme', newTheme);
            applyTheme(newTheme);
        });
    }

    // --- Sidebar Toggle ---
    const sidebar = document.querySelector('.sidebar');
    const mainContent = document.querySelector('.main-content');
    const sidebarToggle = document.querySelector('.sidebar-toggle');
    const toggleIconDots = document.querySelector('.toggle-icon-dots');
    const toggleIconX = document.querySelector('.toggle-icon-x');

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', () => {
            sidebar.classList.toggle('expanded');
            if (mainContent) mainContent.classList.toggle('expanded');
            if (toggleIconDots && toggleIconX) {
                toggleIconDots.style.display = sidebar.classList.contains('expanded') ? 'none' : 'block';
                toggleIconX.style.display = sidebar.classList.contains('expanded') ? 'block' : 'none';
            }
        });
    }

    // --- Change Password Form (Personnel & Admin Settings) ---
    const changePasswordForm = document.getElementById('change-password-form');
    if (changePasswordForm) {
        changePasswordForm.addEventListener('submit', async (event) => {
            event.preventDefault();
            const newPassword = document.getElementById('new-password').value;
            const confirmPassword = document.getElementById('confirm-password').value;

            if (newPassword !== confirmPassword) {
                showModal('Error', 'Passwords do not match.', 'error');
                return;
            }

            if (newPassword.length < 6) {
                showModal('Error', 'Password must be at least 6 characters long.', 'error');
                return;
            }

            try {
                await apiCall('/api/change_password', 'POST', { password: newPassword });
                showModal('Success', 'Password has been changed successfully.', 'success');
                changePasswordForm.reset();
            } catch (error) {
                console.error('Error changing password:', error);
                showModal('Error', 'Failed to change password. Please try again.', 'error');
            }
        });
    }

    // --- Language Preference (Personnel Settings) ---
    const languageSelect = document.getElementById('personnel-language');
    const saveSettingsButton = document.getElementById('save-personnel-settings');

    function applyLanguagePreference() {
        const savedLanguage = localStorage.getItem('languagePreference') || 'en';
        if (languageSelect) {
            languageSelect.value = savedLanguage;
        }
        console.log(`Applying language: ${savedLanguage}`);
    }

    if (saveSettingsButton) {
        saveSettingsButton.addEventListener('click', () => {
            const selectedLanguage = languageSelect.value;
            localStorage.setItem('languagePreference', selectedLanguage);
            showModal('Success', 'Language preference saved.', 'success');
            applyLanguagePreference();
        });
    }
    applyLanguagePreference();

    // --- Page-specific function calls ---
    if (document.querySelector('#admin-overview-html') || document.querySelector('#personnel-overview-html')) {
        setupOverviewPage();
    }

    if (document.querySelector('#admin-alerts-html')) {
        setupAdminAlertsPage();
    }

    if (document.querySelector('#personnel-alerts-html')) {
        setupPersonnelAlertsPage();
    }

    if (document.querySelector('#admin-threat-config-html')) {
        setupAdminThreatConfigPage();
    }

    if (document.querySelector('#admin-activity-log-html')) {
        setupAdminActivityLogPage();
    }

    if (document.querySelector('#admin-camera-management-html')) {
        setupAdminCameraManagementPage();
    }
}

// --- Enhanced Overview Page Functions (Works for both Admin and Personnel) ---
function setupOverviewPage() {
    const video = document.getElementById('video');
    const alertSound = document.getElementById('alert-sound');
    const systemStatusElement = document.getElementById('system-status');
    const alertsTodayElement = document.getElementById('alerts-today');
    const threatLevelElement = document.getElementById('threat-level');
    const camerasActiveElement = document.getElementById('cameras-active');
    const recentAlertsList = document.getElementById('recent-alerts');

    // Video Feed Handling
    if (video) {
        video.src = '/video_feed';
        video.addEventListener('error', () => {
            console.error("Error loading video feed.");
            if (systemStatusElement) {
                systemStatusElement.textContent = 'Offline';
                systemStatusElement.className = 'status-error';
            }
        });
        video.addEventListener('loadedmetadata', () => {
            if (systemStatusElement) {
                systemStatusElement.textContent = 'Running';
                systemStatusElement.className = 'status-ok';
            }
        });
    }

    // Real-time system status updates
    const updateSystemStatus = async () => {
        try {
            const status = await apiCall('/api/system_status');
            systemData = status;

            if (systemStatusElement) {
                systemStatusElement.textContent = status.status.charAt(0).toUpperCase() + status.status.slice(1);
                systemStatusElement.className = status.status === 'running' ? 'status-ok' : 'status-error';
            }

            if (threatLevelElement) {
                threatLevelElement.textContent = status.threat_level;
                threatLevelElement.className = `threat-level-${status.threat_level.toLowerCase()}`;
            }

            if (alertsTodayElement) {
                alertsTodayElement.textContent = status.alerts_today;
                alertsTodayElement.className = status.alerts_today > 0 ? 'status-warning' : 'status-ok';
            }

            if (camerasActiveElement) {
                camerasActiveElement.textContent = status.cameras_active;
                camerasActiveElement.className = status.active_cameras === status.total_cameras ? 'status-ok' : 'status-warning';
            }
        } catch (error) {
            console.error('Error fetching system status:', error);
        }
    };

    // Real-time recent alerts updates
    const updateRecentAlerts = async () => {
        try {
            const alerts = await apiCall('/api/recent_alerts?limit=5');
            
            if (recentAlertsList) {
                recentAlertsList.innerHTML = '';
                
                if (alerts && alerts.length > 0) {
                    alerts.forEach(alert => {
                        const li = document.createElement('li');
                        const timestamp = alert.timestamp ? 
                            new Date(alert.timestamp.seconds * 1000).toLocaleTimeString() : 'N/A';
                        li.textContent = `${timestamp}: ${alert.detections.join(', ')} detected on ${alert.camera}`;
                        li.className = `alert-item threat-level-${alert.threatLevel.toLowerCase()}`;
                        recentAlertsList.appendChild(li);

                        // Check for high-priority alerts
                        if (alert.threatLevel === 'High' && !previousAlerts.includes(alert.id)) {
                            previousAlerts.push(alert.id);
                            if (alertSound) alertSound.play();
                            showModal('High-Priority Alert!', 'A new threat has been detected. Please check the alerts page.', 'warning');
                        }
                    });
                } else {
                    const li = document.createElement('li');
                    li.textContent = 'No recent alerts';
                    li.className = 'alert-item';
                    recentAlertsList.appendChild(li);
                }
            }
        } catch (error) {
            console.error('Error fetching recent alerts:', error);
        }
    };

    // Initial load and periodic updates
    updateSystemStatus();
    updateRecentAlerts();
    
    // Update every 5 seconds
    setInterval(updateSystemStatus, 5000);
    setInterval(updateRecentAlerts, 3000);

    // Firebase real-time listeners as backup
    onSnapshot(collection(db, "artifacts", appId, "public", "data", "alerts"), (snapshot) => {
        updateRecentAlerts();
    });

    onSnapshot(doc(db, "artifacts", appId, "public", "data", "system_status", "current"), (doc) => {
        updateSystemStatus();
    });
}

// --- Enhanced Admin Alerts Page Functions ---
function setupAdminAlertsPage() {
    const alertList = document.getElementById('alert-list');
    const filterButtons = document.querySelectorAll('.filter-btn');
    const alertCounter = document.getElementById('alert-counter');

    let currentFilter = 'unverified';
    let allAlerts = [];

    // Function to render alerts based on current filter
    const renderAlerts = (alerts) => {
        const filteredAlerts = alerts.filter(alert => {
            if (currentFilter === 'all') return true;
            return alert.status === currentFilter;
        });
        
        if (alertList) {
            alertList.innerHTML = '';
            
            if (filteredAlerts.length === 0) {
                alertList.innerHTML = '<li class="no-alerts">No alerts found for this filter.</li>';
                return;
            }
            
            filteredAlerts.forEach(alert => {
                const listItem = document.createElement('li');
                listItem.className = `alert-item status-${alert.status}`;
                
                const timestamp = alert.timestamp ? 
                    new Date(alert.timestamp.seconds * 1000).toLocaleString() : 'N/A';
                
                listItem.innerHTML = `
                    <div class="alert-details">
                        <span class="alert-time">${timestamp}</span>
                        <p><strong>Camera:</strong> ${alert.camera}</p>
                        <p><strong>Detections:</strong> ${alert.detections.join(', ')}</p>
                        <p><strong>Threat Level:</strong> <span class="threat-level-indicator level-${alert.threatLevel.toLowerCase()}">${alert.threatLevel}</span></p>
                        <p><strong>Status:</strong> <span class="status-badge status-${alert.status}">${alert.status.charAt(0).toUpperCase() + alert.status.slice(1)}</span></p>
                    </div>
                    <div class="alert-actions">
                        ${alert.status === 'unverified' ? `
                            <button class="verify-btn" data-id="${alert.id}">Verify</button>
                            <button class="dismiss-btn" data-id="${alert.id}">Dismiss</button>
                        ` : ''}
                    </div>
                `;
                alertList.appendChild(listItem);
            });
            
            // Update counter
            if (alertCounter) {
                alertCounter.textContent = `${filteredAlerts.length} alerts`;
            }
        }
    };

    // Load alerts
    const loadAlerts = async () => {
        try {
            const alerts = await apiCall('/api/alerts');
            allAlerts = alerts;
            renderAlerts(allAlerts);
        } catch (error) {
            console.error('Error loading alerts:', error);
            showModal('Error', 'Failed to load alerts. Please refresh the page.', 'error');
        }
    };

    // Filter button event listeners
    filterButtons.forEach(button => {
        button.addEventListener('click', (e) => {
            filterButtons.forEach(btn => btn.classList.remove('active'));
            e.target.classList.add('active');
            currentFilter = e.target.dataset.status;
            renderAlerts(allAlerts);
        });
    });

    // Alert action handlers
    if (alertList) {
        alertList.addEventListener('click', async (e) => {
            const target = e.target;
            
            if (target.classList.contains('verify-btn')) {
                const alertId = target.dataset.id;
                try {
                    await apiCall(`/api/alert/${alertId}`, 'PUT', { status: 'verified' });
                    showModal('Alert Verified', 'The alert has been marked as verified.', 'success');
                    loadAlerts(); // Reload alerts
                } catch (error) {
                    console.error('Error verifying alert:', error);
                    showModal('Error', 'Failed to verify alert. Please try again.', 'error');
                }
            }

            if (target.classList.contains('dismiss-btn')) {
                const alertId = target.dataset.id;
                showModal('Confirm Dismissal', 'Are you sure you want to dismiss this alert?', 'confirm', async (confirmed) => {
                    if (confirmed) {
                        try {
                            await apiCall(`/api/alert/${alertId}`, 'PUT', { status: 'dismissed' });
                            showModal('Alert Dismissed', 'The alert has been dismissed.', 'success');
                            loadAlerts(); // Reload alerts
                        } catch (error) {
                            console.error('Error dismissing alert:', error);
                            showModal('Error', 'Failed to dismiss alert. Please try again.', 'error');
                        }
                    }
                });
            }
        });
    }

    // Initial load
    loadAlerts();

    // Real-time updates
    onSnapshot(collection(db, "artifacts", appId, "public", "data", "alerts"), (snapshot) => {
        loadAlerts();
    });
}

// --- Personnel Alerts Page Functions ---
function setupPersonnelAlertsPage() {
    const alertList = document.getElementById('alert-list');
    const alertCounter = document.getElementById('alert-counter');

    const loadAlerts = async () => {
        try {
            const alerts = await apiCall('/api/alerts');
            
            if (alertList) {
                alertList.innerHTML = '';
                
                if (alerts.length === 0) {
                    alertList.innerHTML = '<li class="no-alerts">No alerts found.</li>';
                    return;
                }
                
                alerts.forEach(alert => {
                    const listItem = document.createElement('li');
                    listItem.className = 'alert-item';
                    
                    const timestamp = alert.timestamp ? 
                        new Date(alert.timestamp.seconds * 1000).toLocaleString() : 'N/A';
                    
                    listItem.innerHTML = `
                        <div class="alert-details">
                            <span class="alert-time">${timestamp}</span>
                            <p><strong>Camera:</strong> ${alert.camera}</p>
                            <p><strong>Detections:</strong> ${alert.detections.join(', ')}</p>
                            <p><strong>Threat Level:</strong> <span class="threat-level-indicator level-${alert.threatLevel.toLowerCase()}">${alert.threatLevel}</span></p>
                            <p><strong>Status:</strong> <span class="status-badge status-${alert.status}">${alert.status.charAt(0).toUpperCase() + alert.status.slice(1)}</span></p>
                        </div>
                    `;
                    alertList.appendChild(listItem);
                });
                
                if (alertCounter) {
                    alertCounter.textContent = `${alerts.length} alerts`;
                }
            }
        } catch (error) {
            console.error('Error loading alerts:', error);
            showModal('Error', 'Failed to load alerts. Please refresh the page.', 'error');
        }
    };

    // Initial load
    loadAlerts();

    // Real-time updates
    onSnapshot(collection(db, "artifacts", appId, "public", "data", "alerts"), (snapshot) => {
        loadAlerts();
    });
}

// --- Enhanced Camera Management Page Functions ---
function setupAdminCameraManagementPage() {
    const cameraModal = document.getElementById('camera-modal');
    const addCameraBtn = document.getElementById('add-camera-btn');
    const closeModalBtn = document.querySelector('.close-btn');
    const addCameraForm = document.getElementById('add-camera-form');
    const cameraTableBody = document.querySelector('#camera-table tbody');

    // Edit Camera Modal elements
    const editModal = document.getElementById('edit-camera-modal');
    const editForm = document.getElementById('edit-camera-form');
    const editCameraNameInput = document.getElementById('edit-camera-name');
    const editRtspUrlInput = document.getElementById('edit-rtsp-url');
    const closeEditModalBtn = document.querySelector('#edit-camera-modal .close-btn');
    let currentCameraId = null;

    // Load and display cameras
    const loadCameras = async () => {
        try {
            const cameras = await apiCall('/api/cameras');
            
            if (cameraTableBody) {
                cameraTableBody.innerHTML = '';
                cameras.forEach((camera) => {
                    const row = cameraTableBody.insertRow();
                    row.innerHTML = `
                        <td>${camera.name}</td>
                        <td>${camera.rtspUrl || camera.source || 'N/A'}</td>
                        <td>
                            <span class="status-badge status-${camera.status || 'active'}">${(camera.status || 'active').charAt(0).toUpperCase() + (camera.status || 'active').slice(1)}</span>
                        </td>
                        <td>
                            <button class="activate-camera-btn" data-id="${camera.id}" ${camera.is_default ? 'disabled' : ''}>
                                ${camera.is_default ? 'Active' : 'Activate'}
                            </button>
                            <button class="edit-camera-btn" data-id="${camera.id}">Edit</button>
                            <button class="delete-camera-btn" data-id="${camera.id}" ${camera.is_default ? 'disabled' : ''}>
                                Delete
                            </button>
                        </td>
                    `;
                });

                // Add event listeners to new buttons
                document.querySelectorAll('.activate-camera-btn').forEach(button => {
                    button.addEventListener('click', async (e) => {
                        const cameraId = e.target.dataset.id;
                        if (button.disabled) return;
                        
                        try {
                            await apiCall(`/api/cameras/${cameraId}/activate`, 'POST');
                            showModal('Success', 'Camera activated successfully.', 'success');
                            loadCameras();
                        } catch (error) {
                            console.error('Error activating camera:', error);
                            showModal('Error', 'Failed to activate camera.', 'error');
                        }
                    });
                });

                document.querySelectorAll('.edit-camera-btn').forEach(button => {
                    button.addEventListener('click', async (e) => {
                        currentCameraId = e.target.dataset.id;
                        const camera = cameras.find(c => c.id === currentCameraId);
                        if (camera) {
                            editCameraNameInput.value = camera.name;
                            editRtspUrlInput.value = camera.rtspUrl || camera.source || '';
                            editModal.style.display = 'block';
                        }
                    });
                });

                document.querySelectorAll('.delete-camera-btn').forEach(button => {
                    button.addEventListener('click', async (e) => {
                        if (button.disabled) return;
                        
                        const cameraId = e.target.dataset.id;
                        showModal('Confirm Deletion', 'Are you sure you want to delete this camera?', 'confirm', async (confirmed) => {
                            if (confirmed) {
                                try {
                                    await apiCall(`/api/cameras/${cameraId}`, 'DELETE');
                                    showModal('Success', 'Camera deleted successfully.', 'success');
                                    loadCameras();
                                } catch (error) {
                                    console.error('Error deleting camera:', error);
                                    showModal('Error', 'Failed to delete camera.', 'error');
                                }
                            }
                        });
                    });
                });
            }
        } catch (error) {
            console.error('Error loading cameras:', error);
            showModal('Error', 'Failed to load cameras. Please refresh the page.', 'error');
        }
    };

    // Modal handlers
    if (addCameraBtn) {
        addCameraBtn.addEventListener('click', () => {
            if (cameraModal) cameraModal.style.display = 'block';
        });
    }

    if (closeModalBtn) {
        closeModalBtn.addEventListener('click', () => {
            if (cameraModal) cameraModal.style.display = 'none';
        });
    }

    if (closeEditModalBtn) {
        closeEditModalBtn.addEventListener('click', () => {
            if (editModal) editModal.style.display = 'none';
        });
    }

    // Add camera form handler
    if (addCameraForm) {
        addCameraForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const cameraName = document.getElementById('camera-name').value;
            const rtspUrl = document.getElementById('rtsp-url').value;

            try {
                await apiCall('/api/cameras', 'POST', {
                    name: cameraName,
                    rtspUrl: rtspUrl
                });
                showModal('Success', 'New camera added successfully.', 'success');
                if (cameraModal) cameraModal.style.display = 'none';
                addCameraForm.reset();
                loadCameras();
            } catch (error) {
                console.error('Error adding camera:', error);
                showModal('Error', 'Failed to add camera. Please try again.', 'error');
            }
        });
    }

    // Edit camera form handler
    if (editForm) {
        editForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!currentCameraId) return;

            const newCameraName = editCameraNameInput.value;
            const newRtspUrl = editRtspUrlInput.value;

            try {
                await apiCall(`/api/cameras/${currentCameraId}`, 'PUT', {
                    name: newCameraName,
                    rtspUrl: newRtspUrl
                });
                showModal('Success', 'Camera details updated successfully.', 'success');
                if (editModal) editModal.style.display = 'none';
                editForm.reset();
                loadCameras();
            } catch (error) {
                console.error('Error updating camera:', error);
                showModal('Error', 'Failed to update camera. Please try again.', 'error');
            }
        });
    }

    // Initial load
    loadCameras();

    // Real-time updates
    onSnapshot(collection(db, "artifacts", appId, "public", "data", "cameras"), (snapshot) => {
        loadCameras();
    });
}

// --- Enhanced Threat Configuration Page Functions ---
function setupAdminThreatConfigPage() {
    const threatLevelSpan = document.getElementById('threat-level');
    const threatLevelDisplay = document.getElementById('current-threat-level');
    const threatDescription = document.getElementById('threat-description');

    const updateThreatDisplay = async () => {
        try {
            const threatConfig = await apiCall('/api/threat_config');
            const level = threatConfig.threat_level || threatConfig.level || 'Low';
            
            if (threatLevelSpan) {
                threatLevelSpan.textContent = level;
                threatLevelSpan.className = `level-indicator level-${level.toLowerCase()}`;
            }
            
            if (threatLevelDisplay) {
                threatLevelDisplay.textContent = level;
                threatLevelDisplay.className = `threat-level-${level.toLowerCase()}`;
            }
            
            if (threatDescription) {
                const descriptions = {
                    'Low': 'System is detecting basic violations like missing masks or improper face coverings.',
                    'High': 'System has detected weapons, dangerous items, or other high-priority security threats.',
                    'Medium': 'System is in normal monitoring mode with standard threat detection.'
                };
                threatDescription.textContent = descriptions[level] || 'Unknown threat level';
            }
        } catch (error) {
            console.error('Error fetching threat config:', error);
        }
    };

    // Initial load
    updateThreatDisplay();

    // Real-time updates
    onSnapshot(doc(db, "artifacts", appId, "public", "data", "settings", "threat_config"), (doc) => {
        updateThreatDisplay();
    });
}

// --- Enhanced Activity Log Page Functions ---
function setupAdminActivityLogPage() {
    const activityTableBody = document.querySelector('#activity-log-table tbody');
    const logCounter = document.getElementById('log-counter');
    const filterSelect = document.getElementById('log-filter');

    const loadActivityLogs = async () => {
        try {
            const logs = await apiCall('/api/activity_logs');
            
            if (activityTableBody) {
                activityTableBody.innerHTML = '';
                
                if (logs.length === 0) {
                    const row = activityTableBody.insertRow();
                    row.innerHTML = '<td colspan="6" class="no-data">No activity logs found.</td>';
                    return;
                }
                
                logs.forEach(log => {
                    const row = activityTableBody.insertRow();
                    const timestamp = log.timestamp ? 
                        new Date(log.timestamp.seconds * 1000).toLocaleString() : 'N/A';
                    
                    row.innerHTML = `
                        <td>${timestamp}</td>
                        <td>${log.user_id || 'System'}</td>
                        <td>${log.role || 'N/A'}</td>
                        <td>${log.camera || 'N/A'}</td>
                        <td>${Array.isArray(log.detections) ? log.detections.join(', ') : (log.detections || 'N/A')}</td>
                        <td>
                            ${log.threatLevel ? `<span class="threat-level-indicator level-${log.threatLevel.toLowerCase()}">${log.threatLevel}</span>` : 'N/A'}
                        </td>
                        <td>${log.status || 'N/A'}</td>
                        <td>${log.message || 'N/A'}</td>
                    `;
                });
                
                if (logCounter) {
                    logCounter.textContent = `${logs.length} logs`;
                }
            }
        } catch (error) {
            console.error('Error loading activity logs:', error);
            showModal('Error', 'Failed to load activity logs. Please refresh the page.', 'error');
        }
    };

    // Filter functionality
    if (filterSelect) {
        filterSelect.addEventListener('change', () => {
            loadActivityLogs(); // For now, reload all logs. In a real implementation, you'd filter on the backend
        });
    }

    // Initial load
    loadActivityLogs();

    // Real-time updates
    onSnapshot(collection(db, "artifacts", appId, "public", "data", "activity_logs"), (snapshot) => {
        loadActivityLogs();
    });
}

// --- Health Check Function ---
async function performHealthCheck() {
    try {
        const health = await apiCall('/api/health');
        console.log('System Health:', health);
        
        // Update UI based on health status if needed
        const healthIndicator = document.getElementById('health-indicator');
        if (healthIndicator) {
            healthIndicator.className = `health-${health.status}`;
            healthIndicator.textContent = health.status.toUpperCase();
        }
        
        return health;
    } catch (error) {
        console.error('Health check failed:', error);
        const healthIndicator = document.getElementById('health-indicator');
        if (healthIndicator) {
            healthIndicator.className = 'health-error';
            healthIndicator.textContent = 'ERROR';
        }
        return { status: 'error', error: error.message };
    }
}

// --- Initialize periodic health checks ---
setInterval(performHealthCheck, 30000); // Check every 30 seconds

// --- Keyboard Shortcuts ---
document.addEventListener('keydown', (event) => {
    // Ctrl/Cmd + R for refresh
    if ((event.ctrlKey || event.metaKey) && event.key === 'r') {
        event.preventDefault();
        location.reload();
    }
    
    // Escape key to close modals
    if (event.key === 'Escape') {
        const modals = document.querySelectorAll('.custom-modal, #camera-modal, #edit-camera-modal');
        modals.forEach(modal => {
            if (modal.style.display === 'block') {
                modal.style.display = 'none';
            }
        });
    }
});

// --- Window visibility change handler ---
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        // Page became visible, refresh data
        console.log('Page became visible, refreshing data...');
        performHealthCheck();
        
        // Trigger refresh of current page data
        const currentPage = window.location.pathname;
        if (currentPage.includes('overview')) {
            // Refresh overview data
        } else if (currentPage.includes('alerts')) {
            // Refresh alerts data
        }
        // Add more conditions as needed
    }
});

// --- Export functions for testing/debugging ---
if (typeof window !== 'undefined') {
    window.surveillanceSystem = {
        apiCall,
        showModal,
        performHealthCheck,
        systemData,
        userRole,
        userId
    };
}