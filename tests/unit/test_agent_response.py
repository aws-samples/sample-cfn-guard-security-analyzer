"""Tests for lambda/_agent_response.py — the shared multi-path parser.

Strands agents emit chat-style output (narrative + ```json``` block).
The parser must walk: dict → json.loads → fenced block → greedy outermost
{} → fallback.
"""
import json

from _agent_response import extract_agent_payload


def test_path_direct_dict_in_result_field():
    """Agent body where 'result' is already a dict (some pre-stringified paths)."""
    body = {'result': {'properties': [{'name': 'X'}], 'resourceType': 'AWS::S3::Bucket'}}
    out = extract_agent_payload(body, discriminator_keys=['properties'])
    assert out == {'properties': [{'name': 'X'}], 'resourceType': 'AWS::S3::Bucket'}


def test_path_direct_json_loads():
    """'result' is a JSON-serialized string with no narrative wrapper."""
    payload = {'properties': [{'name': 'X'}], 'resourceType': 'AWS::S3::Bucket'}
    body = {'result': json.dumps(payload)}
    out = extract_agent_payload(body, discriminator_keys=['properties'])
    assert out == payload


def test_path_fenced_json_block():
    """The canonical Strands shape: narrative followed by ```json ...```."""
    inner = {'properties': [{'name': 'BucketName', 'risk': 'low'}],
             'resourceType': 'AWS::S3::Bucket'}
    narrative = (
        "I performed a quick security scan. Here is the analysis:\n\n"
        "```json\n" + json.dumps(inner) + "\n```\n\n"
        "Let me know if you need anything else."
    )
    body = {'result': narrative}
    out = extract_agent_payload(body, discriminator_keys=['properties'])
    assert out == inner


def test_path_greedy_outermost_object():
    """When fence markers are missing but raw JSON is embedded in prose."""
    inner = {'resources': [{'name': 'AWS::S3::Bucket', 'url': 'x'}]}
    text = "I found these resources: " + json.dumps(inner) + " That's all."
    body = {'output': text}
    out = extract_agent_payload(body, discriminator_keys=['resources'])
    assert out == inner


def test_path_greedy_with_nested_objects():
    """Greedy regex must handle nested objects via the last-brace fallback."""
    inner = {
        'resourceType': 'AWS::S3::Bucket',
        'properties': [{'name': 'X', 'meta': {'a': 1}}],
        'analysisMetadata': {'mode': 'quick', 'depth': {'k': 'v'}},
    }
    text = "Here's the analysis: " + json.dumps(inner)
    body = {'result': text}
    out = extract_agent_payload(body, discriminator_keys=['properties', 'resourceType'])
    assert out == inner


def test_fallback_returned_when_unparseable():
    """Pure prose with no JSON — fallback must be returned verbatim."""
    body = {'result': "I tried but the page returned an error."}
    fb = {'properties': [], 'resourceType': 'Unknown'}
    out = extract_agent_payload(body, discriminator_keys=['properties'], fallback=fb)
    assert out == fb


def test_fallback_when_no_discriminator_match():
    """JSON exists but doesn't contain any discriminator key."""
    body = {'result': '{"unrelated": "value"}'}
    fb = {'__sentinel__': True}
    # Direct json.loads succeeds — we return the parsed dict as-is.
    out = extract_agent_payload(body, discriminator_keys=['properties'], fallback=fb)
    assert out == {'unrelated': 'value'}


def test_fallback_empty_when_not_provided():
    body = {'result': "no JSON here"}
    out = extract_agent_payload(body, discriminator_keys=['properties'])
    assert out == {}


def test_field_priority_result_then_output_then_response():
    """Verify the result/output/response priority order."""
    payload = {'properties': []}
    body = {
        'result': json.dumps(payload),
        'output': '"ignored"',
        'response': '"ignored"',
    }
    assert extract_agent_payload(body) == payload

    body2 = {'output': json.dumps(payload), 'response': '"ignored"'}
    assert extract_agent_payload(body2) == payload

    body3 = {'response': json.dumps(payload)}
    assert extract_agent_payload(body3) == payload
