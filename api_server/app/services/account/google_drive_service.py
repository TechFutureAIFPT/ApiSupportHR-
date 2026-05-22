from __future__ import annotations

import json
import mimetypes
import secrets
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from urllib.parse import urlparse

from app.core.config import get_settings
from app.repositories.firestore import account_repository as repo
from app.schemas.account import AuthenticatedUser
from app.services.account import uploaded_file_service
from app.services.account.shared import serialize
from app.services.file_extraction_service import extract_text_from_upload


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_DRIVE_STATE_TTL_MS = 10 * 60 * 1000
GOOGLE_TOKEN_REFRESH_SKEW_MS = 60 * 1000
GOOGLE_DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_DRIVE_SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/drive.readonly",
]
GOOGLE_WORKSPACE_EXPORTS = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.presentation": ("application/pdf", ".pdf"),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
    "application/vnd.google-apps.spreadsheet": ("text/csv", ".csv"),
}


class GoogleDriveError(Exception):
    pass


class GoogleDriveConfigError(GoogleDriveError):
    pass


class GoogleDriveValidationError(GoogleDriveError):
    pass


class GoogleDriveProviderError(GoogleDriveError):
    pass


def _require_oauth_config() -> tuple[str, str]:
    settings = get_settings()
    client_id = settings.google_oauth_client_id.strip()
    client_secret = settings.google_oauth_client_secret.strip()
    if not client_id or not client_secret:
        raise GoogleDriveConfigError(
            "Thiếu GOOGLE_OAUTH_CLIENT_ID hoặc GOOGLE_OAUTH_CLIENT_SECRET trong backend."
        )
    return client_id, client_secret


def _normalize_origin(value: str) -> str:
    parsed = urlparse(value.strip())
    if not parsed.scheme or not parsed.netloc:
        raise GoogleDriveValidationError(f"Redirect URI không hợp lệ: {value}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _resolve_redirect_uri(redirect_uri: str | None) -> str:
    settings = get_settings()
    candidate = (redirect_uri or settings.google_oauth_redirect_uri).strip()
    if not candidate:
        raise GoogleDriveValidationError(
            "Thiếu redirect URI. Hãy truyền redirectUri từ frontend hoặc set GOOGLE_OAUTH_REDIRECT_URI."
        )

    origin = _normalize_origin(candidate)
    allowed_origins = {_normalize_origin(item) for item in settings.google_drive_allowed_origins if item.strip()}
    if origin not in allowed_origins:
        raise GoogleDriveValidationError(
            f"Origin {origin} chưa được cho phép. Hãy thêm vào GOOGLE_DRIVE_ALLOWED_ORIGINS."
        )
    return candidate


def _parse_json_response(raw: bytes) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception as exc:  # pragma: no cover - defensive decode path
        raise GoogleDriveProviderError("Google trả về dữ liệu không đọc được.") from exc


def _request_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    form_data: dict[str, Any] | None = None,
    timeout: int = 30,
) -> Any:
    body = None
    request_headers = headers.copy() if headers else {}
    if form_data is not None:
        body = parse.urlencode(form_data).encode("utf-8")
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"

    req = request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return _parse_json_response(response.read())
    except error.HTTPError as exc:
        payload = _parse_json_response(exc.read())
        detail = payload.get("error_description") or payload.get("error") or payload
        raise GoogleDriveProviderError(f"Google API lỗi: {detail}") from exc
    except error.URLError as exc:
        raise GoogleDriveProviderError("Không thể kết nối tới Google API.") from exc


