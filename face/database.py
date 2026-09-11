import sqlite3
from datetime import datetime
import os
import uuid
import threading
import urllib.request
import json
from dotenv import load_dotenv

load_dotenv()

DB_NAME = 'attendance.db'

def trigger_hrm_webhook(user_name, action_type, time_str=None, date_str=None):
    """Sends a real-time HTTP POST payload to the configured HRM Webhook URL."""
    def send_request():
        load_dotenv(override=True)
        webhook_url = os.environ.get("HRM_WEBHOOK_URL", "http://127.0.0.1:8000/api/attendance/webhook/")
        if not webhook_url:
            return
            
        emp_id = get_or_create_user_id(user_name)
        now = datetime.now()
        cur_date = date_str or now.strftime("%Y-%m-%d")
        cur_time = time_str or now.strftime("%H:%M:%S")
        
        payload = {
            "event": "attendance_punch",
            "action": action_type,
            "emp_id": emp_id,
            "user_name": user_name,
            "date": cur_date,
            "time": cur_time,
            "timestamp": f"{cur_date}T{cur_time}"
        }
        
        data_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(webhook_url, data=data_bytes, headers={'Content-Type': 'application/json'})
        
        api_key = os.environ.get("HRM_API_KEY", "")
        if api_key:
            req.add_header('X-HRM-API-Key', api_key)
            req.add_header('Authorization', f'Bearer {api_key}')
            
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                print(f"[HRM Webhook] Sent {action_type} for {user_name} -> Response {response.status}")
        except Exception as e:
            print(f"[HRM Webhook Warning] Could not send event to {webhook_url}: {e}")

    threading.Thread(target=send_request, daemon=True).start()

def send_admin_email(subject, body, recipient=None, html_body=None):
    """Email concept removed - no-op function."""
    pass

def send_approval_action_email(user_name, action_type, time_str, date_str, token, base_url="http://127.0.0.1:8000", recipient=None):
    """Email concept removed - no-op function."""
    pass


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT NOT NULL,
            date TEXT NOT NULL,
            login_time TEXT NOT NULL,
            logout_time TEXT,
            total_hours REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_name TEXT UNIQUE NOT NULL,
            unique_id TEXT UNIQUE NOT NULL
        )
    ''')
    cursor.execute("PRAGMA table_info(users)")
    columns = [info[1] for info in cursor.fetchall()]
    if 'role' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'Employee'")
    if 'email' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT")
        
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_logins (
            token TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            date TEXT NOT NULL,
            login_time TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_actions (
            token TEXT PRIMARY KEY,
            user_name TEXT NOT NULL,
            date TEXT NOT NULL,
            action_time TEXT NOT NULL,
            action_type TEXT NOT NULL,
            status TEXT DEFAULT 'pending'
        )
    ''')
    conn.commit()
    conn.close()

def get_or_create_user_id(user_name):
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute("UPDATE users SET unique_id = REPLACE(unique_id, 'ID-', 'EMP-') WHERE unique_id LIKE 'ID-%'")
    conn.commit()
    
    cursor.execute('SELECT unique_id FROM users WHERE user_name = ?', (user_name,))
    row = cursor.fetchone()
    if row:
        conn.close()
        return row[0]
        
    cursor.execute('SELECT unique_id FROM users')
    all_uids = [r[0] for r in cursor.fetchall() if r[0]]
    max_num = 1000
    for uid_val in all_uids:
        if uid_val.startswith('EMP-'):
            try:
                num = int(uid_val.split('-')[1])
                if num > max_num:
                    max_num = num
            except (IndexError, ValueError):
                pass
    new_id = f"EMP-{max_num + 1}"
    try:
        cursor.execute('INSERT INTO users (user_name, unique_id) VALUES (?, ?)', (user_name, new_id))
        conn.commit()
    except sqlite3.IntegrityError:
        cursor.execute('SELECT unique_id FROM users WHERE user_name = ?', (user_name,))
        r = cursor.fetchone()
        new_id = r[0] if r else new_id
    conn.close()
    return new_id

def get_all_users_details():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_name, unique_id, role, email FROM users')
    rows = cursor.fetchall()
    conn.close()
    
    users = {}
    for r in rows:
        users[r[0]] = {
            "emp_id": r[1],
            "role": r[2] if r[2] else "Employee",
            "email": r[3]
        }
    return users

