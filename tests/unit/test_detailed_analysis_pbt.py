"""Property-based tests for the detailed analysis fix.

Feature: detailed-analysis-fix
Uses hypothesis to validate WebSocket message routing, resilience,
results display, progress calculation, and notification payload completeness.

Since the frontend is vanilla JS (no Node test runner), these tests implement
equivalent Python logic that mirrors the JS functions.
"""

import json
import math
import os

# Set environment variables BEFORE importing service modules
os.environ.setdefault("ANALYSIS_TABLE_NAME", "test-analysis-table")
os.environ.setdefault("CONNECTION_TABLE_NAME", "test-connection-table")
os.environ.setdefault("REPORTS_BUCKET_NAME", "test-reports-bucket")
os.environ.setdefault("STATE_MACHINE_ARN", "arn:aws:states:us-east-1:123456789012:stateMachine:test-sm")

import pytest
from hypothesis import given, settings, strategies as st
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers: mirror JS logic in Python
# ---------------------------------------------------------------------------

# Known step values from handleWebSocketMessage() in app.js
KNOWN_STEPS = ["crawl", "property_analyzed", "analyze", "complete"]

# Known type/action values from handleWebSocketMessage() in app.js
KNOWN_TYPE_ACTIONS = ["progress", "property_complete", "analysis_complete", "error"]

# Step → handler name mapping (mirrors the JS switch statement)
STEP_HANDLER_MAP = {
    "crawl": "handleStepCrawlComplete",
    "property_analyzed": "handleStepPropertyAnalyzed",
    "analyze": "handleStepAnalyzeComplete",
    "complete": "handleStepWorkflowComplete",
}

# Type/action → handler name mapping
TYPE_ACTION_HANDLER_MAP = {
    "progress": "handleProgressUpdate",
    "property_complete": "handlePropertyComplete",
    "analysis_complete": "handleAnalysisComplete",
    "error": "handleError",
}

RISK_LEVELS = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]


def _js_math_round(x: float) -> int:
    """Replicate JavaScript's Math.round which uses 'round half up',
    unlike Python's round() which uses 'round half to even' (banker's rounding).
    """
    return math.floor(x + 0.5)


def handle_websocket_message(data, handlers):
    """Python equivalent of handleWebSocketMessage() from app.js.

    Args:
        data: The message dict.
        handlers: A dict mapping handler names to callable mocks.

    Returns:
        The handler name that was called, or None.
    """
    # Primary routing: type/action
    message_type = data.get("type") or data.get("action")
    if message_type:
        handler_name = TYPE_ACTION_HANDLER_MAP.get(message_type)
        if handler_name:
            handlers[handler_name](data)
            return handler_name

    # Secondary routing: step
    step = data.get("step")
    if step:
        handler_name = STEP_HANDLER_MAP.get(step)
        if handler_name:
            handlers[handler_name](data)
            return handler_name
        # Unknown step — log but don't crash
        return None

    # Unrecognized message — log but don't crash
    return None


def calculate_property_progress(index: int, total: int) -> int:
    """Python equivalent of the progress formula from handleStepPropertyAnalyzed().

    Formula: Math.round(20 + ((index + 1) / total) * 70)
    """
    return _js_math_round(20 + ((index + 1) / total) * 70)


def display_results_logic(properties):
    """Python equivalent of the core displayResults() logic.

    Takes a list of property dicts and returns a list of rendered card dicts,
    each containing the property name and risk_level.
    """
    cards = []
    for prop in properties:
        # Mirror createPropertyCard() — extracts name and risk_level
        card = {
            "name": prop.get("name", "Unknown Property"),
            "risk_level": prop.get("risk_level", "MEDIUM"),
        }
        cards.append(card)
    return cards


def build_notification_payload(property_dict, result_dict, index, total, analysis_id="test-id"):
    """Build the notification payload as the CDK Step Functions template would.

    Mirrors the NotifyPropertyAnalyzed LambdaInvoke payload from stepfunctions_stack.py.
    """
    return {
        "analysisId": analysis_id,
        "step": "property_analyzed",
        "status": "COMPLETED",
        "detail": {
            "property": property_dict,
            "result": result_dict,
            "index": index,
            "total": total,
        },
    }


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