def _request_bytes(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[bytes, dict[str, str]]:
    req = request.Request(url, method=method, headers=headers or {})
    try:
        with request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            metadata = {key: value for key, value in response.headers.items()}
            return payload, metadata
    except error.HTTPError as exc:
        raw = exc.read()
        detail = ""
        try:
            parsed = _parse_json_response(raw)
            detail = parsed.get("error_description") or parsed.get("error") or str(parsed)
        except Exception:
            detail = raw.decode("utf-8", errors="ignore")
        raise GoogleDriveProviderError(f"Không thể tải file từ Google Drive: {detail}") from exc
    except error.URLError as exc:
        raise GoogleDriveProviderError("Không thể kết nối tới Google Drive.") from exc


def _connection_ref(user: AuthenticatedUser):
    return repo.google_drive_connections().document(user.uid)


def _state_ref(state: str):
    return repo.google_drive_oauth_states().document(state)


def _normalize_scopes(scope_value: Any) -> list[str]:
    if isinstance(scope_value, list):
        return [str(item).strip() for item in scope_value if str(item).strip()]
    if isinstance(scope_value, str):
        return [item.strip() for item in scope_value.split() if item.strip()]
    return []


def _sanitize_status_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return {"connected": False, "scopes": []}

    serialized = serialize(payload)
    return {
        "connected": True,
        "email": serialized.get("email"),
        "displayName": serialized.get("displayName"),
        "photoUrl": serialized.get("photoUrl"),
        "scopes": _normalize_scopes(serialized.get("scopes")),
        "connectedAt": serialized.get("connectedAt"),
        "updatedAt": serialized.get("updatedAt"),
        "expiresAt": serialized.get("expiresAt"),
        "driveUserId": serialized.get("driveUserId"),
    }


def create_oauth_url(user: AuthenticatedUser, redirect_uri: str | None = None) -> dict[str, Any]:
    client_id, _ = _require_oauth_config()
    resolved_redirect_uri = _resolve_redirect_uri(redirect_uri)
    state = secrets.token_urlsafe(32)
    now = int(time.time() * 1000)

    _state_ref(state).set(
        {
            "uid": user.uid,
            "redirectUri": resolved_redirect_uri,
            "createdAt": repo.server_timestamp(),
            "expiresAt": now + GOOGLE_DRIVE_STATE_TTL_MS,
        }
    )

    query = parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": resolved_redirect_uri,
            "response_type": "code",
            "scope": " ".join(GOOGLE_DRIVE_SCOPES),
            "access_type": "offline",
            "include_granted_scopes": "true",
            # prompt=consent helps ensure refresh_token is returned on first clean connect.
            "prompt": "consent",
            "state": state,
        }
    )
    return {
        "authUrl": f"{GOOGLE_AUTH_URL}?{query}",
        "state": state,
        "redirectUri": resolved_redirect_uri,
        "scopes": GOOGLE_DRIVE_SCOPES,
    }


def _consume_valid_state(user: AuthenticatedUser, state: str, redirect_uri: str) -> None:
    snapshot = _state_ref(state).get()
    if not snapshot.exists:
        raise GoogleDriveValidationError("OAuth state không tồn tại hoặc đã hết hạn.")

    data = snapshot.to_dict() or {}
    snapshot.reference.delete()

    if data.get("uid") != user.uid:
        raise GoogleDriveValidationError("OAuth state không thuộc về người dùng hiện tại.")
    if data.get("redirectUri") != redirect_uri:
        raise GoogleDriveValidationError("Redirect URI không khớp với OAuth state.")
    if int(data.get("expiresAt") or 0) < int(time.time() * 1000):
        raise GoogleDriveValidationError("OAuth state đã hết hạn. Hãy kết nối lại Google Drive.")


def _fetch_google_user(access_token: str) -> dict[str, Any]:
    return _request_json(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )


def exchange_code(user: AuthenticatedUser, code: str, state: str, redirect_uri: str | None = None) -> dict[str, Any]:
    client_id, client_secret = _require_oauth_config()
    resolved_redirect_uri = _resolve_redirect_uri(redirect_uri)
    _consume_valid_state(user, state, resolved_redirect_uri)

    token_payload = _request_json(
        GOOGLE_TOKEN_URL,
        method="POST",
        form_data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": resolved_redirect_uri,
            "grant_type": "authorization_code",
        },
    )

    access_token = str(token_payload.get("access_token") or "")
    refresh_token = str(token_payload.get("refresh_token") or "")
    if not access_token:
        raise GoogleDriveProviderError("Google không trả về access token.")

    user_info = _fetch_google_user(access_token)
    now = int(time.time() * 1000)
    expires_in = int(token_payload.get("expires_in") or 3600)
    current_snapshot = _connection_ref(user).get()
    current_data = current_snapshot.to_dict() or {}

    connection_payload = {
        "uid": user.uid,
        "email": str(user_info.get("email") or user.email or ""),
        "displayName": str(user_info.get("name") or ""),
        "photoUrl": str(user_info.get("picture") or ""),
        "driveUserId": str(user_info.get("sub") or ""),
        "accessToken": access_token,
        "refreshToken": refresh_token or current_data.get("refreshToken") or "",
        "expiresAt": now + (expires_in * 1000),
        "scopes": _normalize_scopes(token_payload.get("scope")) or GOOGLE_DRIVE_SCOPES,
        "connectedAt": current_data.get("connectedAt") or repo.server_timestamp(),
        "updatedAt": repo.server_timestamp(),
    }

    _connection_ref(user).set(connection_payload, merge=True)
    return _sanitize_status_payload(_connection_ref(user).get().to_dict() or connection_payload)


def get_connection_status(user: AuthenticatedUser) -> dict[str, Any]:
    snapshot = _connection_ref(user).get()
    if not snapshot.exists:
        return {"connected": False, "scopes": []}
    return _sanitize_status_payload(snapshot.to_dict() or {})


