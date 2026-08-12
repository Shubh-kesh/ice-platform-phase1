from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter, AUTH_RATE_LIMIT, REFRESH_RATE_LIMIT, LOGOUT_RATE_LIMIT, GOOGLE_RATE_LIMIT
from app.core.security import create_token, verify_password
from app.middleware.audit import record_audit
from app.models.user import User
from app.schemas.auth import (
    GoogleAuthorizeResponse,
    GoogleCallbackRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.user import UserRead
from app.services import google_auth as ga
from app.services.auth_tokens import issue_session, revoke_token, rotate_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """Same source as the rate-limiter key, so audited IPs match throttled IPs."""
    try:
        return get_remote_address(request)
    except Exception:
        return request.client.host if request.client else None


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(request: Request, payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or user.hashed_password is None or not verify_password(payload.password, user.hashed_password):
        # Deliberately identical error for "no such user", "wrong password" and
        # "Google-only account with no password" — login can't enumerate emails.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    ip = _client_ip(request)
    refresh_token, _ = await issue_session(db, user, ip)

    # Auth events are audited in the same transaction as the session write.
    await record_audit(
        db,
        user_id=user.id,
        action="login",
        table_name="auth",
        record_id=str(user.id),
        changes={},
        ip_address=ip,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(REFRESH_RATE_LIMIT)
async def refresh(request: Request, payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    ip = _client_ip(request)
    outcome = await rotate_session(db, payload.refresh_token, ip)

    if not outcome.success:
        # Security rejections (reuse/theft, deactivated account) are audited
        # before the 401 so the signal survives the transaction rollback on
        # the request's exception path.
        if outcome.event is not None and outcome.event_user_id is not None:
            await record_audit(
                db,
                user_id=outcome.event_user_id,
                action=outcome.event,
                table_name="auth",
                record_id=str(outcome.event_user_id),
                changes={},
                ip_address=ip,
            )
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    assert outcome.user is not None
    assert outcome.new_refresh_token is not None

    await record_audit(
        db,
        user_id=outcome.user.id,
        action="refresh",
        table_name="auth",
        record_id=str(outcome.user.id),
        changes={"event": "refresh_rotation"},
        ip_address=ip,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_token(str(outcome.user.id), outcome.user.role.value, "access"),
        refresh_token=outcome.new_refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LOGOUT_RATE_LIMIT)
async def logout(request: Request, payload: LogoutRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    ip = _client_ip(request)
    session = await revoke_token(db, payload.refresh_token)
    if session is not None:
        await record_audit(
            db,
            user_id=session.user_id,
            action="logout",
            table_name="auth",
            record_id=str(session.user_id),
            changes={},
            ip_address=ip,
        )
        await db.commit()
    # Always 204: logout is idempotent and must not reveal whether a token was valid.


@router.get("/me", response_model=UserRead)
async def read_current_user(user: Annotated[User, Depends(get_current_user)]):
    return user


# --- M11: Google Sign-In (authorization code + PKCE, server-side exchange) ----


@router.get("/google/authorize", response_model=GoogleAuthorizeResponse)
@limiter.limit(GOOGLE_RATE_LIMIT)
async def google_authorize(request: Request):
    """Start a Google sign-in. Public, stateless: returns the consent URL plus
    the flow's `state` and PKCE `code_verifier` (frontend stashes both in
    sessionStorage). Missing/empty client config fails cleanly (503) so the
    login button can hide/disable."""
    if not settings.GOOGLE_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    nonce = ga.generate_nonce()
    state = ga.create_state(nonce)
    code_verifier = ga.generate_code_verifier()
    return GoogleAuthorizeResponse(
        authorize_url=ga.build_authorize_url(state, nonce, ga.generate_code_challenge(code_verifier)),
        state=state,
        code_verifier=code_verifier,
        nonce=nonce,
    )


async def _reject_link_conflict(db: AsyncSession, user_id, ip: str | None) -> None:
    """Audit a duplicate-identity / email-confusion rejection (§7/E, §7/G), then 409."""
    await record_audit(
        db,
        user_id=user_id,
        action="link_conflict",
        table_name="auth",
        record_id=str(user_id),
        changes={"event": "duplicate_google_identity"},
        ip_address=ip,
    )
    await db.commit()
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This Google account is already linked to a different ICE account",
    )


async def _finish_google_session(
    db: AsyncSession, user: User, ip: str | None
) -> TokenResponse:
    """Shared tail of the Google callback: deactivation check, M9 session issue,
    `google_login` audit, single atomic commit. Mirrors the password `login`
    handler so both paths exercise the identical session layer.

    A first-time double link of the same `google_sub` can race past the unique
    index; the loser hits IntegrityError here and becomes a 409 `link_conflict`
    instead of a silent duplicate."""
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    refresh_token, _ = await issue_session(db, user, ip)
    await record_audit(
        db,
        user_id=user.id,
        action="google_login",
        table_name="auth",
        record_id=str(user.id),
        changes={},
        ip_address=ip,
    )

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        await record_audit(
            db,
            user_id=user.id,
            action="link_conflict",
            table_name="auth",
            record_id=str(user.id),
            changes={"event": "concurrent_link_race"},
            ip_address=ip,
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This Google account is already linked to a different ICE account",
        ) from exc
    return TokenResponse(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=refresh_token,
    )


@router.post("/google/callback", response_model=TokenResponse)
@limiter.limit(GOOGLE_RATE_LIMIT)
async def google_callback(request: Request, payload: GoogleCallbackRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    """Complete a Google sign-in: verify state, exchange the code, verify the
    ID token, then resolve/link the ICE user (§7) and issue a normal M9 session.

    Rejections never log the code or ID token. Lookup order is `google_sub`
    first (authoritative identity), verified email second (link path only)."""
    if not settings.GOOGLE_AUTH_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    ip = _client_ip(request)

    try:
        nonce = ga.verify_state(payload.state)
        token_data = ga.exchange_code_for_tokens(payload.code, payload.code_verifier)
        claims = ga.verify_google_id_token(
            token_data["id_token"],
            nonce,
            settings.GOOGLE_CLIENT_ID,
            expected_hd=settings.GOOGLE_HOSTED_DOMAIN or None,
        )
    except ga.GoogleOAuthError:
        # Invalid/expired state, exchange failure, unverified email, bad token.
        # All collapse to one generic message — never distinguish the cause.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not sign in with Google. Please try again.",
        )

    sub = claims["sub"]
    email_lower = claims["email"].lower()

    # 1) Authoritative: existing Google identity.
    result = await db.execute(select(User).where(User.google_sub == sub))
    user = result.scalar_one_or_none()
    if user is not None:
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been deactivated",
            )
        # §7/G — identity is sub; the email may have drifted. Sync it if the
        # new verified email is free; if another ICE account owns it, refuse.
        if user.email.lower() != email_lower:
            other = await db.execute(
                select(User).where(
                    func.lower(User.email) == email_lower, User.id != user.id
                )
            )
            if other.scalar_one_or_none() is not None:
                await _reject_link_conflict(db, user.id, ip)
            old_email = user.email
            user.email = claims["email"]
            user.google_email = claims["email"]
            await record_audit(
                db,
                user_id=user.id,
                action="email_changed",
                table_name="auth",
                record_id=str(user.id),
                changes={
                    "email": {"old": old_email, "new": user.email},
                    "google_email": {"old": None, "new": claims["email"]},
                },
                ip_address=ip,
            )
        elif user.google_email != claims["email"]:
            user.google_email = claims["email"]
        return await _finish_google_session(db, user, ip)

    # 2) Link path: existing/pending ICE user with a matching *verified* email.
    result = await db.execute(
        select(User).where(func.lower(User.email) == email_lower)
    )
    user = result.scalar_one_or_none()
    if user is not None:
        if user.google_sub is not None:
            # §7/E — a different Google identity already owns this ICE email.
            if user.google_sub != sub:
                await _reject_link_conflict(db, user.id, ip)
            return await _finish_google_session(db, user, ip)

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This account has been deactivated",
            )
        # §7/A + §7/F — silent link (email_verified + audit; owner can opt into
        # an explicit consent step later). Role, assignments, password: untouched.
        user.google_sub = sub
        user.google_email = claims["email"]
        await record_audit(
            db,
            user_id=user.id,
            action="account_linked",
            table_name="auth",
            record_id=str(user.id),
            changes={
                "google_sub": {"old": None, "new": sub},
                "google_email": {"old": None, "new": claims["email"]},
            },
            ip_address=ip,
        )
        return await _finish_google_session(db, user, ip)

    # 3) §7/C — no ICE account for this verified email. No public signup.
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="No ICE account found for this email — ask an administrator to add you.",
    )
