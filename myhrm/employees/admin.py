from django.contrib import admin
from .models import Employee, LeaveRequest, Attendance, Payslip, JobPosting, JobApplication, Client, Project, GoalTracking, Holiday, ProjectUpdate, Notification

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('get_username', 'get_first_name', 'get_last_name', 'department', 'role', 'salary', 'is_company_admin', 'sick_leave_balance', 'casual_leave_balance', 'annual_leave_balance')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'department', 'role')
    list_filter = ('department', 'is_company_admin')

    def get_username(self, obj):
        return obj.user.username
    get_username.short_description = 'Username'

    def get_first_name(self, obj):
        return obj.user.first_name
    get_first_name.short_description = 'First Name'

    def get_last_name(self, obj):
        return obj.user.last_name
    get_last_name.short_description = 'Last Name'

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'status')
    list_filter = ('leave_type', 'status')
    search_fields = ('employee__user__username', 'reason')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'clock_in', 'clock_out')
    list_filter = ('date',)
    search_fields = ('employee__user__username',)

@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ('employee', 'month_year', 'basic_salary', 'net_salary', 'status')
    list_filter = ('month_year', 'status')
    search_fields = ('employee__user__username',)

@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ('title', 'location', 'salary_range', 'is_active', 'created_at')
    list_filter = ('is_active', 'location')
    search_fields = ('title', 'description', 'requirements')

@admin.register(JobApplication)
class JobApplicationAdmin(admin.ModelAdmin):
    list_display = ('candidate_name', 'job', 'status', 'applied_at')
    list_filter = ('status', 'job')
    search_fields = ('candidate_name', 'candidate_email', 'cover_letter')

@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ('company_name', 'client_id', 'contact_person', 'email', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('company_name', 'contact_person', 'email')

@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'client', 'deadline', 'progress', 'status', 'created_at')
    list_filter = ('status', 'client')
    search_fields = ('name', 'description')

@admin.register(GoalTracking)
class GoalTrackingAdmin(admin.ModelAdmin):
    list_display = ('subject', 'project', 'start_date', 'end_date', 'status', 'progress')
    list_filter = ('status',)
    search_fields = ('subject', 'description')

@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'created_at')
    list_filter = ('date',)
    search_fields = ('name',)

@admin.register(ProjectUpdate)
class ProjectUpdateAdmin(admin.ModelAdmin):
    list_display = ('project', 'author', 'is_admin', 'created_at')
    list_filter = ('is_admin', 'project')
    search_fields = ('message',)

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'title', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('user__username', 'title', 'message')
