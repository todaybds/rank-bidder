"""Naver SA API client.

- Story 1.3: ``auth`` (HMAC) + ``dry_run_client`` (measurement spike, deprecated)
- Story 1.5: production client — ``bid.put_bid`` / ``estimate.average_position_bid``
"""

from rank_bidder.naver_sa.auth import build_headers, make_signature, now_timestamp_ms
from rank_bidder.naver_sa.bid import put_bid
from rank_bidder.naver_sa.estimate import average_position_bid
from rank_bidder.naver_sa.exceptions import (
    NaverAuthError,
    NaverInvalidRequest,
    NaverKeywordDeleted,
    NaverSAError,
    NaverSANtpDrift,
    NaverSAUnavailable,
)

__all__ = [
    "average_position_bid",
    "build_headers",
    "make_signature",
    "now_timestamp_ms",
    "put_bid",
    "NaverAuthError",
    "NaverInvalidRequest",
    "NaverKeywordDeleted",
    "NaverSAError",
    "NaverSANtpDrift",
    "NaverSAUnavailable",
]
