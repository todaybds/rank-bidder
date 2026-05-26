"""Pytest conftest — Story 1.1 stub.

Story 1.4에서 SERP HTML fixture + 모의 SSM client 등 fixture 추가 예정.
"""

import sys
from pathlib import Path

# Allow `from measurer import handler` from tests (mirrors Lambda runtime PYTHONPATH).
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
