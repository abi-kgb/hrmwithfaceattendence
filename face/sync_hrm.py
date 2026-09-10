import os
import json
import urllib.request
from dotenv import load_dotenv

load_dotenv()

def sync_to_face():
    """
    Sync HRM employees into Face SQLite users table via REST API.
    Pure HTTP communication ensures Face can run independently or on Android.
    """
    import database
    load_dotenv(override=True)
    hrm_url = os.environ.get("HRM_EMPLOYEES_URL", "http://127.0.0.1:8000/api/employees/")
    
    try:
        req = urllib.request.Request(hrm_url, headers={'User-Agent': 'FaceAttendance/1.0'})
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                if data.get("success") and "employees" in data:
                    employees = data["employees"]
                    conn = database.get_connection()
                    cursor = conn.cursor()
                    for emp in employees:
                        name = emp.get("name", "").strip()
                        emp_id = emp.get("emp_id", "").strip()
                        role = emp.get("role", "Employee")
                        email = emp.get("email", "")
                        if name and emp_id:
                            cursor.execute("SELECT id FROM users WHERE user_name = ?", (name,))
                            if cursor.fetchone():
                                cursor.execute(
                                    "UPDATE users SET unique_id = ?, role = ?, email = ? WHERE user_name = ?",
                                    (emp_id, role, email, name)
                                )
                            else:
                                cursor.execute(
                                    "INSERT INTO users (user_name, unique_id, role, email) VALUES (?, ?, ?, ?)",
                                    (name, emp_id, role, email)
                                )
                            
                            photo_url = emp.get("photo_url")
                            if photo_url:
                                try:
                                    user_dir = os.path.join("users", name)
                                    os.makedirs(user_dir, exist_ok=True)
                                    img_target = os.path.join(user_dir, "profile.jpg")
                                    req_img = urllib.request.Request(photo_url, headers={'User-Agent': 'FaceAttendance/1.0'})
                                    with urllib.request.urlopen(req_img, timeout=5) as img_resp:
                                        if img_resp.status == 200:
                                            img_bytes = img_resp.read()
                                            existing_bytes = b""
                                            if os.path.exists(img_target):
                                                with open(img_target, "rb") as f_ex:
                                                    existing_bytes = f_ex.read()
                                            if img_bytes != existing_bytes:
                                                with open(img_target, "wb") as f_out:
                                                    f_out.write(img_bytes)
                                                pkl_path = os.path.join("users", "representations_arcface.pkl")
                                                if os.path.exists(pkl_path):
                                                    os.remove(pkl_path)
                                except Exception as pe:
                                    pass
                    conn.commit()
                    conn.close()
                    print(f"[HRM Sync] Successfully synced {len(employees)} employees from MyHRM API.")
                    return True
    except Exception as e:
        print(f"[HRM Sync Notice] Could not sync employees from {hrm_url}: {e}")
        return False
