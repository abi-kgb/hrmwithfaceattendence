from django.urls import path
from . import views
from . import views_api

urlpatterns = [
    path('api/attendance/webhook/', views_api.attendance_webhook_api, name='attendance_webhook_api'),
    path('api/attendance/request-permission/', views_api.request_permission_api, name='request_permission_api'),
    path('api/attendance/pending-requests/', views_api.get_pending_requests_api, name='get_pending_requests_api'),
    path('api/employees/', views_api.get_employees_api, name='get_employees_api'),
    path('api/attendance/logs/', views_api.get_attendance_logs_api, name='get_attendance_logs_api'),
    path('', views.home_redirect, name='home'),
    path('login/', views.employee_login_view, name='login'),
    path('employee-login/', views.employee_login_view, name='employee_login'),
    path('employe-login/', views.employee_login_view),
    path('employ-login/', views.employee_login_view),
    path('admin-login/', views.admin_login_view, name='admin_login'),
    path('logout/', views.logout_view, name='logout'),
    path('forgot-password/', views.forgot_password_view, name='forgot_password'),
    
    # Employee self-service
    path('dashboard/', views.employee_dashboard, name='employee_dashboard'),
    path('dashboard/projects/<int:project_id>/', views.employee_project_detail_view, name='employee_project_detail'),
    path('clock-in/', views.clock_in, name='clock_in'),
    path('clock-out/', views.clock_out, name='clock_out'),
    path('apply-leave/', views.apply_leave, name='apply_leave'),
    path('profile/update/', views.profile_update_view, name='profile_update'),
    path('profile/change-password/', views.change_password_view, name='change_password'),
    
    # Admin Portal
    path('admin-dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin-dashboard/add-employee/', views.add_employee, name='add_employee'),
    path('admin-dashboard/add-review/', views.add_performance_review, name='add_performance_review'),
    path('admin-dashboard/add-training/', views.add_training, name='add_training'),
    path('admin-dashboard/enroll-training/', views.enroll_training, name='enroll_training'),
    path('admin-dashboard/complete-training/<int:enrollment_id>/', views.complete_training, name='complete_training'),
    path('admin-dashboard/reports/', views.reports_data, name='reports_data'),
    path('admin-dashboard/approve-leave/<int:leave_id>/', views.approve_leave, name='approve_leave'),
    path('admin-dashboard/reject-leave/<int:leave_id>/', views.reject_leave, name='reject_leave'),
    path('admin-dashboard/add-job/', views.add_job, name='add_job'),
    path('admin-dashboard/update-application/<int:app_id>/', views.update_application_status, name='update_application'),
    path('admin-dashboard/generate-payslip/', views.generate_payslip, name='generate_payslip'),
    path('admin-dashboard/toggle-job/<int:job_id>/', views.toggle_job_status, name='toggle_job_status'),
    path('admin-dashboard/delete-employee/<int:employee_id>/', views.delete_employee, name='delete_employee'),
    path('admin-dashboard/edit-employee/<int:employee_id>/', views.edit_employee, name='edit_employee'),
    path('admin-dashboard/upload-document/<int:employee_id>/', views.upload_document, name='upload_document'),
    path('admin-dashboard/delete-document/<int:doc_id>/', views.delete_document, name='delete_document'),
    path('admin-dashboard/edit-document/<int:doc_id>/', views.edit_document, name='edit_document'),
    path('admin-dashboard/reset-employee-password/<int:employee_id>/', views.reset_employee_password, name='reset_employee_password'),
    path('admin-dashboard/delete-payslip/<int:payslip_id>/', views.delete_payslip, name='delete_payslip'),
    path('admin-dashboard/payslip/toggle-status/<int:payslip_id>/', views.toggle_payslip_status, name='toggle_payslip_status'),
    path('admin-dashboard/payslip/<int:payslip_id>/', views.view_payslip, name='view_payslip'),
    path('admin-dashboard/export-attendance-csv/', views.export_attendance_csv, name='export_attendance_csv'),
    
    # Shift Management
    path('admin-dashboard/shifts/', views.shift_list, name='shift_list'),
    path('admin-dashboard/shifts/add/', views.add_shift, name='add_shift'),
    path('admin-dashboard/shifts/edit/<int:shift_id>/', views.edit_shift, name='edit_shift'),
    path('admin-dashboard/shifts/delete/<int:shift_id>/', views.delete_shift, name='delete_shift'),

    # Asset Management
    path('admin-dashboard/assets/add/', views.add_asset, name='add_asset'),
    path('admin-dashboard/assets/assign/<int:asset_id>/', views.assign_asset, name='assign_asset'),
    path('admin-dashboard/assets/delete/<int:asset_id>/', views.delete_asset, name='delete_asset'),

    # Expense Management
    path('admin-dashboard/expenses/approve/<int:expense_id>/', views.approve_expense, name='approve_expense'),
    path('admin-dashboard/expenses/reject/<int:expense_id>/', views.reject_expense, name='reject_expense'),
    path('employee-dashboard/expenses/submit/', views.submit_expense, name='submit_expense'),
    
    # Public Careers Portal
    path('careers/', views.careers_list, name='careers_list'),
    path('career/', views.careers_list),
    path('careers/apply/<int:job_id>/', views.apply_job, name='apply_job'),
    path('career/apply/<int:job_id>/', views.apply_job),

    # New Admin Modules
    path('admin-dashboard/holidays/', views.holidays_view, name='holidays'),
    path('admin-dashboard/clients/', views.clients_view, name='clients'),
    path('admin-dashboard/goals/', views.goals_view, name='goals'),
    path('admin-dashboard/projects/', views.projects_view, name='projects'),
    path('admin-dashboard/projects/update/<int:project_id>/', views.update_project_progress, name='update_project'),
    path('admin-dashboard/projects/edit/<int:project_id>/', views.edit_project, name='edit_project'),
    path('admin-dashboard/projects/<int:project_id>/', views.admin_project_detail_view, name='admin_project_detail'),
    path('admin-dashboard/projects/<int:project_id>/remove-employee/<int:employee_id>/', views.remove_project_employee, name='remove_project_employee'),

    # Client Portal
    path('client-login/', views.client_login_view, name='client_login'),
    path('client-dashboard/', views.client_dashboard_view, name='client_dashboard'),
    path('client-dashboard/projects/<int:project_id>/', views.client_project_detail_view, name='client_project_detail'),
    
    # Shift Requests
    path('dashboard/apply-shift/', views.apply_shift_request, name='apply_shift_request'),
    path('admin-dashboard/shift-requests/', views.admin_shift_requests, name='admin_shift_requests'),
    path('admin-dashboard/shift-requests/approve/<int:req_id>/', views.approve_shift_request, name='approve_shift_request'),
    path('admin-dashboard/shift-requests/reject/<int:req_id>/', views.reject_shift_request, name='reject_shift_request'),

    # Organization Management
    path('admin-dashboard/departments/add/', views.add_department, name='add_department'),
    path('admin-dashboard/departments/edit/<int:dept_id>/', views.edit_department, name='edit_department'),
    path('admin-dashboard/departments/delete/<int:dept_id>/', views.delete_department, name='delete_department'),
    
    path('admin-dashboard/designations/add/', views.add_designation, name='add_designation'),
    path('admin-dashboard/designations/edit/<int:desig_id>/', views.edit_designation, name='edit_designation'),
    path('admin-dashboard/designations/delete/<int:desig_id>/', views.delete_designation, name='delete_designation'),

    # Global
    path('mark-notifications-read/', views.mark_notifications_read, name='mark_notifications_read'),
    path('admin-dashboard/calendar/add-event/', views.add_calendar_event, name='add_calendar_event'),

    # HR Letters & Certificates
    path('admin-dashboard/letters/generate/', views.generate_letter_view, name='generate_letter'),
    path('letters/<int:letter_id>/print/', views.view_letter_print, name='view_letter_print'),
    path('admin-dashboard/letters/delete/<int:letter_id>/', views.delete_letter_view, name='delete_letter'),

    # Personal Private Notes
    path('personal-notes/add/', views.add_personal_note, name='add_personal_note'),
    path('personal-notes/delete/<int:note_id>/', views.delete_personal_note, name='delete_personal_note'),

    # Goals Status & Delete
    path('goals/<int:goal_id>/update-status/', views.update_goal_status, name='update_goal_status'),
    path('goals/<int:goal_id>/delete/', views.delete_goal, name='delete_goal'),

    # Attendance Permission & Email Approvals
    path('dashboard/apply-attendance-permission/', views.apply_attendance_permission, name='apply_attendance_permission'),
    path('attendance/approve/<str:token>/', views.attendance_approve_view, name='attendance_approve'),
    path('attendance/reject/<str:token>/', views.attendance_reject_view, name='attendance_reject'),
    path('admin-dashboard/attendance-requests/<int:req_id>/<str:action>/', views.admin_attendance_request_action, name='admin_attendance_request_action'),

    # PWA Routes
    path('manifest.json', views.manifest_view, name='manifest'),
    path('sw.js', views.service_worker_view, name='service_worker'),
]