def is_logged_in(user_name):
    """Check if the user is currently logged in (has a login without a logout today)."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) FROM attendance 
        WHERE LOWER(user_name) = LOWER(?) AND date = ? AND (logout_time IS NULL OR logout_time = '' OR logout_time = '-')
    ''', (user_name, today))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else 0

def get_user_today_attendance(user_name):
    """Returns today's latest attendance record dict or None."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, login_time, logout_time, total_hours FROM attendance 
        WHERE LOWER(user_name) = LOWER(?) AND date = ?
        ORDER BY id DESC LIMIT 1
    ''', (user_name, today))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "id": row[0],
            "login_time": row[1],
            "logout_time": row[2],
            "total_hours": row[3]
        }
    return None

def has_pending_action(user_name, today_date=None, action_type=None):
    """Check if the user has an unapproved pending logout/permission request."""
    conn = get_connection()
    today = today_date or datetime.now().strftime("%Y-%m-%d")
    cursor = conn.cursor()
    if action_type:
        cursor.execute('''
            SELECT token FROM pending_actions 
            WHERE LOWER(user_name) = LOWER(?) AND date = ? AND LOWER(action_type) = LOWER(?) AND status = 'pending'
        ''', (user_name, today, action_type))
    else:
        cursor.execute('''
            SELECT token FROM pending_actions 
            WHERE LOWER(user_name) = LOWER(?) AND date = ? AND status = 'pending'
        ''', (user_name, today))
    row = cursor.fetchone()
    conn.close()
    return row is not None


def get_login_time(user_name):
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        SELECT login_time FROM attendance 
        WHERE user_name = ? AND date = ? AND logout_time IS NULL
        ORDER BY id DESC LIMIT 1
    ''', (user_name, today))
    row = cursor.fetchone()
    conn.close()
    if row:
        try:
            return datetime.strptime(row[0], "%H:%M:%S").strftime("%I:%M %p")
        except:
            return row[0]
    return "Unknown Time"

def log_login(user_name):
    """Log the user in if they aren't already."""
    if is_logged_in(user_name):
        return False
    
    conn = get_connection()
    cursor = conn.cursor()
    now = datetime.now()
    today_date = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    
    cursor.execute('''
        INSERT INTO attendance (user_name, date, login_time)
        VALUES (?, ?, ?)
    ''', (user_name, today_date, time_str))
    
    conn.commit()
    conn.close()
    
    trigger_hrm_webhook(user_name, 'login', time_str, today_date)
    return True

def has_pending_login(user_name, today_date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT token FROM pending_logins WHERE user_name = ? AND date = ? AND status = 'pending'
    ''', (user_name, today_date))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def create_pending_login(user_name, today_date, time_str):
    conn = get_connection()
    cursor = conn.cursor()
    token = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO pending_logins (token, user_name, date, login_time)
        VALUES (?, ?, ?, ?)
    ''', (token, user_name, today_date, time_str))
    conn.commit()
    conn.close()
    return token

def approve_pending_login(token):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_name, date, login_time FROM pending_logins WHERE token = ? AND status = 'pending'
    ''', (token,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Invalid or already approved token."
        
    user_name, today_date, time_str = row
    
    now = datetime.now()
    exp_hour = int(os.environ.get("EXPIRATION_HOUR", "18"))
    
    if now.strftime("%Y-%m-%d") != today_date or now.hour >= exp_hour:
        conn.close()
        exp_ampm = f"{exp_hour-12} PM" if exp_hour > 12 else (f"{exp_hour} AM" if exp_hour < 12 else "12 PM")
        return False, f"This approval link has expired. (Valid only until {exp_ampm} today)"
    
    cursor.execute('''
        UPDATE pending_logins SET status = 'approved' WHERE token = ?
    ''', (token,))
    
    cursor.execute('''
        INSERT INTO attendance (user_name, date, login_time)
        VALUES (?, ?, ?)
    ''', (user_name, today_date, time_str))
    
    conn.commit()
    conn.close()
    return True, f"Attendance approved for {user_name} at {time_str}"

# (Duplicate has_pending_action merged above)

def create_pending_action(user_name, today_date, time_str, action_type):
    conn = get_connection()
    cursor = conn.cursor()
    token = str(uuid.uuid4())
    cursor.execute('''
        INSERT INTO pending_actions (token, user_name, date, action_time, action_type)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, user_name, today_date, time_str, action_type))
    conn.commit()
    conn.close()
    return token

