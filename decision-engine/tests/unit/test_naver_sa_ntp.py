"""Unit tests — naver_sa.ntp.resync_ntp (Story 1.5).

mock subprocess.run으로 OS 분기 동작 검증.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest
from rank_bidder.naver_sa import ntp


def test_resync_windows_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntp, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")}))
    monkeypatch.setattr(ntp, "_which", lambda _: "C:/Windows/w32tm.exe")
    fake = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake)
    assert ntp.resync_ntp() is True


def test_resync_windows_missing_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntp, "platform", type("P", (), {"system": staticmethod(lambda: "Windows")}))
    monkeypatch.setattr(ntp, "_which", lambda _: None)
    assert ntp.resync_ntp() is False


def test_resync_linux_sudo_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntp, "platform", type("P", (), {"system": staticmethod(lambda: "Linux")}))
    monkeypatch.setattr(
        ntp, "_which", lambda c: "/usr/bin/timedatectl" if c == "timedatectl" else None
    )
    fake_ok = MagicMock(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: fake_ok)
    assert ntp.resync_ntp() is True


def test_resync_linux_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntp, "platform", type("P", (), {"system": staticmethod(lambda: "Linux")}))
    monkeypatch.setattr(
        ntp, "_which", lambda c: "/usr/bin/timedatectl" if c == "timedatectl" else None
    )

    def _raise(*a, **k):
        raise subprocess.TimeoutExpired(cmd=a[0], timeout=k.get("timeout", 10))

    monkeypatch.setattr(subprocess, "run", _raise)
    assert ntp.resync_ntp() is False


def test_resync_unsupported_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ntp, "platform", type("P", (), {"system": staticmethod(lambda: "Plan9")}))
    assert ntp.resync_ntp() is False
