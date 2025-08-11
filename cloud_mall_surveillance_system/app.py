import os
import cv2
import json
import base64
import numpy as np
import threading
import time
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash, Response
from flask_cors import CORS
from firebase_admin import credentials, firestore, initialize_app, auth
from werkzeug.security import generate_password_hash, check_password_hash
from ultralytics import YOLO
from datetime import datetime, timedelta
from functools import wraps
import time

# Initialize Flask App
app = Flask(__name__)
CORS(app)
app.secret_key = os.urandom(24)

# --- Firebase Admin SDK Initialization ---
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    SERVICE_ACCOUNT_KEY_PATH = os.path.join(BASE_DIR, 'firebase-adminsdk.json')

    cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
    initialize_app(cred)
    db = firestore.client()
    print("Firebase Admin SDK initialized successfully.")
except Exception as e:
    print(f"Failed to initialize Firebase Admin SDK: {e}")
    db = None

# --- YOLOv8 Model Initialization ---
try:
    model_path = os.path.join(os.path.dirname(__file__), 'models', 'best.pt')
    if not os.path.exists(model_path):
        raise FileNotFoundError(f"YOLOv8 model not found at {model_path}")
    model = YOLO(model_path)
    print("YOLOv8 model loaded successfully for Flask app!")
except FileNotFoundError as e:
    print(f"Error loading YOLOv8 model: {e}")
    model = None
except Exception as e:
    print(f"An unexpected error occurred while loading YOLOv8 model: {e}")
    model = None

# --- Global Variables for Video Stream and Detection ---
video_stream = None
detection_active = False
frame_lock = threading.Lock()
current_camera_id = None
system_status = "offline"
current_threat_level = "Low"
total_detections = 0
last_object_detected = "N/A"

# --- Utility Functions ---
def get_app_id():
    return os.environ.get('__app_id', 'default-app-id')

def log_activity(user_id, role, message, camera_name="Unknown", detections=None, threat_level="Low"):
    """Enhanced activity logging with more details."""
    if db:
        try:
            app_id = get_app_id()
            activity_data = {
                'user_id': user_id,
                'role': role,
                'message': message,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'camera': camera_name,
                'detections': detections or [],
                'threatLevel': threat_level,
                'status': 'verified'
            }
            logs_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('activity_logs')
            logs_ref.add(activity_data)
            print(f"Activity logged for user {user_id}: {message}")
        except Exception as e:
            print(f"Error logging activity: {e}")

def update_system_status(status):
    """Update system status in Firebase and global variable."""
    global system_status
    system_status = status
    if db:
        try:
            app_id = get_app_id()
            status_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('system_status').document('current')
            status_ref.set({
                'status': status,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'threat_level': current_threat_level,
                'total_detections': total_detections,
                'last_object_detected': last_object_detected
            }, merge=True)
            print(f"System status updated to: {status}")
        except Exception as e:
            print(f"Error updating system status: {e}")

def update_threat_level(level):
    """Update current threat level globally and in Firebase."""
    global current_threat_level
    current_threat_level = level
    if db:
        try:
            app_id = get_app_id()
            threat_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('settings').document('threat_config')
            threat_ref.set({
                'threat_level': level,
                'level': level,
                'timestamp': firestore.SERVER_TIMESTAMP
            }, merge=True)
            print(f"Threat level updated to: {level}")
        except Exception as e:
            print(f"Error updating threat level: {e}")

