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

def resolve_employee(user_name=None, emp_id=None):
    if emp_id:
        emp = Employee.objects.filter(employee_id_code=emp_id).first()
        if emp:
            return emp
    if not user_name:
        return None
    
    clean = str(user_name).strip()
    # 1. Exact match username
    emp = Employee.objects.filter(user__username__iexact=clean).first()
    if emp:
        return emp
    
    # 2. First name + last name match e.g. "Abi B"
    for e in Employee.objects.select_related('user').all():
        full = f"{e.user.first_name} {e.user.last_name}".strip()
        if full.lower() == clean.lower() or e.user.username.lower() == clean.lower():
            return e
            
    # 3. Match by splitting first word (e.g. "Abi" from "Abi B")
    first_word = clean.split()[0].split('_')[0].strip()
    emp = Employee.objects.filter(
        Q(user__username__iexact=first_word) |
        Q(user__first_name__iexact=first_word) |
        Q(user__username__icontains=first_word) |
        Q(user__first_name__icontains=first_word)
    ).first()
    return emp

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
    employee = resolve_employee(user_name=user_name, emp_id=emp_id)
        
    if not employee:
        return JsonResponse({
            "success": False,
            "message": f"Employee not found in MyHRM database for emp_id='{emp_id}', name='{user_name}'"
        }, status=404)
        
    from .models import AttendanceRequest

    late_mins = 0
    if employee.shift and clock_time and action == 'login':
        dt_in = datetime.combine(today_date, clock_time)
        dt_shift_start = datetime.combine(today_date, employee.shift.start_time)
        if dt_in > dt_shift_start:
            late_mins = max(0, int((dt_in - dt_shift_start).total_seconds() / 60))

    attendance_rec = Attendance.objects.filter(employee=employee, date=today_date).first()
    if not attendance_rec:
        attendance_rec = Attendance.objects.create(
            employee=employee,
            date=today_date,
            clock_in=clock_time if action == 'login' else None,
            clock_out=clock_time if action == 'logout' else None,
            late_minutes=late_mins,
            status='Present'
        )
        message = f"Created attendance record for {employee} at {clock_time.strftime('%H:%M:%S')}"
    else:
        if action == 'login':
            # If not yet clocked in, set clock_in. If already clocked in, preserve original clock-in time and clear clock_out so user is actively working.
            if not attendance_rec.clock_in:
                attendance_rec.clock_in = clock_time
            attendance_rec.clock_out = None
            attendance_rec.status = 'Present'
            if late_mins > 0 and (attendance_rec.late_minutes == 0 or attendance_rec.late_minutes is None):
                attendance_rec.late_minutes = late_mins
            attendance_rec.save()
            message = f"Clock-in updated for {employee} at {clock_time.strftime('%H:%M:%S')}"
        elif action == 'logout':
            attendance_rec.clock_out = clock_time
            if employee.shift and attendance_rec.clock_in:
                from datetime import timedelta
                shift_start = employee.shift.start_time
                shift_end = employee.shift.end_time
                dt_s_start = datetime.combine(today_date, shift_start)
                dt_s_end = datetime.combine(today_date, shift_end)
                if shift_end < shift_start:
                    dt_s_end += timedelta(days=1)
                shift_duration = (dt_s_end - dt_s_start).total_seconds() / 60
                
                dt_cin = datetime.combine(today_date, attendance_rec.clock_in)
                dt_cout = datetime.combine(today_date, clock_time)
                if dt_cout < dt_cin:
                    if (dt_cin - dt_cout).total_seconds() > 4 * 3600:
                        dt_cout += timedelta(days=1)
                    else:
                        dt_cout = dt_cin
                worked_duration = (dt_cout - dt_cin).total_seconds() / 60
                if worked_duration > shift_duration:
                    attendance_rec.overtime_minutes = int(worked_duration - shift_duration)
            attendance_rec.save()
            message = f"Clock-out updated for {employee} at {clock_time.strftime('%H:%M:%S')}"
        else:
            message = f"Attendance record updated for {employee}"

    # Auto-create or link AttendanceRequest for Late Arrival
    if action == 'login' and late_mins > 0:
        existing_late_req = AttendanceRequest.objects.filter(
            employee=employee,
            date=today_date,
            request_type__in=['Late Arrival', 'Permission']
        ).first()
        if not existing_late_req:
            shift_start_str = employee.shift.start_time.strftime('%H:%M') if employee.shift else 'Shift Start'
            AttendanceRequest.objects.create(
                employee=employee,
                date=today_date,
                request_type='Late Arrival',
                requested_time=clock_time,
                reason=f"Late arrival by {late_mins} minutes via Face Attendance scan (Shift Start: {shift_start_str}, Clock In: {clock_time.strftime('%H:%M')})",
                status='Pending'
            )

    # Auto-create or link AttendanceRequest for Early Logout
    if action == 'logout' and employee.shift and clock_time:
        shift_end = employee.shift.end_time
        dt_cout = datetime.combine(today_date, clock_time)
        dt_s_end = datetime.combine(today_date, shift_end)
        if dt_cout < dt_s_end:
            early_mins = max(0, int((dt_s_end - dt_cout).total_seconds() / 60))
            if early_mins > 5:
                existing_early_req = AttendanceRequest.objects.filter(
                    employee=employee,
                    date=today_date,
                    request_type__in=['Early Departure', 'Clock Out', 'Emergency Exit']
                ).first()
                if not existing_early_req:
                    AttendanceRequest.objects.create(
                        employee=employee,
                        date=today_date,
                        request_type='Early Departure',
                        requested_time=clock_time,
                        reason=f"Early logout by {early_mins} minutes via Face Attendance scan (Shift End: {shift_end.strftime('%H:%M')}, Clock Out: {clock_time.strftime('%H:%M')})",
                        status='Pending'
                    )

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
        full_name = f"{user.first_name} {user.last_name}".strip() if user else ""
        name = full_name or (user.username if user else "Unknown")
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

