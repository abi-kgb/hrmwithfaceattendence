import cv2
import os
import json
import time
import threading
import queue
import base64
import math
import numpy as np
import socket
from datetime import datetime
from flask import Flask, render_template, Response, jsonify, request, send_from_directory, make_response
from deepface import DeepFace
import database
import mailer
import requests
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

USERS_DIR = "users"
COOLDOWN_MINUTES = 0.25  # 15 seconds cooldown anti-bounce
REQUIRED_HOLD_DURATION = 0.5  # 1.2 seconds continuous gaze required for attendance

# Try importing MediaPipe for 3D Iris & Head Mesh Tracking
try:
    import mediapipe as mp
    mp_face_mesh = mp.solutions.face_mesh
    face_mesh = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        refine_landmarks=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )
    USE_MEDIAPIPE = True
    print("MediaPipe 3D Face Mesh & Iris initialized successfully.")
except Exception as e:
    USE_MEDIAPIPE = False
    print(f"WARNING: MediaPipe initialization error ({e}). Falling back to Haar cascades.")

# Global state variables
camera = None
output_frame = None
lock = threading.Lock()

last_action_times = {}
status_text = ""
status_timer = 0

# Recognition and Capture State
capture_request = None
capture_lock = threading.Lock()
is_recognizing = False

camera_enabled = True
system_paused = False
camera_index = 0
force_camera_restart = False

# Gaze hold timer variables
gaze_start_time = None
current_gaze_duration = 0.0
gaze_status_msg = "LOOK AT CAMERA"

def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

LOCAL_IP = get_local_ip()

@app.route('/api/system/state', methods=['GET', 'POST'])
def system_state():
    global camera_enabled, system_paused, camera_index, force_camera_restart
    if request.method == 'GET':
        return jsonify({
            "camera_enabled": camera_enabled,
            "system_paused": system_paused,
            "camera_index": camera_index
        })
    else:
        data = request.json
        if 'camera_enabled' in data:
            camera_enabled = data['camera_enabled']
        if 'system_paused' in data:
            with lock:
                system_paused = data['system_paused']
                if not system_paused:
                    global status_text
                    status_text = ""
        if 'switch_camera' in data and data['switch_camera']:
            with lock:
                camera_index = (camera_index + 1) % 4
                force_camera_restart = True
        elif 'camera_index' in data:
            with lock:
                if camera_index != data['camera_index']:
                    camera_index = data['camera_index']
                    force_camera_restart = True
        return jsonify({"success": True})

def get_strict_match(df):
    if len(df) == 0:
        return None, None
        
    best = df.iloc[0]
    dist_col = next((c for c in df.columns if 'distance' in c.lower() or 'cosine' in c.lower() or 'arcface' in c.lower()), None)
    
    if dist_col and dist_col in best:
        dist = float(best[dist_col])
        # ArcFace cosine distance threshold: 0.72 allows standard lighting variation
        if dist < 0.72:
            return best['identity'], dist
        print(f"[Match Info] Best candidate {best['identity']} distance {dist:.3f} exceeded threshold 0.72")
        return None, dist
            
    return best['identity'], 0.0

def init_system():
    database.init_db()
    if not os.path.exists(USERS_DIR):
        os.makedirs(USERS_DIR)
    try:
        print("[Init] Pre-warming ArcFace model...")
        DeepFace.build_model("ArcFace")
        print("[Init] ArcFace model pre-warmed.")
    except Exception as e:
        print(f"[Init Warning] ArcFace preload: {e}")

