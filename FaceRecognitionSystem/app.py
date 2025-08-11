import cv2
import dlib
import numpy as np
import os
import pickle
import base64
import json
import time
from flask import Flask, render_template, Response, request, jsonify, redirect, url_for, session, flash
from playsound import playsound # For playing alarm sound (ensure it's installed: pip install playsound)
import logging # Import logging module
from functools import wraps # For creating a decorator

# Flask App Initialization
app = Flask(__name__)
# IMPORTANT: Set a secret key for session management.
# In a production environment, this should be a strong, randomly generated key
# loaded from an environment variable or configuration file.
app.secret_key = 'your_very_secret_key_here_replace_me' # !!! CHANGE THIS IN PRODUCTION !!!

# Configure Logging
# Set up logging to console for better debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
ENCODINGS_FILE = os.path.join(BASE_DIR, "encodings.pkl")
TOLERANCE = 0.36
ALARM_SOUND_FILE = r"C:\Users\hp\.vscode\FinalProjectFolder\police-siren-sound-effect-317645.mp3"

# Global Variables for Face Recognition Models and Data
detector = None
predictor = None
face_recognizer = None
known_face_encodings = []
known_face_names = []

# Variable to track if alarm is currently playing to avoid re-triggering rapidly
alarm_playing = False
last_alarm_time = 0
ALARM_COOLDOWN = 5 # seconds before alarm can be triggered again

# User Management (Basic for Project - In real app, use a database)
USERS = {
    "admin": {"password": "admin123", "role": "admin"},
    "personnel1": {"password": "pass123", "role": "personnel"}
}

