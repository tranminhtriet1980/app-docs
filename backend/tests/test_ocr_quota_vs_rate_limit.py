"""Phân biệt lỗi 429 hết quota (billing) với 429 rate limit tạm thời.

Báo lỗi thực tế 2026-08-17: mọi RateLimitError/429 đều bị coi là "hết quota" (kể cả rate limit
tạm thời do gửi nhiều ảnh liên tiếp), hiện cảnh báo sai "nạp tiền" — reprocess ngay sau đó vẫn
xử lý được bình thường vì quota chưa hề cạn.
"""

import asyncio

import httpx
import pytest
from openai import APIStatusError, RateLimitError

from app.services.ocr_pipeline import (
    _call_with_rate_limit_retry,
    _is_quota_error,
    _is_rate_limit_error,
)


def _api_error(cls, code: str, status: int = 429):
    req = httpx.Request("POST", "https://api.openai.com/v1/x")
    resp = httpx.Response(status, request=req, json={"error": {"message": "x", "type": code, "code": code}})
    return cls(message="x", response=resp, body=resp.json())


def test_insufficient_quota_is_quota_error_not_rate_limit():
    exc = _api_error(RateLimitError, "insufficient_quota")
    assert _is_quota_error(exc) is True
    assert _is_rate_limit_error(exc) is False


def test_rate_limit_exceeded_is_rate_limit_not_quota():
    exc = _api_error(RateLimitError, "rate_limit_exceeded")
    assert _is_quota_error(exc) is False
    assert _is_rate_limit_error(exc) is True


def test_402_status_is_quota_error():
    exc = _api_error(APIStatusError, "some_billing_code", status=402)
    assert _is_quota_error(exc) is True


def test_call_with_rate_limit_retry_succeeds_after_transient_429(monkeypatch):
    monkeypatch.setattr("app.services.ocr_pipeline.asyncio.sleep", _no_sleep)
    attempts = {"n": 0}

    async def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise _api_error(RateLimitError, "rate_limit_exceeded")
        return "ok"

    result = asyncio.run(_call_with_rate_limit_retry(flaky))
    assert result == "ok"
    assert attempts["n"] == 3


def test_call_with_rate_limit_retry_does_not_swallow_quota_error(monkeypatch):
    monkeypatch.setattr("app.services.ocr_pipeline.asyncio.sleep", _no_sleep)

    async def always_quota():
        raise _api_error(RateLimitError, "insufficient_quota")

    with pytest.raises(RateLimitError):
        asyncio.run(_call_with_rate_limit_retry(always_quota))


async def _no_sleep(_seconds):
    return None
