"""Shared parser for AgentCore agent responses.

Strands agents emit chat-style output: explanatory prose followed by a
fenced ```json``` block carrying the structured payload. The default
`json.loads(result_text)` path fails on this shape, so workers need a
multi-path extractor. This module is the canonical version — it lives
in `lambda/` (not `agents/`) because the lambdas are the consumers
that need to parse what the agents emit.

Usage:
    from _agent_response import extract_agent_payload
    response_body = bedrock_agentcore.invoke_agent_runtime(...)
    payload = extract_agent_payload(response_body)
"""
import json
import re
from typing import Any, Dict, List, Optional


_FENCED_JSON_RE = re.compile(r'```json\s*(\{[\s\S]*?\})\s*```')


def _select_result_text(response_body: Any) -> Any:
    """Pick the field that carries the agent's chat output.

    Order matches `quick_scan_worker.py` (Phase 7): result, output,
    response, then fallback to stringifying the whole body. If the
    selected field is itself a dict, return it as-is so the caller
    can use it directly.
    """
    if isinstance(response_body, dict):
        for key in ('result', 'output', 'response'):
            if key in response_body:
                return response_body[key]
        return json.dumps(response_body)
    return response_body


def _greedy_object_match(text: str, discriminator_keys: List[str]) -> Optional[Dict[str, Any]]:
    """Find the outermost JSON object that contains one of the
    discriminator keys. Used as a final fallback when the agent's
    fenced block is malformed but valid JSON exists in the text.
    """
    for key in discriminator_keys:
        # Match a {...} containing "<key>": somewhere within. The
        # `[\s\S]*?` is non-greedy on the inside so we don't run past
        # the matching close brace, but we also try a greedy second
        # pass below for nested structures.
        pattern = re.compile(
            r'\{[\s\S]*?"' + re.escape(key) + r'"\s*:[\s\S]*?\}'
        )
        m = pattern.search(text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        # Greedy pass: outermost { ... } anchored on first { and last }
        # that contains the key. This catches nested objects like
        # { "properties": [...], "metadata": {...} }.
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            candidate = text[first_brace:last_brace + 1]
            if f'"{key}"' in candidate:
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    pass
    return None


def extract_agent_payload(
    response_body: Any,
    discriminator_keys: Optional[List[str]] = None,
    fallback: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Extract structured JSON from an AgentCore response.

    Path order (mirrors `quick_scan_worker.py` Phase 7):
      1. Select result/output/response field (or stringify whole body).
      2. If chosen text is already a dict, return it.
      3. Try `json.loads` directly.
      4. Try a fenced ```json ... ``` block.
      5. Greedy outermost-{} match, gated by `discriminator_keys`.
      6. Return `fallback` (or empty dict) when nothing parses.

    Args:
        response_body: The decoded JSON body from
            `invoke_agent_runtime['response'].read()`.
        discriminator_keys: Keys that identify the JSON payload of
            interest, e.g. ['properties', 'resourceType'] for security
            analysis, ['resources'] for discover, ['guardRule', 'ruleName']
            for guard-rules. Used by the greedy fallback.
        fallback: Dict to return when all parse paths fail. Each
            worker shapes its own "couldn't parse" response.
    """
    if discriminator_keys is None:
        discriminator_keys = []
    if fallback is None:
        fallback = {}

    # Path 1: pick the right field
    result_text = _select_result_text(response_body)

    # Path 2: already a dict
    if isinstance(result_text, dict):
        return result_text

    if not isinstance(result_text, str):
        return fallback

    # Path 3: direct json.loads
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    # Path 4: fenced ```json``` block
    fence_match = _FENCED_JSON_RE.search(result_text)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

    # Path 5: greedy outermost {} containing a discriminator key
    if discriminator_keys:
        greedy = _greedy_object_match(result_text, discriminator_keys)
        if greedy is not None:
            return greedy

    # Path 6: caller-supplied fallback
    return fallback
