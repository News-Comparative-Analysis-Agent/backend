import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from app.core.logger import logger

def send_error_email(error_message: str, traceback_str: str, request_info: str) -> None:
    smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    developer_email = os.getenv("DEVELOPER_EMAIL")

    if not all([smtp_user, smtp_password, developer_email]):
        logger.warning("SMTP 계정 정보나 개발자 이메일이 설정되지 않아 에러 메일을 발송할 수 없습니다.")
        return

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = developer_email
    msg['Subject'] = f"🚨 [Aigent Backend Error] 500 Internal Server Error 발생"

    body = f"""
    <h2>Aigent Backend 서버 에러 발생</h2>
    
    <h3>1. Request Info</h3>
    <pre style="background-color: #f4f4f4; padding: 10px; border-radius: 5px;">{request_info}</pre>

    <h3>2. Error Message</h3>
    <p style="color: red;"><b>{error_message}</b></p>

    <h3>3. Traceback</h3>
    <pre style="background-color: #f4f4f4; padding: 10px; border-radius: 5px; font-size: 12px; overflow-x: auto;">{traceback_str}</pre>
    """
    
    msg.attach(MIMEText(body, 'html'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        logger.info(f"에러 이메일 발송 완료: {developer_email}")
    except Exception as e:
        logger.error(f"이메일 발송 실패: {e}")
