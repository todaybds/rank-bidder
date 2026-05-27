"""OS 분기 NTP 재동기화 helper (Story 1.5, AC5).

403 invalid-timestamp 응답 시 호출 → 동기화 시도 후 재호출 1회 가능.
실패해도 raise 안 함(best-effort). 운영자 알림은 structlog 이벤트로.

Linux 시도 순서 (AC5 — P3 systemctl restart fallback):
1. ``sudo -n timedatectl set-ntp true``
2. ``timedatectl set-ntp true`` (non-sudo)
3. ``sudo -n systemctl restart systemd-timesyncd``
4. ``systemctl restart systemd-timesyncd`` (non-sudo)
"""

from __future__ import annotations

import platform
import shutil
import subprocess

import structlog

log = structlog.get_logger(__name__)


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


def _run_cmd(cmd: list[str], *, timeout_s: float, os_label: str) -> bool:
    """단발 외부 명령 실행 — returncode==0이면 True. 실패/타임아웃은 log 후 False (P20)."""
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if res.returncode == 0:
            log.info(
                "naver_sa.ntp_resync",
                os=os_label,
                cmd=" ".join(cmd),
                returncode=0,
                ok=True,
            )
            return True
        log.warning(
            "naver_sa.ntp_resync_attempt_failed",
            os=os_label,
            cmd=" ".join(cmd),
            returncode=res.returncode,
            stderr=(res.stderr or "")[:200],
        )
        return False
    except subprocess.TimeoutExpired:
        log.warning(
            "naver_sa.ntp_resync_attempt_failed",
            os=os_label,
            cmd=" ".join(cmd),
            reason="timeout",
        )
        return False
    except OSError as exc:
        log.warning(
            "naver_sa.ntp_resync_attempt_failed",
            os=os_label,
            cmd=" ".join(cmd),
            reason=str(exc),
        )
        return False


def resync_ntp(*, timeout_s: float = 10.0) -> bool:
    """현재 OS에 맞는 NTP 재동기화 명령 실행.

    Returns:
        True면 명령이 exit 0으로 끝남 (성공 추정).
        False면 명령 없거나 실패. 호출자는 그대로 1회 재시도 후 NaverSANtpDrift raise.
    """
    sys_name = platform.system()

    if sys_name == "Windows":
        if not _which("w32tm"):
            log.warning("naver_sa.ntp_resync", os="Windows", reason="w32tm not found")
            return False
        return _run_cmd(["w32tm", "/resync"], timeout_s=timeout_s, os_label="Windows")

    if sys_name == "Linux":
        attempts: list[list[str]] = []
        if _which("timedatectl"):
            attempts.append(["sudo", "-n", "timedatectl", "set-ntp", "true"])
            attempts.append(["timedatectl", "set-ntp", "true"])
        if _which("systemctl"):
            attempts.append(["sudo", "-n", "systemctl", "restart", "systemd-timesyncd"])
            attempts.append(["systemctl", "restart", "systemd-timesyncd"])
        if not attempts:
            log.warning(
                "naver_sa.ntp_resync",
                os="Linux",
                reason="neither timedatectl nor systemctl found",
            )
            return False
        for cmd in attempts:
            if _run_cmd(cmd, timeout_s=timeout_s, os_label="Linux"):
                return True
        log.warning(
            "naver_sa.ntp_resync",
            os="Linux",
            reason="all attempts failed (timedatectl + systemctl)",
        )
        return False

    log.warning("naver_sa.ntp_resync", os=sys_name, reason="unsupported platform")
    return False
