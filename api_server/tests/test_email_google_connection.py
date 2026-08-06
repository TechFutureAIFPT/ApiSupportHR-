from app.api.routes.account import email as email_route
from app.schemas.account import AuthenticatedUser


def test_email_uses_server_side_google_connection(monkeypatch):
    user = AuthenticatedUser(uid="user-1", email="qa@example.test")
    seen = {}

    monkeypatch.setattr(
        email_route.google_drive_service,
        "get_valid_access_token",
        lambda current_user: "server-side-token",
    )

    def fake_send_bulk(*, google_access_token, emails):
        seen["token"] = google_access_token
        seen["emails"] = emails
        return [{"to": emails[0]["to"], "status": "sent", "id": "msg-1"}]

    monkeypatch.setattr(email_route, "send_bulk", fake_send_bulk)

    response = email_route.send_emails(
        email_route.EmailSendRequest(
            emails=[email_route.EmailItem(to="candidate@example.test", subject="Interview", body="Hello")]
        ),
        x_google_access_token=None,
        current_user=user,
    )

    assert seen["token"] == "server-side-token"
    assert response.sent == 1
    assert response.failed == 0


def test_google_oauth_requests_gmail_send_scope():
    assert "https://www.googleapis.com/auth/gmail.send" in email_route.google_drive_service.GOOGLE_DRIVE_SCOPES
