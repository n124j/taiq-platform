"""
Email utility — sends via SMTP (aiosmtplib).
Set EMAIL_ENABLED=true + SMTP_* vars in .env to activate real sending.
When EMAIL_ENABLED=false, emails are printed to the backend log instead.
"""
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.core.config import settings

logger = logging.getLogger(__name__)


async def send_email(to: str, subject: str, html_body: str) -> bool:
    """Send an HTML email. Returns True on success, False on failure."""
    if not settings.EMAIL_ENABLED:
        logger.info(f"[EMAIL DISABLED] To: {to} | Subject: {subject}")
        logger.info(f"[EMAIL BODY PREVIEW]\n{html_body[:500]}...")
        return True

    try:
        import aiosmtplib
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{settings.SMTP_FROM_NAME} <{settings.SMTP_FROM_EMAIL}>"
        msg["To"] = to
        msg.attach(MIMEText(html_body, "html"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            start_tls=True,
        )
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception as e:
        logger.error(f"Failed to send email to {to}: {e}")
        return False


def reset_password_email_html(full_name: str, reset_url: str) -> str:
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
</head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(10,15,30,.1);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#050c1f 0%,#0d2654 60%,#1a3a7a 100%);padding:40px 48px;text-align:center;">
            <div style="display:inline-flex;align-items:center;gap:10px;">
              <div style="width:40px;height:40px;background:#0052cc;border-radius:10px;display:inline-block;line-height:40px;text-align:center;">
                <span style="color:white;font-size:18px;font-weight:bold;">T</span>
              </div>
              <span style="color:white;font-size:24px;font-weight:800;font-family:Georgia,serif;">TaIQ</span>
            </div>
            <p style="color:rgba(255,255,255,.6);font-size:13px;margin:8px 0 0;">Your career intelligence platform</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:48px;">
            <h1 style="font-size:26px;font-weight:700;color:#0a0f1e;margin:0 0 8px;">
              Reset your password
            </h1>
            <p style="color:#384060;font-size:15px;line-height:1.6;margin:0 0 24px;">
              Hi {full_name}, we received a request to reset the password for your TaIQ account.
              Click the button below to choose a new one.
            </p>

            <!-- Reset button -->
            <table cellpadding="0" cellspacing="0" style="margin:0 0 32px;">
              <tr>
                <td style="background:#0052cc;border-radius:50px;padding:14px 32px;">
                  <a href="{reset_url}" style="color:white;font-size:15px;font-weight:600;text-decoration:none;display:inline-block;">
                    🔒 Reset My Password
                  </a>
                </td>
              </tr>
            </table>

            <p style="color:#6b7899;font-size:13px;line-height:1.6;margin:0 0 8px;">
              If the button doesn't work, copy and paste this link into your browser:
            </p>
            <p style="margin:0 0 32px;">
              <a href="{reset_url}" style="color:#0052cc;font-size:13px;word-break:break-all;">{reset_url}</a>
            </p>

            <p style="color:#6b7899;font-size:12px;margin:0;">
              This link expires in <strong>1 hour</strong>.
              If you didn't request a password reset, you can safely ignore this email — your password will not be changed.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f4f6fb;border-top:1px solid #c8d0e4;padding:24px 48px;text-align:center;">
            <p style="color:#6b7899;font-size:12px;margin:0 0 8px;">
              © 2025 TaIQ Inc. · 123 Innovation Drive, Philadelphia, PA 19103
            </p>
            <p style="margin:0;">
              <a href="{settings.FRONTEND_URL}/privacy-policy.html" style="color:#0052cc;font-size:12px;text-decoration:none;margin:0 8px;">Privacy Policy</a>
              <a href="{settings.FRONTEND_URL}/terms-of-service.html" style="color:#0052cc;font-size:12px;text-decoration:none;margin:0 8px;">Terms of Service</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""


def welcome_email_html(full_name: str, role: str, verify_url: str) -> str:
    role_label = "Job Seeker" if role == "candidate" else "Employer / Recruiter"
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
</head>
<body style="margin:0;padding:0;background:#f4f6fb;font-family:'Helvetica Neue',Arial,sans-serif;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6fb;padding:40px 0;">
    <tr><td align="center">
      <table width="600" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(10,15,30,.1);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#050c1f 0%,#0d2654 60%,#1a3a7a 100%);padding:40px 48px;text-align:center;">
            <div style="display:inline-flex;align-items:center;gap:10px;">
              <div style="width:40px;height:40px;background:#0052cc;border-radius:10px;display:inline-block;line-height:40px;text-align:center;">
                <span style="color:white;font-size:18px;font-weight:bold;">T</span>
              </div>
              <span style="color:white;font-size:24px;font-weight:800;font-family:Georgia,serif;">TaIQ</span>
            </div>
            <p style="color:rgba(255,255,255,.6);font-size:13px;margin:8px 0 0;">Your career intelligence platform</p>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="padding:48px;">
            <h1 style="font-size:26px;font-weight:700;color:#0a0f1e;margin:0 0 8px;">
              Welcome to TaIQ, {full_name}! 🎉
            </h1>
            <p style="color:#384060;font-size:15px;line-height:1.6;margin:0 0 24px;">
              Your account has been created as a <strong>{role_label}</strong>. 
              You're one step away from accessing thousands of opportunities.
            </p>

            <!-- Verify button -->
            <table cellpadding="0" cellspacing="0" style="margin:0 0 32px;">
              <tr>
                <td style="background:#0052cc;border-radius:50px;padding:14px 32px;">
                  <a href="{verify_url}" style="color:white;font-size:15px;font-weight:600;text-decoration:none;display:inline-block;">
                    ✅ Verify My Email Address
                  </a>
                </td>
              </tr>
            </table>

            <p style="color:#6b7899;font-size:13px;line-height:1.6;margin:0 0 8px;">
              If the button doesn't work, copy and paste this link into your browser:
            </p>
            <p style="margin:0 0 32px;">
              <a href="{verify_url}" style="color:#0052cc;font-size:13px;word-break:break-all;">{verify_url}</a>
            </p>

            <!-- What's next -->
            <div style="background:#f4f6fb;border-radius:12px;padding:24px;margin-bottom:32px;">
              <h3 style="font-size:14px;font-weight:700;color:#0a0f1e;margin:0 0 16px;">What's next?</h3>
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td width="32" valign="top" style="padding-right:12px;font-size:18px;">{'📝' if role == 'candidate' else '🏢'}</td>
                  <td style="color:#384060;font-size:13px;line-height:1.6;">
                    {'Complete your profile and upload your resume to get matched with top jobs.' if role == 'candidate' else 'Set up your company profile and post your first job listing.'}
                  </td>
                </tr>
                <tr><td colspan="2" style="height:12px;"></td></tr>
                <tr>
                  <td width="32" valign="top" style="padding-right:12px;font-size:18px;">🔍</td>
                  <td style="color:#384060;font-size:13px;line-height:1.6;">
                    {'Browse thousands of open positions and apply with one click.' if role == 'candidate' else 'Search our database of pre-screened candidates.'}
                  </td>
                </tr>
              </table>
            </div>

            <p style="color:#6b7899;font-size:12px;margin:0;">
              This link expires in <strong>24 hours</strong>. 
              If you didn't create a TaIQ account, you can safely ignore this email.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f4f6fb;border-top:1px solid #c8d0e4;padding:24px 48px;text-align:center;">
            <p style="color:#6b7899;font-size:12px;margin:0 0 8px;">
              © 2025 TaIQ Inc. · 123 Innovation Drive, Philadelphia, PA 19103
            </p>
            <p style="margin:0;">
              <a href="{settings.FRONTEND_URL}/privacy-policy.html" style="color:#0052cc;font-size:12px;text-decoration:none;margin:0 8px;">Privacy Policy</a>
              <a href="{settings.FRONTEND_URL}/terms-of-service.html" style="color:#0052cc;font-size:12px;text-decoration:none;margin:0 8px;">Terms of Service</a>
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""
