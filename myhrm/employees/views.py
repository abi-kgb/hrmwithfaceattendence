from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.utils import timezone
from datetime import date, datetime
from .models import (
    Employee, LeaveRequest, Attendance, Payslip, ShiftRequest,
    JobPosting, JobApplication, PerformanceReview,
    Training, TrainingEnrollment, Holiday, Client, GoalTracking, Project, ProjectUpdate, EmployeeDocument,
    Shift, Asset, Expense, Department, Designation, ActivityLog, Event, HRLetter, PersonalNote
)
import os
import json
from django.conf import settings

def log_activity(user, action, module, request=None, details=""):
    ip_address = None
    if request:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0]
        else:
            ip_address = request.META.get('REMOTE_ADDR')
            
    ActivityLog.objects.create(
        user=user if getattr(user, 'is_authenticated', False) else None,
        action=action,
        module=module,
        ip_address=ip_address,
        details=details
    )

import base64
import time
from django.core.files.base import ContentFile

def save_and_sync_employee_photo(employee, photo_file=None, photo_b64=None):
    """
    Saves photo to Django Employee model (supports file or base64 data url)
    and syncs directly to Face Attendance user folder for immediate ArcFace matching.
    """
    saved_bytes = None
    
    if photo_b64 and len(photo_b64.strip()) > 50:
        b64_str = photo_b64.strip()
        if "," in b64_str:
            b64_str = b64_str.split(",")[1]
        try:
            saved_bytes = base64.b64decode(b64_str)
            filename = f"photo_{employee.user.username}_{int(time.time())}.jpg"
            employee.photo.save(filename, ContentFile(saved_bytes), save=True)
        except Exception as e:
            print(f"[Photo Save Error] {e}")
    elif photo_file:
        employee.photo = photo_file
        employee.save()
        try:
            employee.photo.open('rb')
            saved_bytes = employee.photo.read()
            employee.photo.close()
        except Exception as e:
            print(f"[Photo Read Error] {e}")
            
    # Sync to Face Attendance folder
    if saved_bytes:
        try:
            full_name = f"{employee.user.first_name} {employee.user.last_name}".strip() or employee.user.username
            face_root = os.path.abspath(os.path.join(settings.BASE_DIR, '..', 'face'))
            users_dir = os.path.join(face_root, 'users')
            if os.path.exists(face_root):
                user_folder = os.path.join(users_dir, full_name)
                os.makedirs(user_folder, exist_ok=True)
                target_img = os.path.join(user_folder, 'profile.jpg')
                with open(target_img, 'wb') as f:
                    f.write(saved_bytes)
                # Invalidate DeepFace representations cache so new face is indexed immediately
                for fname in os.listdir(users_dir):
                    if fname.endswith('.pkl'):
                        try:
                            os.remove(os.path.join(users_dir, fname))
                        except Exception:
                            pass
                print(f"[Face Direct Sync] Updated profile photo for '{full_name}' at {target_img}")
        except Exception as e:
            print(f"[Face Direct Sync Notice] Could not sync photo directly to Face app: {e}")


def get_unified_calendar_events(user=None, employee=None):
    events = []
    
    # 1. Holidays
    holidays = Holiday.objects.all()
    for h in holidays:
        events.append({
            'title': h.name,
            'start': h.date.isoformat(),
            'allDay': True,
            'color': '#10b981' # Emerald Green
        })
        
    # 2. Approved Leaves
    if employee: # If limited to a specific employee
        leaves = LeaveRequest.objects.filter(employee=employee, status='Approved')
    else: # Admin sees all
        leaves = LeaveRequest.objects.filter(status='Approved')
        
    for l in leaves:
        title = f"Leave: {l.employee.user.first_name}" if not employee else f"My Leave ({l.leave_type})"
        # FullCalendar end dates are exclusive, so we add 1 day
        from datetime import timedelta
        end_date = l.end_date + timedelta(days=1)
        events.append({
            'title': title,
            'start': l.start_date.isoformat(),
            'end': end_date.isoformat(),
            'allDay': True,
            'color': '#f59e0b' # Amber
        })
        
    # 3. Birthdays
    current_year = date.today().year
    employees = Employee.objects.all()
    for emp in employees:
        if emp.date_of_birth:
            try:
                bday_this_year = emp.date_of_birth.replace(year=current_year)
            except ValueError:
                bday_this_year = emp.date_of_birth.replace(year=current_year, day=28)
            
            events.append({
                'title': f"🎂 {emp.user.first_name}'s Bday",
                'start': bday_this_year.isoformat(),
                'allDay': True,
                'color': '#8b5cf6' # Purple
            })
            
    # 4. Custom Events / Meetings
    custom_events = Event.objects.all()
    for e in custom_events:
        events.append({
            'title': e.title,
            'start': e.start_time.isoformat(),
            'end': e.end_time.isoformat(),
            'allDay': False,
            'color': '#3b82f6' if e.event_type == 'Meeting' else '#ec4899', # Blue or Pink
            'description': e.description
        })

    # 5. Personal Private Notes (VISIBLE ONLY TO THIS USER)
    if user and getattr(user, 'is_authenticated', False):
        personal_notes = PersonalNote.objects.filter(user=user)
        for pn in personal_notes:
            events.append({
                'id': f"note_{pn.id}",
                'title': f"🔒 Note: {pn.title}",
                'start': pn.date.isoformat(),
                'allDay': True,
                'color': '#6366f1', # Indigo
                'description': pn.note or '',
                'isPersonal': True,
                'noteId': pn.id
            })
        
    return json.dumps(events)

def redirect_user_by_role(user):
    if not user or not user.is_authenticated:
        return redirect('login')

    if user.is_superuser or user.is_staff:
        return redirect('admin_dashboard')

    try:
        if hasattr(user, 'employee') and user.employee and user.employee.is_company_admin:
            return redirect('admin_dashboard')
    except Exception:
        pass

    try:
        if hasattr(user, 'client_profile') and user.client_profile:
            return redirect('client_dashboard')
    except Exception:
        pass

    return redirect('employee_dashboard')

def home_redirect(request):
    return render(request, 'employees/employee_login.html')

def employee_login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            log_activity(user, 'Logged In', 'Authentication', request, 'Unified Login Portal')
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect_user_by_role(user)
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'employees/employee_login.html')

def admin_login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            log_activity(user, 'Logged In', 'Authentication', request, 'Admin Login Portal')
            messages.success(request, f"Welcome back, {user.first_name or user.username}!")
            return redirect_user_by_role(user)
        else:
            messages.error(request, "Invalid username or password.")
            
    return render(request, 'employees/admin_login.html')



def logout_view(request):
    is_admin = False
    is_client = False
    if request.user.is_authenticated:
        if hasattr(request.user, 'employee'):
            is_admin = request.user.employee.is_company_admin
        elif hasattr(request.user, 'client_profile'):
            is_client = True
            
    if request.user.is_authenticated:
        log_activity(request.user, 'Logged Out', 'Authentication', request)
        
    logout(request)
    messages.info(request, "You have been logged out.")
    
    if is_admin:
        return redirect('admin_login')
    elif is_client:
        return redirect('client_login')
    return redirect('employee_login')

def forgot_password_view(request):
    """
    Two-step employee password reset:
      Step 1 – verify identity via username + phone number
      Step 2 – set new password
    """
    step = request.session.get('forgot_step', 1)
    verified_user_id = request.session.get('forgot_verified_user_id')

    if request.method == 'POST':
        action = request.POST.get('action')

        # ── Step 1: Verify identity ─────────────────────────────────────
        if action == 'verify':
            username = request.POST.get('username', '').strip()
            phone = request.POST.get('phone', '').strip()
            try:
                user = User.objects.get(username=username)
                employee = user.employee
                # Normalize phone for comparison (strip spaces/dashes)
                stored_phone = ''.join(filter(str.isdigit, employee.phone or ''))
                entered_phone = ''.join(filter(str.isdigit, phone))
                if stored_phone and entered_phone and stored_phone == entered_phone:
                    request.session['forgot_step'] = 2
                    request.session['forgot_verified_user_id'] = user.id
                    messages.success(request, "Identity verified! Please set your new password.")
                    return redirect('forgot_password')
                else:
                    messages.error(request, "Phone number does not match our records.")
            except (User.DoesNotExist, Employee.DoesNotExist):
                messages.error(request, "No employee account found with that username.")
            return render(request, 'employees/forgot_password.html', {'step': 1})

        # ── Step 2: Reset password ──────────────────────────────────────
        elif action == 'reset' and verified_user_id:
            new_password = request.POST.get('new_password', '')
            confirm_password = request.POST.get('confirm_password', '')
            if len(new_password) < 4:
                messages.error(request, "Password must be at least 4 characters.")
                return render(request, 'employees/forgot_password.html', {'step': 2})
            if new_password != confirm_password:
                messages.error(request, "Passwords do not match.")
                return render(request, 'employees/forgot_password.html', {'step': 2})
            try:
                user = User.objects.get(id=verified_user_id)
                user.set_password(new_password)
                user.save()
                # Clear session state
                request.session.pop('forgot_step', None)
                request.session.pop('forgot_verified_user_id', None)
                messages.success(request, f"Password reset successfully for '{user.username}'! You can now log in.")
                return redirect('employee_login')
            except User.DoesNotExist:
                messages.error(request, "Session expired. Please start again.")
                request.session.pop('forgot_step', None)
                request.session.pop('forgot_verified_user_id', None)
                return redirect('forgot_password')

    # GET – show whichever step is active
    current_step = step if (step == 2 and verified_user_id) else 1
    return render(request, 'employees/forgot_password.html', {'step': current_step})