def run_recognition(frame_crop):
    global is_recognizing, status_text, status_timer
    
    temp_path = f"temp_{time.time()}.jpg"
    cv2.imwrite(temp_path, frame_crop)
    
    try:
        try:
            dfs = DeepFace.find(
                img_path=temp_path,
                db_path=USERS_DIR,
                model_name="ArcFace",
                distance_metric="cosine",
                enforce_detection=False,
                silent=True
            )
        except ValueError as e:
            if "Face could not be detected" in str(e) or "Face not found" in str(e):
                with lock:
                    status_text = "Unknown Face"
                    status_timer = time.time()
                return
            elif "No item found" in str(e):
                dfs = []
            else:
                raise e
                
        if len(dfs) > 0 and len(dfs[0]) > 0:
            matched_path, dist = get_strict_match(dfs[0])
            if not matched_path:
                with lock:
                    status_text = "Unknown Face"
                    status_timer = time.time()
                return

            if not os.path.exists(matched_path):
                pkl_path = os.path.join(USERS_DIR, "representations_arcface.pkl")
                if os.path.exists(pkl_path):
                    os.remove(pkl_path)
                with lock:
                    status_text = "Syncing Database. Try again."
                    status_timer = time.time()
                return
                
            user_name = os.path.basename(os.path.dirname(matched_path))
            print(f"[Recognition Success] Matched user: '{user_name}' (distance: {dist:.3f})")
            now = datetime.now()
            
            with lock:
                last_action = last_action_times.get(user_name)
                today_rec = database.get_user_today_attendance(user_name)
                has_pending = database.has_pending_action(user_name)
                today_str = now.strftime("%Y-%m-%d")
                
                if today_rec is None:
                    # User has not clocked in yet today -> Clock in!
                    time_str = now.strftime("%I:%M %p")
                    if database.log_login(user_name):
                        status_text = f"SUCCESS|{user_name}|Logged in successfully at {time_str}"
                    last_action_times[user_name] = now
                    status_timer = time.time()
                elif today_rec.get('logout_time') is None or today_rec.get('logout_time') in ['', '-']:
                    # User is currently clocked in
                    if has_pending:
                        status_text = f"PENDING|{user_name}|Logout Request is Pending HRM Admin Approval"
                        status_timer = time.time()
                    else:
                        if last_action and (now - last_action).total_seconds() <= COOLDOWN_MINUTES * 60:
                            time_left = int(COOLDOWN_MINUTES * 60 - (now - last_action).total_seconds())
                            status_text = f"Cooldown: {user_name} ({time_left}s)"
                            status_timer = time.time()
                        else:
                            status_text = f"PROMPT_LOGOUT|{user_name}"
                            status_timer = time.time()
                            print(f"[PROMPT_LOGOUT set for {user_name}]")
                else:
                    # User has already clocked out for today
                    try:
                        raw_out = str(today_rec.get('logout_time', ''))[:8]
                        t_out = datetime.strptime(raw_out, "%H:%M:%S").strftime("%I:%M %p")
                    except Exception:
                        t_out = str(today_rec.get('logout_time', ''))
                    status_text = f"SUCCESS|{user_name}|Attendance Completed Today (Clocked Out at {t_out})"
                    status_timer = time.time()
        else:
            with lock:
                status_text = "Unknown Face"
                status_timer = time.time()
    except Exception as e:
        print("[DeepFace Error]", e)
        with lock:
            status_text = f"Error: {str(e)[:30]}"
            status_timer = time.time()
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception:
                pass
        with lock:
            is_recognizing = False

