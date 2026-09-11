from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import date
import uuid

class Department(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    head = models.ForeignKey('Employee', on_delete=models.SET_NULL, null=True, blank=True, related_name='headed_departments')

    def __str__(self):
        return self.name

class Designation(models.Model):
    name = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='designations')
    base_salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)

    def __str__(self):
        return self.name

class Shift(models.Model):
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.name} ({self.start_time.strftime('%H:%M')} - {self.end_time.strftime('%H:%M')})"

class Employee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='employee')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    role = models.CharField(max_length=100, default='Employee') # Keep for simple Admin/Employee check
    
    # Old string fields for data migration (temporary)
    department_old = models.CharField(max_length=100, blank=True, null=True)
    role_old = models.CharField(max_length=100, blank=True, null=True)
    designation_old = models.CharField(max_length=150, blank=True, null=True)
    
    phone = models.CharField(max_length=20, blank=True, null=True)
    hire_date = models.DateField(auto_now_add=True)
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    is_company_admin = models.BooleanField(default=False)
    shift = models.ForeignKey(Shift, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    ot_hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    grace_period_minutes = models.IntegerField(default=120, help_text="Monthly grace period for late arrivals in minutes")
    
    # Extended personal details
    GENDER_CHOICES = [
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    ]
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    employee_id_code = models.CharField(max_length=50, blank=True, null=True, unique=False)
    photo = models.ImageField(upload_to='employee_photos/', blank=True, null=True)
    
    sick_leave_balance = models.IntegerField(default=10)
    casual_leave_balance = models.IntegerField(default=10)
    annual_leave_balance = models.IntegerField(default=20)
    maternity_leave_balance = models.IntegerField(default=90)
    paternity_leave_balance = models.IntegerField(default=14)

    def __str__(self):
        return f"{self.user.first_name} {self.user.last_name} ({self.role})"

class LeaveRequest(models.Model):
    LEAVE_CHOICES = [
        ('Annual', 'Annual Leave'),
        ('Sick', 'Sick Leave'),
        ('Casual', 'Casual Leave'),
        ('Maternity', 'Maternity Leave'),
        ('Paternity', 'Paternity Leave'),
        ('Unpaid', 'Unpaid Leave'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.CharField(max_length=20, choices=LEAVE_CHOICES)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    lop_days = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.employee.user.username} - {self.leave_type} ({self.status})"

class Attendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_records')
    date = models.DateField(default=timezone.now)
    clock_in = models.TimeField(default=timezone.now)
    clock_out = models.TimeField(blank=True, null=True)
    late_minutes = models.IntegerField(default=0)
    overtime_minutes = models.IntegerField(default=0)
    STATUS_CHOICES = [
        ('Present', 'Present'),
        ('Absent', 'Absent'),
        ('Half Day', 'Half Day'),
        ('Work From Home', 'Work From Home'),
        ('Leave', 'Leave'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Present')

    @property
    def total_hours(self):
        if not self.clock_in:
            return None
        import datetime
        dt_in = datetime.datetime.combine(self.date, self.clock_in)
        if self.clock_out:
            dt_out = datetime.datetime.combine(self.date, self.clock_out)
            # Only treat as next day if dt_out is significantly earlier (night shift > 4 hours earlier)
            if dt_out < dt_in:
                if (dt_in - dt_out).total_seconds() > 4 * 3600:
                    dt_out += datetime.timedelta(days=1)
                else:
                    dt_out = dt_in
            diff = dt_out - dt_in
            hours = max(0.0, diff.total_seconds() / 3600.0)
            return round(hours, 2)
        elif self.date == datetime.date.today():
            now = datetime.datetime.now()
            if now > dt_in:
                diff = now - dt_in
                return round(diff.total_seconds() / 3600.0, 2)
        return None

    @property
    def duration_display(self):
        if not self.clock_in:
            return "-"
        import datetime
        dt_in = datetime.datetime.combine(self.date, self.clock_in)
        if self.clock_out:
            dt_out = datetime.datetime.combine(self.date, self.clock_out)
            if dt_out < dt_in:
                if (dt_in - dt_out).total_seconds() > 4 * 3600:
                    dt_out += datetime.timedelta(days=1)
                else:
                    dt_out = dt_in
            total_sec = max(0, int((dt_out - dt_in).total_seconds()))
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            if h > 0 and m > 0:
                return f"{h}h {m}m"
            elif h > 0:
                return f"{h} hrs"
            else:
                return f"{m} mins"
        else:
            if self.date == datetime.date.today():
                now = datetime.datetime.now()
                if now > dt_in:
                    total_sec = max(0, int((now - dt_in).total_seconds()))
                    h = total_sec // 3600
                    m = (total_sec % 3600) // 60
                    if h > 0 and m > 0:
                        return f"{h}h {m}m (Live)"
                    elif h > 0:
                        return f"{h} hrs (Live)"
                    else:
                        return f"{m} mins (Live)"
            return "In progress"

    @property
    def late_arrival_request(self):
        return self.employee.attendance_requests.filter(date=self.date, request_type__in=['Late Arrival', 'Permission']).order_by('-id').first()

    @property
    def early_logout_request(self):
        return self.employee.attendance_requests.filter(date=self.date, request_type__in=['Early Departure', 'Clock Out', 'Emergency Exit']).order_by('-id').first()

    def __str__(self):
        return f"{self.employee.user.username} on {self.date}"

class AttendanceRequest(models.Model):
    REQUEST_TYPES = [
        ('Late Arrival', 'Late Arrival Permission'),
        ('Early Departure', 'Early Departure Permission'),
        ('Clock In', 'Clock In Approval'),
        ('Clock Out', 'Clock Out Approval'),
        ('Permission', 'General Permission'),
        ('Emergency Exit', 'Emergency Exit Permission'),
    ]
    STATUS_CHOICES = [
        ('Pending', 'Pending Admin Approval'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_requests')
    date = models.DateField(default=timezone.now)
    request_type = models.CharField(max_length=50, choices=REQUEST_TYPES, default='Late Arrival')
    requested_time = models.TimeField(help_text="Expected / requested login or logout time")
    reason = models.TextField(help_text="Reason for late arrival or permission")
    token = models.CharField(max_length=100, unique=True, default=uuid.uuid4)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_attendance_requests')
    admin_notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.employee.user.username} - {self.request_type} on {self.date} ({self.status})"

class Payslip(models.Model):
    STATUS_CHOICES = [
        ('Paid', 'Paid'),
        ('Pending', 'Pending'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payslips')
    month_year = models.CharField(max_length=50) # e.g. "June 2026"
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2)
    allowances = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    hra = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    travel_allowance = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    deductions = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    pf_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    tax_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    esi_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    lop_days = models.IntegerField(default=0)
    lop_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total_late_mins = models.IntegerField(default=0)
    severe_late_incidents = models.IntegerField(default=0)
    late_penalty_lop_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    net_salary = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    generated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Payslip for {self.employee.user.username} - {self.month_year} ({self.status})"

class JobPosting(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    requirements = models.TextField()
    location = models.CharField(max_length=100)
    salary_range = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.location} ({'Active' if self.is_active else 'Closed'})"

class JobApplication(models.Model):
    STATUS_CHOICES = [
        ('Applied', 'Applied'),
        ('Shortlisted', 'Shortlisted'),
        ('Interviewing', 'Interviewing'),
        ('Offered', 'Offered'),
        ('Hired', 'Hired'),
        ('Rejected', 'Rejected'),
    ]
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name='applications')
    candidate_name = models.CharField(max_length=150)
    candidate_email = models.EmailField()
    candidate_phone = models.CharField(max_length=20)
    resume_url = models.CharField(max_length=500, blank=True, null=True) # Text link or description
    resume_pdf = models.FileField(upload_to='resumes/', blank=True, null=True)
    cover_letter = models.TextField()
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Applied')
    applied_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.candidate_name} - {self.job.title} ({self.status})"


class PerformanceReview(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='performance_reviews')
    reviewer = models.ForeignKey(Employee, on_delete=models.SET_NULL, related_name='reviews_given', null=True, blank=True)
    review_period = models.CharField(max_length=100)
    rating = models.DecimalField(max_digits=3, decimal_places=1)
    goals = models.TextField(blank=True, null=True)
    feedback = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Review {self.review_period} - {self.employee.user.username} ({self.rating})"


class Training(models.Model):
    STATUS_CHOICES = [
        ('Upcoming', 'Upcoming'),
        ('Active', 'Active'),
        ('Completed', 'Completed'),
    ]
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, null=True)
    trainer = models.CharField(max_length=150, blank=True, null=True)
    start_date = models.DateField(blank=True, null=True)
    end_date = models.DateField(blank=True, null=True)
    is_online = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Upcoming')

    def __str__(self):
        return f"{self.title} ({self.status})"


class TrainingEnrollment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='training_enrollments')
    training = models.ForeignKey(Training, on_delete=models.CASCADE, related_name='enrollments')
    enrolled_at = models.DateTimeField(auto_now_add=True)
    completed = models.BooleanField(default=False)
    certificate_url = models.CharField(max_length=500, blank=True, null=True)

    def __str__(self):
        return f"{self.employee.user.username} -> {self.training.title} ({'Completed' if self.completed else 'Enrolled'})"

class Holiday(models.Model):
    TYPE_CHOICES = [
        ('Holiday', 'Holiday'),
        ('Weekoff', 'Weekoff'),
    ]
    name = models.CharField(max_length=200)
    date = models.DateField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='Holiday')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} on {self.date}"