def approve_pending_action(token):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_name, date, action_time, action_type FROM pending_actions WHERE token = ? AND status = 'pending'
    ''', (token,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        return False, "Invalid or already approved token."
        
    user_name, today_date, time_str, action_type = row
    
    now = datetime.now()
    exp_hour = int(os.environ.get("EXPIRATION_HOUR", "23"))
    
    if now.strftime("%Y-%m-%d") != today_date or now.hour >= exp_hour:
        conn.close()
        exp_ampm = f"{exp_hour-12} PM" if exp_hour > 12 else (f"{exp_hour} AM" if exp_hour < 12 else "12 PM")
        return False, f"This approval link has expired. (Valid only until {exp_ampm} today)"
    
    cursor.execute('''
        UPDATE pending_actions SET status = 'approved' WHERE token = ?
    ''', (token,))
    
    if action_type == 'login':
        cursor.execute('''
            INSERT INTO attendance (user_name, date, login_time)
            VALUES (?, ?, ?)
        ''', (user_name, today_date, time_str))
    elif action_type == 'logout':
        cursor.execute('''
            SELECT id, login_time FROM attendance 
            WHERE user_name = ? AND date = ? AND logout_time IS NULL
            ORDER BY id DESC LIMIT 1
        ''', (user_name, today_date))
        login_row = cursor.fetchone()
        
        if login_row:
            record_id, login_time = login_row
            try:
                t1 = datetime.strptime(login_time, "%H:%M:%S")
                t2 = datetime.strptime(time_str, "%H:%M:%S")
                total_hours = round((t2 - t1).total_seconds() / 3600.0, 2)
            except:
                total_hours = 0.0
            
            cursor.execute('''
                UPDATE attendance SET logout_time = ?, total_hours = ? WHERE id = ?
            ''', (time_str, total_hours, record_id))
    
    conn.commit()
    conn.close()
    return True, f"Successfully approved {action_type} for {user_name} at {time_str}"

def log_logout(user_name):
    """Log the user out and calculate hours."""
    conn = get_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    now_time_str = datetime.now().strftime("%H:%M:%S")
    
    cursor.execute('''
        SELECT id, login_time FROM attendance 
        WHERE user_name = ? AND date = ? AND logout_time IS NULL
        ORDER BY id DESC LIMIT 1
    ''', (user_name, today))
    
    row = cursor.fetchone()
    if row is None:
        conn.close()
        return False
        
    record_id, login_time_str = row
    
    fmt = "%H:%M:%S"
    t1 = datetime.strptime(login_time_str, fmt)
    t2 = datetime.strptime(now_time_str, fmt)
    delta = t2 - t1
    
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    duration_str = f"{hours} hrs {minutes} min"
    
    cursor.execute('''
        UPDATE attendance 
        SET logout_time = ?, total_hours = ? 
        WHERE id = ?
    ''', (now_time_str, duration_str, record_id))
    conn.commit()
    conn.close()
    
    trigger_hrm_webhook(user_name, 'logout', now_time_str, today)
    return True

def get_recent_logs(limit=10):
    """Fetch the most recent attendance logs for the UI."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_name, date, login_time, logout_time, total_hours 
        FROM attendance 
        ORDER BY id DESC LIMIT ?
    ''', (limit,))
    rows = cursor.fetchall()
    conn.close()
    
    logs = []
    for row in rows:
        user, date, login, logout, hours = row
        if logout:
            logs.append({"user": user, "action": "Logged Out", "time": logout, "date": date, "hours": hours})
        logs.append({"user": user, "action": "Logged In", "time": login, "date": date, "hours": None})
    
    logs.sort(key=lambda x: f"{x['date']} {x['time']}", reverse=True)
    return logs[:limit]

def auto_logout_missing():
    """If it is past 18:30, mark any open logins for today as logged out at 18:00."""
    now = datetime.now()
    if now.hour > 18 or (now.hour == 18 and now.minute >= 30):
        conn = get_connection()
        cursor = conn.cursor()
        today = now.strftime("%Y-%m-%d")
        default_logout = "18:00:00"
        
        cursor.execute('''
            SELECT id, login_time FROM attendance
            WHERE date = ? AND logout_time IS NULL
        ''', (today,))
        rows = cursor.fetchall()
        
        for row in rows:
            record_id, login_time = row
            try:
                t1 = datetime.strptime(login_time, "%H:%M:%S")
                t2 = datetime.strptime(default_logout, "%H:%M:%S")
                if t1 > t2:
                    total_hours = 0.0
                else:
                    total_hours = round((t2 - t1).total_seconds() / 3600.0, 2)
            except:
                total_hours = 0.0
                
            cursor.execute('''
                UPDATE attendance 
                SET logout_time = ?, total_hours = ? 
                WHERE id = ?
            ''', (default_logout, total_hours, record_id))
            
        conn.commit()
        conn.close()

