"""Lambda handler that POSTs progress updates to the FastAPI callback endpoint.

Used by Step Functions to notify the backend (and WebSocket clients) of workflow progress.
Event must contain: analysisId. Optional: step, status, detail.
"""

import json
import os
import urllib.request

ALB_ENDPOINT_URL = os.environ.get("ALB_ENDPOINT_URL", "")


def handler(event, context):
    analysis_id = event["analysisId"]
    step = event.get("step", "unknown")
    status = event.get("status", "IN_PROGRESS")
    detail = event.get("detail", {})

    if not ALB_ENDPOINT_URL:
        print("ALB_ENDPOINT_URL not set, skipping notification")
        return {"notified": False, "reason": "ALB_ENDPOINT_URL not configured"}

    url = f"{ALB_ENDPOINT_URL}/callbacks/progress"
    payload = json.dumps({
        "analysisId": analysis_id,
        "updateData": {
            "step": step,
            "status": status,
            "detail": detail,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            print(f"Progress notification sent: {body}")
            return {"notified": True, "response": body}
    except Exception as e:
        print(f"Failed to send progress notification: {e}")
        return {"notified": False, "error": str(e)}
