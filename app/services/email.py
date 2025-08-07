import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.config.config import (
    EMAIL_HOST, 
    EMAIL_PORT, 
    EMAIL_USERNAME, 
    EMAIL_PASSWORD, 
    EMAIL_FROM, 
    EMAIL_TLS
)
import logging
from datetime import datetime

async def send_email(to: str, subject: str, html_content: str) -> bool:
    """
    Send an email using the configured SMTP server
    """
    try:
        # Setup email
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = EMAIL_FROM
        message["To"] = to

        # Create HTML content
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        # Connect to the SMTP server
        with smtplib.SMTP(EMAIL_HOST, EMAIL_PORT) as server:
            if EMAIL_TLS:
                server.starttls()
            
            server.login(EMAIL_USERNAME, EMAIL_PASSWORD)
            server.sendmail(EMAIL_FROM, to, message.as_string())
            
        logging.info(f"Email sent successfully to {to}")
        return True
    except Exception as e:
        logging.error(f"Error sending email: {e}")
        return False

async def send_password_reset_email(email: str, token_id: str, base_url: str) -> bool:
    """
    Send a password reset email with a link containing only the token ID
    """
    # Buat URL reset password dengan token ID saja (aman, tidak mengekspos token asli)
    reset_url = f"{base_url}/reset-password?token_id={token_id}"
    
    # Format tanggal
    current_time = datetime.now().strftime("%d %B %Y, %H:%M WIB")
    
    subject = "Knowvera - Reset Kata Sandi Anda"
    
    html_content = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background-color: #10A37F; padding: 20px; text-align: center; color: white; }}
            .content {{ padding: 20px; background-color: #f9f9f9; }}
            .button {{ display: inline-block; padding: 10px 20px; background-color: #10A37F; color: white; text-decoration: none; border-radius: 4px; }}
            .details {{ background-color: #eee; padding: 15px; margin: 15px 0; border-radius: 4px; }}
            .footer {{ padding: 20px; text-align: center; font-size: 12px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>Knowvera</h1>
            </div>
            <div class="content">
                <h2>Reset Kata Sandi Anda</h2>
                <p>Kami menerima permintaan untuk mengatur ulang kata sandi akun Knowvera Anda pada {current_time}.</p>
                <p>Klik tombol di bawah ini untuk mengatur ulang kata sandi Anda:</p>
                <p style="text-align: center; margin: 30px 0;">
                    <a href="{reset_url}" class="button">Reset Kata Sandi</a>
                </p>
                <div class="details">
                    <p><strong>Penting:</strong></p>
                    <ul>
                        <li>Link reset password ini hanya berlaku selama <strong>10 menit</strong>.</li>
                        <li>Jika Anda tidak melakukan permintaan ini, abaikan email ini.</li>
                    </ul>
                </div>
                <p>Atau, salin dan tempel URL berikut ke browser Anda:</p>
                <p style="word-break: break-all; background-color: #eee; padding: 10px; border-radius: 4px;">{reset_url}</p>
            </div>
            <div class="footer">
                <p>&copy; {datetime.now().year} Knowvera. All rights reserved.</p>
                <p>Ini adalah email yang dikirim secara otomatis, mohon jangan balas email ini.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return await send_email(email, subject, html_content)