def get_all_logs(month=None, exact_date=None, search=None):
    conn = get_connection()
    cursor = conn.cursor()
    
    query = '''
        SELECT a.id, a.user_name, a.date, a.login_time, a.logout_time, a.total_hours, u.unique_id, u.role
        FROM attendance a
        LEFT JOIN users u ON a.user_name = u.user_name
        WHERE 1=1
    '''
    params = []
    
    if exact_date:
        query += ' AND a.date = ?'
        params.append(exact_date)
    elif month:
        query += ' AND a.date LIKE ?'
        params.append(f"{month}-%")
        
    if search:
        search_term = f"%{search}%"
        query += ' AND (a.user_name LIKE ? OR u.unique_id LIKE ?)'
        params.extend([search_term, search_term])
        
    query += ' ORDER BY a.id DESC'
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now()
    
    logs = []
    for r in rows:
        uid = r[6] if r[6] else get_or_create_user_id(r[1])
        role = r[7] if r[7] else "Employee"
        
        date_str = r[2]
        login_time_str = r[3]
        logout_time_str = r[4]
        total_str = r[5]
        
        if not total_str and not logout_time_str and date_str == today_str and login_time_str:
            try:
                login_time = datetime.strptime(login_time_str, "%H:%M:%S").time()
                login_dt = datetime.combine(now.date(), login_time)
                diff = now - login_dt
                if diff.total_seconds() > 0:
                    total_seconds = int(diff.total_seconds())
                    h = total_seconds // 3600
                    m = (total_seconds % 3600) // 60
                    total_str = f"{h} hrs {m} min"
            except ValueError:
                pass
                
        if total_str is not None and "hrs" not in str(total_str):
            try:
                val = float(total_str)
                h = int(val)
                m = int(round((val % 1) * 60))
                total_str = f"{h} hrs {m} min"
            except (ValueError, TypeError):
                pass
                
        logs.append({
            "id": uid,
            "user_name": r[1],
            "date": date_str,
            "login_time": login_time_str,
            "logout_time": logout_time_str if logout_time_str else "-",
            "total_hours": total_str if total_str else "-",
            "role": role
        })
    return logs

def get_today_attendance():
    conn = get_connection()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        SELECT DISTINCT user_name FROM attendance WHERE date = ?
    ''', (today_str,))
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_today_logged_out():
    conn = get_connection()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute('''
        SELECT user_name, logout_time FROM attendance 
        WHERE date = ? 
        ORDER BY id DESC
    ''', (today_str,))
    status_map = {}
    for row in cursor.fetchall():
        user_name = row[0]
        if user_name not in status_map:
            status_map[user_name] = (row[1] is not None)
    conn.close()
    return [u for u, is_logged_out in status_map.items() if is_logged_out]

def get_attendance_extremes_for_month(month_str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.user_name, a.total_hours, u.unique_id, u.role
        FROM attendance a
        LEFT JOIN users u ON a.user_name = u.user_name
        WHERE a.date LIKE ? AND a.total_hours IS NOT NULL
    ''', (f"{month_str}-%",))
    rows = cursor.fetchall()
    conn.close()
    
    user_totals = {}
    user_info = {}
    
    for r in rows:
        name, hrs, uid, role = r
        if not hrs: continue
        
        try:
            parts = hrs.split(' ')
            h = int(parts[0])
            m = int(parts[2])
            val = h + (m / 60.0)
        except:
            try:
                val = float(hrs)
            except:
                continue
                
        user_totals[name] = user_totals.get(name, 0.0) + val
        user_info[name] = {
            "emp_id": uid if uid else get_or_create_user_id(name),
            "role": role if role else "Employee"
        }
        
    if not user_totals:
        return None, None
        
    lowest_name = min(user_totals, key=user_totals.get)
    highest_name = max(user_totals, key=user_totals.get)
    
    lowest = {
        "name": lowest_name,
        "total_hours": round(user_totals[lowest_name], 2),
        "emp_id": user_info[lowest_name]["emp_id"],
        "role": user_info[lowest_name]["role"]
    }
    
    highest = {
        "name": highest_name,
        "total_hours": round(user_totals[highest_name], 2),
        "emp_id": user_info[highest_name]["emp_id"],
        "role": user_info[highest_name]["role"]
    }
    
    return lowest, highest

if __name__ == "__main__":
    init_db()
    print("Database initialized.")