def verify_iris_and_head_pose(frame):
    """
    Evaluates 3D Head Orientation (Yaw/Pitch) and Eye Iris Centering.
    Returns: (is_valid: bool, reason_text: str, landmarks_data: dict)
    """
    if not USE_MEDIAPIPE or frame is None:
        return False, "MEDIAPIPE NOT LOADED", None
        
    try:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = face_mesh.process(rgb_frame)
        if not results.multi_face_landmarks:
            return False, "NO FACE DETECTED", None
            
        landmarks = results.multi_face_landmarks[0].landmark
        
        # 1. Head Yaw (Turning left / right)
        nose = landmarks[1]
        l_ear = landmarks[234]
        r_ear = landmarks[454]
        head_center = (l_ear.x + r_ear.x) / 2.0
        face_width = abs(l_ear.x - r_ear.x)
        
        if abs(nose.x - head_center) > face_width * 0.22:
            return False, "HEAD TURNED - LOOK STRAIGHT", landmarks

        # 2. Head Pitch (Tilting up / down)
        top = landmarks[10]     # Top forehead
        bottom = landmarks[152] # Bottom chin
        if top.z < bottom.z - 0.10:
            return False, "HEAD TILTED DOWN", landmarks
        if bottom.z < top.z - 0.14:
            return False, "HEAD TILTED UP", landmarks

        # 3. Eye Aspect Ratio (EAR) - Closed eyes or looking down
        l_h = abs(landmarks[33].x - landmarks[133].x)
        l_v = abs(landmarks[159].y - landmarks[145].y)
        r_h = abs(landmarks[362].x - landmarks[263].x)
        r_v = abs(landmarks[386].y - landmarks[374].y)
        
        ear_left = l_v / (l_h + 1e-6)
        ear_right = r_v / (r_h + 1e-6)
        
        if ear_left < 0.10 or ear_right < 0.10:
            return False, "EYES CLOSED", landmarks

        # 4. Iris Landmark Alignment (Centered Gaze)
        if len(landmarks) > 473:
            l_iris = landmarks[468] # Left iris center
            r_iris = landmarks[473] # Right iris center
            
            l_inner = landmarks[133]
            l_outer = landmarks[33]
            r_inner = landmarks[362]
            r_outer = landmarks[263]
            
            # Left eye iris x-ratio
            dist_l_in = abs(l_iris.x - l_inner.x)
            dist_l_out = abs(l_iris.x - l_outer.x)
            if dist_l_in * 4.0 < dist_l_out or dist_l_out * 4.0 < dist_l_in:
                return False, "EYES LOOKING SIDEWAY", landmarks

            # Right eye iris x-ratio
            dist_r_in = abs(r_iris.x - r_inner.x)
            dist_r_out = abs(r_iris.x - r_outer.x)
            if dist_r_in * 4.0 < dist_r_out or dist_r_out * 4.0 < dist_r_in:
                return False, "EYES LOOKING SIDEWAY", landmarks

        return True, "PERFECT POSITION", landmarks
    except Exception as e:
        return False, "NO FACE DETECTED", None

def open_camera(index):
    """
    Initializes camera with DirectShow backend and MJPG 640x480 resolution
    to prevent stride mismatch, slice duplication, and noise distortion on Windows.
    """
    cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    if not cap.isOpened():
        cap = cv2.VideoCapture(index)
        
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        ret, test_frame = cap.read()
        if ret and test_frame is not None:
            return cap
            
    # Fallback to default if DirectShow fails
    cap = cv2.VideoCapture(index)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    return cap


