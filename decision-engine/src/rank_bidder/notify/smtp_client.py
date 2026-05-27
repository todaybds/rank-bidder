"""SMTP 클라이언트 — Story 6.1.

stdlib smtplib. STARTTLS 우선, port 465 시 SMTP_SSL. env unset 시 dry-run (log only).

env vars:
  NOTIFY_SMTP_HOST   — 미설정 시 dry-run
  NOTIFY_SMTP_PORT   — default 587
  NOTIFY_SMTP_USER   — 인증 username (없으면 unauth)
  NOTIFY_SMTP_PASS   — 인증 password
  NOTIFY_FROM        — From: 헤더, default 'rank-bidder@localhost'
  NOTIFY_TO          — 수신자 1명 (필수 in non-dry-run)
"""

from __future__ import annotations

import os
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import structlog

log = structlog.get_logger(__name__)


class SMTPSendError(RuntimeError):
    """SMTP 발송 실패 — 호출자가 다음 분 재시도."""


@dataclass(frozen=True)
class Config:
    host: str | None
    port: int
    user: str | None
    password: str | None
    sender: str
    recipient: str | None

    @property
    def is_dry_run(self) -> bool:
        return not self.host or not self.recipient

    @classmethod
    def from_env(cls) -> Config:
        port_raw = os.environ.get("NOTIFY_SMTP_PORT", "587").strip() or "587"
        return cls(
            host=os.environ.get("NOTIFY_SMTP_HOST") or None,
            port=int(port_raw),
            user=os.environ.get("NOTIFY_SMTP_USER") or None,
            password=os.environ.get("NOTIFY_SMTP_PASS") or None,
            sender=os.environ.get("NOTIFY_FROM", "rank-bidder@localhost"),
            recipient=os.environ.get("NOTIFY_TO") or None,
        )


def send(subject: str, body: str, *, cfg: Config | None = None) -> bool:
    """이메일 1건 발송. 성공 True, dry-run True (no-op 표시), 실패 SMTPSendError raise.

    dry-run 시 structlog INFO 로그만 — 테스트 + dev 환경.
    """
    cfg = cfg or Config.from_env()
    if cfg.is_dry_run:
        log.info("notify.dry_run", subject=subject, body_len=len(body))
        return True

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.sender
    msg["To"] = cfg.recipient
    msg.set_content(body, charset="utf-8")

    try:
        if cfg.port == 465:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=15) as smtp:
                if cfg.user:
                    smtp.login(cfg.user, cfg.password or "")
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=15) as smtp:
                smtp.ehlo()
                try:
                    smtp.starttls()
                    smtp.ehlo()
                except smtplib.SMTPNotSupportedError:
                    log.warning("notify.starttls_unsupported", host=cfg.host)
                if cfg.user:
                    smtp.login(cfg.user, cfg.password or "")
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise SMTPSendError(str(exc)) from exc
    log.info("notify.sent", subject=subject, recipient=cfg.recipient)
    return True
