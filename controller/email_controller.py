"""Email controller for EduJunction.

Handles background dispatching of transactional emails such as:
- Account Registration (Welcome Email)
- Normal Login Notification
- Google Login Notification
"""

import os
import smtplib
import ssl
import threading
from datetime import datetime
from email.message import EmailMessage
from utils.config import config
from utils.logger import logger


def render_email_template(title: str, content_html: str) -> str:
    """Create a modern, responsive HTML email template for EduJunction."""
    app_name = config.APP_NAME or "EduJunction"
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
            <div class="logo">🎓 <span style="color: #09090b;">Edu</span><span style="color: #eab308;">Junction</span></div>
            <p>Adaptive Learning & Progress Analytics</p>
        </div>
        <div class="body-content">
            {content_html}
        </div>
        <div class="footer">
            <p><strong><span style="color: #09090b;">Edu</span><span style="color: #eab308;">Junction</span></strong> &bull; Personalized Learning Ecosystem</p>
            <p>&copy; {current_year} {app_name}. All rights reserved.</p>
        </div>
    </div>
</body>
</html>
"""


def _send_email_sync(
    to_email: str,
    subject: str,
    content_html: str,
    plain_text: str = "",
    attachments: list[dict] | None = None,
) -> bool:
    """Synchronously dispatches the email via SMTP with optional attachments."""
    try:
        smtp_server = getattr(config, "SMTP_SERVER", None) or os.getenv("SMTP_SERVER") or os.getenv("SMTP_HOST", "mail.edujunction.co.in")
        smtp_port = int(getattr(config, "SMTP_PORT", None) or os.getenv("SMTP_PORT", "465"))
        smtp_username = getattr(config, "SMTP_USERNAME", None) or os.getenv("SMTP_USERNAME")
        smtp_password = getattr(config, "SMTP_PASSWORD", None) or os.getenv("SMTP_PASSWORD")
        smtp_sender_name = getattr(config, "SMTP_SENDER_NAME", None) or os.getenv("SMTP_SENDER_NAME") or os.getenv("SMTP_FROM_NAME", "EduJunction")
        smtp_from_email = getattr(config, "SMTP_FROM_EMAIL", None) or os.getenv("SMTP_FROM_EMAIL") or smtp_username
        smtp_use_tls = getattr(config, "SMTP_USE_TLS", True)

        if not smtp_username or not smtp_password:
            logger.warning(f"[EMAIL] SMTP credentials not configured. Skipped sending email to {to_email}")
            return False

        html_body = render_email_template(subject, content_html)

        message = EmailMessage()
        message["From"] = f"{smtp_sender_name} <{smtp_from_email}>"
        message["Reply-To"] = smtp_from_email
        message["To"] = to_email
        message["Subject"] = subject

        # Plain-text version
        text_body = plain_text or "Please view this email in an HTML-compatible client."
        message.set_content(text_body)

        # HTML version
        message.add_alternative(html_body, subtype="html")

        # Attachments
        if attachments:
            for att in attachments:
                message.add_attachment(
                    att["content"],
                    maintype=att.get("maintype", "application"),
                    subtype=att.get("subtype", "octet-stream"),
                    filename=att["filename"],
                )

        # Create SSL context (configured to support domain mail servers)
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        if smtp_port == 465:
            with smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=20) as server:
                server.login(smtp_username, smtp_password)
                server.send_message(message)
        else:
            with smtplib.SMTP(smtp_server, smtp_port, timeout=20) as server:
                if smtp_use_tls:
                    server.starttls(context=context)
                server.login(smtp_username, smtp_password)
                server.send_message(message)

        logger.info(f"[EMAIL] Successfully sent email '{subject}' to {to_email}")
        return True

    except Exception as e:
        logger.error(f"[EMAIL] Failed to send email to {to_email}: {str(e)}")
        return False


def send_email_async(
    to_email: str,
    subject: str,
    content_html: str,
    plain_text: str = "",
    attachments: list[dict] | None = None,
) -> None:
    """Dispatches email asynchronously in a background thread so the HTTP request is not blocked."""
    thread = threading.Thread(
        target=_send_email_sync,
        args=(to_email, subject, content_html, plain_text, attachments),
        daemon=True,
    )
    thread.start()


def send_email(to_email: str) -> bool:
    """Standard send_email function for login success notification."""
    subject = "Login Successful - EduJunction"
    content_html = """
        <h2 style="color: #1e293b; margin-top: 0;">Welcome back to EduJunction! 🎓</h2>
        <p>You have successfully logged in to your <strong>EduJunction</strong> account.</p>
        <div class="card">
            <p style="margin: 0; font-size: 14px; color: #475569;">
                📍 <strong>Security Notice:</strong> If this was not you, please secure your account immediately by resetting your password.
            </p>
        </div>
        <p>Continue your learning journey and make progress every day!</p>
        <p><strong>Happy Learning! 🚀</strong></p>
    """
    plain_text = (
        "Welcome back to EduJunction!\n\n"
        "You have successfully logged in to your account.\n\n"
        "If this was not you, please secure your account immediately.\n\n"
        "Happy Learning!\nEduJunction Team"
    )
    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_registration_email(
    to_email: str,
    name: str = "",
    username: str = "",
    role_name: str = "PARENT",
    password: str = "",
    login_method: str = "Standard"
) -> bool:
    """Sends a personalized welcome email upon successful account registration including login credentials."""
    if not to_email or not to_email.strip():
        return False

    display_name = name.strip() if name else "Learner"
    subject = "Welcome to EduJunction! 🎓 Your Account Credentials"

    username_info = f"<p style='margin: 4px 0;'><strong>Username:</strong> <code style='background: #e2e8f0; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>{username}</code></p>" if username else ""
    role_info = f"<p style='margin: 4px 0;'><strong>Account Type:</strong> {role_name.title()}</p>" if role_name else ""
    
    if password:
        password_info = f"<p style='margin: 4px 0;'><strong>Password:</strong> <code style='background: #fef08a; color: #854d0e; padding: 2px 6px; border-radius: 4px; font-weight: bold;'>{password}</code></p>"
    elif login_method == "Google":
        password_info = "<p style='margin: 4px 0;'><strong>Login Method:</strong> <span style='color: #2563eb; font-weight: 600;'>Google 1-Click Sign-in</span> (No separate password required)</p>"
    else:
        password_info = ""

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Welcome to EduJunction, {display_name}! 🎉</h2>
        <p>Thank you for joining <strong>EduJunction</strong>. Your account has been created successfully.</p>
        
        <div class="card" style="border-left: 4px solid #eab308; background: #fffbeb; padding: 18px 20px; border-radius: 10px; margin: 20px 0;">
            <h3 style="margin-top: 0; font-size: 15px; color: #854d0e;">📋 Your Login Credentials:</h3>
            <p style="margin: 4px 0;"><strong>Email:</strong> {to_email}</p>
            {username_info}
            {password_info}
            {role_info}
        </div>

        <div style="text-align: center; margin: 24px 0;">
            <a href="https://www.edujunction.co.in/login" style="display: inline-block; background: #f59e0b; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 12px 28px; border-radius: 8px;">
                🚀 Log In to Your Account
            </a>
        </div>

        <p>With EduJunction, you can:</p>
        <ul style="color: #475569; padding-left: 20px;">
            <li>Track real-time learning analytics and skill mastery.</li>
            <li>Experience curriculum practice exams & adaptive learning paths.</li>
            <li>Collaborate with teachers, parents, and students seamlessly.</li>
        </ul>

        <p style="font-size: 12px; color: #64748b; margin-top: 20px;">
            🔒 <em>Security Tip: Keep your login credentials safe. You can change your password anytime from your profile settings.</em>
        </p>

        <p><strong>Best regards,</strong><br>The EduJunction Team</p>
    """

    plain_text = (
        f"Welcome to EduJunction, {display_name}!\n\n"
        f"Thank you for registering on EduJunction.\n"
        f"Email: {to_email}\n"
        f"Username: {username}\n"
        + (f"Password: {password}\n" if password else (f"Login Method: Google 1-Click Sign-in\n" if login_method == "Google" else ""))
        + f"Role: {role_name}\n\n"
        f"Log in here: https://www.edujunction.co.in/login\n\n"
        f"Best regards,\nThe EduJunction Team"
    )

    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_child_registration_email(
    to_parent_email: str,
    parent_name: str,
    child_name: str,
    child_username: str,
    child_password: str,
    class_grade: str,
    board: str
) -> bool:
    """Sends student login credentials to parent upon creating a child account."""
    if not to_parent_email or not to_parent_email.strip():
        return False

    display_parent = parent_name.strip() if parent_name else "Parent"
    display_child = child_name.strip() if child_name else "Student"
    subject = f"🎓 Student Profile Created for {display_child} - Login Credentials"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Student Account Ready! 🎓</h2>
        <p>Dear <strong>{display_parent}</strong>,</p>
        <p>You have successfully registered a student profile for <strong>{display_child}</strong> on <strong>EduJunction</strong>.</p>
        
        <div class="card" style="border-left: 4px solid #3b82f6; background: #eff6ff; padding: 18px 20px; border-radius: 10px; margin: 20px 0;">
            <h3 style="margin-top: 0; font-size: 15px; color: #1e40af;">👦 Student Login Credentials:</h3>
            <p style="margin: 4px 0;"><strong>Student Name:</strong> {display_child}</p>
            <p style="margin: 4px 0;"><strong>Curriculum & Class:</strong> {board} — {class_grade}</p>
            <p style="margin: 4px 0;"><strong>Student Username:</strong> <code style="background: #dbeafe; color: #1e40af; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{child_username}</code></p>
            <p style="margin: 4px 0;"><strong>Student Password:</strong> <code style="background: #fef08a; color: #854d0e; padding: 2px 6px; border-radius: 4px; font-weight: bold;">{child_password}</code></p>
        </div>

        <div style="text-align: center; margin: 24px 0;">
            <a href="https://www.edujunction.co.in/login" style="display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 12px 28px; border-radius: 8px;">
                🚀 Student Log In Portal
            </a>
        </div>

        <p style="font-size: 13px; color: #475569;">
            Your child can log in anytime using their unique Username and Password to access interactive exams, track daily streak XP, and take mock test series.
        </p>

        <p><strong>Warm regards,</strong><br>The EduJunction Team</p>
    """

    plain_text = (
        f"Dear {display_parent},\n\n"
        f"Student account for {display_child} has been created on EduJunction.\n\n"
        f"--- Student Login Details ---\n"
        f"Student Name: {display_child}\n"
        f"Curriculum: {board} - {class_grade}\n"
        f"Username: {child_username}\n"
        f"Password: {child_password}\n\n"
        f"Log in here: https://www.edujunction.co.in/login\n\n"
        f"Best regards,\nThe EduJunction Team"
    )

    send_email_async(to_parent_email, subject, content_html, plain_text)
    return True


def send_login_email(to_email: str, name: str = "", login_type: str = "Standard") -> bool:
    """Sends a login alert email for Standard Login or Google OAuth Login."""
    display_name = name.strip() if name else "User"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = f"Login Alert ({login_type}) - EduJunction"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Hello, {display_name}! 🎓</h2>
        <p>You have successfully logged in to your <strong>EduJunction</strong> account.</p>
        
        <div class="card">
            <p style="margin: 4px 0;"><strong>Login Method:</strong> {login_type} Sign-in</p>
            <p style="margin: 4px 0;"><strong>Timestamp:</strong> {current_time}</p>
            <p style="margin: 4px 0; font-size: 13px; color: #64748b;">If this login was made by you, no further action is needed.</p>
        </div>

        <p style="color: #475569;">
            If you did not perform this action, please change your password or contact our support team immediately.
        </p>
        <p><strong>Happy Learning! 🚀</strong><br>The EduJunction Team</p>
    """

    plain_text = (
        f"Hello {display_name}!\n\n"
        f"You have successfully logged in to EduJunction via {login_type} Sign-in at {current_time}.\n\n"
        f"If this was not you, please secure your account immediately.\n\n"
        f"Happy Learning!\nThe EduJunction Team"
    )

    send_email_async(to_email, subject, content_html, plain_text)
    return True