@login_required
def employee_dashboard(request):
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        logout(request)
        return redirect('employee_login')
        
    if employee.is_company_admin:
        return redirect('admin_dashboard')
        
    # Get today's attendance record
    today = date.today()
    attendance = Attendance.objects.filter(employee=employee, date=today).first()
    
    # Get leave requests
    leaves = LeaveRequest.objects.filter(employee=employee).order_by('-id')
    
    # Get payslips
    payslips = Payslip.objects.filter(employee=employee).order_by('-id')
    
    # Get shifts for shift request
    shifts = Shift.objects.all()
    shift_requests = ShiftRequest.objects.filter(employee=employee).order_by('-id')

    # Personal reviews and trainings
    performance_reviews = PerformanceReview.objects.filter(employee=employee).order_by('-created_at')
    training_enrollments = TrainingEnrollment.objects.filter(employee=employee).order_by('-enrolled_at')

    # Leave Balance calculations
    sick_max = 10
    casual_max = 10
    annual_max = 20
    
    sick_pct = int((employee.sick_leave_balance / sick_max) * 100) if employee.sick_leave_balance > 0 else 0
    casual_pct = int((employee.casual_leave_balance / casual_max) * 100) if employee.casual_leave_balance > 0 else 0
    annual_pct = int((employee.annual_leave_balance / annual_max) * 100) if employee.annual_leave_balance > 0 else 0
    
    # Pagination for Employee's own Attendance Logs
    from django.core.paginator import Paginator
    attendance_qs = Attendance.objects.filter(employee=employee).order_by('-date', '-clock_in')
    paginator = Paginator(attendance_qs, 20)
    page_number = request.GET.get('page')
    attendance_history = paginator.get_page(page_number)
    

    holidays = Holiday.objects.all().order_by('date')
    events = []
    for h in holidays:
        events.append({
            'title': h.name,
            'start': h.date.isoformat(),
            'color': '#2563eb' if getattr(h, 'type', 'Holiday') == 'Holiday' else '#94a3b8',
            'extendedProps': {
                'type': getattr(h, 'type', 'Holiday')
            }
        })
    events_json = json.dumps(events, cls=DjangoJSONEncoder)

    goals = GoalTracking.objects.all().order_by('-created_at')
    projects = Project.objects.filter(assigned_employees=employee).order_by('-created_at')

    context = {
        'projects': projects,
        'goals': goals,
        'events_json': events_json,
        'employee': employee,
        'attendance': attendance,
        'leaves': leaves,
        'payslips': payslips,
        'leave_choices': LeaveRequest.LEAVE_CHOICES,
        'today': today,
        'attendance_history': attendance_history,
        'performance_reviews': performance_reviews,
        'training_enrollments': training_enrollments,
        'sick_pct': sick_pct,
        'casual_pct': casual_pct,
        'annual_pct': annual_pct,
        'sick_max': sick_max,
        'casual_max': casual_max,
        'annual_max': annual_max,
        'shifts': shifts,
        'shift_requests': shift_requests,
        'assets': Asset.objects.filter(assigned_to=employee).order_by('-assigned_date'),
        'expenses': Expense.objects.filter(employee=employee).order_by('-date_submitted'),
        'calendar_events_json': get_unified_calendar_events(user=request.user, employee=employee),
        'my_letters': HRLetter.objects.filter(employee=employee).order_by('-issue_date'),
    }
    return render(request, 'employees/employee_dashboard.html', context)

@login_required
def employee_project_detail_view(request, project_id):
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        return redirect('employee_login')
        
    project = get_object_or_404(Project, id=project_id, assigned_employees=employee)
    updates = project.updates.all().order_by('created_at')
    
    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        if message:
            ProjectUpdate.objects.create(
                project=project,
                author=request.user,
                message=message
            )
            messages.success(request, 'Message posted successfully.')
        return redirect('employee_project_detail', project_id=project.id)
        
    return render(request, 'employees/employee_project_detail.html', {
        'project': project,
        'updates': updates,
        'employee': employee,
    })

@login_required
def clock_in(request):
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        return redirect('login')
        
    today = date.today()
    already_exists = Attendance.objects.filter(employee=employee, date=today).exists()
    if not already_exists:
        now = timezone.localtime()
        att = Attendance.objects.create(employee=employee)
        
        late_mins = 0
        if employee.shift:
            shift_start = employee.shift.start_time
            import datetime
            dt_now = datetime.datetime.combine(now.date(), now.time())
            dt_shift_start = datetime.datetime.combine(now.date(), shift_start)
            if dt_now > dt_shift_start:
                diff = dt_now - dt_shift_start
                late_mins = int(diff.total_seconds() / 60)
        
        att.late_minutes = late_mins
        att.save()
        messages.success(request, "Clocked in successfully!")
    else:
        messages.warning(request, "You have already clocked in today.")
    return redirect('employee_dashboard')

@login_required
def clock_out(request):
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        return redirect('login')
        
    today = date.today()
    attendance = Attendance.objects.filter(employee=employee, date=today).first()
    if attendance:
        if not attendance.clock_out:
            now = timezone.localtime()
            attendance.clock_out = now.time()
            
            if employee.shift:
                shift_start = employee.shift.start_time
                shift_end = employee.shift.end_time
                import datetime
                dt_shift_start = datetime.datetime.combine(today, shift_start)
                
                if shift_end < shift_start:
                    # Overnight shift
                    dt_shift_end = datetime.datetime.combine(today + datetime.timedelta(days=1), shift_end)
                else:
                    dt_shift_end = datetime.datetime.combine(today, shift_end)
                    
                shift_duration = (dt_shift_end - dt_shift_start).total_seconds() / 60
                
                dt_in = datetime.datetime.combine(today, attendance.clock_in)
                dt_out = datetime.datetime.combine(today, attendance.clock_out)
                
                if dt_out < dt_in:
                    dt_out += datetime.timedelta(days=1)
                    
                worked_duration = (dt_out - dt_in).total_seconds() / 60
                
                if worked_duration > shift_duration:
                    attendance.overtime_minutes = int(worked_duration - shift_duration)
                    
            attendance.save()
            messages.success(request, "Clocked out successfully!")
        else:
            messages.warning(request, "You have already clocked out today.")
    else:
        messages.error(request, "You need to clock in first.")
    return redirect('employee_dashboard')

@login_required
def apply_leave(request):
    try:
        employee = request.user.employee
    except Employee.DoesNotExist:
        return redirect('login')
        
    if request.method == 'POST':
        leave_type = request.POST.get('leave_type')
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        reason = request.POST.get('reason')
        
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            
            if start_date > end_date:
                messages.error(request, "Start date cannot be after end date.")
            elif start_date < date.today():
                messages.error(request, "You cannot apply for leave on past dates.")
            else:
                # Calculate required days
                days = (end_date - start_date).days + 1
                
                # Check balance before submitting request
                balance = 0
                lop_days = 0
                
                if leave_type == 'Sick':
                    balance = employee.sick_leave_balance
                    lop_days = max(0, days - balance)
                elif leave_type == 'Casual':
                    balance = employee.casual_leave_balance
                    lop_days = max(0, days - balance)
                elif leave_type == 'Annual':
                    balance = employee.annual_leave_balance
                    lop_days = max(0, days - balance)
                elif leave_type in ['Maternity', 'Paternity']:
                    # Usually paid leaves without a strictly tracked balance in basic HRM
                    lop_days = 0
                elif leave_type == 'Unpaid':
                    lop_days = days
                
                leave = LeaveRequest.objects.create(
                    employee=employee,
                    leave_type=leave_type,
                    start_date=start_date,
                    end_date=end_date,
                    reason=reason,
                    lop_days=lop_days
                )
                
                admins = Employee.objects.filter(is_company_admin=True)
                for adm in admins:
                    if adm.user and adm.user != request.user:
                        Notification.objects.create(user=adm.user, title="Leave Request Submitted", message=f"New leave request from {employee.user.get_full_name()} ({leave_type}).")

                if lop_days > 0:
                    messages.warning(request, f"Leave submitted! Note: You requested {days} days but only have {balance} remaining. {lop_days} day(s) will be recorded as Loss of Pay (LOP).")
                else:
                    messages.success(request, "Leave request submitted successfully!")
        except ValueError:
            messages.error(request, "Invalid date format submitted.")
            
    return redirect('employee_dashboard')