class Client(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='client_profile', null=True, blank=True)
    company_name = models.CharField(max_length=200)
    client_id = models.CharField(max_length=50, blank=True, null=True)
    contact_person = models.CharField(max_length=150)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, null=True)
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Inactive', 'Inactive'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.company_name

class Project(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Completed', 'Completed'),
        ('On Hold', 'On Hold'),
    ]
    name = models.CharField(max_length=200)
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name='projects')
    assigned_employees = models.ManyToManyField(Employee, related_name='assigned_projects', blank=True)
    description = models.TextField(blank=True, null=True)
    deadline = models.DateField(blank=True, null=True)
    progress = models.IntegerField(default=0)  # 0-100
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"

class ProjectUpdate(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='updates')
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    message = models.TextField()
    is_admin = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update on {self.project.name} by {self.author.username} at {self.created_at}"

class GoalTracking(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Pending', 'Pending'),
        ('Completed', 'Completed'),
    ]
    subject = models.CharField(max_length=200)
    project = models.ForeignKey('Project', on_delete=models.SET_NULL, null=True, blank=True, related_name='goals')
    start_date = models.DateField()
    end_date = models.DateField()
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    progress = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.subject} ({self.status})"

class EmployeeDocument(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    name = models.CharField(max_length=200)
    document_type = models.CharField(max_length=50)
    file = models.FileField(upload_to='employee_docs/')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} - {self.employee.user.username}"

class ShiftRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_requests')
    requested_shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='requested_shifts')
    reason = models.TextField()
    status = models.CharField(max_length=20, default='Pending') # Pending, Approved, Rejected
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Shift Request by {self.employee.user.username} for {self.requested_shift.name}"

class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    link = models.CharField(max_length=500, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"To {self.user.username} - {self.title}"

@receiver(post_save, sender=Notification)
def send_notification_email(sender, instance, created, **kwargs):
    if created and instance.user.email:
        send_mail(
            subject=f"CreativeTech HRM: {instance.title}",
            message=f"Hello {instance.user.first_name or instance.user.username},\n\n{instance.message}\n\nLog in to your dashboard to view more details.",
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@creativetech.com'),
            recipient_list=[instance.user.email],
            fail_silently=True,
        )

class Asset(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Assigned', 'Assigned'),
        ('Maintenance', 'Maintenance'),
        ('Lost', 'Lost'),
    ]
    name = models.CharField(max_length=200)
    asset_id = models.CharField(max_length=100, unique=True)
    category = models.CharField(max_length=100)
    assigned_to = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='assets')
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Available')
    assigned_date = models.DateField(null=True, blank=True)
    return_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.asset_id})"

class Expense(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    CATEGORY_CHOICES = [
        ('Travel', 'Travel'),
        ('Food', 'Food'),
        ('Office Supplies', 'Office Supplies'),
        ('Medical', 'Medical'),
        ('Other', 'Other'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='expenses')
    title = models.CharField(max_length=200)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=100, choices=CATEGORY_CHOICES, default='Other')
    receipt = models.FileField(upload_to='expenses/', blank=True, null=True)
    prescription = models.FileField(upload_to='expenses/medical/', blank=True, null=True)
    medical_report = models.FileField(upload_to='expenses/medical/', blank=True, null=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default='Pending')
    date_submitted = models.DateTimeField(auto_now_add=True)
    date_processed = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.title} - {self.employee.user.username} ({self.status})"

class ActivityLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='activity_logs')
    action = models.CharField(max_length=255)
    module = models.CharField(max_length=100, default='General')
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.user} - {self.action} at {self.timestamp}"

class Event(models.Model):
    EVENT_TYPES = [
        ('Meeting', 'Meeting'),
        ('Company Event', 'Company Event'),
        ('Training', 'Training'),
        ('Other', 'Other')
    ]
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, default='Meeting')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_events')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.event_type})"

class HRLetter(models.Model):
    LETTER_TYPES = [
        ('Offer Letter', 'Offer Letter'),
        ('Experience Certificate', 'Experience Certificate'),
        ('Relieving Letter', 'Relieving Letter'),
        ('NOC Certificate', 'NOC Certificate'),
        ('Custom Letter', 'Custom Letter'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='hr_letters')
    letter_type = models.CharField(max_length=50, choices=LETTER_TYPES)
    title = models.CharField(max_length=255)
    reference_number = models.CharField(max_length=100, unique=True)
    issue_date = models.DateField(default=timezone.now)
    content = models.TextField()
    signatory_name = models.CharField(max_length=150, default="HR Manager")
    signatory_title = models.CharField(max_length=150, default="Head of Human Resources")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_letters')

    def __str__(self):
        return f"{self.title} - {self.reference_number}"

class PersonalNote(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='personal_notes')
    title = models.CharField(max_length=255)
    note = models.TextField(blank=True, null=True)
    date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Private Note: {self.title} ({self.user.username})"