def disconnect(user: AuthenticatedUser) -> bool:
    snapshot = _connection_ref(user).get()
    if not snapshot.exists:
        return False
    snapshot.reference.delete()
    return True


def _refresh_access_token(user: AuthenticatedUser, current_data: dict[str, Any]) -> dict[str, Any]:
    client_id, client_secret = _require_oauth_config()
    refresh_token = str(current_data.get("refreshToken") or "")
    if not refresh_token:
        raise GoogleDriveValidationError("Kết nối Google Drive đã hết hạn. Hãy kết nối lại.")

    token_payload = _request_json(
        GOOGLE_TOKEN_URL,
        method="POST",
        form_data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )

    access_token = str(token_payload.get("access_token") or "")
    if not access_token:
        raise GoogleDriveProviderError("Google không trả về access token khi refresh.")

    expires_in = int(token_payload.get("expires_in") or 3600)
    refreshed = {
        **current_data,
        "accessToken": access_token,
        "expiresAt": int(time.time() * 1000) + (expires_in * 1000),
        "updatedAt": repo.server_timestamp(),
    }
    scopes = _normalize_scopes(token_payload.get("scope"))
    if scopes:
        refreshed["scopes"] = scopes

    _connection_ref(user).set(refreshed, merge=True)
    return refreshed


def _get_valid_connection(user: AuthenticatedUser) -> dict[str, Any]:
    snapshot = _connection_ref(user).get()
    if not snapshot.exists:
        raise GoogleDriveValidationError("Tài khoản chưa kết nối Google Drive.")

    connection = snapshot.to_dict() or {}
    now = int(time.time() * 1000)
    access_token = str(connection.get("accessToken") or "")
    expires_at = int(connection.get("expiresAt") or 0)

    if access_token and expires_at > now + GOOGLE_TOKEN_REFRESH_SKEW_MS:
        return connection
    return _refresh_access_token(user, connection)


def _auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def _build_drive_url(path: str, params: dict[str, Any] | None = None) -> str:
    query = parse.urlencode({key: value for key, value in (params or {}).items() if value not in (None, "")})
    return f"{GOOGLE_DRIVE_API_BASE}{path}{'?' + query if query else ''}"


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _parse_mime_types(value: str | None) -> list[str]:
    if not value:
        return []
    return sorted({item.strip() for item in value.split(",") if item.strip()})


def _build_mime_type_query(mime_types: list[str]) -> str | None:
    if not mime_types:
        return None

    parts = [f"mimeType = '{_escape_drive_query(GOOGLE_DRIVE_FOLDER_MIME_TYPE)}'"]
    parts.extend(f"mimeType = '{_escape_drive_query(mime_type)}'" for mime_type in mime_types)
    return f"({' or '.join(parts)})"


def _normalize_file_item(item: dict[str, Any]) -> dict[str, Any]:
    size_value = item.get("size")
    try:
        size = int(size_value) if size_value not in (None, "") else None
    except Exception:
        size = None

    mime_type = str(item.get("mimeType") or "")
    return {
        "id": str(item.get("id") or ""),
        "name": str(item.get("name") or ""),
        "mimeType": mime_type,
        "size": size,
        "modifiedTime": item.get("modifiedTime"),
        "iconLink": item.get("iconLink"),
        "webViewLink": item.get("webViewLink"),
        "parents": list(item.get("parents") or []),
        "owners": [
            {
                "displayName": str(owner.get("displayName") or ""),
                "emailAddress": str(owner.get("emailAddress") or ""),
            }
            for owner in list(item.get("owners") or [])
        ],
        "isGoogleWorkspaceFile": mime_type.startswith("application/vnd.google-apps."),
    }


def list_files(
    user: AuthenticatedUser,
    *,
    search: str | None = None,
    folder_id: str | None = None,
    mime_types: str | None = None,
    page_size: int = 20,
    page_token: str | None = None,
) -> dict[str, Any]:
    connection = _get_valid_connection(user)
    access_token = str(connection.get("accessToken") or "")

    query_parts = ["trashed = false"]
    if folder_id:
        query_parts.append(f"'{_escape_drive_query(folder_id)}' in parents")
    if search:
        query_parts.append(f"name contains '{_escape_drive_query(search)}'")
    mime_query = _build_mime_type_query(_parse_mime_types(mime_types))
    if mime_query:
        query_parts.append(mime_query)

    payload = _request_json(
        _build_drive_url(
            "/files",
            {
                "pageSize": min(max(int(page_size or 20), 1), 100),
                "pageToken": page_token or "",
                "spaces": "drive",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "orderBy": "folder,name_natural",
                "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,iconLink,webViewLink,parents,owners(displayName,emailAddress))",
                "q": " and ".join(query_parts),
            },
        ),
        headers=_auth_headers(access_token),
    )

    items = [_normalize_file_item(item) for item in list(payload.get("files") or [])]
    return {
        "files": items,
        "nextPageToken": payload.get("nextPageToken"),
    }


