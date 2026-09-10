from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from .models import Employee, LeaveRequest, Attendance, Payslip, JobPosting, JobApplication, PerformanceReview, Training, TrainingEnrollment, Client as ClientModel, Project, GoalTracking, Holiday, ProjectUpdate
from datetime import date, timedelta

class HRMTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        
        # Create an admin user & employee
        self.admin_user = User.objects.create_user(
            username='admin_test',
            password='password123',
            email='admin@creativetech.com',
            first_name='Admin',
            last_name='User'
        )
        self.admin_employee = Employee.objects.create(
            user=self.admin_user,
            department='Management',
            role='HR Manager',
            salary=8000.00,
            is_company_admin=True
        )

        # Create a standard employee user & employee
        self.emp_user = User.objects.create_user(
            username='emp_test',
            password='password123',
            email='emp@creativetech.com',
            first_name='Employee',
            last_name='User'
        )
        self.emp_employee = Employee.objects.create(
            user=self.emp_user,
            department='Engineering',
            role='Software Developer',
            salary=5000.00,
            is_company_admin=False
        )

    def test_login_and_redirection(self):
        # Test anonymous access redirects to employee_login
        response = self.client.get(reverse('home'))
        self.assertRedirects(response, reverse('employee_login'))

        # Test login as employee redirects to employee dashboard
        response = self.client.post(reverse('employee_login'), {'username': 'emp_test', 'password': 'password123'})
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.client.logout()

        # Test login as admin redirects to admin dashboard
        response = self.client.post(reverse('admin_login'), {'username': 'admin_test', 'password': 'password123'})
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.client.logout()

        # Test admin logging in at employee portal is redirected to admin dashboard
        response = self.client.post(reverse('employee_login'), {'username': 'admin_test', 'password': 'password123'})
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.client.logout()

        # Test employee logging in at admin portal is redirected to employee dashboard
        response = self.client.post(reverse('admin_login'), {'username': 'emp_test', 'password': 'password123'})
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.client.logout()

    def test_role_restrictions(self):
        # Employee should not be allowed to access admin dashboard
        self.client.login(username='emp_test', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.client.logout()

        # Admin should not see employee dashboard, they get redirected to admin dashboard
        self.client.login(username='admin_test', password='password123')
        response = self.client.get(reverse('employee_dashboard'))
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.client.logout()

        # Unauthenticated admin dashboard access redirects to admin_login
        response = self.client.get(reverse('admin_dashboard'))
        self.assertRedirects(response, reverse('admin_login'))

        # Unauthenticated employee dashboard access redirects to employee_login with next parameter
        response = self.client.get(reverse('employee_dashboard'))
        self.assertRedirects(response, f"{reverse('employee_login')}?next={reverse('employee_dashboard')}")

    def test_attendance_actions(self):
        self.client.login(username='emp_test', password='password123')
        
        # Clock in
        response = self.client.post(reverse('clock_in'))
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.assertEqual(Attendance.objects.filter(employee=self.emp_employee).count(), 1)
        
        # Clock out
        response = self.client.post(reverse('clock_out'))
        self.assertRedirects(response, reverse('employee_dashboard'))
        record = Attendance.objects.filter(employee=self.emp_employee).first()
        self.assertIsNotNone(record.clock_out)

    def test_leave_request(self):
        self.client.login(username='emp_test', password='password123')
        
        # Apply leave
        start = date.today() + timedelta(days=5)
        end = start + timedelta(days=2)
        response = self.client.post(reverse('apply_leave'), {
            'leave_type': 'Annual',
            'start_date': start.strftime('%Y-%m-%d'),
            'end_date': end.strftime('%Y-%m-%d'),
            'reason': 'Family trip'
        })
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.assertEqual(LeaveRequest.objects.filter(employee=self.emp_employee).count(), 1)
        
        # Admin approves leave
        self.client.logout()
        self.client.login(username='admin_test', password='password123')
        leave_req = LeaveRequest.objects.filter(employee=self.emp_employee).first()
        response = self.client.get(reverse('approve_leave', args=[leave_req.id]))
        self.assertRedirects(response, reverse('admin_dashboard'))
        
        leave_req.refresh_from_db()
        self.assertEqual(leave_req.status, 'Approved')

    def test_leave_balance_deduction(self):
        # Initial annual balance is 20
        self.assertEqual(self.emp_employee.annual_leave_balance, 20)

        # Apply for 3 days of annual leave
        start = date.today() + timedelta(days=5)
        end = start + timedelta(days=2) # 5, 6, 7 (3 days)
        leave = LeaveRequest.objects.create(
            employee=self.emp_employee,
            leave_type='Annual',
            start_date=start,
            end_date=end,
            reason='Vacation',
            status='Pending'
        )

        # Admin approves the leave
        self.client.login(username='admin_test', password='password123')
        self.client.get(reverse('approve_leave', args=[leave.id]))

        # Refresh from db and verify balance is 17 (20 - 3)
        self.emp_employee.refresh_from_db()
        self.assertEqual(self.emp_employee.annual_leave_balance, 17)

    def test_job_posting_and_application(self):
        # Create a job posting
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('add_job'), {
            'title': 'Senior Django Engineer',
            'description': 'Develop core features',
            'requirements': '3+ years Django',
            'location': 'Remote',
            'salary_range': '$90,000 - $110,000'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertEqual(JobPosting.objects.count(), 1)
        self.client.logout()

        # Public candidate applies
        job = JobPosting.objects.first()
        response = self.client.post(reverse('apply_job', args=[job.id]), {
            'candidate_name': 'Sarah Connor',
            'candidate_email': 'sarah@skynet.com',
            'candidate_phone': '555-9876',
            'resume_url': 'http://resume.com/sarah',
            'cover_letter': 'I know how to code and fight.'
        })
        self.assertRedirects(response, reverse('careers_list'))
        self.assertEqual(JobApplication.objects.count(), 1)

        # Admin shortlists candidate
        self.client.login(username='admin_test', password='password123')
        application = JobApplication.objects.first()
        response = self.client.post(reverse('update_application', args=[application.id]), {
            'status': 'Shortlisted'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        application.refresh_from_db()
        self.assertEqual(application.status, 'Shortlisted')

    def test_job_application_pdf_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        import os
        
        # Create a job posting first
        job = JobPosting.objects.create(
            title='PDF Specialist',
            description='Test PDF uploads',
            requirements='Django experience',
            location='New York',
            salary_range='$80,000'
        )
        
        # Candidate submits application with PDF resume file
        pdf_content = b"%PDF-1.4 mock pdf content"
        mock_pdf = SimpleUploadedFile("my_resume.pdf", pdf_content, content_type="application/pdf")
        
        response = self.client.post(reverse('apply_job', args=[job.id]), {
            'candidate_name': 'PDF Candidate',
            'candidate_email': 'pdf@test.com',
            'candidate_phone': '1234567890',
            'resume_pdf': mock_pdf,
            'cover_letter': 'Please hire me.'
        })
        self.assertRedirects(response, reverse('careers_list'))
        
        # Verify the application was saved and file exists
        application = JobApplication.objects.filter(candidate_name='PDF Candidate').first()
        self.assertIsNotNone(application)
        self.assertTrue(application.resume_pdf.name.startswith('resumes/my_resume'))
        
        # Verify it loads on the Admin Dashboard page
        self.client.login(username='admin_test', password='password123')
        response = self.client.get(reverse('admin_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, application.resume_pdf.url)
        self.client.logout()
        
        # Clean up file
        if application.resume_pdf:
            path = application.resume_pdf.path
            try:
                application.resume_pdf.close()
            except Exception:
                pass
            del application
            import gc
            gc.collect()
            if os.path.exists(path):
                try:
                    os.remove(path)
                except PermissionError:
                    pass

    def test_payroll_generation(self):
        self.client.login(username='admin_test', password='password123')

        # Generate a payslip for the employee
        response = self.client.post(reverse('generate_payslip'), {
            'employee_id': self.emp_employee.id,
            'month_year': 'June 2026',
            'allowances': '500.00',
            'deductions': '200.00',
            'status': 'Pending'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))

        # Verify payslip is generated with correct net calculation
        payslip = Payslip.objects.first()
        self.assertEqual(payslip.employee, self.emp_employee)
        self.assertEqual(float(payslip.basic_salary), 5000.00)
        self.assertEqual(float(payslip.allowances), 500.00)
        self.assertEqual(float(payslip.deductions), 200.00)
        self.assertEqual(float(payslip.net_salary), 5300.00) # 5000 + 500 - 200
        self.assertEqual(payslip.status, 'Pending')

    def test_payroll_generation_with_attendance_hours(self):
        import datetime
        self.client.login(username='admin_test', password='password123')
        
        t_in = datetime.time(9, 0, 0)
        t_out = datetime.time(17, 0, 0)
        record = Attendance.objects.create(
            employee=self.emp_employee,
            clock_out=t_out
        )
        Attendance.objects.filter(id=record.id).update(
            date=datetime.date(2026, 6, 15),
            clock_in=t_in
        )

        response = self.client.post(reverse('generate_payslip'), {
            'employee_id': self.emp_employee.id,
            'month_year': 'June 2026',
            'allowances': '100.00',
            'deductions': '50.00',
            'status': 'Paid'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))

        payslip = Payslip.objects.filter(employee=self.emp_employee, month_year='June 2026').first()
        self.assertIsNotNone(payslip)
        self.assertEqual(float(payslip.basic_salary), 222.22)
        self.assertEqual(float(payslip.allowances), 100.00)
        self.assertEqual(float(payslip.deductions), 50.00)
        self.assertEqual(float(payslip.net_salary), 272.22)
        self.assertEqual(payslip.status, 'Paid')

    def test_attendance_total_hours(self):
        import datetime
        t_in = datetime.time(9, 0, 0)
        t_out = datetime.time(17, 30, 0)
        record = Attendance.objects.create(
            employee=self.emp_employee,
            clock_out=t_out
        )
        Attendance.objects.filter(id=record.id).update(clock_in=t_in)
        record.refresh_from_db()
        # Worked from 09:00 to 17:30 = 8.5 hours
        self.assertEqual(record.total_hours, 8.5)

    def test_employee_profile_update(self):
        self.client.login(username='emp_test', password='password123')
        response = self.client.post(reverse('profile_update'), {
            'email': 'new_emp@creativetech.com',
            'phone': '123-456-7890'
        })
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.emp_user.refresh_from_db()
        self.emp_employee.refresh_from_db()
        self.assertEqual(self.emp_user.email, 'new_emp@creativetech.com')
        self.assertEqual(self.emp_employee.phone, '123-456-7890')
        self.client.logout()

    def test_employee_password_change(self):
        self.client.login(username='emp_test', password='password123')
        # Incorrect old password
        response = self.client.post(reverse('change_password'), {
            'old_password': 'wrong_password',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        })
        self.assertRedirects(response, reverse('employee_dashboard'))
        
        # Correct password change
        response = self.client.post(reverse('change_password'), {
            'old_password': 'password123',
            'new_password': 'newpassword123',
            'confirm_password': 'newpassword123'
        })
        self.assertRedirects(response, reverse('employee_dashboard'))
        self.client.logout()
        
        # Verify login with new password works
        login_success = self.client.login(username='emp_test', password='newpassword123')
        self.assertTrue(login_success)

    def test_toggle_job_status(self):
        job = JobPosting.objects.create(
            title='QA Analyst',
            description='Test code',
            requirements='Django experience',
            location='Hybrid',
            is_active=True
        )
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('toggle_job_status', args=[job.id]))
        self.assertRedirects(response, reverse('admin_dashboard'))
        job.refresh_from_db()
        self.assertFalse(job.is_active)

    def test_performance_review_creation(self):
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('add_performance_review'), {
            'employee_id': self.emp_employee.id,
            'review_period': 'Q2 2026',
            'rating': '4.5',
            'goals': 'Improve code coverage',
            'feedback': 'Solid performer'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertEqual(PerformanceReview.objects.filter(employee=self.emp_employee).count(), 1)

    def test_training_enrollment_and_completion(self):
        self.client.login(username='admin_test', password='password123')
        # Create training
        response = self.client.post(reverse('add_training'), {
            'title': 'Django Advanced', 'trainer': 'Jane Trainer', 'start_date': '', 'end_date': '', 'is_online': 'on'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        training = Training.objects.first()
        # Enroll employee
        response = self.client.post(reverse('enroll_training'), {'employee_id': self.emp_employee.id, 'training_id': training.id})
        self.assertRedirects(response, reverse('admin_dashboard'))
        enroll = TrainingEnrollment.objects.filter(employee=self.emp_employee, training=training).first()
        self.assertIsNotNone(enroll)
        # Complete training
        response = self.client.post(reverse('complete_training', args=[enroll.id]), {})
        self.assertRedirects(response, reverse('admin_dashboard'))
        enroll.refresh_from_db()
        self.assertTrue(enroll.completed)

    def test_reports_page_rendering(self):
        self.client.login(username='admin_test', password='password123')
        response = self.client.get(reverse('reports_data'))
        self.assertEqual(response.status_code, 200)

    def test_employee_extended_fields(self):
        # Update employee with extended fields
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('add_employee'), {
            'username': 'new_emp', 'first_name': 'New', 'last_name': 'Emp', 'email': 'new@company.com', 'password': 'pw12345',
            'department': 'Engineering', 'role': 'Engineer', 'phone': '555-1234', 'salary': '4000',
            'gender': 'Male', 'date_of_birth': '1990-01-01', 'address': '123 Main', 'designation': 'Senior', 'employee_id_code': 'CT-999'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        created = Employee.objects.filter(user__username='new_emp').first()
        self.assertIsNotNone(created)
        self.assertEqual(created.designation, 'Senior')
        self.assertEqual(created.employee_id_code, 'CT-999')

    def test_reset_employee_password(self):
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('reset_employee_password', args=[self.emp_employee.id]), {
            'new_password': 'brandnewpassword123'
        })
        self.assertRedirects(response, reverse('admin_dashboard'))
        
        # Logout admin and try to login as employee using new password
        self.client.logout()
        login_success = self.client.login(username='emp_test', password='brandnewpassword123')
        self.assertTrue(login_success)
        self.client.logout()

    def test_delete_employee(self):
        self.client.login(username='admin_test', password='password123')
        self.assertTrue(Employee.objects.filter(id=self.emp_employee.id).exists())
        
        response = self.client.post(reverse('delete_employee', args=[self.emp_employee.id]))
        self.assertRedirects(response, reverse('admin_dashboard'))
        
        self.assertFalse(Employee.objects.filter(id=self.emp_employee.id).exists())
        self.assertFalse(User.objects.filter(username='emp_test').exists())

    def test_delete_self_restriction(self):
        self.client.login(username='admin_test', password='password123')
        self.assertTrue(Employee.objects.filter(id=self.admin_employee.id).exists())
        
        response = self.client.post(reverse('delete_employee', args=[self.admin_employee.id]))
        self.assertRedirects(response, reverse('admin_dashboard'))
        
        self.assertTrue(Employee.objects.filter(id=self.admin_employee.id).exists())
        self.assertTrue(User.objects.filter(username='admin_test').exists())

    def test_admin_attendance_logs_filtering(self):
        self.client.login(username='admin_test', password='password123')
        
        past_date_1 = date.today() - timedelta(days=2)
        past_date_2 = date.today() - timedelta(days=5)
        
        att1 = Attendance.objects.create(employee=self.emp_employee)
        Attendance.objects.filter(id=att1.id).update(date=past_date_1)
        
        att2 = Attendance.objects.create(employee=self.admin_employee)
        Attendance.objects.filter(id=att2.id).update(date=past_date_2)
        
        # Access with no filters
        response = self.client.get(reverse('admin_dashboard'), {'tab': 'attendance'})
        self.assertEqual(response.status_code, 200)
        logs = response.context['attendance_logs_page']
        self.assertGreaterEqual(logs.paginator.count, 2)
        
        # Access with employee filter
        response = self.client.get(reverse('admin_dashboard'), {
            'tab': 'attendance',
            'attendance_employee': self.emp_employee.id
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_employee_id'], self.emp_employee.id)
        
        # Access with date filter
        response = self.client.get(reverse('admin_dashboard'), {
            'tab': 'attendance',
            'attendance_date': past_date_2.strftime('%Y-%m-%d')
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['selected_date_str'], past_date_2.strftime('%Y-%m-%d'))

    def test_delete_payslip(self):
        # Create a payslip
        payslip = Payslip.objects.create(
            employee=self.emp_employee,
            month_year='April 2026',
            basic_salary=3000.00,
            allowances=500.00,
            deductions=100.00,
            net_salary=3400.00,
            status='Pending'
        )
        self.assertEqual(Payslip.objects.count(), 1)
        
        # Log in as admin and delete
        self.client.login(username='admin_test', password='password123')
        response = self.client.post(reverse('delete_payslip', args=[payslip.id]))
        self.assertRedirects(response, reverse('admin_dashboard'))
        self.assertEqual(Payslip.objects.count(), 0)

    def test_new_admin_modules(self):
        # Log in as admin
        self.client.login(username='admin_test', password='password123')

        # Test Holiday creation
        response = self.client.post(reverse('holidays'), {
            'name': 'New Year Day',
            'date': '2026-01-01'
        })
        self.assertRedirects(response, reverse('holidays'))
        self.assertTrue(Holiday.objects.filter(name='New Year Day').exists())

        # Test Client creation (with login User)
        response = self.client.post(reverse('clients'), {
            'company_name': 'Test Client Corp',
            'client_id': 'CL-TEST',
            'contact_person': 'Jane Client',
            'email': 'jane@testclient.com',
            'phone': '9876543210',
            'username': 'client_user_test',
            'password': 'clientpassword123'
        })
        self.assertRedirects(response, reverse('clients'))
        client_obj = ClientModel.objects.filter(company_name='Test Client Corp').first()
        self.assertIsNotNone(client_obj)
        self.assertIsNotNone(client_obj.user)
        self.assertEqual(client_obj.user.username, 'client_user_test')

        # Test Project creation (linked to Client)
        response = self.client.post(reverse('projects'), {
            'name': 'Test Portal Design',
            'client_id': client_obj.id,
            'deadline': '2026-12-31',
            'progress': '10',
            'status': 'Active',
            'description': 'Building a dashboard'
        })
        self.assertRedirects(response, reverse('projects'))
        project_obj = Project.objects.filter(name='Test Portal Design').first()
        self.assertIsNotNone(project_obj)
        self.assertEqual(project_obj.client, client_obj)

        # Test update project progress
        response = self.client.post(reverse('update_project', args=[project_obj.id]), {
            'progress': '45',
            'status': 'Active'
        })
        self.assertRedirects(response, reverse('projects'))
        project_obj.refresh_from_db()
        self.assertEqual(project_obj.progress, 45)

        # Test Goal tracking creation
        response = self.client.post(reverse('goals'), {
            'type': 'Revenue',
            'subject': 'Double profit margin',
            'target_achievement': '100% growth',
            'start_date': '2026-01-01',
            'end_date': '2026-12-31',
            'description': 'Targeting enterprise clients',
            'status': 'Active'
        })
        self.assertRedirects(response, reverse('goals'))
        self.assertTrue(GoalTracking.objects.filter(subject='Double profit margin').exists())

    def test_client_portal(self):
        # Create client user and Client profile
        user = User.objects.create_user(username='portal_client', password='password123', email='c@c.com', first_name='Portal')
        client_obj = ClientModel.objects.create(
            user=user,
            company_name='Portal Client LLC',
            client_id='CL-PORTAL',
            contact_person='Portal User',
            email='c@c.com'
        )

        # Create project for client
        project_obj = Project.objects.create(
            name='Portal Client Website',
            client=client_obj,
            progress=65,
            status='Active'
        )

        # Access client login page
        response = self.client.get(reverse('client_login'))
        self.assertEqual(response.status_code, 200)

        # Post correct credentials
        response = self.client.post(reverse('client_login'), {
            'username': 'portal_client',
            'password': 'password123'
        })
        self.assertRedirects(response, reverse('client_dashboard'))

        # Check client dashboard contains correct project information
        response = self.client.get(reverse('client_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Portal Client LLC')
        self.assertContains(response, 'Portal Client Website')
        self.assertContains(response, '65%')

    def test_project_updates_and_replies(self):
        # Create client profile
        user = User.objects.create_user(username='comment_client', password='password123', email='cc@cc.com')
        client_obj = ClientModel.objects.create(
            user=user,
            company_name='Comment Client Corp',
            contact_person='Jane Commenter',
            email='cc@cc.com'
        )

        # Create project linked to client
        project_obj = Project.objects.create(
            name='Discussion Project',
            client=client_obj,
            progress=0,
            status='Active'
        )

        # Admin logs in
        self.client.login(username='admin_test', password='password123')

        # Admin updates project details & posts daily status update
        response = self.client.post(reverse('admin_project_detail', args=[project_obj.id]), {
            'status': 'Active',
            'progress': '15',
            'message': 'Day 1: Setup database schema and initial structure.'
        })
        self.assertRedirects(response, reverse('admin_project_detail', args=[project_obj.id]))

        # Verify database changes
        project_obj.refresh_from_db()
        self.assertEqual(project_obj.progress, 15)
        self.assertTrue(ProjectUpdate.objects.filter(project=project_obj, is_admin=True, message__icontains='Day 1').exists())

        # Admin logs out
        self.client.logout()

        # Client logs in
        self.client.login(username='comment_client', password='password123')

        # Client views project discussion detail page
        response = self.client.get(reverse('client_project_detail', args=[project_obj.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Day 1: Setup database schema and initial structure.')

        # Client posts a reply/input
        response = self.client.post(reverse('client_project_detail', args=[project_obj.id]), {
            'message': 'Thanks for the update. Looks good! Can we confirm the indexing keys?'
        })
        self.assertRedirects(response, reverse('client_project_detail', args=[project_obj.id]))

        # Verify client reply is saved
        self.assertTrue(ProjectUpdate.objects.filter(project=project_obj, is_admin=False, message__icontains='indexing keys').exists())

        # Admin logs in again and reads the reply
        self.client.logout()
        self.client.login(username='admin_test', password='password123')
        response = self.client.get(reverse('admin_project_detail', args=[project_obj.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Thanks for the update. Looks good!')






