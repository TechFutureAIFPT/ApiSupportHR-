from __future__ import annotations

from functools import lru_cache
from typing import Any

from app.core.config import get_settings


@lru_cache(maxsize=4)
def _jwks_client(jwks_url: str) -> Any:
    try:
        from jwt import PyJWKClient
    except ModuleNotFoundError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("PyJWT is required when AUTH_PROVIDER=supabase.") from error
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def verify_supabase_token(token: str) -> dict[str, Any]:
    """Validate issuer, audience, expiry and signature for a Supabase access token."""
    try:
        import jwt
    except ModuleNotFoundError as error:  # pragma: no cover - deployment dependency
        raise RuntimeError("PyJWT is required when AUTH_PROVIDER=supabase.") from error

    settings = get_settings()
    signing_key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256", "EdDSA"],
        audience=settings.supabase_jwt_audience,
        issuer=settings.supabase_jwt_issuer,
        options={"require": ["sub", "aud", "exp", "iss"]},
    )
    claims["uid"] = str(claims.get("sub") or "")
    return claims