# Helper function/decorator to restrict views to admin employees only
def admin_only(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('admin_login')
        try:
            if not request.user.employee.is_company_admin:
                messages.error(request, "Unauthorized access. Admins only.")
                return redirect('employee_dashboard')
        except Employee.DoesNotExist:
            logout(request)
            return redirect('admin_login')
        return view_func(request, *args, **kwargs)
    return wrapper

@admin_only
def admin_dashboard(request):
    admin_employee = request.user.employee
    
    # Get stats
    total_employees = Employee.objects.filter(is_company_admin=False).count()
    pending_leaves = LeaveRequest.objects.filter(status='Pending').count()
    clocked_in_today = Attendance.objects.filter(date=date.today()).count()
    
    # Additional Metrics for Visual Charts
    approved_leaves = LeaveRequest.objects.filter(status='Approved').count()
    rejected_leaves = LeaveRequest.objects.filter(status='Rejected').count()
    
    from django.db.models import Count
    dept_counts = Employee.objects.filter(is_company_admin=False).values('department__name').annotate(count=Count('id')).order_by('-count')
    dept_stats = [{'name': d['department__name'] if d['department__name'] else 'Unassigned', 'count': d['count']} for d in dept_counts]
    for d in dept_stats:
        d['percentage'] = int((d['count'] / total_employees) * 100) if total_employees > 0 else 0

    total_leaves = pending_leaves + approved_leaves + rejected_leaves
    pending_leaves_pct = 0
    approved_leaves_pct = 0
    rejected_leaves_pct = 0
    approved_offset = 25
    rejected_offset = 25
    
    if total_leaves > 0:
        pending_leaves_pct = int((pending_leaves / total_leaves) * 100)
        approved_leaves_pct = int((approved_leaves / total_leaves) * 100)
        rejected_leaves_pct = 100 - pending_leaves_pct - approved_leaves_pct
        
        approved_offset = 25 - pending_leaves_pct
        rejected_offset = 25 - pending_leaves_pct - approved_leaves_pct

    # Get lists
    employees_list = Employee.objects.all().order_by('-id')
    pending_requests = LeaveRequest.objects.filter(status='Pending').order_by('-id')
    recent_attendance = Attendance.objects.filter(date=date.today()).order_by('-clock_in')
    
    # Historical Attendance Log Filtering & Pagination
    from django.core.paginator import Paginator
    selected_employee_id = request.GET.get('attendance_employee')
    selected_date_str = request.GET.get('attendance_date')
    selected_month_str = request.GET.get('attendance_month')
    
    attendance_qs = Attendance.objects.all().select_related('employee', 'employee__user').order_by('-date', '-clock_in')
    
    selected_employee_id_int = None
    if selected_employee_id:
        try:
            selected_employee_id_int = int(selected_employee_id)
            attendance_qs = attendance_qs.filter(employee_id=selected_employee_id_int)
        except ValueError:
            pass
            
    if selected_date_str:
        try:
            selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
            attendance_qs = attendance_qs.filter(date=selected_date)
        except ValueError:
            pass
            
    monthly_summary = []
    if selected_month_str:
        try:
            year, month = map(int, selected_month_str.split('-'))
            attendance_qs = attendance_qs.filter(date__year=year, date__month=month)
            
            import calendar
            from django.db.models import Sum
            _, no_of_days = calendar.monthrange(year, month)
            
            sundays = sum(1 for d in range(1, no_of_days + 1) if calendar.weekday(year, month, d) == 6)
            holidays_qs = Holiday.objects.filter(date__year=year, date__month=month)
            holidays = holidays_qs.count()
            holiday_dates = list(holidays_qs.values_list('date', flat=True))
            
            no_of_working_days = no_of_days - sundays - holidays
            
            for emp in employees_list:
                if selected_employee_id_int and emp.id != selected_employee_id_int:
                    continue
                emp_att = Attendance.objects.filter(employee=emp, date__year=year, date__month=month)
                present_qs = emp_att.filter(status__in=['Present', 'Half Day', 'Work From Home'])
                present = present_qs.count()
                
                holiday_working = 0
                for att in present_qs:
                    if att.date.weekday() == 6 or att.date in holiday_dates:
                        holiday_working += 1
                        
                absent = no_of_working_days - (present - holiday_working)
                if absent < 0: absent = 0
                
                total_days = present + sundays + holidays - holiday_working
                
                ot_mins = present_qs.aggregate(Sum('overtime_minutes'))['overtime_minutes__sum'] or 0
                ot_hours = round(ot_mins / 60.0, 2)
                
                permission = emp_att.aggregate(Sum('late_minutes'))['late_minutes__sum'] or 0
                nsa = 0
                
                monthly_summary.append({
                    'emp': emp,
                    'no_of_days': no_of_days,
                    'no_of_working_days': no_of_working_days,
                    'present': present,
                    'absent': absent,
                    'holiday_working': holiday_working,
                    'sundays': sundays,
                    'holidays': holidays,
                    'total_days': total_days,
                    'ot': ot_hours,
                    'permission': permission,
                    'nsa': nsa
                })
        except ValueError:
            pass
            
    paginator = Paginator(attendance_qs, 20)
    page_number = request.GET.get('page')
    attendance_logs_page = paginator.get_page(page_number)
    
    # Recruitment listings
    job_postings = JobPosting.objects.all().order_by('-created_at')
    applications = JobApplication.objects.all().order_by('-applied_at')
    application_statuses = [status[0] for status in JobApplication.STATUS_CHOICES]
    
    # Payslips listings
    payslips = Payslip.objects.all().order_by('-id')
    # Performance reviews and trainings
    reviews = PerformanceReview.objects.all().order_by('-created_at')
    trainings = Training.objects.all().order_by('-start_date')
    enrollments = TrainingEnrollment.objects.all().order_by('-enrolled_at')
    all_performance_reviews = PerformanceReview.objects.all().order_by('-id')
    
    goals = GoalTracking.objects.all().order_by('-created_at')
    departments = Department.objects.all().order_by('name')
    designations = Designation.objects.all().order_by('name')

    context = {
        'goals': goals,
        'admin_employee': admin_employee,
        'total_employees': total_employees,
        'pending_leaves': pending_leaves,
        'approved_leaves': approved_leaves,
        'rejected_leaves': rejected_leaves,
        'total_leaves': total_leaves,
        'pending_leaves_pct': pending_leaves_pct,
        'pending_leaves_pct_rem': 100 - pending_leaves_pct,
        'approved_leaves_pct': approved_leaves_pct,
        'approved_leaves_pct_rem': 100 - approved_leaves_pct,
        'rejected_leaves_pct': rejected_leaves_pct,
        'rejected_leaves_pct_rem': 100 - rejected_leaves_pct,
        'approved_offset': approved_offset,
        'rejected_offset': rejected_offset,
        'dept_stats': dept_stats,
        'clocked_in_today': clocked_in_today,
        'employees_list': employees_list,
        'pending_requests': pending_requests,
        'recent_attendance': recent_attendance,
        'attendance_logs_page': attendance_logs_page,
        'monthly_summary': monthly_summary,
        'selected_employee_id': selected_employee_id_int,
        'selected_date_str': selected_date_str or '',
        'selected_month_str': selected_month_str or '',
        'job_postings': job_postings,
        'applications': applications,
        'application_statuses': application_statuses,
        'all_performance_reviews': all_performance_reviews,
        'payslips': payslips,
        'reviews': reviews,
        'trainings': trainings,
        'enrollments': enrollments,
        'shifts': Shift.objects.all().order_by('name'),
        'assets': Asset.objects.all().order_by('-id'),
        'expenses': Expense.objects.all().order_by('-id'),
        'departments': departments,
        'designations': designations,
        'activity_logs': ActivityLog.objects.all().order_by('-timestamp')[:500],
        'calendar_events_json': get_unified_calendar_events(user=request.user),
        'holidays': Holiday.objects.all().order_by('date'),
        'hr_letters': HRLetter.objects.select_related('employee__user').all().order_by('-issue_date'),
    }
    return render(request, 'employees/admin_dashboard.html', context)

@admin_only
def add_employee(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        password = request.POST.get('password')
        department_id = request.POST.get('department_id')
        department_name = request.POST.get('department')
        designation_id = request.POST.get('designation_id')
        designation = request.POST.get('designation', '')
        
        if not department_id and department_name:
            dept_obj, _ = Department.objects.get_or_create(name=department_name)
            department_id = dept_obj.id
            
        if not designation_id and designation:
            desig_obj, _ = Designation.objects.get_or_create(name=designation)
            designation_id = desig_obj.id

        role = request.POST.get('role', 'Employee')
        phone = request.POST.get('phone')
        salary = request.POST.get('salary', 0.0)
        gender = request.POST.get('gender')
        date_of_birth = request.POST.get('date_of_birth')
        address = request.POST.get('address')
        
        # Auto-generate employee ID
        prefix_map = {
            'General Manager (GM)': 'GM',
            'Manager (BM)': 'M',
            'Employee (EMP)': 'EMP',
            'General HR (GH)': 'GH',
            'HR': 'HR',
            'Admin': 'ADM'
        }
        prefix = prefix_map.get(designation, 'EMP')
        
        # Find the highest existing ID with this prefix
        import re
        existing_emps = Employee.objects.filter(employee_id_code__startswith=prefix)
        max_num = 0
        for emp in existing_emps:
            if emp.employee_id_code:
                match = re.match(fr"^{prefix}(\d+)$", emp.employee_id_code)
                if match:
                    num = int(match.group(1))
                    if num > max_num:
                        max_num = num
                        
        next_num = max_num + 1
        employee_id_code = f"{prefix}{next_num:03d}"

        is_admin_flag = request.POST.get('is_company_admin') == 'on'
        shift_id = request.POST.get('shift_id')
        ot_hourly_rate = request.POST.get('ot_hourly_rate', 0.0)
        grace_period_minutes = int(request.POST.get('grace_period_minutes', 120))
        
        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
        elif User.objects.filter(email=email).exists():
            messages.error(request, "Email already exists.")
        else:
            user = User.objects.create_user(
                username=username,
                password=password,
                email=email,
                first_name=first_name,
                last_name=last_name
            )
            emp_kwargs = dict(
                user=user,
                phone=phone,
                salary=salary,
                is_company_admin=is_admin_flag,
                ot_hourly_rate=ot_hourly_rate,
                grace_period_minutes=grace_period_minutes,
                role=role
            )
            if department_id:
                emp_kwargs['department_id'] = department_id
            if designation_id:
                emp_kwargs['designation_id'] = designation_id
            if shift_id:
                try:
                    emp_kwargs['shift_id'] = shift_id
                except ValueError:
                    pass
            if gender:
                emp_kwargs['gender'] = gender
            if date_of_birth:
                try:
                    emp_kwargs['date_of_birth'] = datetime.strptime(date_of_birth, '%Y-%m-%d').date()
                except Exception:
                    pass
            if address:
                emp_kwargs['address'] = address
            if employee_id_code:
                emp_kwargs['employee_id_code'] = employee_id_code

            new_emp = Employee.objects.create(**emp_kwargs)
            
            # Save photo from file or camera capture
            photo_file = request.FILES.get('photo')
            photo_b64 = request.POST.get('photo_b64')
            if photo_file or photo_b64:
                save_and_sync_employee_photo(new_emp, photo_file=photo_file, photo_b64=photo_b64)

            log_activity(request.user, f'Created Employee {first_name} {last_name}', 'Employee Management', request)
            messages.success(request, f"Employee {first_name} {last_name} created successfully!")
            
    return redirect('admin_dashboard')

@admin_only
def approve_leave(request, leave_id):
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    if leave.status == 'Pending':
        days = (leave.end_date - leave.start_date).days + 1
        emp = leave.employee
        
        # Deduct balance based on type
        if leave.leave_type == 'Sick':
            emp.sick_leave_balance = max(0, emp.sick_leave_balance - days)
        elif leave.leave_type == 'Casual':
            emp.casual_leave_balance = max(0, emp.casual_leave_balance - days)
        elif leave.leave_type == 'Annual':
            emp.annual_leave_balance = max(0, emp.annual_leave_balance - days)
            
        emp.save()
        leave.status = 'Approved'
        leave.save()
        
        if leave.employee.user and leave.employee.user != request.user:
            Notification.objects.create(user=leave.employee.user, title="Leave Approved", message=f"Your {leave.leave_type} request has been approved.")
            
        messages.success(request, f"Leave request for {leave.employee.user.first_name} was approved and balances updated.")
    return redirect('admin_dashboard')

@admin_only
def reject_leave(request, leave_id):
    leave = get_object_or_404(LeaveRequest, id=leave_id)
    if leave.status == 'Pending':
        leave.status = 'Rejected'
        leave.save()
        
        if leave.employee.user and leave.employee.user != request.user:
            Notification.objects.create(user=leave.employee.user, title="Leave Rejected", message=f"Your {leave.leave_type} request has been rejected.")
            
        messages.success(request, f"Leave request for {leave.employee.user.first_name} was rejected.")
    return redirect('admin_dashboard')

# --- Recruitment / ATS Views ---

def careers_list(request):
    if request.method == 'POST':
        job_id = request.POST.get('job_id')
        job = get_object_or_404(JobPosting, id=job_id)
        candidate_name = request.POST.get('candidate_name')
        candidate_email = request.POST.get('candidate_email')
        candidate_phone = request.POST.get('candidate_phone')
        resume_url = request.POST.get('resume_url')
        resume_pdf = request.FILES.get('resume_pdf')
        cover_letter = request.POST.get('cover_letter')
        
        JobApplication.objects.create(
            job=job,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            candidate_phone=candidate_phone,
            resume_url=resume_url,
            resume_pdf=resume_pdf,
            cover_letter=cover_letter
        )
        messages.success(request, f"Application for the {job.title} position submitted successfully!")
        return redirect('careers_list')
        
    jobs = JobPosting.objects.filter(is_active=True).order_by('-created_at')
    return render(request, 'employees/careers_list.html', {'jobs': jobs})

def apply_job(request, job_id):
    # Keep for backward compatibility with tests
    job = get_object_or_404(JobPosting, id=job_id)
    if request.method == 'POST':
        candidate_name = request.POST.get('candidate_name')
        candidate_email = request.POST.get('candidate_email')
        candidate_phone = request.POST.get('candidate_phone')
        resume_url = request.POST.get('resume_url')
        resume_pdf = request.FILES.get('resume_pdf')
        cover_letter = request.POST.get('cover_letter')
        
        JobApplication.objects.create(
            job=job,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            candidate_phone=candidate_phone,
            resume_url=resume_url,
            resume_pdf=resume_pdf,
            cover_letter=cover_letter
        )
        messages.success(request, f"Application for the {job.title} position submitted successfully!")
        return redirect('careers_list')
        
    return render(request, 'employees/apply_job.html', {'job': job})

@admin_only
def add_job(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        requirements = request.POST.get('requirements')
        location = request.POST.get('location')
        salary_range = request.POST.get('salary_range')
        
        JobPosting.objects.create(
            title=title,
            description=description,
            requirements=requirements,
            location=location,
            salary_range=salary_range
        )
        messages.success(request, f"Job posting '{title}' created successfully!")
    return redirect('admin_dashboard')

@admin_only
def update_application_status(request, app_id):
    application = get_object_or_404(JobApplication, id=app_id)
    if request.method == 'POST':
        status = request.POST.get('status')
        old_status = application.status
        application.status = status
        application.save()
        
        # Send Email Notification
        if status != old_status:
            from django.core.mail import send_mail
            from django.conf import settings
            
            subject = f"Update on your application for {application.job.title}"
            if status == 'Interviewing':
                message = f"Hi {application.candidate_name},\n\nGood news! We would like to invite you for an interview for the {application.job.title} position.\n\nOur team will be in touch shortly with details.\n\nBest regards,\nHR Team"
            elif status == 'Rejected':
                message = f"Hi {application.candidate_name},\n\nThank you for taking the time to apply for the {application.job.title} position.\n\nAfter careful consideration, we have decided to move forward with other candidates whose qualifications better meet our needs at this time.\n\nWe wish you the best in your job search.\n\nBest regards,\nHR Team"
            elif status == 'Offered':
                message = f"Hi {application.candidate_name},\n\nCongratulations! We are thrilled to offer you the {application.job.title} position. We will be sending your official offer letter shortly.\n\nBest regards,\nHR Team"
            elif status == 'Hired':
                message = f"Hi {application.candidate_name},\n\nWelcome to the team! We are excited to have you on board as our new {application.job.title}.\n\nBest regards,\nHR Team"
            else:
                message = f"Hi {application.candidate_name},\n\nYour application status for the {application.job.title} position has been updated to: {status}.\n\nBest regards,\nHR Team"
            
            try:
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,
                    [application.candidate_email],
                    fail_silently=True
                )
            except Exception as e:
                pass
                
        messages.success(request, f"Candidate {application.candidate_name}'s status updated to {status}, and an email has been sent!")
    return redirect('admin_dashboard')

# --- Payroll / Payslip Views ---

@admin_only
def generate_payslip(request):
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        month_year = request.POST.get('month_year')
        # Detailed breakdowns
        hra = float(request.POST.get('hra', 0.0))
        travel_allowance = float(request.POST.get('travel_allowance', 0.0))
        other_allowances = float(request.POST.get('allowances', 0.0))
        pf_deduction = float(request.POST.get('pf_deduction', 0.0))
        tax_deduction = float(request.POST.get('tax_deduction', 0.0))
        esi_deduction = float(request.POST.get('esi_deduction', 0.0))
        other_deductions = float(request.POST.get('deductions', 0.0))
        allowances = hra + travel_allowance + other_allowances
        deductions = pf_deduction + tax_deduction + esi_deduction + other_deductions
        status = request.POST.get('status', 'Pending')
        
        employee = get_object_or_404(Employee, id=employee_id)
        
        # Calculate attendance hours to derive dynamic basic salary
        import re
        month_map = {
            'january': 1, 'jan': 1,
            'february': 2, 'feb': 2,
            'march': 3, 'mar': 3,
            'april': 4, 'apr': 4,
            'may': 5,
            'june': 6, 'jun': 6,
            'july': 7, 'jul': 7,
            'august': 8, 'aug': 8,
            'september': 9, 'sep': 9,
            'october': 10, 'oct': 10,
            'november': 11, 'nov': 11,
            'december': 12, 'dec': 12
        }
        
        match = re.search(r'([a-zA-Z]+)\s*(\d{4})', month_year)
        total_hours_worked = 0.0
        total_lop_days = 0
        hourly_rate = 0.0
        
        total_late_mins = 0
        severe_late_incidents = 0
        total_ot_mins = 0
        
        if match:
            m_name = match.group(1).lower()
            year = int(match.group(2))
            month = month_map.get(m_name)
            if month:
                records = Attendance.objects.filter(
                    employee=employee,
                    date__year=year,
                    date__month=month
                )
                for r in records:
                    th = r.total_hours
                    if th is not None:
                        total_hours_worked += th
                    total_ot_mins += r.overtime_minutes
                    if r.late_minutes >= 30:
                        severe_late_incidents += 1
                    elif r.late_minutes > 0:
                        total_late_mins += r.late_minutes
                
                from django.db.models import Sum
                lop_agg = LeaveRequest.objects.filter(
                    employee=employee,
                    status='Approved',
                    start_date__year=year,
                    start_date__month=month
                ).aggregate(total_lop=Sum('lop_days'))
                total_lop_days = lop_agg['total_lop'] or 0

        base_salary = float(employee.salary)
        
        # Calculate Overtime Pay
        ot_hours = total_ot_mins / 60.0
        ot_pay = ot_hours * float(employee.ot_hourly_rate)
        allowances += ot_pay
        
        # Calculate Late Penalty LOP
        late_penalty_lop_days = 0.0
        if total_late_mins > employee.grace_period_minutes:
            excess_late_mins = total_late_mins - employee.grace_period_minutes
            # Convert excess late mins to days based on a standard 9-hour shift (540 mins)
            # If employee has a shift, we can use shift duration
            shift_mins = 540
            if employee.shift:
                import datetime
                shift_duration = (datetime.datetime.combine(datetime.date.today(), employee.shift.end_time) - datetime.datetime.combine(datetime.date.today(), employee.shift.start_time)).total_seconds() / 60
                if shift_duration < 0:
                    shift_duration += 24 * 60
                shift_mins = shift_duration or 540
            late_penalty_lop_days += excess_late_mins / shift_mins
            
        # 30-Minute Penalty Rule
        late_penalty_lop_days += (severe_late_incidents // 4) * 0.5
        
        total_lop_days += float(late_penalty_lop_days)
        
        lop_deduction = round((base_salary / 30.0) * total_lop_days, 2)

        # Basic salary is fixed. Any absences or lateness are handled by lop_deduction.
        basic = base_salary

        total_deductions = deductions + lop_deduction
        net = basic + allowances - total_deductions
        
        # Check if payslip already exists for this employee for this month
        already_exists = Payslip.objects.filter(employee=employee, month_year=month_year).exists()
        if already_exists:
            messages.error(request, f"Payslip for {employee.user.first_name} for {month_year} already exists.")
        else:
            Payslip.objects.create(
                employee=employee,
                month_year=month_year,
                basic_salary=basic,
                allowances=allowances,
                hra=hra,
                travel_allowance=travel_allowance,
                deductions=total_deductions,
                pf_deduction=pf_deduction,
                tax_deduction=tax_deduction,
                esi_deduction=esi_deduction,
                lop_days=total_lop_days,
                lop_deduction=lop_deduction,
                total_late_mins=total_late_mins,
                severe_late_incidents=severe_late_incidents,
                late_penalty_lop_days=late_penalty_lop_days,
                net_salary=net,
                status=status
            )
            
            if employee.user and employee.user != request.user:
                Notification.objects.create(user=employee.user, title="New Payslip Available", message=f"Your payslip for {month_year} is now available.")

            if total_hours_worked > 0:
                messages.success(
                    request,
                    f"Payslip for {employee.user.first_name} generated successfully. "
                    f"Worked {total_hours_worked:.1f} hours in {month_year} "
                    f"(Hourly Rate: ₹{hourly_rate:.2f}/hr, Calculated Basic: ₹{basic:.2f})."
                )
            else:
                messages.success(
                    request,
                    f"Payslip for {employee.user.first_name} generated successfully. "
                    f"No attendance logs found for {month_year}; used full base salary (₹{basic:.2f})."
                )
            
    return redirect('admin_dashboard')


@admin_only
def add_performance_review(request):
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        reviewer_id = request.POST.get('reviewer_id')
        review_period = request.POST.get('review_period')
        rating = request.POST.get('rating')
        goals = request.POST.get('goals')
        feedback = request.POST.get('feedback')

        employee = get_object_or_404(Employee, id=employee_id)
        reviewer = None
        if reviewer_id:
            reviewer = Employee.objects.filter(id=reviewer_id).first()

        PerformanceReview.objects.create(
            employee=employee,
            reviewer=reviewer,
            review_period=review_period,
            rating=rating or 0,
            goals=goals,
            feedback=feedback
        )
        if employee.user and employee.user != request.user:
            Notification.objects.create(user=employee.user, title="New Performance Review", message=f"A new performance review for {review_period} has been added to your profile.")
        messages.success(request, "Performance review added.")
    return redirect('admin_dashboard')


@admin_only
def add_training(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description')
        trainer = request.POST.get('trainer')
        start_date = request.POST.get('start_date') or None
        end_date = request.POST.get('end_date') or None
        is_online = request.POST.get('is_online') == 'on'
        status = request.POST.get('status') or 'Upcoming'

        Training.objects.create(
            title=title,
            description=description,
            trainer=trainer,
            start_date=start_date,
            end_date=end_date,
            is_online=is_online,
            status=status
        )
        messages.success(request, "Training program created.")
    return redirect('admin_dashboard')


@admin_only
def enroll_training(request):
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        training_id = request.POST.get('training_id')
        employee = get_object_or_404(Employee, id=employee_id)
        training = get_object_or_404(Training, id=training_id)
        TrainingEnrollment.objects.create(employee=employee, training=training)
        if employee.user and employee.user != request.user:
            Notification.objects.create(user=employee.user, title="New Training Enrollment", message=f"You have been enrolled in '{training.title}'.")
        messages.success(request, f"{employee.user.first_name} enrolled in {training.title}.")
    return redirect('admin_dashboard')


@admin_only
def complete_training(request, enrollment_id):
    enrollment = get_object_or_404(TrainingEnrollment, id=enrollment_id)
    enrollment.completed = True
    cert = request.POST.get('certificate_url') if request.method == 'POST' else None
    if cert:
        enrollment.certificate_url = cert
    enrollment.save()
    messages.success(request, f"Marked training '{enrollment.training.title}' as completed for {enrollment.employee.user.first_name}.")
    return redirect('admin_dashboard')


@admin_only
def reports_data(request):
    # Attendance summary
    from django.db.models import Count, Sum
    total_employees = Employee.objects.filter(is_company_admin=False).count()
    attendance_counts = Attendance.objects.values('status').annotate(count=Count('id'))
    attendance_summary = {a['status']: a['count'] for a in attendance_counts}

    # Leave stats
    leave_counts = LeaveRequest.objects.values('leave_type').annotate(count=Count('id'))
    leave_summary = {l['leave_type']: l['count'] for l in leave_counts}

    # Payroll totals (simple sums)
    payroll_total = Payslip.objects.aggregate(total=Sum('net_salary'))['total'] or 0

    goals = GoalTracking.objects.all().order_by('-created_at')

    context = {
        'goals': goals,
        'attendance_summary': attendance_summary,
        'leave_summary': leave_summary,
        'payroll_total': payroll_total,
        'total_employees': total_employees,
    }
    return render(request, 'employees/reports.html', context)


@login_required
def profile_update_view(request):
    if request.method == 'POST':
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        
        user = request.user
        employee = user.employee
        
        if not email:
            messages.error(request, "Email address is required.")
        else:
            if User.objects.filter(email=email).exclude(id=user.id).exists():
                messages.error(request, "Email address is already in use by another user.")
            else:
                user.email = email
                user.save()
                employee.phone = phone
                if request.FILES.get('photo'):
                    employee.photo = request.FILES.get('photo')
                employee.save()
                messages.success(request, "Profile details updated successfully!")
                
    return redirect('employee_dashboard')


@login_required
def change_password_view(request):
    if request.method == 'POST':
        old_password = request.POST.get('old_password')
        new_password = request.POST.get('new_password')
        confirm_password = request.POST.get('confirm_password')
        
        user = request.user
        
        if not user.check_password(old_password):
            messages.error(request, "Incorrect current password.")
        elif new_password != confirm_password:
            messages.error(request, "New passwords do not match.")
        elif len(new_password) < 6:
            messages.error(request, "New password must be at least 6 characters long.")
        else:
            user.set_password(new_password)
            user.save()
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, user)
            messages.success(request, "Password updated successfully!")
            
    return redirect('employee_dashboard')


@admin_only
def toggle_job_status(request, job_id):
    job = get_object_or_404(JobPosting, id=job_id)
    job.is_active = not job.is_active
    job.save()
    status_str = "activated" if job.is_active else "deactivated"
    messages.success(request, f"Job posting '{job.title}' has been {status_str}.")
    return redirect('admin_dashboard')


@admin_only
def delete_employee(request, employee_id):
    if request.method == 'POST':
        employee = get_object_or_404(Employee, id=employee_id)
        if employee.user == request.user:
            messages.error(request, "You cannot delete your own admin account.")
            return redirect('admin_dashboard')
        
        user = employee.user
        username = user.username
        user.delete()
        messages.success(request, f"Employee '{username}' deleted successfully.")
    return redirect('admin_dashboard')


@admin_only
def reset_employee_password(request, employee_id):
    if request.method == 'POST':
        employee = get_object_or_404(Employee, id=employee_id)
        new_pw = request.POST.get('new_password', '').strip()
        if new_pw:
            employee.user.set_password(new_pw)
            employee.user.save()
            messages.success(request, f"Password for '{employee.user.username}' reset successfully.")
        else:
            messages.error(request, "Password cannot be empty.")
    return redirect('admin_dashboard')


@admin_only
def delete_payslip(request, payslip_id):
    if request.method == 'POST':
        payslip = Payslip.objects.filter(id=payslip_id).first()
        if payslip:
            emp_name = payslip.employee.user.first_name or payslip.employee.user.username
            month = payslip.month_year
            payslip.delete()
            messages.success(request, f"Payslip for {emp_name} for {month} has been deleted.")
        else:
            messages.warning(request, "This payslip was already deleted or does not exist.")
    return redirect('admin_dashboard')

@admin_only
def toggle_payslip_status(request, payslip_id):
    if request.method == 'POST':
        payslip = get_object_or_404(Payslip, id=payslip_id)
        new_status = request.POST.get('status')
        if new_status in ['Paid', 'Pending']:
            payslip.status = new_status
        else:
            payslip.status = 'Pending' if payslip.status == 'Paid' else 'Paid'

        if payslip.status == 'Paid' and payslip.employee.user:
            from .models import Notification
            Notification.objects.create(
                user=payslip.employee.user,
                title="Payslip Marked as Paid",
                message=f"Your payslip for {payslip.month_year} has been marked as Paid."
            )
        payslip.save()
        messages.success(request, f"Payslip for {payslip.employee.user.first_name} ({payslip.month_year}) status changed to '{payslip.status}'.")
    return redirect('/admin-dashboard/?tab=payroll')

@admin_only
def view_payslip(request, payslip_id):
    from django.shortcuts import get_object_or_404
    payslip = get_object_or_404(Payslip, id=payslip_id)
    return render(request, 'employees/view_payslip.html', {'payslip': payslip, 'employee': payslip.employee})

import json
from django.core.serializers.json import DjangoJSONEncoder

@admin_only
def holidays_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        date_str = request.POST.get('date')
        type_str = request.POST.get('type', 'Holiday')
        if name and date_str:
            Holiday.objects.create(name=name, date=date_str, type=type_str)
            msg = f"A new {type_str} '{name}' has been added on {date_str}."
            employees = Employee.objects.all()
            for emp in employees:
                if emp.user and emp.user != request.user:
                    Notification.objects.create(user=emp.user, title="New Company Schedule", message=msg)
            messages.success(request, f"'{name}' added successfully.")
        return redirect('/admin-dashboard/?tab=calendar')
        
    holidays = Holiday.objects.all().order_by('date')
    
    events = []
    for h in holidays:
        events.append({
            'title': h.name,
            'start': h.date.isoformat(),
            'color': '#2563eb' if h.type == 'Holiday' else '#94a3b8',
            'extendedProps': {
                'type': h.type
            }
        })
    events_json = json.dumps(events, cls=DjangoJSONEncoder)
    
    return render(request, 'employees/holidays.html', {'holidays': holidays, 'events_json': events_json})

@admin_only
def clients_view(request):
    if request.method == 'POST':
        company_name = request.POST.get('company_name')
        client_id_val = request.POST.get('client_id')
        contact_person = request.POST.get('contact_person')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()

        # Optionally create a User for client portal login
        user_obj = None
        if username and password:
            if User.objects.filter(username=username).exists():
                messages.error(request, f"Username '{username}' already taken. Client not created.")
                return redirect('clients')
            user_obj = User.objects.create_user(
                username=username, password=password,
                email=email, first_name=contact_person
            )

        Client.objects.create(
            user=user_obj,
            company_name=company_name,
            client_id=client_id_val,
            contact_person=contact_person,
            email=email,
            phone=phone
        )
        if user_obj:
            messages.success(request, f"Client '{company_name}' added with portal login '{username}'.")
        else:
            messages.success(request, f"Client '{company_name}' added successfully.")
        return redirect('clients')

    clients = Client.objects.all().order_by('-created_at')
    return render(request, 'employees/clients.html', {'clients': clients})

@admin_only
def goals_view(request):
    if request.method == 'POST':
        subject = request.POST.get('subject')
        project_id = request.POST.get('project_id')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        description = request.POST.get('description')
        status = request.POST.get('status', 'Active')
        
        project = None
        if project_id:
            project = Project.objects.filter(id=project_id).first()
        
        goal = GoalTracking.objects.create(
            subject=subject,
            project=project,
            start_date=start_date,
            end_date=end_date,
            description=description,
            status=status
        )
        
        # Broadcast notifications
        msg = f"A new goal '{subject}' has been added."
        
        # 1. Notify all employees
        employees = Employee.objects.all()
        for emp in employees:
            if emp.user and emp.user != request.user:
                Notification.objects.create(user=emp.user, title="New Goal Added", message=msg)
                
        # 2. Notify client if project exists
        if project and project.client and project.client.user and project.client.user != request.user:
            Notification.objects.create(user=project.client.user, title="New Project Goal", message=msg)

        messages.success(request, "Goal created successfully.")
        return redirect('goals')

    goals = GoalTracking.objects.all().order_by('-created_at')
    projects = Project.objects.all().order_by('name')
    return render(request, 'employees/goals.html', {'goals': goals, 'projects': projects})

@admin_only
def update_goal_status(request, goal_id):
    if request.method == 'POST':
        goal = get_object_or_404(GoalTracking, id=goal_id)
        new_status = request.POST.get('status')
        if new_status in ['Active', 'Pending', 'Completed']:
            goal.status = new_status
            goal.save()
            messages.success(request, f"Goal status updated to {new_status}.")
    return redirect('goals')

@admin_only
def delete_goal(request, goal_id):
    if request.method == 'POST':
        goal = get_object_or_404(GoalTracking, id=goal_id)
        goal.delete()
        messages.success(request, "Goal deleted successfully.")
    return redirect('goals')

@admin_only
def projects_view(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        client_id = request.POST.get('client_id') or None
        description = request.POST.get('description')
        deadline = request.POST.get('deadline') or None
        progress = int(request.POST.get('progress', 0))
        status = request.POST.get('status', 'Active')
        client = None
        if client_id:
            client = Client.objects.filter(id=client_id).first()
        assigned_employee_ids = request.POST.getlist('assigned_employees')
        
        project = Project.objects.create(
            name=name, client=client, description=description,
            deadline=deadline, progress=progress, status=status
        )
        
        if assigned_employee_ids:
            project.assigned_employees.set(assigned_employee_ids)
            for emp_id in assigned_employee_ids:
                emp = Employee.objects.filter(id=emp_id).first()
                if emp and emp.user and emp.user != request.user:
                    Notification.objects.create(user=emp.user, title="New Project Assignment", message=f"You have been assigned to project '{name}'.")

        msg = f"Project '{name}' has been created."
        if client and client.user and client.user != request.user:
            Notification.objects.create(user=client.user, title="New Project Created", message=msg)
            
        admins = Employee.objects.filter(is_company_admin=True)
        for adm in admins:
            if adm.user and adm.user != request.user:
                Notification.objects.create(user=adm.user, title="New Project Created", message=msg)
                
        messages.success(request, f"Project '{name}' created successfully.")
        return redirect('projects')

    projects = Project.objects.all().select_related('client').prefetch_related('assigned_employees__user').order_by('-created_at')
    clients = Client.objects.filter(status='Active').order_by('company_name')
    all_employees = Employee.objects.select_related('user').order_by('user__first_name')
    return render(request, 'employees/projects.html', {'projects': projects, 'clients': clients, 'all_employees': all_employees})

@admin_only
def update_project_progress(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == 'POST':
        project.progress = int(request.POST.get('progress', project.progress))
        project.status = request.POST.get('status', project.status)
        project.save()
        messages.success(request, f"Project '{project.name}' updated.")
    return redirect('projects')

@admin_only
def edit_project(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if request.method == 'POST':
        project.name = request.POST.get('name', project.name)
        client_id = request.POST.get('client_id')
        if client_id:
            project.client = Client.objects.filter(id=client_id).first()
        else:
            project.client = None
        project.deadline = request.POST.get('deadline') or None
        project.progress = int(request.POST.get('progress', project.progress))
        project.status = request.POST.get('status', project.status)
        project.description = request.POST.get('description', project.description)
        project.save()

        assigned_employee_ids = request.POST.getlist('assigned_employees')
        if assigned_employee_ids:
            project.assigned_employees.set(assigned_employee_ids)

        messages.success(request, f"Project '{project.name}' updated successfully.")
    return redirect('projects')

# ---- Client Portal ----

client_login_view = employee_login_view

@login_required
def client_dashboard_view(request):
    try:
        client = request.user.client_profile
    except Exception:
        messages.error(request, "Access denied. This area is for clients only.")
        return redirect('client_login')
    projects = Project.objects.filter(client=client).order_by('-created_at')

    holidays = Holiday.objects.all().order_by('date')
    events = []
    for h in holidays:
        events.append({
            'title': h.name,
            'start': h.date.isoformat(),
            'color': '#2563eb' if getattr(h, 'type', 'Holiday') == 'Holiday' else '#94a3b8',
            'extendedProps': {
                'type': getattr(h, 'type', 'Holiday')
            }
        })
    events_json = json.dumps(events, cls=DjangoJSONEncoder)
    
    goals = GoalTracking.objects.filter(project__client=client).order_by('-created_at')

    completed_count = projects.filter(status='Completed').count()
    active_count = projects.exclude(status='Completed').count()

    return render(request, 'employees/client_dashboard.html', {
        'goals': goals,
        'events_json': events_json,
        'client': client,
        'projects': projects,
        'completed_count': completed_count,
        'active_count': active_count,
    })


@admin_only
def admin_project_detail_view(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    updates = project.updates.all().order_by('created_at')
    all_employees = Employee.objects.select_related('user').order_by('user__first_name')
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        if action == 'add_member':
            emp_id = request.POST.get('employee_id')
            if emp_id:
                emp = Employee.objects.filter(id=emp_id).first()
                if emp:
                    project.assigned_employees.add(emp)
                    messages.success(request, f"{emp.user.get_full_name()} added to project.")
                    if emp.user and emp.user != request.user:
                        Notification.objects.create(user=emp.user, title="Project Assignment", message=f"You have been assigned to project '{project.name}'.")
            return redirect('admin_project_detail', project_id=project.id)
            
        message = request.POST.get('message', '').strip()
        progress = request.POST.get('progress')
        status = request.POST.get('status')
        
        updated_anything = False
        
        if progress is not None and progress != '':
            project.progress = int(progress)
            updated_anything = True
        if status:
            project.status = status
            updated_anything = True
            
        if updated_anything:
            project.save()
            
        if message:
            ProjectUpdate.objects.create(
                project=project,
                author=request.user,
                message=message,
                is_admin=True
            )
            messages.success(request, "Project status update posted successfully.")
            if project.client and project.client.user and project.client.user != request.user:
                Notification.objects.create(user=project.client.user, title="Project Update", message=f"A new update was posted for project '{project.name}'.")
            for emp in project.assigned_employees.all():
                if emp.user:
                    Notification.objects.create(user=emp.user, title="Project Update", message=f"A new update was posted for project '{project.name}'.")
        elif updated_anything:
            messages.success(request, "Project details updated.")
            
        return redirect('admin_project_detail', project_id=project.id)
        
    return render(request, 'employees/admin_project_detail.html', {
        'project': project,
        'updates': updates,
        'all_employees': all_employees
    })

@admin_only
def remove_project_employee(request, project_id, employee_id):
    project = get_object_or_404(Project, id=project_id)
    emp = get_object_or_404(Employee, id=employee_id)
    project.assigned_employees.remove(emp)
    
    if emp.user and emp.user != request.user:
        Notification.objects.create(user=emp.user, title="Project Removal", message=f"You have been removed from project '{project.name}'.")
        
    messages.success(request, f"{emp.user.get_full_name()} removed from project.")
    return redirect('admin_project_detail', project_id=project.id)


@login_required
def client_project_detail_view(request, project_id):
    try:
        client = request.user.client_profile
    except Exception:
        messages.error(request, "Access denied. This area is for clients only.")
        return redirect('client_login')
        
    project = get_object_or_404(Project, id=project_id, client=client)
    updates = project.updates.all().order_by('created_at')
    
    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        if message:
            ProjectUpdate.objects.create(
                project=project,
                author=request.user,
                message=message,
                is_admin=False
            )
            messages.success(request, "Your reply has been posted.")
            admins = Employee.objects.filter(is_company_admin=True)
            for adm in admins:
                if adm.user and adm.user != request.user:
                    Notification.objects.create(user=adm.user, title="Client Project Update", message=f"Client '{client.company_name}' posted an update for project '{project.name}'.")
        return redirect('client_project_detail', project_id=project.id)
        
    return render(request, 'employees/client_project_detail.html', {
        'project': project,
        'updates': updates
    })

@admin_only
def edit_employee(request, employee_id):
    if request.method == 'POST':
        employee = get_object_or_404(Employee, id=employee_id)
        user = employee.user
        
        user.first_name = request.POST.get('first_name', user.first_name)
        user.last_name = request.POST.get('last_name', user.last_name)
        user.email = request.POST.get('email', user.email)
        user.save()
        
        dept_id = request.POST.get('department_id')
        if dept_id:
            employee.department_id = dept_id
        desig_id = request.POST.get('designation_id')
        if desig_id:
            employee.designation_id = desig_id
        role = request.POST.get('role')
        if role:
            employee.role = role
        if request.POST.get('basic_salary'):
            employee.salary = request.POST.get('basic_salary')
            
        shift_id = request.POST.get('shift_id')
        if shift_id:
            try:
                employee.shift_id = shift_id
            except ValueError:
                pass
        else:
            employee.shift = None
            
        if request.POST.get('ot_hourly_rate'):
            employee.ot_hourly_rate = request.POST.get('ot_hourly_rate')
            
        if request.POST.get('grace_period_minutes'):
            employee.grace_period_minutes = int(request.POST.get('grace_period_minutes'))
            
        employee.save()
        
        # Save photo from file or camera capture
        photo_file = request.FILES.get('photo')
        photo_b64 = request.POST.get('photo_b64')
        if photo_file or photo_b64:
            save_and_sync_employee_photo(employee, photo_file=photo_file, photo_b64=photo_b64)

        Notification.objects.create(user=user, title="Profile Updated", message="Your employee profile and/or settings have been updated by the administrator.")
        messages.success(request, f"Employee {user.first_name} {user.last_name} updated successfully!")
    return redirect('admin_dashboard')

from django.urls import reverse
from django.http import HttpResponseRedirect

@admin_only
def upload_document(request, employee_id):
    if request.method == 'POST':
        employee = get_object_or_404(Employee, id=employee_id)
        name = request.POST.get('name')
        document_type = request.POST.get('document_type')
        file = request.FILES.get('document')
        
        if file and name and document_type:
            EmployeeDocument.objects.create(
                employee=employee,
                name=name,
                document_type=document_type,
                file=file
            )
            messages.success(request, "Document uploaded successfully.")
        else:
            messages.error(request, "Please provide all required fields and a valid file.")
        return HttpResponseRedirect(reverse('admin_dashboard') + f'?tab=directory&open_modal=docsModal-{employee.id}')
    return redirect('admin_dashboard')

@admin_only
def edit_document(request, doc_id):
    if request.method == 'POST':
        doc = get_object_or_404(EmployeeDocument, id=doc_id)
        file = request.FILES.get('document')
        employee_id = doc.employee.id
        
        if file:
            doc.file.delete(save=False)
            doc.file = file
            doc.save()
            messages.success(request, "Document updated successfully.")
        return HttpResponseRedirect(reverse('admin_dashboard') + f'?tab=directory&open_modal=docsModal-{employee_id}')
    return redirect('admin_dashboard')

@admin_only
def delete_document(request, doc_id):
    doc = get_object_or_404(EmployeeDocument, id=doc_id)
    employee_id = doc.employee.id
    doc.delete()
    messages.success(request, "Document deleted successfully.")
    return HttpResponseRedirect(reverse('admin_dashboard') + f'?tab=directory&open_modal=docsModal-{employee_id}')

def client_login(request):
    if request.user.is_authenticated:
        try:
            client = request.user.client_profile
            return redirect('client_dashboard')
        except Exception:
            pass
            
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            try:
                client = user.client_profile
                login(request, user)
                return redirect('client_dashboard')
            except Exception:
                messages.error(request, "This account is not a client account.")
        else:
            messages.error(request, "Invalid username or password.")
def delete_shift(request, shift_id):
    shift = get_object_or_404(Shift, id=shift_id)
    if request.method == 'POST':
        shift.delete()
        messages.success(request, "Shift deleted successfully.")
    return redirect('shift_list')

from django.http import JsonResponse
from .models import Notification, Holiday, Project, ProjectUpdate, GoalTracking
import json
from django.core.serializers.json import DjangoJSONEncoder


@admin_only
def admin_project_detail_view(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    updates = project.updates.all().order_by('created_at')
    all_employees = Employee.objects.select_related('user').order_by('user__first_name')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'add_member':
            emp_id = request.POST.get('employee_id')
            if emp_id:
                emp = Employee.objects.filter(id=emp_id).first()
                if emp:
                    project.assigned_employees.add(emp)
                    messages.success(request, f'{emp.user.get_full_name()} added to project.')
                    if emp.user and emp.user != request.user:
                        Notification.objects.create(user=emp.user, title='Project Assignment', message=f'You have been assigned to project \'{project.name}\'.')
            return redirect('admin_project_detail', project_id=project.id)

        message = request.POST.get('message', '').strip()
        progress = request.POST.get('progress')
        status = request.POST.get('status')

        updated_anything = False

        if progress is not None and progress != '':
            project.progress = int(progress)
            updated_anything = True
        if status:
            project.status = status
            updated_anything = True

        if updated_anything:
            project.save()

        if message:
            ProjectUpdate.objects.create(
                project=project,
                author=request.user,
                message=message,
                is_admin=True
            )
            messages.success(request, 'Project status update posted successfully.')
            if project.client and project.client.user and project.client.user != request.user:
                Notification.objects.create(user=project.client.user, title='Project Update', message=f'A new update was posted for project \'{project.name}\'.')
            for emp in project.assigned_employees.all():
                if emp.user:
                    Notification.objects.create(user=emp.user, title='Project Update', message=f'A new update was posted for project \'{project.name}\'.')
        elif updated_anything:
            messages.success(request, 'Project details updated.')

        return redirect('admin_project_detail', project_id=project.id)

    return render(request, 'employees/admin_project_detail.html', {
        'project': project,
        'updates': updates,
        'all_employees': all_employees
    })

@admin_only
def remove_project_employee(request, project_id, employee_id):
    project = get_object_or_404(Project, id=project_id)
    emp = get_object_or_404(Employee, id=employee_id)
    project.assigned_employees.remove(emp)

    if emp.user and emp.user != request.user:
        Notification.objects.create(user=emp.user, title='Project Removal', message=f'You have been removed from project \'{project.name}\'.')

    messages.success(request, f'{emp.user.get_full_name()} removed from project.')
    return redirect('admin_project_detail', project_id=project.id)

@login_required
def client_project_detail_view(request, project_id):
    try:
        client = request.user.client_profile
    except Exception:
        messages.error(request, 'Access denied. This area is for clients only.')
        return redirect('client_login')

    project = get_object_or_404(Project, id=project_id, client=client)
    updates = project.updates.all().order_by('created_at')

    if request.method == 'POST':
        message = request.POST.get('message', '').strip()
        if message:
            ProjectUpdate.objects.create(
                project=project,
                author=request.user,
                message=message,
                is_admin=False
            )
            messages.success(request, 'Your reply has been posted.')
            admins = Employee.objects.filter(is_company_admin=True)
            for adm in admins:
                if adm.user and adm.user != request.user:
                    Notification.objects.create(user=adm.user, title='Client Project Update', message=f'Client \'{client.company_name}\' posted an update for project \'{project.name}\'.')
            for emp in project.assigned_employees.all():
                if emp.user and emp.user != request.user:
                    Notification.objects.create(user=emp.user, title='Client Project Update', message=f'Client \'{client.company_name}\' posted an update for project \'{project.name}\'.')
        return redirect('client_project_detail', project_id=project.id)

    return render(request, 'employees/client_project_detail.html', {
        'project': project,
        'client': client,
        'updates': updates
    })

@login_required
def apply_shift_request(request):
    if request.method == 'POST':
        try:
            employee = request.user.employee
            shift_id = request.POST.get('requested_shift')
            reason = request.POST.get('reason')
            requested_shift = get_object_or_404(Shift, id=shift_id)
            
            ShiftRequest.objects.create(
                employee=employee,
                requested_shift=requested_shift,
                reason=reason,
                status='Pending'
            )
            messages.success(request, 'Shift change request submitted successfully.')
            
            # Notify admins
            for adm in Employee.objects.filter(is_company_admin=True):
                if adm.user:
                    Notification.objects.create(user=adm.user, title="New Shift Request", message=f"{employee.user.first_name} {employee.user.last_name} has requested a shift change to '{requested_shift.name}'.")
                    
        except Employee.DoesNotExist:
            messages.error(request, 'Employee record not found.')
    return redirect('employee_dashboard')

@admin_only
def admin_shift_requests(request):
    pending_requests = ShiftRequest.objects.filter(status='Pending').order_by('created_at')
    history = ShiftRequest.objects.exclude(status='Pending').order_by('-created_at')
    return render(request, 'employees/admin_shift_requests.html', {
        'pending_requests': pending_requests,
        'history': history
    })

@admin_only
def approve_shift_request(request, req_id):
    req = get_object_or_404(ShiftRequest, id=req_id)
    if req.status == 'Pending':
        req.status = 'Approved'
        req.save()
        
        # Update employee's shift
        req.employee.shift = req.requested_shift
        req.employee.save()
        
        Notification.objects.create(user=req.employee.user, title="Shift Request Approved", message=f"Your request to change your shift to '{req.requested_shift.name}' has been approved.")
        messages.success(request, f"Shift request for {req.employee.user.first_name} approved.")
    return redirect('admin_shift_requests')

@admin_only
def reject_shift_request(request, req_id):
    req = get_object_or_404(ShiftRequest, id=req_id)
    if req.status == 'Pending':
        req.status = 'Rejected'
        req.save()
        
        Notification.objects.create(user=req.employee.user, title="Shift Request Rejected", message=f"Your request to change your shift to '{req.requested_shift.name}' has been rejected.")
        messages.success(request, f"Shift request for {req.employee.user.first_name} rejected.")
    return redirect('admin_shift_requests')

@login_required
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return JsonResponse({'status': 'ok'})

@admin_only
def add_calendar_event(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        description = request.POST.get('description', '')
        event_type = request.POST.get('event_type')
        start_date = request.POST.get('start_date')
        start_time = request.POST.get('start_time', '09:00')
        end_date = request.POST.get('end_date')
        end_time = request.POST.get('end_time', '10:00')

        if title and event_type and start_date and end_date:
            try:
                from datetime import datetime
                s_dt = datetime.strptime(f"{start_date} {start_time}", "%Y-%m-%d %H:%M")
                e_dt = datetime.strptime(f"{end_date} {end_time}", "%Y-%m-%d %H:%M")
                
                Event.objects.create(
                    title=title,
                    description=description,
                    event_type=event_type,
                    start_time=s_dt,
                    end_time=e_dt,
                    created_by=request.user
                )
                log_activity(request.user, f"Created {event_type}: {title}", "Unified Calendar", request)
                messages.success(request, f"Event '{title}' added to calendar.")
            except Exception as e:
                messages.error(request, f"Error saving event: {str(e)}")
        else:
            messages.error(request, "Please fill out all required fields.")
            
    return redirect('/admin-dashboard/?tab=calendar')

@admin_only
def shift_list(request):
    shifts = Shift.objects.all().order_by('name')
    return render(request, 'employees/shift_list.html', {'shifts': shifts})

@admin_only
def add_shift(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        start_time = request.POST.get('start_time')
        end_time = request.POST.get('end_time')
        
        Shift.objects.create(
            name=name,
            start_time=start_time,
            end_time=end_time
        )
        messages.success(request, 'Shift added successfully.')
        return redirect('shift_list')
    return render(request, 'employees/shift_form.html')

@admin_only
def edit_shift(request, shift_id):
    shift = get_object_or_404(Shift, id=shift_id)
    if request.method == 'POST':
        shift.name = request.POST.get('name')
        shift.start_time = request.POST.get('start_time')
        shift.end_time = request.POST.get('end_time')
        shift.save()
        messages.success(request, 'Shift updated successfully.')
        return redirect('shift_list')
    return render(request, 'employees/shift_form.html', {'shift': shift})

@admin_only
def delete_shift(request, shift_id):
    shift = get_object_or_404(Shift, id=shift_id)
    if request.method == 'POST':
        shift.delete()
        messages.success(request, 'Shift deleted successfully.')
    return redirect('shift_list')

import csv
from django.http import HttpResponse

@admin_only
def export_attendance_csv(request):
    selected_month_str = request.GET.get('attendance_month')
    selected_employee_id = request.GET.get('attendance_employee')
    if selected_employee_id == 'None':
        selected_employee_id = None
        
    if not selected_month_str:
        messages.error(request, "Please select a month to export.")
        return redirect('admin_dashboard')
        
    try:
        year, month = map(int, selected_month_str.split('-'))
    except ValueError:
        messages.error(request, "Invalid month format.")
        return redirect('admin_dashboard')
        
    import calendar
    from django.db.models import Sum
    _, no_of_days = calendar.monthrange(year, month)
    
    sundays = sum(1 for d in range(1, no_of_days + 1) if calendar.weekday(year, month, d) == 6)
    holidays_qs = Holiday.objects.filter(date__year=year, date__month=month)
    holidays = holidays_qs.count()
    holiday_dates = list(holidays_qs.values_list('date', flat=True))
    
    no_of_working_days = no_of_days - sundays - holidays
    
    employees_list = Employee.objects.all().order_by('-id')
    
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="Attendance_Summary_{year}_{month}.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['SlNo', 'Employee Code', 'Employee Name', 'No of Days', 'No of Working Days', 'Present', 'Absent', 'Holiday Working', 'Sunday', 'Holidays', 'Total Days', 'OT (Hrs)', 'Permission (Mins)', 'NSA'])
    
    sl_no = 1
    for emp in employees_list:
        if selected_employee_id and str(emp.id) != selected_employee_id:
            continue
            
        emp_att = Attendance.objects.filter(employee=emp, date__year=year, date__month=month)
        present_qs = emp_att.filter(status__in=['Present', 'Half Day', 'Work From Home'])
        present = present_qs.count()
        
        holiday_working = 0
        for att in present_qs:
            if att.date.weekday() == 6 or att.date in holiday_dates:
                holiday_working += 1
                
        absent = no_of_working_days - (present - holiday_working)
        if absent < 0: absent = 0
        
        total_days = present + sundays + holidays - holiday_working
        
        ot_mins = present_qs.aggregate(Sum('overtime_minutes'))['overtime_minutes__sum'] or 0
        ot_hours = round(ot_mins / 60.0, 2)
        
        permission = emp_att.aggregate(Sum('late_minutes'))['late_minutes__sum'] or 0
        nsa = 0
        
        writer.writerow([
            sl_no,
            emp.employee_id_code if hasattr(emp, 'employee_id_code') and emp.employee_id_code else '-',
            emp.user.get_full_name() or emp.user.username,
            no_of_days,
            no_of_working_days,
            present,
            absent,
            holiday_working,
            sundays,
            holidays,
            total_days,
            ot_hours,
            permission,
            nsa
        ])
        sl_no += 1
        
    return response

# Asset Management Views
@admin_only
def add_asset(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        asset_id = request.POST.get('asset_id')
        category = request.POST.get('category')
        
        if Asset.objects.filter(asset_id=asset_id).exists():
            messages.error(request, 'An asset with this ID already exists.')
            return redirect('/admin-dashboard/?tab=assets')
            
        assigned_to_id = request.POST.get('assigned_to')
        if assigned_to_id:
            employee = get_object_or_404(Employee, id=assigned_to_id)
            from datetime import date
            Asset.objects.create(name=name, asset_id=asset_id, category=category, assigned_to=employee, status='Assigned', assigned_date=date.today())
            messages.success(request, f'Asset added and assigned to {employee.user.username}.')
        else:
            Asset.objects.create(name=name, asset_id=asset_id, category=category)
            messages.success(request, 'Asset added successfully.')
    return redirect('/admin-dashboard/?tab=assets')

@admin_only
def assign_asset(request, asset_id):
    asset = get_object_or_404(Asset, id=asset_id)
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        if employee_id:
            employee = get_object_or_404(Employee, id=employee_id)
            asset.assigned_to = employee
            asset.status = 'Assigned'
            from datetime import date
            asset.assigned_date = date.today()
            asset.save()
            messages.success(request, f'Asset {asset.name} assigned to {employee.user.username}.')
        else:
            asset.assigned_to = None
            asset.status = 'Available'
            asset.assigned_date = None
            from datetime import date
            asset.return_date = date.today()
            asset.save()
            messages.success(request, f'Asset {asset.name} returned.')
    return redirect('/admin-dashboard/?tab=assets')

@admin_only
def delete_asset(request, asset_id):
    asset = get_object_or_404(Asset, id=asset_id)
    if request.method == 'POST':
        asset.delete()
        messages.success(request, 'Asset deleted successfully.')
    return redirect('/admin-dashboard/?tab=assets')

# Expense Management Views
@admin_only
def approve_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    if request.method == 'POST':
        expense.status = 'Approved'
        from django.utils import timezone
        expense.date_processed = timezone.now()
        expense.save()
        log_activity(request.user, f'Approved Expense for {expense.employee.user.username}', 'Expense Management', request)
        messages.success(request, 'Expense approved.')
        Notification.objects.create(user=expense.employee.user, title="Expense Approved", message=f"Your expense claim for '{expense.title}' has been approved.")
    return redirect('/admin-dashboard/?tab=expenses')

@admin_only
def reject_expense(request, expense_id):
    expense = get_object_or_404(Expense, id=expense_id)
    if request.method == 'POST':
        expense.status = 'Rejected'
        from django.utils import timezone
        expense.date_processed = timezone.now()
        expense.save()
        log_activity(request.user, f'Rejected Expense for {expense.employee.user.username}', 'Expense Management', request)
        messages.success(request, 'Expense rejected.')
        Notification.objects.create(user=expense.employee.user, title="Expense Rejected", message=f"Your expense claim for '{expense.title}' has been rejected.")
    return redirect('/admin-dashboard/?tab=expenses')

@login_required
def submit_expense(request):
    if request.method == 'POST':
        try:
            employee = request.user.employee
            title = request.POST.get('title')
            amount = request.POST.get('amount')
            category = request.POST.get('category')
            receipt = request.FILES.get('receipt')
            prescription = request.FILES.get('prescription')
            medical_report = request.FILES.get('medical_report')
            
            Expense.objects.create(
                employee=employee,
                title=title,
                amount=amount,
                category=category,
                receipt=receipt,
                prescription=prescription,
                medical_report=medical_report
            )
            messages.success(request, 'Expense claim submitted successfully.')
            Notification.objects.create(user=request.user, title="Expense Submitted", message=f"Your expense claim for '{title}' is pending approval.")
        except Exception as e:
            messages.error(request, f"Error submitting expense: {e}")
    return redirect('employee_dashboard')

# Organization Management Views
@admin_only
def add_department(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        description = request.POST.get('description')
        head_id = request.POST.get('head_id')
        
        department = Department(name=name, description=description)
        if head_id:
            head = get_object_or_404(Employee, id=head_id)
            department.head = head
        department.save()
        messages.success(request, 'Department added successfully.')
    return redirect('/admin-dashboard/?tab=departments')

@admin_only
def edit_department(request, dept_id):
    department = get_object_or_404(Department, id=dept_id)
    if request.method == 'POST':
        department.name = request.POST.get('name')
        department.description = request.POST.get('description')
        head_id = request.POST.get('head_id')
        if head_id:
            department.head = get_object_or_404(Employee, id=head_id)
        else:
            department.head = None
        department.save()
        messages.success(request, 'Department updated successfully.')
    return redirect('/admin-dashboard/?tab=departments')

@admin_only
def delete_department(request, dept_id):
    department = get_object_or_404(Department, id=dept_id)
    if request.method == 'POST':
        department.delete()
        messages.success(request, 'Department deleted successfully.')
    return redirect('/admin-dashboard/?tab=departments')

@admin_only
def add_designation(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        dept_id = request.POST.get('department_id')
        base_salary = request.POST.get('base_salary') or 0.0
        
        department = get_object_or_404(Department, id=dept_id)
        Designation.objects.create(name=name, department=department, base_salary=base_salary)
        messages.success(request, 'Designation added successfully.')
    return redirect('/admin-dashboard/?tab=designations')

@admin_only
def edit_designation(request, desig_id):
    designation = get_object_or_404(Designation, id=desig_id)
    if request.method == 'POST':
        designation.name = request.POST.get('name')
        dept_id = request.POST.get('department_id')
        designation.department = get_object_or_404(Department, id=dept_id)
        designation.base_salary = request.POST.get('base_salary') or 0.0
        designation.save()
        messages.success(request, 'Designation updated successfully.')
    return redirect('/admin-dashboard/?tab=designations')

@admin_only
def delete_designation(request, desig_id):
    designation = get_object_or_404(Designation, id=desig_id)
    if request.method == 'POST':
        designation.delete()
        messages.success(request, 'Designation deleted successfully.')
    return redirect('/admin-dashboard/?tab=designations')

DEFAULT_LETTER_TEMPLATES = {
    'Offer Letter': "<p>Dear <strong>{employee_name}</strong>,</p><p>We are pleased to offer you employment at <strong>CreativeTech Solutions</strong> for the position of <strong>{designation}</strong> in the <strong>{department}</strong> department.</p><p>Your official date of joining will be <strong>{joining_date}</strong>. Your annual gross compensation package will be <strong>${salary}</strong>, payable in regular monthly installments.</p><p>We are excited about the prospect of you joining our team and look forward to your contributions toward our mutual growth and success.</p><p>Sincerely,</p>",

    'Experience Certificate': "<p><strong>TO WHOM IT MAY CONCERN</strong></p><p>This is to certify that <strong>{employee_name}</strong> (Employee ID: <strong>{employee_id}</strong>) was employed with <strong>CreativeTech Solutions</strong> as a <strong>{designation}</strong> in the <strong>{department}</strong> department from <strong>{joining_date}</strong> to <strong>{today_date}</strong>.</p><p>During their tenure with us, we found them to be hardworking, dedicated, and professional in carrying out their responsibilities.</p><p>We wish them all the best and continued success in their future career endeavors.</p>",

    'Relieving Letter': "<p>Dear <strong>{employee_name}</strong>,</p><p>With reference to your resignation letter, we hereby accept your resignation and relieve you from your duties as <strong>{designation}</strong> at <strong>CreativeTech Solutions</strong> effective as of <strong>{today_date}</strong>.</p><p>We confirm that all company assets have been returned and financial dues/settlements have been completed in full.</p><p>We appreciate your valuable contributions during your time with us and wish you the very best in your future pursuits.</p>",

    'NOC Certificate': "<p><strong>NO OBJECTION CERTIFICATE (NOC)</strong></p><p>This is to certify that <strong>{employee_name}</strong>, serving as <strong>{designation}</strong> in the <strong>{department}</strong> department, is an active employee of <strong>CreativeTech Solutions</strong>.</p><p>The company has no objection to the employee applying for official travel, training programs, or external professional affiliations as requested.</p><p>This certificate is issued upon the request of the employee for official verification purposes.</p>"
}

@admin_only
def generate_letter_view(request):
    employees = Employee.objects.select_related('user', 'department', 'designation').all()
    
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        letter_type = request.POST.get('letter_type')
        title = request.POST.get('title')
        content = request.POST.get('content')
        signatory_name = request.POST.get('signatory_name', 'HR Manager')
        signatory_title = request.POST.get('signatory_title', 'Head of Human Resources')
        
        employee = get_object_or_404(Employee, id=employee_id)
        
        import uuid
        ref_code = f"CT-HR-{timezone.now().year}-{uuid.uuid4().hex[:6].upper()}"
        
        letter = HRLetter.objects.create(
            employee=employee,
            letter_type=letter_type,
            title=title or f"{letter_type} - {employee.user.first_name} {employee.user.last_name}",
            reference_number=ref_code,
            issue_date=date.today(),
            content=content,
            signatory_name=signatory_name,
            signatory_title=signatory_title,
            created_by=request.user
        )
        
        log_activity(request.user, f"Generated {letter_type} for {employee.user.username}", "HR Certificates", request)
        messages.success(request, f"{letter_type} generated successfully!")
        return redirect('view_letter_print', letter_id=letter.id)
        
    return render(request, 'employees/generate_letter.html', {
        'employees': employees,
        'templates_json': json.dumps(DEFAULT_LETTER_TEMPLATES)
    })

@login_required
def view_letter_print(request, letter_id):
    letter = get_object_or_404(HRLetter, id=letter_id)
    if not request.user.employee.is_company_admin and letter.employee != request.user.employee:
        messages.error(request, "Permission denied.")
        return redirect('employee_dashboard')
        
    return render(request, 'employees/view_letter.html', {'letter': letter})

@admin_only
def delete_letter_view(request, letter_id):
    letter = get_object_or_404(HRLetter, id=letter_id)
    if request.method == 'POST':
        letter.delete()
        messages.success(request, "Letter deleted successfully.")
    return redirect('/admin-dashboard/?tab=letters')

def manifest_view(request):
    manifest_path = os.path.join(settings.BASE_DIR, 'employees', 'static', 'employees', 'manifest.json')
    if os.path.exists(manifest_path):
        with open(manifest_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='application/manifest+json')
    return JsonResponse({'name': 'Creative Tech HRM', 'short_name': 'HRM Mobile', 'start_url': '/'})

def service_worker_view(request):
    sw_path = os.path.join(settings.BASE_DIR, 'employees', 'static', 'employees', 'sw.js')
    if os.path.exists(sw_path):
        with open(sw_path, 'rb') as f:
            return HttpResponse(f.read(), content_type='application/javascript')
    return HttpResponse("// sw.js", content_type='application/javascript')

@login_required
def add_personal_note(request):
    if request.method == 'POST':
        title = request.POST.get('title')
        note_text = request.POST.get('note')
        note_date = request.POST.get('date')
        if title and note_date:
            PersonalNote.objects.create(
                user=request.user,
                title=title,
                note=note_text,
                date=note_date
            )
            messages.success(request, "🔒 Private note added to your calendar.")
        else:
            messages.error(request, "Please fill in title and date.")
    return redirect(request.META.get('HTTP_REFERER', 'home'))

@login_required
def delete_personal_note(request, note_id):
    note = get_object_or_404(PersonalNote, id=note_id, user=request.user)
    note.delete()
    messages.success(request, "Private note deleted.")
    return redirect(request.META.get('HTTP_REFERER', 'home'))

