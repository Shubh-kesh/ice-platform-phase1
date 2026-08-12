"""
M11 — Google Sign-In helpers for the /auth/google/* endpoints.

OAuth 2.0 Authorization Code + PKCE flow with **stateless** session state:

* The backend never stores anything for a flow. `state` is self-verifying:
  `state = base64(json{nonce, ts}) + "." + base64(hmac_sha256(secret, that_json))`.
  The callback recomputes the HMAC (constant-time compare) and enforces the
  freshness window — no Redis/DB needed (Redis is provisioned but unused).
* PKCE `code_verifier` travels to the backend inside the callback body
  (Google never echoes it), so the exchange can prove it owns the authorize
  request even if `state` leaked.
* The ID token is verified server-side, signature-first: RS256 against Google's
  published JWKS, exact `iss`/`aud`, exp/iat/nbf, plus the M11-specific
  `nonce`, `email_verified`, and optional `hd` checks.

The key source is injectable (`certs_source=None` -> production JWKS fetch) so
tests can mint an RS256 token with a scratch keypair and serve its public key —
exercising the real signature/iss/aud/exp/nonce verification path with zero
network. None of these helpers ever logs or returns the raw code or ID token.

Dependency note: verification reuses the codebase's `python-jose` (already the
JWT library in `app.core.security`) instead of adding the `google-auth` SDK.
google-auth's public API does not accept an injectable cert source, which the
M11 test plan (§13) requires; keys come from the same public JWKS endpoint via
httpx. Behavior is identical to `google.oauth2.id_token.verify_oauth2_token`.
"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Callable

import httpx
from jose import JWTError, jwt  # type: ignore[import-untyped]  # no types-python-jose stubs

from app.core.config import settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_URI = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_OPENID_SCOPES = "openid email profile"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")
GoogleSigningKey = str | dict[str, Any]

# Network timeout for Google token/JWKS calls.
_CERTS_CLIENT = httpx.Client(timeout=10.0, headers={"Accept": "application/json"})


class GoogleOAuthError(Exception):
    """Any Google flow failure. Message is deliberately generic — it never
    contains a token, code, or user identity."""


# --- verifier / state --------------------------------------------------------


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


def generate_code_verifier() -> str:
    return secrets.token_urlsafe(48)


def generate_code_challenge(verifier: str) -> str:
    """S256 PKCE challenge: base64url(sha256(verifier)), no padding."""
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def create_state(nonce: str) -> str:
    """Self-verifying, timestamped state: base64(json) + "." + base64(HMAC)."""
    payload = json.dumps({"n": nonce, "t": int(time.time())}, separators=(",", ":"))
    sig = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256
    ).digest()
    return (
        base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii")
    )


def verify_state(state: str) -> str:
    """Recover the nonce from a state value, checking HMAC and freshness."""
    if not state or "." not in state:
        raise GoogleOAuthError("Invalid authentication state")
    payload_b64, sig_b64 = state.split(".", 1)
    try:
        payload = base64.urlsafe_b64decode(payload_b64.encode("ascii"))
        sig = base64.urlsafe_b64decode(sig_b64.encode("ascii"))
    except Exception as exc:
        raise GoogleOAuthError("Invalid authentication state") from exc

    expected = hmac.new(
        settings.SECRET_KEY.encode("utf-8"), payload, hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, sig):
        raise GoogleOAuthError("Invalid authentication state")

    try:
        data = json.loads(payload.decode("utf-8"))
        nonce = data["n"]
        issued_at = int(data["t"])
    except (KeyError, ValueError, TypeError) as exc:
        raise GoogleOAuthError("Invalid authentication state") from exc

    if time.time() - issued_at > settings.GOOGLE_AUTH_STATE_MAX_AGE_SECONDS:
        raise GoogleOAuthError("Authentication request expired")
    if time.time() - issued_at < 0:
        raise GoogleOAuthError("Invalid authentication state")

    if not nonce or len(nonce) < 16:
        raise GoogleOAuthError("Invalid authentication state")
    return nonce


def build_authorize_url(state: str, nonce: str, code_challenge: str) -> str:
    """Assemble the Google consent URL (authorization-code + PKCE request)."""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_OPENID_SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "online",
        "prompt": "select_account",
    }
    if settings.GOOGLE_HOSTED_DOMAIN:
        params["hd"] = settings.GOOGLE_HOSTED_DOMAIN
    return f"{GOOGLE_AUTH_URL}?{httpx.QueryParams(params)}"


# --- token exchange + ID-token verification ----------------------------------


def exchange_code_for_tokens(code: str, code_verifier: str) -> dict:
    """POST the authorization code + PKCE verifier to Google's token endpoint.

    Only the ID token is used downstream; no Google access/refresh token is
    requested (scopes are openid/email/profile).
    """
    try:
        response = _CERTS_CLIENT.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise GoogleOAuthError("Could not exchange the authorization code") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise GoogleOAuthError("Could not exchange the authorization code") from exc

    if not isinstance(data.get("id_token"), str):
        raise GoogleOAuthError("Google did not return an identity token")
    return data


def _fetch_google_certs() -> dict[str, GoogleSigningKey]:
    """Production key source: Google's published JWKS (public RS256 keys).

    Google currently publishes RSA JWKs with `n`/`e`; some responses may also
    include an `x5c` certificate chain. Keep both representations because
    python-jose can verify either, and do not accept non-signing/non-RS256 keys.
    """
    try:
        response = _CERTS_CLIENT.get(GOOGLE_JWKS_URI)
        response.raise_for_status()
        keys = response.json().get("keys") or []
    except (httpx.HTTPError, ValueError) as exc:
        raise GoogleOAuthError("Could not load Google signing keys") from exc

    certs: dict[str, GoogleSigningKey] = {}
    for key in keys:
        kid = key.get("kid")
        x5c = key.get("x5c")
        if (
            not kid
            or key.get("kty") != "RSA"
            or key.get("alg") not in (None, "RS256")
            or key.get("use") not in (None, "sig")
        ):
            continue
        if isinstance(x5c, list) and x5c:
            der = x5c[0]
            certs[kid] = (
                "-----BEGIN CERTIFICATE-----\n"
                + "\n".join(der[i : i + 64] for i in range(0, len(der), 64))
                + "\n-----END CERTIFICATE-----"
            )
        elif key.get("n") and key.get("e"):
            certs[kid] = key
    if not certs:
        raise GoogleOAuthError("Google returned no usable signing keys")
    return certs


def verify_google_id_token(
    token: str,
    expected_nonce: str,
    expected_aud: str,
    expected_iss: tuple[str, ...] = GOOGLE_ISSUERS,
    expected_hd: str | None = None,
    certs_source: Callable[[], dict[str, GoogleSigningKey]] | None = None,
) -> dict:
    """Verify a Google ID token end-to-end and return its claims.

    Enforces, in order: signature (RS256 via Google's keys), issuer, audience,
    exp/iat/nbf, nonce binding, and (for M11) `email_verified == true` plus the
    optional `hd` workspace-domain lock. Raises GoogleOAuthError with a generic
    message on any failure; on success the claims identify the Google account
    via `sub`, with a verified `email`.
    """
    certs = certs_source() if certs_source is not None else _fetch_google_certs()

    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise GoogleOAuthError("Invalid identity token") from exc

    cert = certs.get(unverified_header.get("kid") or "")
    if cert is None:
        raise GoogleOAuthError("Could not find a matching Google signing key")

    try:
        claims = jwt.decode(
            token,
            cert,
            algorithms=["RS256"],
            audience=expected_aud,
            # `verify_at_hash` is disabled to match the google-auth reference
            # implementation (verify_oauth2_token). Google ID tokens carry an
            # `at_hash` claim bound to the exchange's access token; we never use
            # or store that access token, so verifying the binding adds nothing
            # and python-jose would otherwise demand the access token here.
            options={
                "verify_iat": True,
                "verify_nbf": True,
                "verify_exp": True,
                "verify_at_hash": False,
            },
        )
    except JWTError as exc:
        raise GoogleOAuthError("Identity token could not be verified") from exc

    if claims.get("iss") not in expected_iss:
        raise GoogleOAuthError("Identity token has an invalid issuer")

    if claims.get("nonce") != expected_nonce:
        raise GoogleOAuthError("Identity token is not bound to this request")

    if expected_hd and claims.get("hd") != expected_hd:
        raise GoogleOAuthError("Identity token is not from the allowed workspace")

    email = claims.get("email")
    if not email or claims.get("email_verified") is not True:
        # Never link or log in on an unverified email — email is only ever a
        # link *path*, never proof of identity on its own.
        raise GoogleOAuthError("Google email is not verified")

    if not claims.get("sub"):
        raise GoogleOAuthError("Identity token is missing a subject")
    return claims