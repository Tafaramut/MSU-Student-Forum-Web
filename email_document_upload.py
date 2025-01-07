import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from docx import Document
from PyPDF2 import PdfReader


account_sid = os.getenv('TWILIO_ACCOUNT_SID')
auth_token = os.getenv('TWILIO_AUTH_TOKEN')
twilio_phone_number = os.getenv('TWILIO_PHONE_NUMBER')

# Access email configuration from environment variables
SMTP_SERVER = os.getenv('SMTP_SERVER')
SMTP_PORT = int(os.getenv('SMTP_PORT'))
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD')
RECIPIENT_EMAIL = os.getenv('RECIPIENT_EMAIL')



def extract_text_from_pdf(file_path):
    """Extract text from a PDF file."""
    pdf = PdfReader(file_path)
    text = ""
    for page in pdf.pages:
        text += page.extract_text()
    return text

def extract_text_from_word(file_path):
    """Extract text from a Word document."""
    doc = Document(file_path)
    text = ""
    for paragraph in doc.paragraphs:
        text += paragraph.text + "\n"
    return text

def send_email_with_attachment(file_path, subject, filename, caption):
    """Send an email with the document attachment."""
    try:
        message = MIMEMultipart()
        message['From'] = os.getenv('EMAIL_ADDRESS')
        message['To'] = os.getenv('RECIPIENT_EMAIL')
        message['Subject'] = subject  # Subject remains unchanged

        # Email body includes the caption
        body = f"{caption}\n\nThe document '{filename}' is attached for your review."
        message.attach(MIMEText(body, 'plain'))

        # Attach the file
        with open(file_path, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={os.path.basename(file_path)}"
        )
        message.attach(part)

        # Send the email
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, message.as_string())
        print("Email sent successfully.")
    except Exception as e:
        print(f"Failed to send email: {e}")