# Authentication Decorator
def login_required(role=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'username' not in session:
                flash('Please log in to access this page.', 'info')
                return redirect(url_for('login_page'))
            if role and session.get('role') != role:
                flash(f'Access denied. You need {role} privileges.', 'danger')
                # Redirect based on current role or to a generic access denied page
                if session.get('role') == 'admin':
                    return redirect(url_for('admin_overview_page'))
                elif session.get('role') == 'personnel':
                    return redirect(url_for('personnel_overview_page'))
                else:
                    return redirect(url_for('login_page')) # Fallback
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# Load Models and Encodings on App Startup
def load_models_and_encodings():
    global detector, predictor, face_recognizer, known_face_encodings, known_face_names

    app.logger.info("Loading dlib models...")
    try:
        detector = dlib.get_frontal_face_detector()
        predictor_path = os.path.join(MODELS_DIR, "shape_predictor_68_face_landmarks.dat")
        predictor = dlib.shape_predictor(predictor_path)
        face_recognizer_path = os.path.join(MODELS_DIR, "dlib_face_recognition_resnet_model_v1.dat")
        face_recognizer = dlib.face_recognition_model_v1(face_recognizer_path)
        app.logger.info("dlib models loaded successfully.")
    except Exception as e:
        app.logger.error(f"Error loading dlib models: {e}")
        app.logger.error(f"Make sure '{MODELS_DIR}' directory exists and contains the .dat files.")
        exit()

    app.logger.info(f"Loading known face encodings from '{ENCODINGS_FILE}'...")
    try:
        with open(ENCODINGS_FILE, 'rb') as f:
            data = pickle.load(f)
            known_face_encodings = data["encodings"]
            known_face_names = data["names"]
        app.logger.info(f"Loaded {len(known_face_encodings)} known faces for {len(set(known_face_names))} unique individuals.")
        if not known_face_encodings:
            app.logger.warning("Warning: No known faces loaded. The system will identify everyone as 'Unknown'.")
    except FileNotFoundError:
        app.logger.error(f"Error: '{ENCODINGS_FILE}' not found. Please run the model_evaluation script first.")
        exit()
    except Exception as e:
        app.logger.error(f"Error loading encodings from '{ENCODINGS_FILE}': {e}")
        exit()

with app.app_context():
    load_models_and_encodings()

# Helper Function for Face Recognition
def recognize_face(rgb_image):
    global alarm_playing, last_alarm_time

    faces_in_frame = detector(rgb_image, 0)

    results = []
    unknown_face_detected_in_this_frame = False

    if not faces_in_frame:
        return [], False

    for face_rect in faces_in_frame:
        shape = predictor(rgb_image, face_rect)
        face_encoding = np.array(face_recognizer.compute_face_descriptor(rgb_image, shape))

        name = "Unknown"
        
        if known_face_encodings:
            distances = np.linalg.norm(known_face_encodings - face_encoding, axis=1)
            min_distance_idx = np.argmin(distances)
            min_distance = distances[min_distance_idx]

            if min_distance < TOLERANCE:
                name = known_face_names[min_distance_idx]
            else:
                unknown_face_detected_in_this_frame = True
        else:
            unknown_face_detected_in_this_frame = True

        x1, y1, x2, y2 = face_rect.left(), face_rect.top(), face_rect.right(), face_rect.bottom()
        
        results.append({
            "name": name,
            "box": [x1, y1, x2, y2],
            "distance": float(min_distance) if known_face_encodings else None
        })

    if unknown_face_detected_in_this_frame:
        current_time = time.time()
        if not alarm_playing and (current_time - last_alarm_time) > ALARM_COOLDOWN:
            app.logger.warning("SERVER ALARM: Unknown face detected!")
            try:
                playsound(ALARM_SOUND_FILE, block=False)
                alarm_playing = True
                last_alarm_time = current_time
            except Exception as e:
                app.logger.error(f"Error playing alarm sound: {e}. Make sure '{ALARM_SOUND_FILE}' exists and is accessible.")
        return results, True
    else:
        alarm_playing = False
        return results, False

# Flask Routes
@app.route('/')
def root_redirect():
    """Redirects to the login page if not authenticated, otherwise to personnel overview."""
    if 'username' not in session:
        return redirect(url_for('login_page'))
    # Redirect based on role after successful login
    if session.get('role') == 'admin':
        return redirect(url_for('admin_overview_page'))
    else: # Default to personnel for non-admin or if role is personnel
        return redirect(url_for('personnel_overview_page'))


@app.route('/login', methods=['GET', 'POST'])
def login_page():
    """Handles user login."""
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        user = USERS.get(username)
        if user and user['password'] == password:
            session['username'] = username
            session['role'] = user['role']
            flash('Logged in successfully!', 'success')
            if user['role'] == 'admin':
                return redirect(url_for('admin_overview_page'))
            else:
                return redirect(url_for('personnel_overview_page'))
        else:
            flash('Invalid username or password.', 'danger')
    return render_template('index.html') # Render index.html as the login page

@app.route('/logout')
def logout():
    """Logs out the current user."""
    session.pop('username', None)
    session.pop('role', None)
    flash('You have been logged out.', 'info')
    return redirect(url_for('login_page'))

# Admin Pages
@app.route('/admin_overview.html')
@login_required(role='admin')
def admin_overview_page():
    """Renders the admin overview HTML page, requires admin role."""
    return render_template('admin_overview.html')

@app.route('/admin_camera_management.html')
@login_required(role='admin')
def admin_camera_management_page():
    """Renders the admin camera management HTML page, requires admin role."""
    return render_template('admin_camera_management.html')

@app.route('/admin_alerts.html')
@login_required(role='admin')
def admin_alerts_page():
    """Renders the admin alerts HTML page, requires admin role."""
    return render_template('admin_alerts.html')

@app.route('/admin_threat_config.html')
@login_required(role='admin')
def admin_threat_config_page():
    """Renders the admin detection config HTML page, requires admin role."""
    return render_template('admin_threat_config.html')

@app.route('/admin_activity_log.html')
@login_required(role='admin')
def admin_activity_log_page():
    """Renders the admin activity logs HTML page, requires admin role."""
    return render_template('admin_activity_log.html')

@app.route('/admin_settings.html')
@login_required(role='admin')
def admin_settings_page():
    """Renders the admin settings HTML page, requires admin role."""
    return render_template('admin_settings.html')

# Personnel Pages
@app.route('/personnel_overview.html')
@login_required() # No specific role required, just logged in
def personnel_overview_page():
    """Renders the personnel overview HTML page, requires login."""
    return render_template('personnel_overview.html')

@app.route('/personnel_alerts.html')
@login_required() # No specific role required, just logged in
def personnel_alerts_page():
    """Renders the personnel alerts HTML page, requires login."""
    return render_template('personnel_alerts.html')

@app.route('/personnel_settings.html')
@login_required() # No specific role required, just logged in
def personnel_settings_page():
    """Renders the personnel settings HTML page, requires login."""
    return render_template('personnel_settings.html')


@app.route('/process_frame', methods=['POST'])
@login_required() # Ensure only logged-in users can send frames
def process_frame():
    """
    Receives a base64 encoded image frame, processes it for face recognition,
    and returns recognition results and alarm status.
    """
    data = request.json
    if 'image' not in data:
        app.logger.error("No image data provided in process_frame request.")
        return jsonify({"error": "No image data provided"}), 400

    img_data = data['image'].split(',')[1]
    nparr = np.frombuffer(base64.b64decode(img_data), np.uint8)
    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if frame is None:
        app.logger.error("Could not decode image in process_frame.")
        return jsonify({"error": "Could not decode image"}), 400

    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

    try:
        recognition_results, trigger_alarm = recognize_face(rgb_frame)
    except Exception as e:
        app.logger.error(f"Error during face recognition in process_frame: {e}")
        return jsonify({"error": "Error during face recognition"}), 500

    return jsonify({
        "results": recognition_results,
        "alarm": trigger_alarm
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)