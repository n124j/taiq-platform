import secrets
from datetime import timedelta
from fastapi import APIRouter, Cookie, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import verify_password, get_password_hash, create_access_token, decode_access_token
from app.core.email import send_email, welcome_email_html, reset_password_email_html
from app.core.config import settings
from app.core.activity import track
from app.core import oauth as oauth_helper
from app.models.models import User, UserRole
from app.schemas.schemas import UserCreate, UserLogin, Token, UserOut
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_STATE_COOKIE = "oauth_state"


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(payload: UserCreate, db: AsyncSession = Depends(get_db)):
    existing = await db.scalar(select(User).where(User.email == payload.email))
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
        role=payload.role,
        is_active=True,   # set False if you want email-gated activation
    )
    db.add(user)
    await db.flush()
    await track(db, user, "registered", f"Account created as {payload.role.value}")

    # Send welcome + verification email (non-blocking — failure won't break registration)
    try:
        verify_url = f"{settings.FRONTEND_URL}/verify.html?token={create_access_token({'sub': str(user.id), 'purpose': 'verify_email'})}"
        html = welcome_email_html(
            full_name=user.full_name or "there",
            role=user.role.value,
            verify_url=verify_url,
        )
        await send_email(
            to=user.email,
            subject=f"Welcome to TaIQ — Please verify your email",
            html_body=html,
        )
    except Exception as e:
        logger.warning(f"Welcome email failed (non-fatal): {e}")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    user_out = UserOut.model_validate(user)
    return Token(access_token=token, user=user_out)


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    payload = decode_access_token(token)
    if not payload or payload.get("purpose") != "verify_email":
        raise HTTPException(status_code=400, detail="Invalid or expired verification link")

    user_id = payload.get("sub")
    user = await db.get(User, int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if not user.is_email_verified:
        user.is_email_verified = True
        await track(db, user, "email_verified", "Email address verified")
        await db.commit()

    return {"message": "Email verified successfully"}


class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification")
async def resend_verification(payload: ResendVerificationRequest, db: AsyncSession = Depends(get_db)):
    # Always return success to avoid leaking whether an email exists
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user and not user.is_email_verified:
        try:
            verify_url = f"{settings.FRONTEND_URL}/verify.html?token={create_access_token({'sub': str(user.id), 'purpose': 'verify_email'})}"
            from app.core.email import welcome_email_html
            html = welcome_email_html(
                full_name=user.full_name or "there",
                role=user.role.value,
                verify_url=verify_url,
            )
            await send_email(
                to=user.email,
                subject="TaIQ — Verify your email address",
                html_body=html,
            )
        except Exception as e:
            logger.warning(f"Resend verification email failed: {e}")
    return {"message": "If that email exists and is unverified, a new verification link has been sent."}


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/forgot-password")
async def forgot_password(payload: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    # Always return success to avoid leaking whether an email exists
    user = await db.scalar(select(User).where(User.email == payload.email))
    if user:
        try:
            reset_token = create_access_token(
                {"sub": str(user.id), "purpose": "reset_password"},
                expires_delta=timedelta(hours=1),
            )
            reset_url = f"{settings.FRONTEND_URL}/reset-password.html?token={reset_token}"
            html = reset_password_email_html(full_name=user.full_name or "there", reset_url=reset_url)
            await send_email(to=user.email, subject="TaIQ — Reset your password", html_body=html)
        except Exception as e:
            logger.warning(f"Password reset email failed: {e}")
    return {"message": "If that email exists, a password reset link has been sent."}


@router.post("/reset-password")
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    if len(payload.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    token_payload = decode_access_token(payload.token)
    if not token_payload or token_payload.get("purpose") != "reset_password":
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    user = await db.get(User, int(token_payload["sub"]))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.hashed_password = get_password_hash(payload.new_password)
    await track(db, user, "password_changed", "Password reset via email link")
    return {"message": "Password has been reset successfully. You can now sign in."}


@router.post("/login", response_model=Token)
async def login(payload: UserLogin, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(select(User).where(User.email == payload.email))
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    if not user.is_email_verified:
        raise HTTPException(status_code=403, detail="Please verify your email before logging in. Check your inbox for the verification link.")

    await track(db, user, "login", "Signed in to account")
    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    user_out = UserOut.model_validate(user)
    return Token(access_token=token, user=user_out)


# ── OAuth (Google / GitHub) ─────────────────────────────────────────────────────
@router.get("/{provider}/login")
async def oauth_login(provider: str):
    if provider not in oauth_helper.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")

    cfg = oauth_helper.PROVIDERS[provider]
    if not cfg["client_id"] or not cfg["client_secret"]:
        raise HTTPException(status_code=503, detail=f"{provider.title()} login is not configured")

    state = secrets.token_urlsafe(24)
    response = RedirectResponse(oauth_helper.build_authorize_url(provider, state))
    response.set_cookie(
        OAUTH_STATE_COOKIE, state, max_age=300, httponly=True, samesite="lax"
    )
    return response


@router.get("/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    oauth_state: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
):
    def failure(reason: str) -> RedirectResponse:
        resp = RedirectResponse(f"{settings.FRONTEND_URL}/index.html?oauth_error=1&reason={reason}")
        resp.delete_cookie(OAUTH_STATE_COOKIE)
        return resp

    if provider not in oauth_helper.PROVIDERS:
        raise HTTPException(status_code=404, detail="Unknown OAuth provider")

    if error or not code or not state or not oauth_state or state != oauth_state:
        return failure("invalid_request")

    try:
        access_token = await oauth_helper.exchange_code_for_token(provider, code)
        profile = await oauth_helper.fetch_profile(provider, access_token)
    except Exception as e:
        logger.warning(f"OAuth {provider} exchange failed: {e}")
        return failure("provider_error")

    email = profile.get("email")
    if not email:
        return failure("no_email")

    user = await db.scalar(select(User).where(User.email == email))
    if user:
        if not user.oauth_provider:
            user.oauth_provider = provider
            user.oauth_id = profile.get("provider_id")
        if not user.is_email_verified:
            user.is_email_verified = True
        await track(db, user, "login", f"Signed in via {provider.title()} OAuth")
    else:
        user = User(
            email=email,
            hashed_password=None,
            full_name=profile.get("name") or email.split("@")[0],
            role=UserRole.candidate,
            is_active=True,
            is_email_verified=True,
            avatar_url=profile.get("avatar_url"),
            oauth_provider=provider,
            oauth_id=profile.get("provider_id"),
        )
        db.add(user)
        await db.flush()
        await track(db, user, "registered", f"Account created via {provider.title()} OAuth")

    token = create_access_token({"sub": str(user.id), "role": user.role.value})
    resp = RedirectResponse(f"{settings.FRONTEND_URL}/index.html?oauth_token={token}")
    resp.delete_cookie(OAUTH_STATE_COOKIE)
    return resp