step_st = st.sampled_from(KNOWN_STEPS)

# Strategy for arbitrary dicts that do NOT have recognized type/action/step fields
# to test unrecognized message resilience
arbitrary_key_st = st.text(min_size=0, max_size=20).filter(
    lambda k: k not in ("type", "action", "step")
)
arbitrary_value_st = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(min_value=-1000, max_value=1000),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(min_size=0, max_size=50),
)
arbitrary_dict_st = st.dictionaries(
    keys=arbitrary_key_st,
    values=arbitrary_value_st,
    min_size=0,
    max_size=10,
)

property_st = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=60),
    "risk_level": st.sampled_from(RISK_LEVELS),
    "description": st.text(min_size=0, max_size=200),
    "security_impact": st.text(min_size=0, max_size=200),
    "recommendation": st.text(min_size=0, max_size=200),
})

properties_list_st = st.lists(property_st, min_size=1, max_size=20)

result_st = st.fixed_dictionaries({
    "name": st.text(min_size=1, max_size=60),
    "risk_level": st.sampled_from(RISK_LEVELS),
    "analysis": st.text(min_size=0, max_size=200),
})


# ---------------------------------------------------------------------------
# Property 1: Step-based message routing correctness
# Tag: Feature: detailed-analysis-fix, Property 1: Step-based message routing correctness
# **Validates: Requirements 1.1**
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(step=step_st)
def test_step_based_message_routing_correctness(step):
    """Property 1: Step-based message routing correctness.

    For any WebSocket message containing a step field with a value in
    {"crawl", "property_analyzed", "analyze", "complete"}, the
    handleWebSocketMessage() function shall invoke the corresponding
    step handler and no other handler.

    **Validates: Requirements 1.1**
    """
    # Create mock handlers
    handlers = {name: MagicMock(name=name) for name in
                list(STEP_HANDLER_MAP.values()) + list(TYPE_ACTION_HANDLER_MAP.values())}

    data = {"step": step, "status": "COMPLETED", "detail": {}}
    called = handle_websocket_message(data, handlers)

    expected_handler = STEP_HANDLER_MAP[step]

    # The correct handler was called
    assert called == expected_handler, (
        f"For step='{step}', expected handler '{expected_handler}' but got '{called}'"
    )

    # The correct handler was called exactly once
    handlers[expected_handler].assert_called_once_with(data)

    # No other handler was called
    for name, mock in handlers.items():
        if name != expected_handler:
            mock.assert_not_called(), (
                f"Handler '{name}' should not have been called for step='{step}'"
            )


# ---------------------------------------------------------------------------
# Property 2: Unrecognized message resilience
# Tag: Feature: detailed-analysis-fix, Property 2: Unrecognized message resilience
# **Validates: Requirements 1.5**
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=arbitrary_dict_st)
def test_unrecognized_message_resilience(data):
    """Property 2: Unrecognized message resilience.

    For any arbitrary JSON object that does not contain a recognized type,
    action, or step field, the handleWebSocketMessage() function shall
    return without throwing an exception.

    **Validates: Requirements 1.5**
    """
    handlers = {name: MagicMock(name=name) for name in
                list(STEP_HANDLER_MAP.values()) + list(TYPE_ACTION_HANDLER_MAP.values())}

    # Should not raise any exception
    result = handle_websocket_message(data, handlers)

    # No handler should have been called
    for name, mock in handlers.items():
        mock.assert_not_called(), (
            f"Handler '{name}' should not have been called for unrecognized message"
        )

    # Result should be None (no handler matched)
    assert result is None


