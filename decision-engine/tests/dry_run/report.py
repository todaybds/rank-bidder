"""Story 1.3 dry-run 결과 → ``ops/naver-semantics-dryrun-result.md`` 보고서 생성기.

실행:
    uv run --package decision-engine python -m rank_bidder.tests.dry_run.report

또는 직접:
    uv run python decision-engine/tests/dry_run/report.py
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "results"
OUTPUT_PATH = Path(__file__).resolve().parents[3] / "ops" / "naver-semantics-dryrun-result.md"


def main() -> int:
    if not RESULTS_DIR.exists():
        print(f"❌ {RESULTS_DIR} 없음 — 먼저 `uv run pytest -m naver_live -s` 실행.")
        return 1

    sections: list[str] = ["# Naver SA Semantics Dry-Run — 측정 결과\n"]

    put_get_records = _load_jsonl_glob("naver-put-get-*.jsonl")
    if put_get_records:
        sections.append(_section_put_get_sequence(put_get_records))
    else:
        sections.append("## PUT→GET 시퀀스\n\n(데이터 없음)\n")

    rate_records = _load_jsonl_glob("naver-rate-limit-*.jsonl")
    if rate_records:
        sections.append(_section_rate_limit(rate_records))

    probe_403 = _load_jsonl_glob("naver-403-probe-*.jsonl")
    if probe_403:
        sections.append(_section_403_probe(probe_403))

    fsync_files = sorted(RESULTS_DIR.glob("sqlite-fsync-*.json"))
    if fsync_files:
        fsync_data = json.loads(fsync_files[-1].read_text(encoding="utf-8"))
        sections.append(_section_fsync(fsync_data))

    sections.append(_section_d15_calibrate_template())

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text("\n".join(sections), encoding="utf-8")
    print(f"✅ 보고서 작성: {OUTPUT_PATH}")
    return 0


def _load_jsonl_glob(pattern: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(RESULTS_DIR.glob(pattern)):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _section_put_get_sequence(records: list[dict[str, Any]]) -> str:
    lines = ["## PUT→GET 시점별 bidAmt 변화 (AC2+AC3)\n"]

    by_seq: dict[int, list[dict[str, Any]]] = {}
    for r in records:
        seq = r.get("seq")
        if seq is not None:
            by_seq.setdefault(seq, []).append(r)

    for seq, rs in sorted(by_seq.items()):
        put = next((r for r in rs if r["step"] == "put"), None)
        if put is None:
            continue
        lines.append(f"\n### Sequence {seq} — target_bid = {put['target_bid']}원\n")
        lines.append("| 시점 | actual bidAmt | match | HTTP | latency_ms | elapsed_ms |")
        lines.append("|---|---|---|---|---|---|")
        lines.append(f"| PUT | — | — | {put['status']} | {put['latency_ms']} | 0 |")
        for r in rs:
            if r["step"].startswith("get_"):
                actual = r.get("actual_bid", "—")
                match = "✓" if r.get("match") else "✗" if r.get("match") is False else "?"
                lines.append(
                    f"| {r['step']} | {actual} | {match} | {r['status']} | "
                    f"{r['latency_ms']} | {r['elapsed_since_put_ms']} |"
                )

    # latency 분포 (모든 GET 합산).
    get_latencies = [
        r["latency_ms"]
        for r in records
        if r.get("step", "").startswith("get_") and r.get("status") == 200
    ]
    if get_latencies:
        lines.append("\n### GET latency 분포 (200 OK only)\n")
        lines.append(
            f"- n = {len(get_latencies)}, p50 = {round(statistics.median(get_latencies), 1)}ms, "
            f"p90 ≈ {round(_p(get_latencies, 0.9), 1)}ms, max = {round(max(get_latencies), 1)}ms"
        )

    # status 분포.
    statuses = Counter(r.get("status") for r in records if "status" in r)
    if statuses:
        lines.append("\n### HTTP status 분포\n")
        for status, count in sorted(statuses.items()):
            lines.append(f"- {status}: {count}회")

    return "\n".join(lines)


def _section_rate_limit(records: list[dict[str, Any]]) -> str:
    lines = ["\n## Rate Limit Probe — 10초 동안 20회 GET (AC3)\n"]
    statuses = Counter(r["status"] for r in records)
    error_codes = Counter(r.get("error_code") for r in records if r.get("error_code"))
    latencies = [r["latency_ms"] for r in records]
    lines.append(f"- 총 {len(records)}회, status 분포: {dict(statuses)}")
    if error_codes:
        lines.append(f"- error code 분포: {dict(error_codes)}")
    lines.append(
        f"- latency: p50 = {round(statistics.median(latencies), 1)}ms, "
        f"max = {round(max(latencies), 1)}ms"
    )
    if statuses.get(429, 0) > 0 or any(c == 1016 for c in error_codes):
        lines.append("\n⚠️ Rate limit 발생 — Story 1.5 토큰버킷 임계값 재산정 필요.")
    else:
        lines.append("\n✅ 2 RPS는 안전. 토큰버킷 5-8 RPS 설정 가능 (Story 1.5).")
    return "\n".join(lines)


def _section_403_probe(records: list[dict[str, Any]]) -> str:
    lines = ["\n## 403 Invalid Timestamp Probe (AC1)\n"]
    for r in records:
        lines.append(f"- step={r['step']}, status={r['status']}, latency={r['latency_ms']}ms")
        if r.get("body"):
            lines.append(f"  - body: `{json.dumps(r['body'], ensure_ascii=False)}`")
    return "\n".join(lines)


def _section_fsync(data: dict[str, Any]) -> str:
    p99_ratio_pct = round(data["p99_ms"] * 100 / 60_000 * 100, 2)  # 100 PUT/min 기준
    return (
        f"\n## SQLite synchronous=FULL fsync latency (AC4)\n\n"
        f"- 측정 환경: Python {data['python_version']}, SQLite {data['sqlite_version']}, "
        f"{data['platform']}\n"
        f"- N = {data['n_iterations']} write transactions × INSERT 100 bytes\n"
        f"- **p50 = {data['p50_ms']}ms / p90 = {data['p90_ms']}ms / "
        f"p99 = {data['p99_ms']}ms / max = {data['max_ms']}ms**\n"
        f"- Architecture 가정 (~5ms × 100 PUT/min ≈ 9%) 검증:\n"
        f"  - p50 {data['p50_ms']}ms × 100/min = {round(data['p50_ms'] * 100, 1)}ms/min "
        f"= {round(data['p50_ms'] * 100 / 600, 2)}% (5분 사이클 기준)\n"
        f"  - p99 worst-case ~{p99_ratio_pct}% (참고용 — 실제 PUT은 사이클당 1-N회로 한정)\n"
    )


def _section_d15_calibrate_template() -> str:
    return (
        "\n## D15 룰 변경 권고 (AC5+AC6 — 운영자 검토 후 architecture.md 수정)\n\n"
        "### D15 (c) Write-ahead PUT + reconcile-on-PUT_SENT-only\n"
        "- [ ] PUT 응답이 즉시 반영되는가? (위 GET_0s 결과 확인)\n"
        "- [ ] 그렇다면 reconcile 룰 단순화 가능 (PUT 응답 200만 보고 COMMITTED 전이)\n"
        "- [ ] 아니라면 현 룰 (PUT_SENT 상태 행만 다음 사이클 시작 시 GET reconcile) 유지\n\n"
        "### D15 (i) PUT response semantics — `put_sent_at < now - 3분 → APPLIED`\n"
        "- [ ] 3분 임계가 적절한가? GET 결과의 `match` 컬럼이 어느 시점부터 `✓` 시작하는지 확인\n"
        "- [ ] 더 빠르면 (예: 1분 내) → 임계 단축\n"
        "- [ ] 더 늦으면 (5분 후도 mismatch) → 임계 연장 또는 별도 reconcile 사이클\n\n"
        "### D15 (j) SQLite durability\n"
        "- [ ] p50 fsync latency 실측이 가정 ~5ms와 일치하는가?\n"
        "- [ ] 큰 차이가 있다면 architecture.md D4·D15(j) 의 9% 비용 계산 갱신\n"
        "- [ ] 1000회 중 max latency > 100ms 발생 빈도 확인 — 큰 spike는 사이클 overlap 위험\n\n"
        "### 변경 적용 후\n"
        "- [ ] architecture.md 수정 + Change Log 기록\n"
        "- [ ] Story 1.3 Completion Notes에 변경 요약 박제\n"
        "- [ ] Story 1.5 (SA API 풀세트 client) 시작 가능 — 본 보고서가 source of truth\n"
    )


def _p(values: list[float], q: float) -> float:
    sorted_vals = sorted(values)
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * q
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


if __name__ == "__main__":
    raise SystemExit(main())
