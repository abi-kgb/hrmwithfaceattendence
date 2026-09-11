import os
import threading
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.utils.html import strip_tags

def send_attendance_approval_email(att_req, base_url="http://127.0.0.1:8000"):
    """
    Sends a rich HTML email to the company Admin with styled Approve and Reject buttons.
    """
    def _send():
        emp = att_req.employee
        user = emp.user
        emp_name = f"{user.first_name} {user.last_name}".strip() or user.username
        emp_code = emp.employee_id_code or f"EMP-{emp.id}"
        dept_name = emp.department.name if emp.department else "General"
        
        approve_url = f"{base_url}/attendance/approve/{att_req.token}/"
        reject_url = f"{base_url}/attendance/reject/{att_req.token}/"
        
        subject = f"🔔 Action Required: {att_req.request_type} Request from {emp_name} ({emp_code})"
        
        is_logout = att_req.request_type in ['Early Departure', 'Clock Out', 'Emergency Exit', 'Logout Approval']
        action_verb = "Clock-Out" if is_logout else "Login"
        approve_btn_text = f"✅ Approve & Save {action_verb}"
        subtitle_text = "Early Departure / Clock-Out Permission Request" if is_logout else "Late Arrival / Attendance Permission Request"
        note_text = f"Upon approval, the employee's {action_verb.lower()} time will be officially marked and recorded in the database."

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f1f5f9; margin: 0; padding: 20px; }}
            .container {{ max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 12px; overflow: hidden; box-shadow: 0 4px 15px rgba(0,0,0,0.08); border: 1px solid #e2e8f0; }}
            .header {{ background: linear-gradient(135deg, #1e293b, #0f172a); color: #ffffff; padding: 24px; text-align: center; }}
            .header h1 {{ margin: 0; font-size: 20px; font-weight: 700; }}
            .header p {{ margin: 6px 0 0 0; font-size: 13px; color: #94a3b8; }}
            .body {{ padding: 24px; color: #334155; }}
            .info-box {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 20px; }}
            .reason-box {{ background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px 16px; border-radius: 4px; margin-bottom: 24px; font-size: 14px; }}
            .btn {{ display: inline-block; padding: 12px 24px; font-size: 15px; font-weight: 700; text-decoration: none; border-radius: 8px; text-align: center; margin: 0 6px; }}
            .btn-approve {{ background-color: #10b981; color: #ffffff !important; box-shadow: 0 4px 10px rgba(16,185,129,0.3); }}
            .btn-reject {{ background-color: #ef4444; color: #ffffff !important; box-shadow: 0 4px 10px rgba(239,68,68,0.3); }}
            .footer {{ background: #f8fafc; border-top: 1px solid #e2e8f0; padding: 16px; text-align: center; font-size: 12px; color: #94a3b8; }}
          </style>
        </head>
        <body>
          <div class="container">
            <div class="header">
              <h1>🛡️ SmartHR Attendance Approval</h1>
              <p>{subtitle_text}</p>
            </div>
            <div class="body">
              <p style="font-size: 15px; margin-top: 0;">Hello Admin,</p>
              <p style="font-size: 14px; line-height: 1.5;">An employee has requested permission for <strong>{att_req.request_type}</strong>. Please review the details below and take action:</p>
              
              <div class="info-box">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Employee Name:</td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 700; text-align: right;">{emp_name}</td>
                  </tr>
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Employee ID / Role:</td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600; text-align: right;">{emp_code} ({emp.role})</td>
                  </tr>
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Department:</td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600; text-align: right;">{dept_name}</td>
                  </tr>
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Date:</td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600; text-align: right;">{att_req.date.strftime('%d %B %Y')}</td>
                  </tr>
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Requested Time:</td>
                    <td style="padding: 6px 0; color: #2563eb; font-weight: 700; text-align: right;">{att_req.requested_time.strftime('%I:%M %p')}</td>
                  </tr>
                  <tr>
                    <td style="padding: 6px 0; color: #64748b; font-weight: 600;">Request Type:</td>
                    <td style="padding: 6px 0; color: #d97706; font-weight: 700; text-align: right;">{att_req.request_type}</td>
                  </tr>
                </table>
              </div>

              <div class="reason-box">
                <strong style="color: #1e40af; display: block; margin-bottom: 4px;">📝 Reason provided:</strong>
                <span style="color: #1e293b;">{att_req.reason}</span>
              </div>

              <p style="text-align: center; font-size: 14px; font-weight: 600; color: #475569; margin-bottom: 12px;">Click below to approve or reject this request:</p>
              
              <table style="margin: 0 auto; border-collapse: separate; border-spacing: 12px 0;">
                <tr>
                  <td>
                    <a href="{approve_url}" class="btn btn-approve" style="background-color: #10b981; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 700; display: inline-block;">
                      {approve_btn_text}
                    </a>
                  </td>
                  <td>
                    <a href="{reject_url}" class="btn btn-reject" style="background-color: #ef4444; color: #ffffff; padding: 12px 24px; border-radius: 8px; text-decoration: none; font-weight: 700; display: inline-block;">
                      ❌ Reject Request
                    </a>
                  </td>
                </tr>
              </table>

              <p style="font-size: 12px; color: #94a3b8; text-align: center; margin-top: 24px;">
                {note_text}
              </p>
            </div>
            <div class="footer">
              SmartHR Automated Attendance Management System &bull; Secure Tokenized Approval Link
            </div>
          </div>
        </body>
        </html>
        """
        
        text_content = f"""SmartHR Attendance Approval Request

Employee Name: {emp_name}
Employee ID: {emp_code} ({emp.role})
Department: {dept_name}
Date: {att_req.date.strftime('%d %B %Y')}
Requested Time: {att_req.requested_time.strftime('%I:%M %p')}
Request Type: {att_req.request_type}
Reason: {att_req.reason}

==================================================
ACTIONS:
==================================================

✅ [APPROVE & SAVE]:
{approve_url}

❌ [DISAPPROVE / REJECT]:
{reject_url}

==================================================
Upon approval, the attendance record will be saved automatically.
"""
        
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'adminuser.93@gmail.com')
        admin_email = getattr(settings, 'ADMIN_EMAIL', os.environ.get("ADMIN_EMAIL", "abhinaya.kgb@gmail.com"))
        
        try:
            msg = EmailMultiAlternatives(subject, text_content, from_email, [admin_email])
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=False)
            print(f"[Email Service] Sent attendance approval email for {emp_name} to {admin_email}")
        except Exception as e:
            print(f"[Email Service Error] Failed to send email: {e}")
            # Fallback to direct smtplib if Django settings SMTP is default
            try:
                import smtplib
                from email.mime.multipart import MIMEMultipart
                from email.mime.text import MIMEText
                
                smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
                smtp_port = int(os.environ.get("SMTP_PORT", "587"))
                smtp_user = os.environ.get("SMTP_USER", "")
                smtp_pass = os.environ.get("SMTP_PASS", "")
                
                if smtp_user and smtp_pass:
                    m = MIMEMultipart("alternative")
                    m["Subject"] = subject
                    m["From"] = smtp_user
                    m["To"] = admin_email
                    m.attach(MIMEText(text_content, "plain"))
                    m.attach(MIMEText(html_content, "html"))
                    
                    server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(m)
                    server.quit()
                    print(f"[Email Service Fallback] Sent via SMTP to {admin_email}")
            except Exception as e2:
                print(f"[Email Service SMTP Error] {e2}")

    threading.Thread(target=_send, daemon=True).start()