def send_password_reset_otp_email(
    to_email: str,
    name: str = "",
    username: str = "",
    otp_code: str = "",
) -> bool:
    """Dispatches a secure One-Time Password (OTP) email for password reset."""
    if not to_email or not to_email.strip():
        return False

    display_name = name.strip() if name else "User"
    otp_ttl = getattr(config, "OTP_TTL_MINUTES", 10)
    subject = f"🔐 Your EduJunction Password Reset OTP: {otp_code}"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Password Reset Verification Code 🔐</h2>
        <p>Hello <strong>{display_name}</strong>,</p>
        <p>We received a request to reset the password for your <strong>EduJunction</strong> account (Username: <strong>{username}</strong>).</p>
        
        <p>Please enter the following 6-digit verification code to complete your password reset:</p>

        <div style="background-color: #fef9c3; border: 2px dashed #eab308; padding: 20px; border-radius: 12px; margin: 24px 0; text-align: center;">
            <span style="font-size: 32px; font-weight: 900; letter-spacing: 6px; color: #854d0e; font-family: monospace;">{otp_code}</span>
            <p style="margin: 8px 0 0; font-size: 12px; color: #a16207; font-weight: 600;">Valid for {otp_ttl} minutes</p>
        </div>

        <div style="background-color: #fef2f2; border-left: 4px solid #ef4444; padding: 12px 16px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 0; font-size: 13px; color: #991b1b; font-weight: 500;">
                ⚠️ <strong>Security Notice:</strong> Do not share this OTP with anyone. If you did not request this verification code, your account may be secure and you can safely ignore this email.
            </p>
        </div>

        <p><strong>Happy Learning! 🚀</strong><br>The EduJunction Team</p>
    """

    plain_text = (
        f"Hello {display_name},\n\n"
        f"Your EduJunction password reset OTP is: {otp_code}\n\n"
        f"This OTP is valid for {otp_ttl} minutes. Please enter this code on the password reset screen to set your new password.\n\n"
        f"If you did not request this reset, please ignore this email.\n\n"
        f"Best regards,\nThe EduJunction Team"
    )

    send_email_async(to_email.strip(), subject, content_html, plain_text)
    return True


def send_password_changed_email(to_email: str, name: str = "", username: str = "", role_name: str = "Parent") -> bool:
    """Sends a security confirmation email immediately after password is reset."""
    display_name = name.strip() if name else "Learner"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    subject = "🔐 Security Alert: Your EduJunction Password Was Changed"

    username_info = f"<p style='margin: 4px 0;'><strong>Username:</strong> <code>{username}</code></p>" if username else ""
    role_info = f"<p style='margin: 4px 0;'><strong>Account Role:</strong> {role_name.title()}</p>" if role_name else ""

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Password Changed Successfully 🔐</h2>
        <p>Hello <strong>{display_name}</strong>,</p>
        <p>This is a confirmation that the password for your <strong>EduJunction</strong> account was recently changed.</p>
        
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
        <p><strong>Happy Learning! 🚀</strong><br>The EduJunction Team</p>
    """

    plain_text = (
        f"Hello {display_name},\n\n"
        f"This is a confirmation that the password for your EduJunction account ({username or to_email}) was recently changed at {current_time}.\n\n"
        f"If you did not perform this change, please contact support or reset your password immediately.\n\n"
        f"Best regards,\nThe EduJunction Team"
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
    subject = f"🎓 Student Registration Notice: {display_student} registered in EduJunction"

    school_info = f"<p style='margin: 4px 0;'><strong>School Name:</strong> {display_school}</p>" if school_name else ""
    parent_info = f"<p style='margin: 4px 0;'><strong>Registered By:</strong> {display_parent} ({parent_email})</p>" if parent_email else f"<p style='margin: 4px 0;'><strong>Registered By:</strong> {display_parent}</p>"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Student Academic Registration Notice 🎓</h2>
        <p>Dear Administrator / Educator,</p>
        <p>This is to inform you that <strong>{display_student}</strong> has been registered on the <strong>EduJunction</strong> Adaptive Learning & Diagnostic Assessment Platform affiliated with your institution.</p>
        
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
                💡 <strong>About EduJunction Diagnostic Platform:</strong><br>
                EduJunction assists students in continuous curriculum mastery through adaptive 10-mark diagnostic exams, automated misconception classification, and evolutionary topic mastery tracking aligned with {target_board} standards.
            </p>
        </div>

        <p style="color: #475569;">If you are an educator associated with this student, you can access diagnostic dossiers and learning paths to monitor academic progress.</p>
        <p><strong>Warm regards,</strong><br>The EduJunction Academic Support Team</p>
    """

    plain_text = (
        f"Dear Administrator / Educator,\n\n"
        f"This is to notify you that {display_student} has been registered on the EduJunction platform.\n\n"
        f"Student Name: {display_student}\n"
        f"Class / Grade: {class_grade}\n"
        f"Target Board: {target_board}\n"
        f"School: {display_school}\n"
        f"Registered By: {display_parent} ({parent_email})\n"
        f"Date: {reg_date}\n\n"
        f"Best regards,\nThe EduJunction Academic Support Team"
    )

    send_email_async(to_school_email.strip(), subject, content_html, plain_text)
    return True


def send_student_exam_report_email(
    to_email: str,
    student_name: str,
    board: str,
    class_grade: str,
    subject_name: str,
    exam_title: str,
    exam_date: str,
    marks_obtained: float,
    total_marks: float,
    accuracy_percentage: float,
    pdf_bytes: bytes,
) -> bool:
    """Dispatches a detailed Exam Result Performance Report PDF attached to the parent/student email."""
    if not to_email or not to_email.strip():
        return False

    display_name = student_name.strip() if student_name else "Student"
    subject = f"📊 Performance Report: {display_name}'s {subject_name} Exam Result ({marks_obtained}/{total_marks})"

    content_html = f"""
        <h2 style="color: #1e293b; margin-top: 0;">Exam Result & Assessment Report</h2>
        <p>Dear Parent / Guardian,</p>
        <p><strong>{display_name}</strong> has just completed an assessment on <strong>EduJunction</strong>.</p>
        
        <div class="card" style="border-left: 4px solid #0284c7; background: #f0f9ff;">
            <h3 style="margin-top: 0; color: #0369a1;">📝 Exam Score Overview:</h3>
            <p style="margin: 4px 0;"><strong>Student Name:</strong> {display_name}</p>
            <p style="margin: 4px 0;"><strong>Curriculum:</strong> {board} - {class_grade}</p>
            <p style="margin: 4px 0;"><strong>Subject:</strong> {subject_name}</p>
            <p style="margin: 4px 0;"><strong>Score:</strong> <span style="font-size: 16px; font-weight: bold; color: #0284c7;">{marks_obtained} / {total_marks} ({accuracy_percentage}%)</span></p>
            <p style="margin: 4px 0;"><strong>Date:</strong> {exam_date}</p>
        </div>

        <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 14px 18px; border-radius: 8px; margin: 16px 0;">
            <p style="margin: 0; font-size: 13px; color: #475569;">
                📎 <strong>Attached PDF Report:</strong> We have attached the full student diagnostic performance report PDF with question-by-question breakdown, conceptual strengths, and recommended action steps.
            </p>
        </div>

        <p>You can also review active mastery and adaptive learning roadmaps in the EduJunction Parent Portal.</p>
        <p><strong>Warm regards,</strong><br>The EduJunction Academic Assessment Team</p>
    """

    plain_text = (
        f"Dear Parent / Guardian,\n\n"
        f"{display_name} has completed the {subject_name} exam on EduJunction.\n"
        f"Score: {marks_obtained}/{total_marks} ({accuracy_percentage}%)\n"
        f"Curriculum: {board} - {class_grade}\n"
        f"Date: {exam_date}\n\n"
        f"Please find the detailed PDF Diagnostic Report attached to this email.\n\n"
        f"Best regards,\nThe EduJunction Academic Assessment Team"
    )

    clean_filename = f"EduJunction_Report_{display_name.replace(' ', '_')}_{subject_name.replace(' ', '_')}.pdf"

    attachments = [
        {
            "filename": clean_filename,
            "content": pdf_bytes,
            "maintype": "application",
            "subtype": "pdf",
        }
    ]

    send_email_async(to_email.strip(), subject, content_html, plain_text, attachments)
    return True


def send_payment_confirmation_email(
    user_email: str,
    user_name: str,
    order_details: dict,
) -> bool:
    """Dispatches a dynamic, branded payment confirmation & invoice email to the student/parent

    and sends an instant notification copy to the company's official receiving email.
    """
    if not user_email or not user_email.strip():
        logger.warning("[EMAIL] send_payment_confirmation_email called with empty user_email.")
        return False

    display_name = user_name.strip() if user_name else "Valued Student / Parent"
    student_name = order_details.get("student_name") or display_name
    board = order_details.get("board", "CBSE")
    class_grade = order_details.get("class_grade", "Class 10")
    subject_name = order_details.get("subject", "General")
    quantity = int(order_details.get("quantity", 1))
    amount_paid = float(order_details.get("amount_paid", 0.0))
    currency = order_details.get("currency", "INR")
    currency_symbol = "₹" if currency == "INR" else f"{currency} "
    order_id = order_details.get("order_id", "N/A")
    payment_id = order_details.get("payment_id", "N/A")
    contact_phone = order_details.get("contact_phone", "N/A")
    tx_date = order_details.get("date") or datetime.now().strftime("%d %b %Y, %I:%M %p IST")
    sets_text = f"{quantity} Full-Length Model Test Paper Set{'s' if quantity > 1 else ''}"

    subject = f"🎉 Payment Successful ({currency_symbol}{amount_paid:,.2f}): {board} {class_grade} {subject_name} Unlocked!"

    content_html = f"""
        <h2 style="color: #0f172a; margin-top: 0; font-size: 22px;">🎉 Payment Confirmed & Test Paper Unlocked!</h2>
        <p>Dear <strong>{display_name}</strong>,</p>
        <p>Thank you for choosing <strong>EduJunction</strong>. Your payment of <strong><span style="color: #15803d; font-size: 18px;">{currency_symbol}{amount_paid:,.2f}</span></strong> has been successfully processed, and your Model Test Paper sets are now active and ready for practice.</p>

        <div class="card" style="border-left: 4px solid #16a34a; background: #f0fdf4; padding: 20px; border-radius: 12px; margin: 24px 0;">
            <h3 style="margin-top: 0; color: #15803d; font-size: 16px; border-bottom: 1px solid #bbf7d0; padding-bottom: 8px;">
                🧾 Official Payment Receipt & Order Breakdown:
            </h3>
            <table style="width: 100%; font-size: 14px; border-collapse: collapse; margin-top: 10px;">
                <tr>
                    <td style="padding: 6px 0; color: #64748b; width: 42%;"><strong>Candidate / Student:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: bold;">{student_name}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Curriculum & Class:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600;">{board} — {class_grade}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Subject & Sets:</strong></td>
                    <td style="padding: 6px 0; color: #0f172a; font-weight: 600;">{subject_name} ({sets_text})</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Total Amount Paid:</strong></td>
                    <td style="padding: 6px 0; color: #15803d; font-weight: 900; font-size: 16px;">{currency_symbol}{amount_paid:,.2f}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Payment ID:</strong></td>
                    <td style="padding: 6px 0; color: #334155; font-family: monospace; font-size: 12px;">{payment_id}</td>
                </tr>
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Order ID:</strong></td>
                    <td style="padding: 6px 0; color: #334155; font-family: monospace; font-size: 12px;">{order_id}</td>
                </tr>
                {f'<tr><td style="padding: 6px 0; color: #64748b;"><strong>Contact Mobile:</strong></td><td style="padding: 6px 0; color: #0f172a;">+91 {contact_phone}</td></tr>' if contact_phone and contact_phone != 'N/A' else ''}
                <tr>
                    <td style="padding: 6px 0; color: #64748b;"><strong>Date & Time:</strong></td>
                    <td style="padding: 6px 0; color: #475569;">{tx_date}</td>
                </tr>
            </table>
        </div>

        <div style="text-align: center; margin: 30px 0;">
            <a href="https://www.edujunction.co.in/dashboard" style="display: inline-block; background: linear-gradient(135deg, #f59e0b, #d97706); color: #ffffff; text-decoration: none; font-weight: bold; font-size: 15px; padding: 14px 32px; border-radius: 12px; box-shadow: 0 4px 12px rgba(217, 119, 6, 0.25);">
                🚀 Start Practicing Model Papers Now
            </a>
        </div>

        <p style="font-size: 13px; color: #64748b; line-height: 1.6;">
            💡 <strong>Next Steps:</strong> You can log in to your EduJunction dashboard anytime to attempt the online timed exam, get instant evaluation, or download the printable specimen question paper PDF.
        </p>

        <p>If you have any questions or require support, feel free to reply directly to this email.</p>
        <p><strong>Warm regards,</strong><br>The EduJunction Billing & Student Support Team</p>
    """

    plain_text = (
        f"Dear {display_name},\n\n"
        f"Thank you for choosing EduJunction! Your payment of {currency_symbol}{amount_paid:,.2f} is confirmed.\n\n"
        f"--- Order Details ---\n"
        f"Student: {student_name}\n"
        f"Curriculum: {board} - {class_grade}\n"
        f"Subject: {subject_name} ({sets_text})\n"
        f"Amount Paid: {currency_symbol}{amount_paid:,.2f}\n"
        f"Payment ID: {payment_id}\n"
        f"Order ID: {order_id}\n"
        f"Date: {tx_date}\n\n"
        f"Access your model papers anytime at https://www.edujunction.co.in/dashboard\n\n"
        f"Best regards,\nThe EduJunction Team"
    )

    # 1. Send confirmation to Student / Parent
    send_email_async(user_email.strip(), subject, content_html, plain_text)

    # 2. Send instant business transaction copy to Company Official Receiving Email
    company_email = getattr(config, "SMTP_FROM_EMAIL", None) or getattr(config, "SMTP_USERNAME", None) or os.getenv("SMTP_FROM_EMAIL") or os.getenv("SMTP_USERNAME")
    if company_email and company_email.strip() and company_email.strip().lower() != user_email.strip().lower():
        admin_subject = f"[EduJunction Alert] 💰 {currency_symbol}{amount_paid:,.2f} Received - {student_name} ({board} {class_grade} {subject_name})"
        admin_content_html = f"""
            <h2 style="color: #0f172a; margin-top: 0;">💰 New Subscription Payment Received</h2>
            <p>A new Model Paper subscription order has just been paid and activated.</p>
            <div class="card" style="border-left: 4px solid #f59e0b; background: #fffbeb;">
                <p style="margin: 4px 0;"><strong>Amount Received:</strong> <span style="font-size: 18px; font-weight: bold; color: #b45309;">{currency_symbol}{amount_paid:,.2f}</span></p>
                <p style="margin: 4px 0;"><strong>Student:</strong> {student_name}</p>
                <p style="margin: 4px 0;"><strong>Payer Name:</strong> {display_name}</p>
                <p style="margin: 4px 0;"><strong>Payer Email:</strong> {user_email}</p>
                <p style="margin: 4px 0;"><strong>Mobile Number:</strong> +91 {contact_phone}</p>
                <p style="margin: 4px 0;"><strong>Curriculum:</strong> {board} {class_grade} — {subject_name} ({sets_text})</p>
                <p style="margin: 4px 0;"><strong>Razorpay Payment ID:</strong> {payment_id}</p>
                <p style="margin: 4px 0;"><strong>Razorpay Order ID:</strong> {order_id}</p>
                <p style="margin: 4px 0;"><strong>Timestamp:</strong> {tx_date}</p>
            </div>
        """
        admin_plain_text = f"New Subscription Received:\nAmount: {currency_symbol}{amount_paid:,.2f}\nStudent: {student_name}\nPayer: {display_name} ({user_email}, Phone: {contact_phone})\nCurriculum: {board} {class_grade} {subject_name} ({sets_text})\nPayment ID: {payment_id}\nOrder ID: {order_id}"
        send_email_async(company_email.strip(), admin_subject, admin_content_html, admin_plain_text)

    return True


def send_payment_failed_email(
    user_email: str,
    user_name: str,
    order_details: dict,
    failure_reason: str = "Payment was cancelled or could not be completed.",
) -> bool:
    """Dispatches an empathetic notification when a payment attempt fails or is aborted."""
    if not user_email or not user_email.strip():
        return False

    display_name = user_name.strip() if user_name else "Valued Student / Parent"
    board = order_details.get("board", "CBSE")
    class_grade = order_details.get("class_grade", "Class 10")
    subject_name = order_details.get("subject", "General")
    amount_paid = float(order_details.get("amount_paid", 0.0))
    currency_symbol = "₹"
    order_id = order_details.get("order_id", "N/A")
    tx_date = order_details.get("date") or datetime.now().strftime("%d %b %Y, %I:%M %p IST")

    subject = f"⚠️ Payment Incomplete: {board} {class_grade} {subject_name} Model Paper Pass"

    content_html = f"""
        <h2 style="color: #991b1b; margin-top: 0; font-size: 20px;">⚠️ Your Payment Could Not Be Completed</h2>
        <p>Dear <strong>{display_name}</strong>,</p>
        <p>We noticed that your recent attempt to unlock <strong>{board} {class_grade} {subject_name}</strong> Model Test Papers ({currency_symbol}{amount_paid:,.2f}) was not completed.</p>

        <div class="card" style="border-left: 4px solid #ef4444; background: #fef2f2; padding: 16px; border-radius: 8px; margin: 20px 0;">
            <p style="margin: 4px 0;"><strong>Status Note:</strong> {failure_reason}</p>
            <p style="margin: 4px 0;"><strong>Order ID:</strong> {order_id}</p>
            <p style="margin: 4px 0;"><strong>Time:</strong> {tx_date}</p>
        </div>

        <p>No money was deducted from your account. If any amount was debited by your bank, it will automatically be refunded within 3-5 business days as per banking norms.</p>

        <div style="text-align: center; margin: 26px 0;">
            <a href="https://www.edujunction.co.in/pricing" style="display: inline-block; background: #2563eb; color: #ffffff; text-decoration: none; font-weight: bold; font-size: 14px; padding: 12px 28px; border-radius: 10px;">
                🔄 Try Again with UPI / Card
            </a>
        </div>

        <p style="font-size: 13px; color: #64748b;">If you need assistance with payment or have any questions, simply reply to this email.</p>
        <p><strong>Warm regards,</strong><br>The EduJunction Support Team</p>
    """

    plain_text = (
        f"Dear {display_name},\n\n"
        f"Your payment attempt for {board} {class_grade} {subject_name} ({currency_symbol}{amount_paid:,.2f}) was not completed.\n"
        f"Reason: {failure_reason}\n\n"
        f"No amount has been charged. You can retry your payment at: https://www.edujunction.co.in/pricing\n\n"
        f"Best regards,\nEduJunction Support Team"
    )

    send_email_async(user_email.strip(), subject, content_html, plain_text)
    return True
