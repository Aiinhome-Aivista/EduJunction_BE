"""Email controller for SahajPath.

Handles background dispatching of transactional emails such as:
- Account Registration (Welcome Email)
- Normal Login Notification
- Google Login Notification
"""

import os
import smtplib
import threading
from datetime import datetime
from email.message import EmailMessage
from utils.config import config
from utils.logger import logger


def render_email_template(title: str, content_html: str) -> str:
    """Create a modern, responsive HTML email template for SahajPath."""
    app_name = config.APP_NAME or "SahajPath"
    current_year = datetime.now().year

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #f8fafc;
            color: #1e293b;
            margin: 0;
            padding: 0;
            -webkit-font-smoothing: antialiased;
        }}
        .wrapper {{
            max-width: 600px;
            margin: 30px auto;
            background: #ffffff;
            border-radius: 16px;
            overflow: hidden;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.05), 0 8px 10px -6px rgba(0, 0, 0, 0.01);
            border: 1px solid #e2e8f0;
        }}
        .header {{
            background-color: #ffffff;
            padding: 32px 36px 24px;
            text-align: center;
            border-bottom: 2px solid #fef08a;
        }}
        .header .logo {{
            font-size: 28px;
            font-weight: 900;
            letter-spacing: -0.5px;
        }}
        .header p {{
            margin: 8px 0 0;
            font-size: 13px;
            font-weight: 500;
            color: #64748b;
        }}
        .body-content {{
            padding: 36px;
            font-size: 15px;
            line-height: 1.65;
            color: #334155;
        }}
        .card {{
            background: #f8fafc;
            border-left: 4px solid #eab308;
            padding: 16px 20px;
            border-radius: 8px;
            margin: 20px 0;
        }}
        .footer {{
            background-color: #f8fafc;
            padding: 24px 36px;
            text-align: center;
            font-size: 12px;
            color: #64748b;
            border-top: 1px solid #e2e8f0;
        }}
        .footer p {{
            margin: 4px 0;
        }}
    </style>
</head>
<body>
    <div class="wrapper">
        <div class="header">
            <div class="logo">🎓 <span style="color: #09090b;">Sahaj</span><span style="color: #eab308;">Path</span></div>
            <p>AI-Powered Adaptive Learning & Progress Analytics</p>
        </div>
        <div class="body-content">
            {content_html}
        </div>
        <div class="footer">
            <p><strong><span style="color: #09090b;">Sahaj</span><span style="color: #eab308;">Path</span></strong> &bull; Personalized Learning Ecosystem</p>
            <p>&copy; {current_year} {app_name}. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""


def _send_email_sync(to_email: str, subject: str, content_html: str, plain_text: str = "") -> bool:
    """Synchronously dispatches the email via SMTP."""
    try:
        smtp_server = config.SMTP_SERVER or os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(config.SMTP_PORT or os.getenv("SMTP_PORT", "587"))
        smtp_username = config.SMTP_USERNAME or os.getenv("SMTP_USERNAME")
        smtp_password = config.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD")
        smtp_sender_name = config.SMTP_SENDER_NAME or os.getenv("SMTP_SENDER_NAME", "SahajPath")
        smtp_use_tls = config.SMTP_USE_TLS if hasattr(config, "SMTP_USE_TLS") else True

        if not smtp_username or not smtp_password:
            logger.warning(f"[EMAIL] SMTP credentials not configured. Skipped sending email to {to_email}")
            return False

        html_body = render_email_template(subject, content_html)

        message = EmailMessage()
        message["From"] = f"{smtp_sender_name} <{smtp_username}>"
        message["To"] = to_email
        message["Subject"] = subject

        # Plain-text version
        text_body = plain_text or "Please view this email in an HTML-compatible client."
        message.set_content(text_body)

        # HTML version
        message.add_alternative(html_body, subtype="html")

        with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
            if smtp_use_tls:
                server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(message)

        logger.info(f"[EMAIL] Successfully sent email '{subject}' to {to_email}")
        return True

    except Exception as e:
        logger.error(f"[EMAIL] Failed to send email to {to_email}: {str(e)}")
        return False


def send_email_async(to_email: str, subject: str, content_html: str, plain_text: str = "") -> None:
    """Dispatches email asynchronously in a background thread so the HTTP request is not blocked."""
    thread = threading.Thread(
        target=_send_email_sync,
        args=(to_email, subject, content_html, plain_text),
        daemon=True,
    )
    thread.start()