# --- Custom Decorator for Firebase Authentication ---
def firebase_authenticated(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'uid' not in session:
            flash("Please log in to access this page.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- Admin User Creation Logic ---
def create_default_admin_user():
    """Creates a default admin user if one does not already exist."""
    admin_email = "admin@example.com"
    admin_password = "password123"

    try:
        user_record = auth.get_user_by_email(admin_email)
        print("Default admin user already exists.")
        return user_record.uid
    except auth.UserNotFoundError:
        try:
            print("Creating default admin user...")
            user = auth.create_user(
                email=admin_email,
                password=admin_password
            )
            app_id = get_app_id()
            user_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('users').document(user.uid)
            user_doc_ref.set({
                'email': admin_email,
                'firstName': 'System',
                'lastName': 'Admin',
                'role': 'admin',
                'created_at': firestore.SERVER_TIMESTAMP
            })
            print(f"Default admin user created successfully with UID: {user.uid}")
            return user.uid
        except Exception as e:
            print(f"Error creating default admin user: {e}")
            return None
    except Exception as e:
        print(f"Error checking for default admin user: {e}")
        return None

def register_default_webcam():
    """Registers default webcam in Firestore if it doesn't exist."""
    global current_camera_id
    if db:
        try:
            app_id = get_app_id()
            cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
            
            # Check if default webcam already exists
            existing_cameras = list(cameras_ref.where('is_default', '==', True).limit(1).stream())
            
            if not existing_cameras:
                print("Default webcam not found in Firestore. Registering now...")
                doc_ref = cameras_ref.document()
                camera_data = {
                    'id': doc_ref.id,
                    'name': 'Default Webcam',
                    'rtspUrl': '0',
                    'source': '0',
                    'is_active': True,
                    'status': 'active',
                    'is_default': True,
                    'timestamp': firestore.SERVER_TIMESTAMP
                }
                doc_ref.set(camera_data)
                current_camera_id = doc_ref.id
                print(f"Default webcam registered successfully with ID: {doc_ref.id}")
            else:
                # Get the default camera ID
                for doc in existing_cameras:
                    current_camera_id = doc.id
                    print(f"Found existing default webcam with ID: {current_camera_id}")
                    break

        except Exception as e:
            print(f"Error registering default webcam: {e}")

def initialize_system_collections():
    """Initialize required Firebase collections with default data."""
    if not db:
        return
    
    try:
        app_id = get_app_id()
        
        # Initialize system status
        status_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('system_status').document('current')
        status_ref.set({
            'status': 'starting',
            'threat_level': 'Low',
            'timestamp': firestore.SERVER_TIMESTAMP,
            'total_detections': 0,
            'last_object_detected': 'N/A'
        }, merge=True)
        
        # Initialize threat config
        threat_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('settings').document('threat_config')
        threat_ref.set({
            'threat_level': 'Low',
            'level': 'Low',
            'monitored_objects': ['knife', 'gun', 'person'],
            'timestamp': firestore.SERVER_TIMESTAMP
        }, merge=True)
        
        print("System collections initialized successfully.")
        
    except Exception as e:
        print(f"Error initializing system collections: {e}")

# Initialize system on startup
admin_uid = None
if db:
    admin_uid = create_default_admin_user()
    register_default_webcam()
    initialize_system_collections()
    update_system_status("starting")

# --- Enhanced Camera Management Class ---
class VideoCapture:
    """Enhanced video capture class with better error handling and reconnection."""
    def __init__(self, source=0):
        self.source = source
        self.cap = None
        self.last_frame_time = time.time()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 3
        
        self.connect()

    def connect(self):
        """Establish connection to video source."""
        try:
            # Handle different source types
            if isinstance(self.source, str) and self.source.isdigit():
                source = int(self.source)
            else:
                source = self.source

            self.cap = cv2.VideoCapture(source)
            
            # Set camera properties for better performance
            if self.cap.isOpened():
                self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                self.cap.set(cv2.CAP_PROP_FPS, 30)
                
                print(f"Successfully opened video source at {source}")
                self.reconnect_attempts = 0
                update_system_status("running")
                return True
            else:
                print(f"Failed to open video source at {source}")
                update_system_status("offline")
                return False
        except Exception as e:
            print(f"Error connecting to video source {self.source}: {e}")
            update_system_status("offline")
            return False

    def get_frame(self):
        """Get frame with automatic reconnection on failure."""
        if not self.cap or not self.cap.isOpened():
            if self.reconnect_attempts < self.max_reconnect_attempts:
                print("Attempting to reconnect to camera...")
                self.reconnect_attempts += 1
                if self.connect():
                    return self.get_frame()
            update_system_status("offline")
            return None

        ret, frame = self.cap.read()
        if ret:
            self.last_frame_time = time.time()
            self.reconnect_attempts = 0
            if system_status != "running":
                update_system_status("running")
            return frame
        else:
            # Check if we haven't received a frame for too long
            if time.time() - self.last_frame_time > 5.0:  # 5 seconds timeout
                print("No frames received, attempting reconnection...")
                self.release()
                self.connect()
            return None

    def release(self):
        """Release video capture resources."""
        if self.cap:
            self.cap.release()
            self.cap = None

    def switch_source(self, new_source):
        """Switch to a new video source."""
        self.release()
        self.source = new_source
        self.reconnect_attempts = 0
        return self.connect()

# --- Enhanced Video Streaming and Detection Logic ---
def generate_frames():
    """Enhanced frame generator with improved detection and logging."""
    global video_stream, detection_active, frame_lock, current_camera_id, current_threat_level
    global total_detections, last_object_detected

    alert_cooldown = {}
    cooldown_duration = 5  # seconds

    while True:
        with frame_lock:
            if video_stream is None or not video_stream.cap or not video_stream.cap.isOpened():
                time.sleep(1)
                continue

            frame = video_stream.get_frame()
            if frame is not None:
                # Run YOLOv8 inference on the frame
                if model:
                    try:
                        results = model(frame)
                        annotated_frame = results[0].plot()

                        # Get detections for logging
                        detections = []
                        if results[0].boxes is not None:
                            for box in results[0].boxes:
                                class_id = int(box.cls)
                                class_name = model.names[class_id]
                                detections.append(class_name)

                        # Update global detection stats
                        if detections:
                            total_detections += len(detections)
                            last_object_detected = detections[-1]

                        # Determine threat level based on detections
                        threat_level = 'Low'
                        if any(detection in ["weapon", "other_coverings", "knife", "gun"] for detection in detections):
                            threat_level = 'High'
                        elif any(detection in ["medical_mask", "nomask", "person"] for detection in detections):
                            threat_level = 'Low'

                        # Update global threat level if changed
                        if threat_level != current_threat_level:
                            update_threat_level(threat_level)

                        # Log to Firestore if detections are made and cooldown has passed
                        if detections and db:
                            current_time = time.time()
                            detection_key = f"{current_camera_id}_{'-'.join(sorted(detections))}"
                            
                            if detection_key not in alert_cooldown or (current_time - alert_cooldown[detection_key]) > cooldown_duration:
                                alert_cooldown[detection_key] = current_time
                                
                                # Get current camera name
                                camera_name = "Unknown Camera"
                                if current_camera_id:
                                    try:
                                        app_id = get_app_id()
                                        camera_doc = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras').document(current_camera_id).get()
                                        if camera_doc.exists:
                                            camera_name = camera_doc.to_dict().get('name', 'Unknown Camera')
                                    except Exception as e:
                                        print(f"Error fetching camera name: {e}")
                                
                                # Log alert to Firebase
                                try:
                                    app_id = get_app_id()
                                    alerts_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('alerts')
                                    alert_doc = alerts_ref.add({
                                        'camera': camera_name,
                                        'camera_id': current_camera_id,
                                        'detections': detections,
                                        'threatLevel': threat_level,
                                        'status': 'unverified',
                                        'timestamp': firestore.SERVER_TIMESTAMP
                                    })
                                    print(f"Alert logged: {detections} - {threat_level} priority on {camera_name}")
                                    
                                    # Also log system activity
                                    if admin_uid:
                                        log_activity(
                                            admin_uid, 
                                            'system', 
                                            f"Auto-detection: {', '.join(detections)} detected",
                                            camera_name,
                                            detections,
                                            threat_level
                                        )
                                        
                                except Exception as e:
                                    print(f"Error logging alert to Firebase: {e}")

                    except Exception as e:
                        print(f"Error during YOLO inference: {e}")
                        annotated_frame = frame
                else:
                    annotated_frame = frame

                # Encode frame to JPEG
                ret, buffer = cv2.imencode('.jpg', annotated_frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                if not ret:
                    continue

                frame = buffer.tobytes()
                yield (b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            else:
                time.sleep(0.1)

# --- Routes ---
@app.route('/')
def index():
    if 'uid' in session:
        user_role = session.get('role', 'anonymous')
        if user_role == 'admin':
            return redirect(url_for('admin_overview_page'))
        else:
            return redirect(url_for('personnel_overview_page'))
    return render_template('index.html')

@app.route('/login', methods=['POST'])
def login():
    try:
        id_token = request.json.get('idToken')
        if not id_token:
            return jsonify({'error': 'ID token not provided'}), 400

        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token['uid']

        expires_in = timedelta(hours=5)
        session_cookie = auth.create_session_cookie(id_token, expires_in=expires_in)
        session['uid'] = uid

        # Fetch user role from Firestore
        app_id = get_app_id()
        user_doc = db.collection('artifacts').document(app_id).collection('public').document('data').collection('users').document(uid).get()
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_role = user_data.get('role', 'personnel')
        else:
            user_role = 'personnel'

        session['role'] = user_role

        # Log login activity
        log_activity(uid, user_role, "User logged in")

        if user_role == 'admin':
            redirect_url = url_for('admin_overview_page')
        else:
            redirect_url = url_for('personnel_overview_page')

        return jsonify({'status': 'success', 'redirect_url': redirect_url})

    except auth.InvalidIdTokenError:
        return jsonify({'error': 'Invalid ID token'}), 401
    except Exception as e:
        print(f"Login error: {e}")
        return jsonify({'error': 'Authentication failed'}), 500

@app.route('/logout')
def logout():
    if 'uid' in session:
        log_activity(session['uid'], session.get('role', 'unknown'), "User logged out")
    session.pop('uid', None)
    session.pop('role', None)
    return redirect(url_for('index'))

# --- Admin Routes ---
@app.route('/admin_overview')
@firebase_authenticated
def admin_overview_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_overview.html')

@app.route('/admin_camera_management')
@firebase_authenticated
def admin_camera_management_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_camera_management.html')

@app.route('/admin_alerts')
@firebase_authenticated
def admin_alerts_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_alerts.html')

@app.route('/admin_threat_config')
@firebase_authenticated
def admin_threat_config_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_threat_config.html')

@app.route('/admin_activity_log')
@firebase_authenticated
def admin_activity_log_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_activity_log.html')

@app.route('/admin_settings')
@firebase_authenticated
def admin_settings_page():
    if session.get('role') != 'admin':
        return redirect(url_for('personnel_overview_page'))
    return render_template('admin_settings.html')

# --- Personnel Routes ---
@app.route('/personnel_overview')
@firebase_authenticated
def personnel_overview_page():
    return render_template('personnel_overview.html')

@app.route('/personnel_alerts')
@firebase_authenticated
def personnel_alerts_page():
    return render_template('personnel_alerts.html')

@app.route('/personnel_settings')
@firebase_authenticated
def personnel_settings_page():
    return render_template('personnel_settings.html')

# --- Enhanced API Endpoints ---

@app.route('/api/system_status', methods=['GET'])
@firebase_authenticated
def get_system_status():
    """Get current system status and statistics."""
    try:
        app_id = get_app_id()
        
        # Get system status from Firebase
        status_doc = db.collection('artifacts').document(app_id).collection('public').document('data').collection('system_status').document('current').get()
        system_data = status_doc.to_dict() if status_doc.exists else {}
        
        # Get alerts count for today
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        alerts_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('alerts')
        alerts_today_query = alerts_ref.where('timestamp', '>=', today).stream()
        alerts_today = len(list(alerts_today_query))
        
        # Get active cameras count
        cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
        cameras = list(cameras_ref.stream())
        total_cameras = len(cameras)
        active_cameras = len([cam for cam in cameras if cam.to_dict().get('status', 'active') == 'active'])
        
        response_data = {
            'status': system_data.get('status', system_status),
            'threat_level': system_data.get('threat_level', current_threat_level),
            'alerts_today': alerts_today,
            'cameras_active': f"{active_cameras}/{total_cameras}",
            'active_cameras': active_cameras,
            'total_cameras': total_cameras,
            'total_detections': system_data.get('total_detections', total_detections),
            'last_object_detected': system_data.get('last_object_detected', last_object_detected)
        }
        
        return jsonify(response_data)
        
    except Exception as e:
        print(f"Error fetching system status: {e}")
        return jsonify({"error": "Failed to fetch system status"}), 500

@app.route('/api/alerts', methods=['GET'])
@firebase_authenticated
def get_alerts():
    try:
        status_filter = request.args.get('status', 'all')
        limit = int(request.args.get('limit', 50))
        
        app_id = get_app_id()
        alerts_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('alerts')
        
        # Get all alerts and filter in Python since Firestore has limitations with orderBy + where
        all_alerts = list(alerts_ref.stream())
        
        alerts = []
        for doc in all_alerts:
            alert_data = doc.to_dict()
            alert_data['id'] = doc.id
            
            # Apply status filter
            if status_filter == 'all' or alert_data.get('status') == status_filter:
                alerts.append(alert_data)
        
        # Sort by timestamp (most recent first)
        alerts.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)
        
        # Apply limit
        alerts = alerts[:limit]
        
        return jsonify(alerts)
        
    except Exception as e:
        print(f"Error fetching alerts: {e}")
        return jsonify({"error": "Failed to fetch alerts"}), 500
        
@app.route('/api/alert/<alert_id>', methods=['PUT'])
@firebase_authenticated
def update_alert(alert_id):
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        data = request.json
        new_status = data.get('status')
        
        if new_status not in ['verified', 'dismissed', 'unverified']:
            return jsonify({"error": "Invalid status"}), 400
        
        app_id = get_app_id()
        alerts_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('alerts').document(alert_id)
        
        # Get the alert data before updating
        alert_doc = alerts_doc_ref.get()
        if not alert_doc.exists:
            return jsonify({"error": "Alert not found"}), 404
            
        alert_data = alert_doc.to_dict()
        
        # Update the alert
        alerts_doc_ref.update({
            'status': new_status,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'updated_by': session['uid']
        })
        
        # Log activity based on status change
        if new_status == 'verified':
            log_activity(
                session['uid'], 
                session.get('role'), 
                f"Alert verified - {', '.join(alert_data.get('detections', []))} detected on {alert_data.get('camera', 'Unknown')}",
                alert_data.get('camera', 'Unknown'),
                alert_data.get('detections', []),
                alert_data.get('threatLevel', 'Low')
            )
        elif new_status == 'dismissed':
            log_activity(
                session['uid'], 
                session.get('role'), 
                f"Alert dismissed - ID: {alert_id}",
                alert_data.get('camera', 'Unknown'),
                alert_data.get('detections', []),
                alert_data.get('threatLevel', 'Low')
            )
            
        return jsonify({"success": True, "message": f"Alert {new_status} successfully"})
        
    except Exception as e:
        print(f"Error updating alert: {e}")
        return jsonify({"error": "Failed to update alert"}), 500

@app.route('/api/cameras', methods=['GET', 'POST'])
@firebase_authenticated
def handle_cameras():
    app_id = get_app_id()
    cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
    
    if request.method == 'GET':
        try:
            cameras = []
            for doc in cameras_ref.stream():
                camera_data = doc.to_dict()
                camera_data['id'] = doc.id
                cameras.append(camera_data)
            return jsonify(cameras)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({"error": "Unauthorized"}), 403
        
        try:
            data = request.json
            camera_name = data.get('name', '').strip()
            rtsp_url = data.get('rtspUrl', '').strip()
            
            if not camera_name or not rtsp_url:
                return jsonify({"error": "Camera name and RTSP URL are required"}), 400
            
            new_camera_doc = cameras_ref.document()
            camera_data = {
                'id': new_camera_doc.id,
                'name': camera_name,
                'rtspUrl': rtsp_url,
                'source': rtsp_url,
                'status': 'active',
                'is_active': True,
                'is_default': False,
                'timestamp': firestore.SERVER_TIMESTAMP
            }
            new_camera_doc.set(camera_data)
            
            # Log activity
            log_activity(
                session['uid'], 
                'admin', 
                f"New camera '{camera_name}' added with RTSP: {rtsp_url}"
            )
            
            return jsonify({"success": True, "message": "Camera added successfully.", "camera": camera_data})
            
        except Exception as e:
            print(f"Error adding camera: {e}")
            return jsonify({"error": "Failed to add camera"}), 500

@app.route('/api/cameras/<camera_id>', methods=['PUT', 'DELETE'])
@firebase_authenticated
def manage_camera(camera_id):
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    app_id = get_app_id()
    cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
    camera_doc_ref = cameras_ref.document(camera_id)
    
    if request.method == 'PUT':
        try:
            data = request.json
            update_data = {}
            
            if 'name' in data:
                update_data['name'] = data['name'].strip()
            if 'rtspUrl' in data:
                update_data['rtspUrl'] = data['rtspUrl'].strip()
                update_data['source'] = data['rtspUrl'].strip()
            if 'status' in data:
                update_data['status'] = data['status']
                update_data['is_active'] = data['status'] == 'active'
                
            update_data['updated_at'] = firestore.SERVER_TIMESTAMP
            
            camera_doc_ref.update(update_data)
            
            log_activity(
                session['uid'], 
                'admin', 
                f"Camera {camera_id} updated"
            )
            
            return jsonify({"success": True, "message": "Camera updated successfully."})
            
        except Exception as e:
            print(f"Error updating camera: {e}")
            return jsonify({"error": "Failed to update camera"}), 500
            
    elif request.method == 'DELETE':
        try:
            # Check if this is the default camera
            camera_doc = camera_doc_ref.get()
            if camera_doc.exists and camera_doc.to_dict().get('is_default'):
                return jsonify({"error": "Cannot delete default camera"}), 400
                
            camera_data = camera_doc.to_dict()
            camera_doc_ref.delete()
            
            log_activity(
                session['uid'], 
                'admin', 
                f"Camera '{camera_data.get('name', 'Unknown')}' deleted"
            )
            
            return jsonify({"success": True, "message": "Camera deleted successfully."})
            
        except Exception as e:
            print(f"Error deleting camera: {e}")
            return jsonify({"error": "Failed to delete camera"}), 500

@app.route('/api/cameras/<camera_id>/activate', methods=['POST'])
@firebase_authenticated
def activate_camera(camera_id):
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    global video_stream, current_camera_id
    
    try:
        app_id = get_app_id()
        cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
        
        # Get the camera details
        camera_doc = cameras_ref.document(camera_id).get()
        if not camera_doc.exists:
            return jsonify({"error": "Camera not found"}), 404
            
        camera_data = camera_doc.to_dict()
        camera_source = camera_data.get('source') or camera_data.get('rtspUrl', '0')
        camera_name = camera_data.get('name', 'Unknown Camera')
        
        # Switch video stream to new camera
        with frame_lock:
            if video_stream:
                success = video_stream.switch_source(camera_source)
            else:
                video_stream = VideoCapture(camera_source)
                success = video_stream.cap and video_stream.cap.isOpened()
            
            if success:
                current_camera_id = camera_id
                log_activity(
                    session['uid'], 
                    'admin', 
                    f"Switched to camera: {camera_name}"
                )
                return jsonify({"success": True, "message": f"Switched to camera: {camera_name}"})
            else:
                return jsonify({"error": "Failed to connect to camera"}), 500
                
    except Exception as e:
        print(f"Error activating camera: {e}")
        return jsonify({"error": "Failed to activate camera"}), 500

@app.route('/api/threat_config', methods=['GET', 'POST'])
@firebase_authenticated
def handle_threat_config():
    app_id = get_app_id()
    config_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('settings').document('threat_config')

    if request.method == 'GET':
        try:
            config_doc = config_doc_ref.get()
            if config_doc.exists:
                config_data = config_doc.to_dict()
                return jsonify({
                    'threat_level': config_data.get('threat_level', current_threat_level),
                    'level': config_data.get('level', current_threat_level),
                    'monitored_objects': config_data.get('monitored_objects', ['knife', 'gun', 'person'])
                })
            else:
                return jsonify({
                    "threat_level": current_threat_level, 
                    "level": current_threat_level,
                    "monitored_objects": ['knife', 'gun', 'person']
                })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    elif request.method == 'POST':
        if session.get('role') != 'admin':
            return jsonify({"error": "Unauthorized"}), 403
        
        try:
            data = request.json
            threat_level = data.get('threat_level') or data.get('level', 'Low')
            monitored_objects = data.get('monitored_objects', ['knife', 'gun', 'person'])
            
            config_doc_ref.set({
                'threat_level': threat_level,
                'level': threat_level,
                'monitored_objects': monitored_objects,
                'timestamp': firestore.SERVER_TIMESTAMP,
                'updated_by': session['uid']
            }, merge=True)
            
            update_threat_level(threat_level)
            
            log_activity(
                session['uid'], 
                'admin', 
                f"Threat config updated. New level: {threat_level}"
            )
            
            return jsonify({"success": True, "message": "Threat config updated."})
            
        except Exception as e:
            print(f"Error updating threat config: {e}")
            return jsonify({"error": "Failed to update threat config"}), 500

@app.route('/api/activity_logs', methods=['GET'])
@firebase_authenticated
def get_activity_logs():
    try:
        limit = int(request.args.get('limit', 100))
        status_filter = request.args.get('status', 'all')
        
        app_id = get_app_id()
        logs_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('activity_logs')
        
        # Get all logs
        all_logs = list(logs_ref.stream())
        
        logs = []
        for doc in all_logs:
            log_data = doc.to_dict()
            log_data['id'] = doc.id
            
            # Apply status filter if needed
            if status_filter == 'all' or log_data.get('status') == status_filter:
                logs.append(log_data)
        
        # Sort by timestamp (most recent first)
        logs.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)
        
        # Apply limit
        logs = logs[:limit]
        
        return jsonify(logs)
        
    except Exception as e:
        print(f"Error fetching activity logs: {e}")
        return jsonify({"error": "Failed to fetch activity logs"}), 500

@app.route('/api/recent_alerts', methods=['GET'])
@firebase_authenticated
def get_recent_alerts():
    try:
        limit = int(request.args.get('limit', 5))
        app_id = get_app_id()
        alerts_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('alerts')
        
        # Get all alerts and sort in Python
        all_alerts = list(alerts_ref.stream())
        
        alerts = []
        for doc in all_alerts:
            alert_data = doc.to_dict()
            alert_data['id'] = doc.id
            alerts.append(alert_data)
            
        # Sort by timestamp (most recent first)
        alerts.sort(key=lambda x: x.get('timestamp', datetime.min), reverse=True)
        
        return jsonify(alerts[:limit])
        
    except Exception as e:
        print(f"Error fetching recent alerts: {e}")
        return jsonify({"error": "Failed to fetch recent alerts"}), 500

@app.route('/api/change_password', methods=['POST'])
@firebase_authenticated
def change_password():
    try:
        data = request.json
        current_password = data.get('current_password')
        new_password = data.get('new_password') or data.get('password')
        
        if not new_password or len(new_password) < 6:
            return jsonify({"error": "Password must be at least 6 characters long"}), 400
            
        # Update password in Firebase Auth
        auth.update_user(session['uid'], password=new_password)
        
        log_activity(
            session['uid'], 
            session.get('role'), 
            "Password changed successfully"
        )
        
        return jsonify({"success": True, "message": "Password updated successfully."})
        
    except Exception as e:
        print(f"Error changing password: {e}")
        return jsonify({"error": "Failed to change password"}), 500

@app.route('/api/users', methods=['GET'])
@firebase_authenticated
def get_users():
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    try:
        app_id = get_app_id()
        users_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('users')
        users = [{"id": doc.id, **doc.to_dict()} for doc in users_ref.stream()]
        return jsonify(users)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/users/<user_id>', methods=['PUT', 'DELETE'])
@firebase_authenticated
def manage_user(user_id):
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
    
    if request.method == 'PUT':
        try:
            data = request.json
            new_role = data.get('role')
            if new_role not in ['admin', 'personnel']:
                return jsonify({"error": "Invalid role"}), 400
            
            app_id = get_app_id()
            user_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('users').document(user_id)
            user_doc_ref.update({"role": new_role, "updated_at": firestore.SERVER_TIMESTAMP})
            
            log_activity(
                session['uid'], 
                'admin', 
                f"User {user_id} role updated to {new_role}"
            )
            
            return jsonify({"success": True, "message": "User role updated successfully."})
            
        except Exception as e:
            return jsonify({"error": str(e)}), 500
            
    elif request.method == 'DELETE':
        try:
            app_id = get_app_id()
            
            # Delete user from Firebase Authentication
            auth.delete_user(user_id)
            
            # Delete user document from Firestore
            user_doc_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('users').document(user_id)
            user_doc_ref.delete()
            
            log_activity(
                session['uid'], 
                'admin', 
                f"User {user_id} deleted"
            )
            
            return jsonify({"success": True, "message": "User deleted successfully."})
            
        except auth.UserNotFoundError:
            return jsonify({"error": "User not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@app.route('/video_feed')
@firebase_authenticated
def video_feed():
    try:
        global video_stream, current_camera_id
        
        # If no current camera, get the default one
        if not current_camera_id:
            app_id = get_app_id()
            cameras_ref = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras')
            
            # Try to get default camera first
            for doc in cameras_ref.where('is_default', '==', True).limit(1).stream():
                current_camera_id = doc.id
                camera_source = doc.to_dict().get('source') or doc.to_dict().get('rtspUrl', '0')
                break
            else:
                # Get first active camera
                for doc in cameras_ref.where('status', '==', 'active').limit(1).stream():
                    current_camera_id = doc.id
                    camera_source = doc.to_dict().get('source') or doc.to_dict().get('rtspUrl', '0')
                    break
                else:
                    return "No active cameras available", 503
        else:
            # Get current camera source
            app_id = get_app_id()
            camera_doc = db.collection('artifacts').document(app_id).collection('public').document('data').collection('cameras').document(current_camera_id).get()
            if camera_doc.exists:
                camera_data = camera_doc.to_dict()
                camera_source = camera_data.get('source') or camera_data.get('rtspUrl', '0')
            else:
                return "Current camera not found", 404

        # Initialize or check video stream
        with frame_lock:
            if video_stream is None:
                video_stream = VideoCapture(camera_source)
            elif not video_stream.cap or not video_stream.cap.isOpened():
                video_stream.connect()
        
        if video_stream and video_stream.cap and video_stream.cap.isOpened():
            return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')
        else:
            update_system_status("offline")
            return "Camera not available", 503

    except Exception as e:
        print(f"Error in video feed: {e}")
        update_system_status("offline")
        return "Error streaming video", 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint to monitor system status."""
    try:
        system_health = {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'video_stream_active': video_stream is not None and video_stream.cap is not None and video_stream.cap.isOpened() if video_stream else False,
            'model_loaded': model is not None,
            'firebase_connected': db is not None,
            'current_camera_id': current_camera_id,
            'system_status': system_status,
            'threat_level': current_threat_level,
            'total_detections': total_detections,
            'last_object_detected': last_object_detected
        }
        
        # Check if any critical components are down
        if not system_health['model_loaded'] or not system_health['firebase_connected']:
            system_health['status'] = 'degraded'
        
        if not system_health['video_stream_active']:
            system_health['status'] = 'offline'
            
        return jsonify(system_health)
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

if __name__ == '__main__':
    # Initialize video stream with default camera
    try:
        if current_camera_id:
            print(f"Initializing video stream with camera ID: {current_camera_id}")
            video_stream = VideoCapture('0')  # Start with default webcam
            update_system_status("running")
        else:
            print("No camera found, video stream will be initialized on first request")
            update_system_status("offline")
    except Exception as e:
        print(f"Error initializing video stream: {e}")
        update_system_status("offline")
    
    print("Flask surveillance system is starting...")
    print("Access the system at: http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)