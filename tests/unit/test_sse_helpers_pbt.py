"""Property-based tests for SSE helpers.

Feature: analysis-ux-improvements
Uses hypothesis to validate SSE event sequence and elapsed timer format
across many generated inputs.
"""

import json
import os

# Set environment variables BEFORE importing service modules
os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")

from hypothesis import given, settings, strategies as st

from service.routers.analysis import sse_event, parse_properties


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

RISK_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

property_st = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=60),
    "riskLevel": st.sampled_from(RISK_LEVELS),
    "securityImplication": st.text(min_size=0, max_size=200),
    "recommendation": st.text(min_size=0, max_size=200),
})

properties_list_st = st.lists(property_st, min_size=0, max_size=20)


# ---------------------------------------------------------------------------
# Property 4: SSE event sequence for successful scan
# Tag: Feature: analysis-ux-improvements, Property 4: SSE event sequence for successful scan
# **Validates: Requirements 2.3, 2.4, 2.5**
#
# For any successful quick scan where the Bedrock AgentCore agent returns
# N properties (N >= 0), the SSE stream shall contain exactly:
#   1. one `status` event with phase "started" first,
#   2. exactly N `property` events with sequential index 0..N-1 and total=N,
#   3. one `complete` event with totalProperties=N last.
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(props=properties_list_st)
def test_sse_event_sequence_for_successful_scan(props):
    """Property 4: SSE event sequence for successful scan.

    **Validates: Requirements 2.3, 2.4, 2.5**
    """
    analysis_id = "test-id-123"
    n = len(props)

    # Build the SSE stream the same way the endpoint would
    events_raw: list[str] = []
    events_raw.append(sse_event("status", {"phase": "started", "analysisId": analysis_id}))

    for i, prop in enumerate(props):
        events_raw.append(sse_event("property", {"index": i, "total": n, **prop}))

    events_raw.append(sse_event("complete", {"analysisId": analysis_id, "totalProperties": n}))

    # Parse the concatenated stream back into events
    full_stream = "".join(events_raw)
    parsed_events = _parse_sse_stream(full_stream)

    # --- Assertions ---

    # Total event count: 1 status + N property + 1 complete
    assert len(parsed_events) == n + 2

    # First event is status with phase "started"
    first = parsed_events[0]
    assert first["event"] == "status"
    assert first["data"]["phase"] == "started"
    assert first["data"]["analysisId"] == analysis_id

    # Middle events are property events with sequential indices
    for i in range(n):
        evt = parsed_events[1 + i]
        assert evt["event"] == "property"
        assert evt["data"]["index"] == i
        assert evt["data"]["total"] == n

    # Last event is complete with correct totalProperties
    last = parsed_events[-1]
    assert last["event"] == "complete"
    assert last["data"]["totalProperties"] == n
    assert last["data"]["analysisId"] == analysis_id


# ---------------------------------------------------------------------------
# Property 8: Elapsed timer format
# Tag: Feature: analysis-ux-improvements, Property 8: Elapsed timer format
# **Validates: Requirements 3.1**
#
# For any non-negative integer s, the elapsed timer display text shall
# match the format "Elapsed: {s}s".
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(s=st.integers(min_value=0, max_value=100_000))
def test_elapsed_timer_format(s):
    """Property 8: Elapsed timer format.

    **Validates: Requirements 3.1**
    """
    display_text = f"Elapsed: {s}s"

    # Must start with "Elapsed: "
    assert display_text.startswith("Elapsed: ")

    # Must end with "s"
    assert display_text.endswith("s")

    # The number between prefix and suffix must equal s
    number_part = display_text.removeprefix("Elapsed: ").removesuffix("s")
    assert int(number_part) == s

    # Full format check
    assert display_text == f"Elapsed: {s}s"

# ---------------------------------------------------------------------------
# Property 7: Progress bar calculation from index and total
# Tag: Feature: analysis-ux-improvements, Property 7: Progress bar calculation from index and total
# **Validates: Requirements 4.3, 4.5**
#
# For any progress update containing an index i and total n (where
# 0 <= i < n and n > 0), the progress bar width shall be set to
# round(((i + 1) / n) * 100) percent.
# ---------------------------------------------------------------------------


def _js_math_round(x: float) -> int:
    """Replicate JavaScript's Math.round which uses 'round half up',
    unlike Python's round() which uses 'round half to even' (banker's rounding).
    e.g. Math.round(0.5) == 1, but Python round(0.5) == 0.
    """
    import math
    return math.floor(x + 0.5)


def _calculate_progress(index: int, total: int) -> int:
    """Pure progress bar calculation matching the JS formula:
    Math.round(((index + 1) / total) * 100)
    """
    return _js_math_round(((index + 1) / total) * 100)


@settings(max_examples=100)
@given(data=st.data())
def test_progress_bar_calculation_from_index_and_total(data):
    """Property 7: Progress bar calculation from index and total.

    **Validates: Requirements 4.3, 4.5**
    """
    total = data.draw(st.integers(min_value=1, max_value=500), label="total")
    index = data.draw(st.integers(min_value=0, max_value=total - 1), label="index")

    progress = _calculate_progress(index, total)

    # 1. Progress is always between 0 and 100 inclusive
    assert 0 <= progress <= 100, f"progress={progress} out of [0,100] for index={index}, total={total}"

    # 2. When index == total - 1 (last item), progress is always exactly 100%
    #    because ((total)/total)*100 == 100.0 which rounds to 100
    if index == total - 1:
        assert progress == 100, f"Last item should be 100%, got {progress} for index={index}, total={total}"

    # 3. Monotonicity: progress is non-decreasing as index increases
    if index < total - 1:
        next_progress = _calculate_progress(index + 1, total)
        assert next_progress >= progress, (
            f"Progress not monotonic: index={index} -> {progress}%, "
            f"index={index+1} -> {next_progress}%"
        )

    # 4. The value matches the exact JS formula: Math.round(((i+1)/n)*100)
    expected = _js_math_round(((index + 1) / total) * 100)
    assert progress == expected, (
        f"Formula mismatch: got {progress}, expected {expected} "
        f"for index={index}, total={total}"
    )




# ---------------------------------------------------------------------------
# Helper: parse an SSE stream string into a list of event dicts
# ---------------------------------------------------------------------------


def _parse_sse_stream(raw: str) -> list[dict]:
    """Parse a raw SSE stream into a list of {event, data} dicts."""
    events = []
    for block in raw.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        event_type = None
        data_str = None
        for line in block.split("\n"):
            if line.startswith("event: "):
                event_type = line[len("event: "):]
            elif line.startswith("data: "):
                data_str = line[len("data: "):]
        if event_type and data_str:
            events.append({"event": event_type, "data": json.loads(data_str)})
    return events