def send_email(to_email: str) -> bool:
    """Standard send_email function for login success notification."""
    subject = "Login Successful - SahajPath"
    content_html = """
        <h2 style="color: #1e293b; margin-top: 0;">Welcome back to SahajPath! 🎓</h2>
        <p>You have successfully logged in to your <strong>SahajPath</strong> account.</p>
        <div class="card">
            <p style="margin: 0; font-size: 14px; color: #475569;">
                📍 <strong>Security Notice:</strong> If this was not you, please secure your account immediately by resetting your password.
            </p>
        </div>
        <p>Continue your learning journey and make progress every day!</p>
        <p><strong>Happy Learning! 🚀</strong></p>
    """
    plain_text = (
        "Welcome back to SahajPath!\n\n"
        "You have successfully logged in to your account.\n\n"
        "If this was not you, please secure your account immediately.\n\n"
        "Happy Learning!\nSahajPath Team"
    )
    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_registration_email(to_email: str, name: str = "", username: str = "", role_name: str = "PARENT") -> bool:
    """Sends a personalized welcome email upon successful account registration."""
    display_name = name.strip() if name else "Learner"
    subject = "Welcome to SahajPath! 🎓 Your Account is Ready"

    username_info = f"<p><strong>Username:</strong> <code>{username}</code></p>" if username else ""
    role_info = f"<p><strong>Role:</strong> {role_name.title()}</p>" if role_name else ""

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Welcome aboard, {display_name}! 🎉</h2>
        <p>Thank you for joining <strong>SahajPath</strong>. Your account has been created successfully.</p>
        
        <div class="card">
            <h3 style="margin-top: 0; font-size: 15px; color: #334155;">📋 Account Details:</h3>
            <p style="margin: 4px 0;"><strong>Email:</strong> {to_email}</p>
            {username_info}
            {role_info}
        </div>

        <p>With SahajPath, you can:</p>
        <ul style="color: #475569; padding-left: 20px;">
            <li>Track real-time learning analytics and skill mastery.</li>
            <li>Experience AI-generated practice exams & adaptive learning paths.</li>
            <li>Collaborate with teachers, parents, and students seamlessly.</li>
        </ul>

        <p>Get started today and unlock the power of AI-assisted education!</p>
        <p><strong>Best regards,</strong><br>The SahajPath Team</p>
    """

    plain_text = (
        f"Welcome aboard, {display_name}!\n\n"
        f"Thank you for registering on SahajPath.\n"
        f"Email: {to_email}\n"
        f"Username: {username}\n"
        f"Role: {role_name}\n\n"
        f"Best regards,\nThe SahajPath Team"
    )

    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_login_email(to_email: str, name: str = "", login_type: str = "Standard") -> bool:
    """Sends a login alert email for Standard Login or Google OAuth Login."""
    display_name = name.strip() if name else "User"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"Login Alert ({login_type}) - SahajPath"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Hello, {display_name}! 🎓</h2>
        <p>You have successfully logged in to your <strong>SahajPath</strong> account.</p>
        
        <div class="card">
            <p style="margin: 4px 0;"><strong>Login Method:</strong> {login_type} Sign-in</p>
            <p style="margin: 4px 0;"><strong>Timestamp:</strong> {current_time}</p>
            <p style="margin: 4px 0; font-size: 13px; color: #64748b;">If this login was made by you, no further action is needed.</p>
        </div>

        <p style="color: #475569;">
            If you did not perform this action, please change your password or contact our support team immediately.
        </p>
        <p><strong>Happy Learning! 🚀</strong><br>The SahajPath Team</p>
    """

    plain_text = (
        f"Hello {display_name}!\n\n"
        f"You have successfully logged in to SahajPath via {login_type} Sign-in at {current_time}.\n\n"
        f"If this was not you, please secure your account immediately.\n\n"
        f"Happy Learning!\nThe SahajPath Team"
    )

    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_password_changed_email(to_email: str, name: str = "", username: str = "", role_name: str = "Parent") -> bool:
    """Sends a security confirmation email immediately after password is reset."""
    display_name = name.strip() if name else "Learner"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = "🔐 Security Alert: Your SahajPath Password Was Changed"

    username_info = f"<p style='margin: 4px 0;'><strong>Username:</strong> <code>{username}</code></p>" if username else ""
    role_info = f"<p style='margin: 4px 0;'><strong>Account Role:</strong> {role_name.title()}</p>" if role_name else ""

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Password Changed Successfully 🔐</h2>
        <p>Hello <strong>{display_name}</strong>,</p>
        <p>This is a confirmation that the password for your <strong>SahajPath</strong> account was recently changed.</p>
        
        <div class="card">
            <h3 style="margin-top: 0; font-size: 15px; color: #334155;">📋 Account Details:</h3>
            <p style="margin: 4px 0;"><strong>Email:</strong> {to_email}</p>
            {username_info}
            {role_info}
            <p style="margin: 4px 0;"><strong>Time of Change:</strong> {current_time}</p>
        </div>

        <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 14px 18px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; font-size: 13px; color: #991b1b; font-weight: 500;">
                ⚠️ <strong>Didn't make this change?</strong><br>
                If you did not reset your password, your account may be compromised. Please contact support immediately or use the Forgot Password option to secure your account.
            </p>
        </div>

        <p style="color: #475569;">If you made this change yourself, you can safely disregard this email.</p>
        <p><strong>Happy Learning! 🚀</strong><br>The SahajPath Team</p>
    """

    plain_text = (
        f"Hello {display_name},\n\n"
        f"This is a confirmation that the password for your SahajPath account ({username or to_email}) was recently changed at {current_time}.\n\n"
        f"If you did not perform this change, please contact support or reset your password immediately.\n\n"
        f"Best regards,\nThe SahajPath Team"
    )

    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_school_student_registered_email(
    to_school_email: str,
    student_name: str,
    class_grade: str,
    target_board: str,
    school_name: str = "",
    parent_name: str = "",
    parent_email: str = "",
) -> bool:
    """Sends an official academic notification email to the school when a student is registered with their school email."""
    if not to_school_email or not to_school_email.strip():
        return False

    display_student = student_name.strip() if student_name else "Student"
    display_school = school_name.strip() if school_name else "Your Institution"
    display_parent = parent_name.strip() if parent_name else "Parent / Guardian"
    reg_date = datetime.now().strftime("%d %b %Y, %I:%M %p")
    subject = f"🎓 Student Registration Notice: {display_student} registered in SahajPath"

    school_info = f"<p style='margin: 4px 0;'><strong>School Name:</strong> {display_school}</p>" if school_name else ""
    parent_info = f"<p style='margin: 4px 0;'><strong>Registered By:</strong> {display_parent} ({parent_email})</p>" if parent_email else f"<p style='margin: 4px 0;'><strong>Registered By:</strong> {display_parent}</p>"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Student Academic Registration Notice 🎓</h2>
        <p>Dear Administrator / Educator,</p>
        <p>This is to inform you that <strong>{display_student}</strong> has been registered on the <strong>SahajPath</strong> Adaptive Learning & Diagnostic Assessment Platform affiliated with your institution.</p>
        
        <div class="card">
            <h3 style="margin-top: 0; font-size: 15px; color: #334155;">📋 Student Academic Profile:</h3>
            <p style="margin: 4px 0;"><strong>Student Name:</strong> {display_student}</p>
            <p style="margin: 4px 0;"><strong>Class / Grade:</strong> {class_grade}</p>
            <p style="margin: 4px 0;"><strong>Target Board:</strong> {target_board}</p>
            {school_info}
            {parent_info}
            <p style="margin: 4px 0;"><strong>Registration Date:</strong> {reg_date}</p>
        </div>

        <div style="background-color: #f0fdf4; border-left: 4px solid #22c55e; padding: 14px 18px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; font-size: 13px; color: #166534; font-weight: 500;">
                💡 <strong>About SahajPath Diagnostic Platform:</strong><br>
                SahajPath assists students in continuous curriculum mastery through adaptive 10-mark diagnostic exams, AI misconception classification, and evolutionary topic mastery tracking aligned with {target_board} standards.
            </p>
        </div>

        <p style="color: #475569;">If you are an educator associated with this student, you can access diagnostic dossiers and learning paths to monitor academic progress.</p>
        <p><strong>Warm regards,</strong><br>The SahajPath Academic Support Team</p>
    """

    plain_text = (
        f"Dear Administrator / Educator,\n\n"
        f"This is to notify you that {display_student} has been registered on the SahajPath platform.\n\n"
        f"Student Name: {display_student}\n"
        f"Class / Grade: {class_grade}\n"
        f"Target Board: {target_board}\n"
        f"School: {display_school}\n"
        f"Registered By: {display_parent} ({parent_email})\n"
        f"Date: {reg_date}\n\n"
        f"Best regards,\nThe SahajPath Academic Support Team"
    )

    send_email_async(to_school_email.strip(), subject, content_html, plain_text)
    return True