def process_camera():
    global camera, output_frame, status_text, status_timer, capture_request, is_recognizing
    global camera_index, force_camera_restart
    global gaze_start_time, current_gaze_duration, gaze_status_msg
    
    current_index = camera_index
    cascade_path = os.path.join(cv2.data.haarcascades, 'haarcascade_frontalface_default.xml')
    face_cascade = cv2.CascadeClassifier(cascade_path)
    
    last_frame_time = time.time()
    
    while True:
        try:
            current_time = time.time()
            dt = current_time - last_frame_time
            last_frame_time = current_time
            
            if force_camera_restart:
                if camera and camera.isOpened():
                    camera.release()
                    camera = None
                current_index = camera_index
                with lock:
                    force_camera_restart = False
                    
            if not camera_enabled or system_paused:
                if camera and camera.isOpened():
                    camera.release()
                    camera = None
                blank_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                msg = "SYSTEM PAUSED" if system_paused else "CAMERA OFF"
                cv2.putText(blank_frame, msg, (180, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 100, 100), 2)
                with lock:
                    output_frame = blank_frame.copy()
                time.sleep(0.2)
                continue

            if camera is None or not camera.isOpened():
                camera = open_camera(current_index)
                if camera is None or not camera.isOpened():
                    error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                    cv2.putText(error_frame, "CAMERA NOT FOUND", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                    with lock:
                        output_frame = error_frame.copy()
                    time.sleep(1)
                    continue

            success, frame = camera.read()
            if not success or frame is None:
                error_frame = np.zeros((480, 640, 3), dtype=np.uint8)
                cv2.putText(error_frame, "CAMERA DISCONNECTED", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2)
                with lock:
                    output_frame = error_frame.copy()
                if camera:
                    camera.release()
                    camera = None
                time.sleep(1)
                continue
                
            display_frame = frame.copy()
            h, w, _ = display_frame.shape
            
            # Draw semi-transparent Target Guide Oval in center
            overlay = display_frame.copy()
            cv2.ellipse(overlay, (w // 2, h // 2), (int(w * 0.22), int(h * 0.32)), 0, 0, 360, (255, 255, 255), 2)
            cv2.addWeighted(overlay, 0.4, display_frame, 0.6, 0, display_frame)
            
            # Run Iris & Head Pose Filter
            is_valid_gaze, reason_text, landmarks = verify_iris_and_head_pose(frame)
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = []
            if face_cascade and not face_cascade.empty():
                faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(100, 100))
            
            with capture_lock:
                req = capture_request
                
            if req and not req["event"].is_set():
                if len(faces) > 0:
                    faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
                    (fx, fy, fw, fh) = faces[0]
                    margin = 20
                    y1, y2 = max(0, fy-margin), min(h, fy+fh+margin)
                    x1, x2 = max(0, fx-margin), min(w, fx+fw+margin)
                    face_crop = frame[y1:y2, x1:x2]
                    
                    ret1, buf1 = cv2.imencode('.jpg', face_crop)
                    ret2, buf2 = cv2.imencode('.jpg', frame)
                    if ret1 and ret2:
                        b64_crop = base64.b64encode(buf1).decode('utf-8')
                        b64_full = base64.b64encode(buf2).decode('utf-8')
                        req["result"] = {"success": True, "image": b64_crop, "full_image": b64_full}
                    else:
                        req["result"] = {"success": False, "message": "Image encoding failed."}
                    req["event"].set()
                    gaze_start_time = None
                    current_gaze_duration = 0.0
                
            elif len(faces) > 0:
                faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
                (fx, fy, fw, fh) = faces[0]
                
                # --- Smart Distance & Position Evaluation ---
                face_ratio_h = fh / float(h)
                face_ratio_w = fw / float(w)
                fc_x = (fx + fw / 2.0) / float(w)
                fc_y = (fy + fh / 2.0) / float(h)

                # Generous natural matching ellipse (rx=0.18, ry=0.25)
                rx, ry = 0.18, 0.25
                center_dist = ((fc_x - 0.5) / rx) ** 2 + ((fc_y - 0.5) / ry) ** 2
                
                pos_status = "OK"
                guidance_msg = ""
                box_color = (0, 215, 255)  # Amber default
                
                if face_ratio_h > 0.85 or face_ratio_w > 0.80:
                    pos_status = "TOO_CLOSE"
                    guidance_msg = "MOVE BACK SLIGHTLY"
                    box_color = (0, 165, 255)
                elif face_ratio_h < 0.12 or face_ratio_w < 0.10:
                    pos_status = "TOO_FAR"
                    guidance_msg = "MOVE CLOSER TO CAMERA"
                    box_color = (0, 215, 255)
                elif center_dist > 1.3:
                    pos_status = "OFF_CENTER"
                    box_color = (0, 215, 255)
                    if fc_y < 0.38:
                        guidance_msg = "MOVE FACE DOWN"
                    elif fc_y > 0.62:
                        guidance_msg = "MOVE FACE UP"
                    elif fc_x < 0.38:
                        guidance_msg = "MOVE FACE RIGHT"
                    elif fc_x > 0.62:
                        guidance_msg = "MOVE FACE LEFT"
                    else:
                        guidance_msg = "CENTER YOUR FACE"
                elif is_valid_gaze or reason_text in ["NO FACE DETECTED", "KEEP LOOKING AT CAMERA", "MEDIAPIPE NOT LOADED", "PERFECT POSITION"]:
                    pos_status = "PERFECT"
                    box_color = (0, 255, 0)  # Green
                else:
                    pos_status = "INVALID_GAZE"
                    guidance_msg = reason_text
                    box_color = (0, 165, 255)
                    
                gaze_status_msg = guidance_msg if pos_status != "PERFECT" else "PERFECT POSITION"

                if pos_status == "PERFECT":
                    current_gaze_duration = min(REQUIRED_HOLD_DURATION, current_gaze_duration + max(0.03, dt))
                    progress = min(1.0, current_gaze_duration / REQUIRED_HOLD_DURATION)
                    
                    if progress >= 1.0:
                        hud_text = "VERIFIED - RECOGNIZING..."
                    else:
                        hud_text = f"HOLD GAZE: {current_gaze_duration:.1f}s / {REQUIRED_HOLD_DURATION:.1f}s"
                else:
                    current_gaze_duration = max(0.0, current_gaze_duration - max(0.02, dt * 0.5))
                    progress = min(1.0, current_gaze_duration / REQUIRED_HOLD_DURATION)
                    hud_text = guidance_msg

                # Draw Bounding Box (Square)
                cv2.rectangle(display_frame, (fx, fy), (fx+fw, fy+fh), box_color, 2)
                    
                # Draw Iris landmarks if available
                if landmarks and len(landmarks) > 473:
                    l_iris = landmarks[468]
                    r_iris = landmarks[473]
                    cv2.circle(display_frame, (int(l_iris.x * w), int(l_iris.y * h)), 3, (255, 255, 0), -1)
                    cv2.circle(display_frame, (int(r_iris.x * w), int(r_iris.y * h)), 3, (255, 255, 0), -1)
                    
                # Trigger recognition once 1.5 seconds hold is reached
                if current_gaze_duration >= REQUIRED_HOLD_DURATION and not is_recognizing:
                    is_recognizing = True
                    gaze_start_time = None
                    current_gaze_duration = 0.0
                    
                    margin = 20
                    y1, y2 = max(0, fy-margin), min(h, fy+fh+margin)
                    x1, x2 = max(0, fx-margin), min(w, fx+fw+margin)
                    face_crop = frame[y1:y2, x1:x2]
                    
                    threading.Thread(target=run_recognition, args=(face_crop,), daemon=True).start()
            else:
                gaze_start_time = None
                current_gaze_duration = 0.0
                gaze_status_msg = "POSITION FACE IN TARGET ZONE"
                    
            with lock:
                if status_text and not status_text.startswith("PROMPT_LOGOUT") and time.time() - status_timer > 4:
                    status_text = ""

            with lock:
                output_frame = display_frame.copy()
                
            time.sleep(0.03)
        except Exception as e:
            print("Camera loop error:", e)
            time.sleep(0.1)

def generate_frames():
    global output_frame
    while True:
        with lock:
            if output_frame is None:
                time.sleep(0.01)
                continue
            ret, buffer = cv2.imencode('.jpg', output_frame)
            frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def get_status():
    with lock:
        return jsonify({
            "is_recognizing": is_recognizing,
            "status_text": status_text,
            "gaze_duration": round(current_gaze_duration, 1),
            "gaze_status": gaze_status_msg,
            "required_duration": REQUIRED_HOLD_DURATION
        })

@app.route('/api/capture_preview', methods=['POST'])
def capture_preview():
    global capture_request
    event = threading.Event()
    with capture_lock:
        capture_request = {"event": event, "result": None}
    
    success = event.wait(timeout=5.0)
    with capture_lock:
        result = capture_request["result"]
        capture_request = None
        
    if not success or result is None:
        return jsonify({"success": False, "message": "Camera timeout. Please hold gaze steady."})
    return jsonify(result)

@app.route('/api/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name', '').strip()
    emp_no = data.get('emp_no', '').strip()
    email = data.get('email', '').strip()
    role = data.get('role', 'Employee')
    img_b64 = data.get('image', '')
    
    if not name:
        return jsonify({"success": False, "message": "Name is required."})
        
    user_folder = os.path.join(USERS_DIR, name)
    if not os.path.exists(user_folder):
        os.makedirs(user_folder)
        
    if img_b64:
        if "," in img_b64:
            img_b64 = img_b64.split(",")[1]
        try:
            img_data = base64.b64decode(img_b64)
            img_path = os.path.join(user_folder, "profile.jpg")
            with open(img_path, "wb") as f:
                f.write(img_data)
                
            # Remove existing DeepFace representation pkl cache to force recalculation
            pkl_path = os.path.join(USERS_DIR, "representations_arcface.pkl")
            if os.path.exists(pkl_path):
                os.remove(pkl_path)
        except Exception as e:
            print(f"Error saving image for {name}: {e}")
        
    # Save user details in Database
    database.init_db()
    conn = database.get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO users (user_name, unique_id, role, email)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(user_name) DO UPDATE SET unique_id=?, role=?, email=?
    ''', (name, emp_no, role, email, emp_no, role, email))
    conn.commit()
    conn.close()
    
    return jsonify({"success": True, "message": f"User {name} registered successfully."})

@app.route('/api/admin/verify', methods=['POST'])
def admin_verify():
    data = request.json
    password = data.get('password', '')
    admin_pwd = os.environ.get("ADMIN_PASSWORD", "admin123")
    if password == admin_pwd:
        return jsonify({"success": True})
    return jsonify({"success": False, "message": "Invalid password"})

@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    load_dotenv(override=True)
    hrm_url = os.environ.get("HRM_EMPLOYEES_URL", "http://127.0.0.1:8000/api/employees/")
    
    # 1. Fetch live employee list from MyHRM
    try:
        import urllib.request
        req = urllib.request.Request(hrm_url, headers={'User-Agent': 'FaceAttendance/1.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                res_data = json.loads(response.read().decode('utf-8'))
                if res_data.get("success") and "employees" in res_data:
                    hrm_employees = res_data["employees"]
                    # Update local database with MyHRM records for consistency
                    conn = database.get_connection()
                    cursor = conn.cursor()
                    for emp in hrm_employees:
                        emp_name = emp.get("name", "").strip()
                        emp_id = emp.get("emp_id", "").strip()
                        emp_role = emp.get("role", "Employee")
                        emp_email = emp.get("email", "")
                        if emp_name and emp_id:
                            cursor.execute("SELECT id FROM users WHERE user_name = ?", (emp_name,))
                            existing = cursor.fetchone()
                            if existing:
                                cursor.execute("UPDATE users SET unique_id = ?, role = ?, email = ? WHERE user_name = ?", 
                                               (emp_id, emp_role, emp_email, emp_name))
                            else:
                                cursor.execute("INSERT OR REPLACE INTO users (user_name, unique_id, role, email) VALUES (?, ?, ?, ?)", 
                                               (emp_name, emp_id, emp_role, emp_email))
                    conn.commit()
                    conn.close()
                    return jsonify({"users": hrm_employees})
    except Exception as e:
        print(f"[Warning] Could not fetch live employees from MyHRM: {e}")
        
    # Fallback to local database if HRM server is temporarily unreachable
    users_details = database.get_all_users_details()
    user_list = []
    for name, info in users_details.items():
        user_list.append({
            "name": name,
            "emp_id": info.get("emp_id") or "EMP",
            "role": info.get("role") or "Employee",
            "email": info.get("email", "")
        })
    return jsonify({"users": user_list})

@app.route('/api/admin/logs', methods=['GET'])
def admin_logs():
    load_dotenv(override=True)
    hrm_logs_url = os.environ.get("HRM_LOGS_URL", "http://127.0.0.1:8000/api/attendance/logs/")
    try:
        import urllib.request
        req = urllib.request.Request(hrm_logs_url, headers={'User-Agent': 'FaceAttendance/1.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            if response.status == 200:
                res_data = json.loads(response.read().decode('utf-8'))
                if res_data.get("success") and "logs" in res_data:
                    return jsonify(res_data["logs"])
    except Exception as e:
        print(f"[Warning] Could not fetch live logs from MyHRM: {e}")
        
    logs = database.get_all_logs()
    return jsonify(logs)


@app.route('/api/admin/delete_user/<user_name>', methods=['DELETE'])
def delete_user(user_name):
    folder = os.path.join(USERS_DIR, user_name)
    if os.path.exists(folder):
        import shutil
        shutil.rmtree(folder)
        pkl_path = os.path.join(USERS_DIR, "representations_arcface.pkl")
        if os.path.exists(pkl_path):
            os.remove(pkl_path)
            
        conn = database.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM users WHERE user_name = ?", (user_name,))
        conn.commit()
        conn.close()
@app.route('/api/admin/requests', methods=['GET'])
def admin_requests():
    load_dotenv(override=True)
    hrm_req_url = os.environ.get("HRM_PENDING_REQ_URL", "http://127.0.0.1:8000/api/attendance/pending-requests/")
    try:
        resp = requests.get(hrm_req_url, timeout=4)
        if resp.status_code == 200:
            res_data = resp.json()
            if res_data.get("success") and "requests" in res_data:
                return jsonify(res_data["requests"])
    except Exception as e:
        print(f"[Warning] Could not fetch pending requests from MyHRM: {e}")
    return jsonify([])

@app.route('/api/admin/action_request', methods=['POST'])
def admin_action_request():
    data = request.json or {}
    token = data.get('token')
    action = data.get('action', 'approve')
    if not token:
        return jsonify({"success": False, "message": "Token required."}), 400
    try:
        hrm_act_url = f"http://127.0.0.1:8000/attendance/{action}/{token}/"
        resp = requests.get(hrm_act_url, timeout=5)
        return jsonify({"success": True, "message": f"Request {action}d successfully."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/request_logout', methods=['POST'])
def request_logout():
    global status_text, status_timer, last_action_times
    data = request.json or {}
    user_name = data.get('user_name', '').strip()
    
    if not user_name:
        return jsonify({"success": False, "message": "User name required."}), 400
        
    now = datetime.now()
    time_str = now.strftime("%I:%M %p")
    today_str = now.strftime("%Y-%m-%d")
    cur_time_str = now.strftime("%H:%M:%S")
    
    # Send Permission Request to HRM Admin Dashboard
    token = str(uuid.uuid4())
    hrm_url = os.environ.get("HRM_PERMISSION_URL", "http://127.0.0.1:8000/api/attendance/request-permission/")
    try:
        req_payload = {
            "user_name": user_name,
            "action": "Early Departure",
            "reason": f"Logout requested via Face Attendance camera at {time_str}",
            "time": cur_time_str,
            "date": today_str
        }
        resp = requests.post(hrm_url, json=req_payload, timeout=5)
        if resp.status_code == 200:
            resp_data = resp.json()
            if resp_data.get("token"):
                token = resp_data.get("token")
        print(f"[HRM Request Permission] Response: {resp.status_code} -> {resp.text[:100]}")
    except Exception as e:
        print(f"[HRM Request Permission Error] {e}")
    
    # Record in local pending_actions with synchronized token
    try:
        conn = database.get_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT OR REPLACE INTO pending_actions (token, user_name, date, action_time, action_type, status)
            VALUES (?, ?, ?, ?, 'Early Departure', 'pending')
        ''', (token, user_name, today_str, cur_time_str))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Pending Actions SQLite Error] {e}")

    with lock:
        last_action_times[user_name] = now
        status_text = f"PENDING|{user_name}|Logout Request Sent to HRM Admin for Approval"
        status_timer = time.time()
        
    return jsonify({
        "success": True, 
        "message": f"Logout request for {user_name} sent to HRM Admin Dashboard for approval."
    })



@app.route('/api/clear_prompt', methods=['POST'])
def clear_prompt():
    global status_text, status_timer
    with lock:
        if status_text.startswith("PROMPT_LOGOUT"):
            status_text = ""
            status_timer = time.time()
        else:
            status_text = ""
            status_timer = time.time()
    return jsonify({"success": True})

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS, DELETE'
    return response

if __name__ == '__main__':
    init_system()
    
    # Start video processing thread
    t = threading.Thread(target=process_camera, daemon=True)
    t.start()
    
    # Start HRM sync thread (runs in background)
    def hrm_sync_loop():
        interval = int(os.getenv('HRM_SYNC_INTERVAL', '60'))
        while True:
            try:
                import sync_hrm
                sync_hrm.sync_to_face()
            except Exception as e:
                print(f"[HRM Sync Error] {e}")
            time.sleep(interval)
    threading.Thread(target=hrm_sync_loop, daemon=True).start()
    
    port = int(os.getenv('PORT', 5001))
    print(f"Server launching on http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
