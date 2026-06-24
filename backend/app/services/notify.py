import asyncio
import smtplib
import uuid
from email.mime.text import MIMEText

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Notification, User


async def create_notification(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    title: str,
    message: str,
    link: str | None = None,
) -> Notification:
    note = Notification(user_id=user_id, title=title, message=message, link=link)
    db.add(note)
    await db.flush()
    return note


async def notify_user(
    db: AsyncSession,
    *,
    user: User,
    title: str,
    message: str,
    link: str | None = None,
    send_email: bool = True,
) -> Notification:
    note = await create_notification(db, user_id=user.id, title=title, message=message, link=link)
    if send_email and settings.smtp_host:
        body = f"{message}\n\n{link or settings.app_base_url}"
        await asyncio.to_thread(_send_email_sync, user.email, title, body)
    return note


def _send_email_sync(to_email: str, subject: str, body: str) -> None:
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_user and settings.smtp_password:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)


async def notify_applicant_event(
    db: AsyncSession,
    *,
    owner: User,
    applicant_name: str,
    applicant_id: uuid.UUID,
    event: str,
) -> None:
    link = f"{settings.app_base_url}/applicants/{applicant_id}/review"
    if event == "conflict":
        title = f"Xung đột dữ liệu — {applicant_name}"
        message = f"Hồ sơ '{applicant_name}' có xung đột cần giải quyết."
    elif event == "ready":
        title = f"Sẵn sàng export — {applicant_name}"
        message = f"Hồ sơ '{applicant_name}' đã sẵn sàng xuất form."
    else:
        title = f"Cập nhật hồ sơ — {applicant_name}"
        message = f"Hồ sơ '{applicant_name}' đã được cập nhật."
    await notify_user(db, user=owner, title=title, message=message, link=link)
