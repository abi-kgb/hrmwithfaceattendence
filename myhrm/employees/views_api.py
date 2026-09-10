import json
from datetime import datetime, date, time
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from .models import Employee, Attendance

def parse_time_string(time_str):
    if not time_str:
        return datetime.now().time()
    for fmt in ("%H:%M:%S", "%H:%M:%S.%f", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
        try:
            return datetime.strptime(str(time_str).strip(), fmt).time()
        except ValueError:
            pass
    return datetime.now().time()

@csrf_exempt
def attendance_webhook_api(request):
    """
    Webhook API endpoint to receive real-time attendance events (clock-in / clock-out)
    from the Face Attendance System.
    """
    if request.method != 'POST':
        return JsonResponse({"success": False, "message": "Only POST requests allowed"}, status=405)
        
    try:
        data = json.loads(request.body)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Invalid JSON body: {str(e)}"}, status=400)
        
    action = data.get('action') or data.get('event_type') or 'login'
    emp_id = data.get('emp_id') or data.get('unique_id')
    user_name = data.get('user_name') or data.get('name')
    date_str = data.get('date')
    time_str = data.get('time')
    
    if not emp_id and not user_name:
        return JsonResponse({"success": False, "message": "Missing emp_id or user_name"}, status=400)
        
    today_date = date.today()
    if date_str:
        try:
            today_date = datetime.strptime(str(date_str).strip(), "%Y-%m-%d").date()
        except Exception:
            pass
            
    clock_time = parse_time_string(time_str)

    employee = None
    if emp_id:
        employee = Employee.objects.filter(employee_id_code=emp_id).first()
        
    if not employee and user_name:
        clean_name = user_name.split('_')[0].strip()
        employee = Employee.objects.filter(
            Q(user__username__iexact=clean_name) |
            Q(user__first_name__iexact=clean_name) |
            Q(user__username__icontains=clean_name)
        ).first()
        
    if not employee:
        return JsonResponse({
            "success": False,
            "message": f"Employee not found in MyHRM database for emp_id='{emp_id}', name='{user_name}'"
        }, status=404)
        
    attendance_rec = Attendance.objects.filter(employee=employee, date=today_date).first()
    if not attendance_rec:
        attendance_rec = Attendance.objects.create(
            employee=employee,
            date=today_date,
            clock_in=clock_time if action == 'login' else None,
            clock_out=clock_time if action == 'logout' else None,
            status='Present'
        )
        message = f"Created attendance record for {employee} at {clock_time.strftime('%H:%M:%S')}"
    else:
        if action == 'login':
            attendance_rec.clock_in = clock_time
            attendance_rec.status = 'Present'
            attendance_rec.save()
            message = f"Clock-in updated for {employee} at {clock_time.strftime('%H:%M:%S')}"
        elif action == 'logout':
            attendance_rec.clock_out = clock_time
            attendance_rec.save()
            message = f"Clock-out updated for {employee} at {clock_time.strftime('%H:%M:%S')}"
        else:
            message = f"Attendance record updated for {employee}"

    attendance_rec.refresh_from_db()

    return JsonResponse({
        "success": True,
        "message": message,
        "data": {
            "employee_id": employee.employee_id_code,
            "employee_name": f"{employee.user.first_name} {employee.user.last_name}".strip() or employee.user.username,
            "date": str(today_date),
            "clock_in": str(attendance_rec.clock_in) if attendance_rec.clock_in else None,
            "clock_out": str(attendance_rec.clock_out) if attendance_rec.clock_out else None
        }
    })

@csrf_exempt
def get_employees_api(request):
    """
    Returns list of all active employees registered in MyHRM.
    Used by Face Attendance app for syncing users.
    """
    employees = Employee.objects.select_related('user').all()
    data = []
    for emp in employees:
        user = emp.user
        full_name = f"{user.first_name} {user.last_name}".strip() or user.username
        emp_code = emp.employee_id_code or f"EMP{emp.id:04d}"
        photo_url = request.build_absolute_uri(emp.photo.url) if emp.photo else None
        data.append({
            "emp_id": emp_code,
            "name": full_name,
            "role": emp.role or "Employee",
            "email": user.email or "",
            "department": emp.department.name if emp.department else "",
            "photo_url": photo_url
        })
    return JsonResponse({"success": True, "employees": data})

@csrf_exempt
def get_attendance_logs_api(request):
    """
    Returns list of attendance logs from MyHRM for sync/display in Face Admin dashboard.
    """
    records = Attendance.objects.select_related('employee', 'employee__user').order_by('-date', '-id')
    logs = []
    for att in records:
        emp = att.employee
        user = emp.user if emp else None
        name = f"{user.first_name} {user.last_name}".strip() if user else (user.username if user else "Unknown")
        emp_code = emp.employee_id_code if emp else "EMP"
        role = emp.role if emp else "Employee"
        
        login_str = att.clock_in.strftime("%I:%M %p") if att.clock_in else "-"
        logout_str = att.clock_out.strftime("%I:%M %p") if att.clock_out else "-"
        
        total_str = "-"
        if att.clock_in and att.clock_out:
            td = datetime.combine(att.date, att.clock_out) - datetime.combine(att.date, att.clock_in)
            total_sec = max(0, int(td.total_seconds()))
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            total_str = f"{h} hrs {m} min"
        elif att.clock_in and not att.clock_out and att.date == date.today():
            now_dt = datetime.now()
            login_dt = datetime.combine(att.date, att.clock_in)
            if now_dt > login_dt:
                td = now_dt - login_dt
                total_sec = int(td.total_seconds())
                h = total_sec // 3600
                m = (total_sec % 3600) // 60
                total_str = f"{h} hrs {m} min"

        logs.append({
            "id": emp_code,
            "user_name": name,
            "date": str(att.date),
            "login_time": login_str,
            "logout_time": logout_str,
            "total_hours": total_str,
            "role": role
        })
    return JsonResponse({"success": True, "logs": logs})