@csrf_exempt
def request_permission_api(request):
    """
    API to submit Late Arrival / Early Departure permission requests from Face App.
    Sends interactive Approve & Disapprove email to the Admin (abhinaya.kgb@gmail.com).
    """
    if request.method != 'POST':
        return JsonResponse({"success": False, "message": "Only POST allowed"}, status=405)
        
    try:
        data = json.loads(request.body)
    except Exception as e:
        return JsonResponse({"success": False, "message": f"Invalid JSON: {str(e)}"}, status=400)
        
    user_name = data.get('user_name', '').strip()
    action = data.get('action', 'Early Departure').strip()
    reason = data.get('reason', 'Submitted via Face Attendance System').strip()
    time_str = data.get('time')
    date_str = data.get('date')
    
    if not user_name:
        return JsonResponse({"success": False, "message": "user_name is required"}, status=400)
        
    today_date = date.today()
    if date_str:
        try:
            today_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            pass
            
    clock_time = parse_time_string(time_str)
    
    # Resolve employee
    employee = resolve_employee(user_name=user_name)
    
    if not employee:
        return JsonResponse({"success": False, "message": f"Employee '{user_name}' not found in HRM"}, status=404)
        
    from .models import AttendanceRequest
    from .email_service import send_attendance_approval_email
    
    req_type = 'Early Departure' if action in ['logout', 'Early Departure', 'Clock Out'] else 'Late Arrival'
    
    # Check if existing pending request exists
    att_req = AttendanceRequest.objects.filter(
        employee=employee,
        date=today_date,
        request_type=req_type,
        status='Pending'
    ).first()
    
    if not att_req:
        att_req = AttendanceRequest.objects.create(
            employee=employee,
            request_type=req_type,
            date=today_date,
            requested_time=clock_time,
            reason=reason,
            status='Pending'
        )
    else:
        att_req.requested_time = clock_time
        att_req.reason = reason
        att_req.save()
        
    return JsonResponse({
        "success": True,
        "token": att_req.token,
        "message": f"Permission request for {user_name} sent to HRM Admin Dashboard for approval."
    })

@csrf_exempt
def get_pending_requests_api(request):
    """
    API to fetch all pending attendance & logout permission requests.
    """
    from .models import AttendanceRequest
    pending_list = []
    for req in AttendanceRequest.objects.filter(status='Pending').order_by('-created_at'):
        pending_list.append({
            "id": req.id,
            "token": str(req.token),
            "user_name": f"{req.employee.user.first_name} {req.employee.user.last_name}".strip() or req.employee.user.username,
            "date": str(req.date),
            "requested_time": req.requested_time.strftime("%H:%M") if req.requested_time else "",
            "request_type": req.request_type,
            "reason": req.reason or "Logout request",
            "status": req.status
        })
    return JsonResponse({"success": True, "requests": pending_list})
