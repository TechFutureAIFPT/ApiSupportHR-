from __future__ import annotations

import base64
import json
from email.mime.text import MIMEText
from typing import Any
from urllib import error, request as urllib_request

GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailSendError(Exception):
    pass


def _build_raw_message(to: str, subject: str, body: str, sender: str = "me") -> str:
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = sender
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw


def send_email(
    google_access_token: str,
    to: str,
    subject: str,
    body: str,
) -> dict[str, Any]:
    raw = _build_raw_message(to=to, subject=subject, body=body)
    payload = json.dumps({"raw": raw}).encode("utf-8")

    req = urllib_request.Request(
        GMAIL_SEND_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {google_access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib_request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise GmailSendError(f"Gmail API error {exc.code}: {detail}") from exc


def send_bulk(
    google_access_token: str,
    emails: list[dict[str, str]],
) -> list[dict[str, Any]]:
    results = []
    for item in emails:
        try:
            result = send_email(
                google_access_token=google_access_token,
                to=item["to"],
                subject=item.get("subject", "Thông báo tuyển dụng"),
                body=item["body"],
            )
            results.append({"to": item["to"], "status": "sent", "id": result.get("id")})
        except GmailSendError as exc:
            results.append({"to": item["to"], "status": "failed", "error": str(exc)})
    return results