# ---------------------------------------------------------------------------
# Property 3: Detailed results display completeness
# Tag: Feature: detailed-analysis-fix, Property 3: Detailed results display completeness
# **Validates: Requirements 2.2**
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(properties=properties_list_st)
def test_detailed_results_display_completeness(properties):
    """Property 3: Detailed results display completeness.

    For any valid results object containing an array of property objects,
    the displayResults() function shall create exactly one property card
    per property, and each card shall contain the property's name and
    risk level.

    **Validates: Requirements 2.2**
    """
    cards = display_results_logic(properties)

    # Output count matches input count
    assert len(cards) == len(properties), (
        f"Expected {len(properties)} cards, got {len(cards)}"
    )

    # Each card contains the property's name and risk level
    for i, (card, prop) in enumerate(zip(cards, properties)):
        assert card["name"] == prop["name"], (
            f"Card {i} name mismatch: expected '{prop['name']}', got '{card['name']}'"
        )
        assert card["risk_level"] == prop["risk_level"], (
            f"Card {i} risk_level mismatch: expected '{prop['risk_level']}', got '{card['risk_level']}'"
        )


# ---------------------------------------------------------------------------
# Property 4: Per-property progress calculation
# Tag: Feature: detailed-analysis-fix, Property 4: Per-property progress calculation
# **Validates: Requirements 4.3**
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(data=st.data())
def test_per_property_progress_calculation(data):
    """Property 4: Per-property progress calculation.

    For any property index i (0-based) and total property count n
    (where 0 <= i < n and n > 0), the progress percentage shall equal
    Math.round(20 + ((i + 1) / n) * 70) and fall within [20, 90].

    **Validates: Requirements 4.3**
    """
    total = data.draw(st.integers(min_value=1, max_value=500), label="total")
    index = data.draw(st.integers(min_value=0, max_value=total - 1), label="index")

    progress = calculate_property_progress(index, total)

    # 1. Progress matches the exact formula
    expected = _js_math_round(20 + ((index + 1) / total) * 70)
    assert progress == expected, (
        f"Formula mismatch: got {progress}, expected {expected} "
        f"for index={index}, total={total}"
    )

    # 2. Progress is within [20, 90]
    assert 20 <= progress <= 90, (
        f"Progress {progress} out of [20, 90] for index={index}, total={total}"
    )

    # 3. Monotonicity: progress is non-decreasing as index increases
    if index < total - 1:
        next_progress = calculate_property_progress(index + 1, total)
        assert next_progress >= progress, (
            f"Progress not monotonic: index={index} -> {progress}%, "
            f"index={index + 1} -> {next_progress}%"
        )


# ---------------------------------------------------------------------------
# Property 5: Per-property notification payload completeness
# Tag: Feature: detailed-analysis-fix, Property 5: Per-property notification payload completeness
# **Validates: Requirements 5.1**
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    prop=property_st,
    result=result_st,
    data=st.data(),
)
def test_notification_payload_completeness(prop, result, data):
    """Property 5: Per-property notification payload completeness.

    For any property analyzed within the Step Functions Map state, the
    progress notification payload shall contain the fields step (equal to
    "property_analyzed"), detail.property, detail.result, detail.index,
    and detail.total.

    **Validates: Requirements 5.1**
    """
    total = data.draw(st.integers(min_value=1, max_value=100), label="total")
    index = data.draw(st.integers(min_value=0, max_value=total - 1), label="index")

    payload = build_notification_payload(prop, result, index, total)

    # step must be "property_analyzed"
    assert payload["step"] == "property_analyzed", (
        f"step should be 'property_analyzed', got '{payload['step']}'"
    )

    # detail must contain all required fields
    detail = payload.get("detail")
    assert detail is not None, "Payload must contain 'detail'"
    assert "property" in detail, "detail must contain 'property'"
    assert "result" in detail, "detail must contain 'result'"
    assert "index" in detail, "detail must contain 'index'"
    assert "total" in detail, "detail must contain 'total'"

    # Verify the values match what was passed in
    assert detail["property"] == prop
    assert detail["result"] == result
    assert detail["index"] == index
    assert detail["total"] == total

    # analysisId must be present
    assert "analysisId" in payload, "Payload must contain 'analysisId'"
