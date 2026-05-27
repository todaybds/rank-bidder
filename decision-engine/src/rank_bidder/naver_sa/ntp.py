"""OS 분기 NTP 재동기화 helper (Story 1.5, AC5).

403 invalid-timestamp 응답 시 호출 → 동기화 시도 후 재호출 1회 가능.
실패해도 raise 안 함(best-effort). 운영자 알림은 structlog 이벤트로.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

import structlog

log = structlog.get_logger(__name__)


def _which(cmd: str) -> str | None:
    return shutil.which(cmd)


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
        try:
            res = subprocess.run(
                ["w32tm", "/resync"],
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
            ok = res.returncode == 0
            log.info(
                "naver_sa.ntp_resync",
                os="Windows",
                cmd="w32tm /resync",
                returncode=res.returncode,
                ok=ok,
            )
            return ok
        except subprocess.TimeoutExpired:
            log.warning("naver_sa.ntp_resync", os="Windows", reason="timeout")
            return False
        except OSError as exc:
            log.warning("naver_sa.ntp_resync", os="Windows", reason=str(exc))
            return False

    # Linux / macOS / Unix
    if sys_name == "Linux":
        # timedatectl이 가장 흔함. sudo 없이 set-ntp 가능한 환경도 있음(컨테이너 등) → sudo 시도 후 fallback.
        if _which("timedatectl"):
            for cmd in (
                ["sudo", "-n", "timedatectl", "set-ntp", "true"],
                ["timedatectl", "set-ntp", "true"],
            ):
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
                            os="Linux",
                            cmd=" ".join(cmd),
                            returncode=0,
                            ok=True,
                        )
                        return True
                except (subprocess.TimeoutExpired, OSError):
                    continue
        log.warning("naver_sa.ntp_resync", os="Linux", reason="timedatectl unavailable or failed")
        return False

    log.warning("naver_sa.ntp_resync", os=sys_name, reason="unsupported platform")
    return False
