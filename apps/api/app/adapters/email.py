"""Outbound email: verification and reset codes, 2FA codes and email broadcasts.

`BrevoApiEmailSender` sends through Brevo's HTTPS API (BREVO_API_KEY): for hosts that block
outbound SMTP, such as Render's free tier. Otherwise `SmtpEmailSender` sends through any SMTP
server with `aiosmtplib` (STARTTLS on 587, implicit TLS on 465). With neither, the stub logs
instead of sending. Messages are sent off the request path (app/worker/dispatch.py).
"""

import logging
from collections import deque
from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import httpx

from app.adapters.readiness import configured
from app.core.config import get_adapters_settings

# What the stub "sent", newest last — lets local dev and tests read a verification code
# without a real SMS/email provider. Bounded, and only the stub writes to it.
OUTBOX: deque[dict] = deque(maxlen=200)

logger = logging.getLogger("zuula.adapters.email")


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class StubEmailSender:
    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.info("Email (stub, not sent): to=%s subject=%r body=%r", to, subject, body)
        OUTBOX.append({"to": to, "subject": subject, "body": body})


class SmtpEmailSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        sender: str,
        timeout: float = 15.0,
    ):
        self._host = host
        self._port = port
        self._username = username or None
        self._password = password or None
        self._sender = sender
        self._timeout = timeout

    def build(self, *, to: str, subject: str, body: str) -> EmailMessage:
        message = EmailMessage()
        message["From"] = f"Zuula <{self._sender}>"
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        return message

    async def send(self, *, to: str, subject: str, body: str) -> None:
        await aiosmtplib.send(
            self.build(to=to, subject=subject, body=body),
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
            use_tls=self._port == 465,
            start_tls=self._port == 587,
            timeout=self._timeout,
        )


class EmailError(RuntimeError):
    pass


BREVO_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"


class BrevoApiEmailSender:
    def __init__(self, *, api_key: str, sender: str, timeout: float = 15.0):
        self._api_key = api_key
        self._sender = sender
        self._timeout = timeout

    async def send(self, *, to: str, subject: str, body: str) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                BREVO_URL,
                headers={"api-key": self._api_key, "accept": "application/json"},
                json={
                    "sender": {"name": "Zuula", "email": self._sender},
                    "to": [{"email": to}],
                    "subject": subject,
                    "textContent": body,
                },
            )
        if response.status_code >= 400:
            # Brevo's error body names the problem (e.g. an unverified sender), never the key.
            raise EmailError(f"Brevo refused the email ({response.status_code}): {response.text}")

    async def check(self) -> None:
        """Raises EmailError unless Brevo accepts the key (for /readyz): a wrong key, such as
        the SMTP key instead of an API key, otherwise only shows when a code never arrives."""
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(
                BREVO_ACCOUNT_URL, headers={"api-key": self._api_key, "accept": "application/json"}
            )
        if response.status_code >= 400:
            raise EmailError(f"Brevo refused the API key ({response.status_code}): {response.text}")


def get_email_sender() -> EmailSender:
    if configured("email"):
        settings = get_adapters_settings()
        if settings.brevo_api_key:
            return BrevoApiEmailSender(api_key=settings.brevo_api_key, sender=settings.email_from)
        return SmtpEmailSender(
            host=settings.email_smtp_host,
            port=settings.email_smtp_port,
            username=settings.email_smtp_user,
            password=settings.email_smtp_password,
            sender=settings.email_from,
        )
    return StubEmailSender()