def get_file_metadata(user: AuthenticatedUser, file_id: str) -> dict[str, Any]:
    connection = _get_valid_connection(user)
    access_token = str(connection.get("accessToken") or "")
    payload = _request_json(
        _build_drive_url(
            f"/files/{parse.quote(file_id)}",
            {
                "supportsAllDrives": "true",
                "fields": "id,name,mimeType,size,modifiedTime,iconLink,webViewLink,parents,owners(displayName,emailAddress)",
            },
        ),
        headers=_auth_headers(access_token),
    )
    return _normalize_file_item(payload)


def _append_extension(filename: str, extension: str) -> str:
    if filename.lower().endswith(extension.lower()):
        return filename
    stem = Path(filename).stem if Path(filename).suffix else filename
    return f"{stem}{extension}"


def _download_file_bytes(user: AuthenticatedUser, file_id: str) -> tuple[bytes, str, str, dict[str, Any]]:
    connection = _get_valid_connection(user)
    access_token = str(connection.get("accessToken") or "")
    metadata = get_file_metadata(user, file_id)

    source_mime_type = str(metadata.get("mimeType") or "")
    filename = str(metadata.get("name") or file_id)
    download_mime_type = source_mime_type

    if source_mime_type.startswith("application/vnd.google-apps."):
        export_config = GOOGLE_WORKSPACE_EXPORTS.get(source_mime_type)
        if not export_config:
            raise GoogleDriveValidationError(
                f"Chưa hỗ trợ import loại Google Workspace file này: {source_mime_type}"
            )
        download_mime_type, extension = export_config
        filename = _append_extension(filename, extension)
        url = _build_drive_url(
            f"/files/{parse.quote(file_id)}/export",
            {"mimeType": download_mime_type},
        )
    else:
        url = _build_drive_url(
            f"/files/{parse.quote(file_id)}",
            {"alt": "media", "supportsAllDrives": "true"},
        )
        guessed_mime, _ = mimetypes.guess_type(filename)
        if not download_mime_type and guessed_mime:
            download_mime_type = guessed_mime

    payload, response_headers = _request_bytes(url, headers=_auth_headers(access_token))
    if not download_mime_type:
        download_mime_type = response_headers.get("Content-Type", "application/octet-stream")
    return payload, filename, download_mime_type, metadata


def import_file_from_drive(user: AuthenticatedUser, payload: dict[str, Any]) -> dict[str, Any]:
    file_id = str(payload.get("fileId") or "").strip()
    if not file_id:
        raise GoogleDriveValidationError("Thiếu fileId Google Drive.")

    started_at = time.perf_counter()
    file_bytes, filename, mime_type, drive_metadata = _download_file_bytes(user, file_id)
    source_mime_type = str(drive_metadata.get("mimeType") or "")
    force_ocr = bool(payload.get("forceOcr"))
    file_type = str(payload.get("fileType") or "cv")

    extracted_text = extract_text_from_upload(
        file_bytes=file_bytes,
        filename=filename,
        content_type=mime_type,
        force_ocr=force_ocr,
        document_type=file_type,
    )

    processing_time_ms = int((time.perf_counter() - started_at) * 1000)
    ocr_method = "google-drive-export" if source_mime_type.startswith("application/vnd.google-apps.") else "google-drive-download"
    saved_uploaded_file_id = None

    if bool(payload.get("persistUploadedFile", True)):
        saved_uploaded_file_id = uploaded_file_service.save_uploaded_file(
            user,
            {
                "fileName": filename,
                "fileType": file_type,
                "fileSize": len(file_bytes),
                "mimeType": mime_type,
                "ocrMethod": ocr_method,
                "extractedText": extracted_text,
                "processingTimeMs": processing_time_ms,
                "analysisSessionId": payload.get("analysisSessionId"),
                "candidateName": payload.get("candidateName"),
                "jobPosition": payload.get("jobPosition"),
            },
        )

    return {
        "fileId": file_id,
        "fileName": filename,
        "mimeType": mime_type,
        "sourceMimeType": source_mime_type,
        "fileSize": len(file_bytes),
        "extractedText": extracted_text,
        "ocrMethod": ocr_method,
        "processingTimeMs": processing_time_ms,
        "savedUploadedFileId": saved_uploaded_file_id,
        "webViewLink": drive_metadata.get("webViewLink"),
        "driveFile": drive_metadata,
    }
