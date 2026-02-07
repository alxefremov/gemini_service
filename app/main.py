from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, Dict

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from google.api_core.exceptions import GoogleAPIError
from pydantic import BaseModel

from . import gemini, storage
from .config import get_settings
from .schemas import (
    ChatRequest,
    DeleteResponse,
    HealthResponse,
    RegisterRequest,
    TokenRequest,
    TokenResponse,
    UserInfo,
)

logger = logging.getLogger("uvicorn.error")
settings = get_settings()
app = FastAPI(title="Gemini Workshop Gateway")


class ErrorResponse(BaseModel):
    detail: str


def _get_actor_email(authorization: str | None, fallback_email: str | None = None) -> str | None:
    """
    Extract email from bearer token if present, otherwise use fallback (for no-token flows).
    """
    if authorization:
        claims = _verify_token(authorization)
        email = claims.get("email")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_payload")
        return email.lower()
    if fallback_email:
        return fallback_email.lower()
    return None


def _require_admin(authorization: str | None, admin_header: str | None) -> str:
    """
    Resolve acting email and ensure it is in admin list.
    """
    actor = _get_actor_email(authorization, admin_header)
    if not actor:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin_email_required")
    if actor not in [a.lower() for a in settings.admin_emails]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_only")
    return actor


def _create_token(email: str, user: storage.UserRecord) -> TokenResponse:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.token_ttl_minutes)
    payload: Dict = {
        "email": email.lower(),
        "exp": int(expires_at.timestamp()),
        "requests_used": user.requests_used,
        "request_limit": user.request_limit,
        "concurrency_cap": user.concurrency_cap,
        "alias": user.alias,
    }
    token = jwt.encode(payload, settings.token_secret, algorithm="HS256")
    return TokenResponse(
        token=token,
        expires_at=expires_at,
        request_limit=user.request_limit,
        requests_used=user.requests_used,
        concurrency_cap=user.concurrency_cap,
        alias=user.alias,
    )


def _verify_token(auth_header: str | None) -> Dict:
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    token = auth_header.split(" ", 1)[1]
    try:
        return jwt.decode(token, settings.token_secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token_expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse()


@app.post(
    "/register",
    response_model=dict,
    responses={403: {"model": ErrorResponse}},
)
def register(body: RegisterRequest, authorization: str | None = Header(default=None), x_admin_email: str | None = Header(default=None)):
    if not settings.allow_registration_endpoint:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration_disabled")
    _require_admin(authorization, x_admin_email)
    users_payload = [user.dict() for user in body.users]
    count = storage.register_users(users_payload)
    return {"registered": count}


@app.post(
    "/token",
    response_model=TokenResponse,
    responses={403: {"model": ErrorResponse}},
)
def token(body: TokenRequest):
    user = storage.get_user(body.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_not_registered")
    if user.blocked:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_blocked")
    return _create_token(body.email, user)


@app.get(
    "/user/{email}",
    response_model=UserInfo,
    responses={403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_user(email: str, authorization: str | None = Header(default=None), x_admin_email: str | None = Header(default=None)):
    if not settings.allow_registration_endpoint:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_lookup_disabled")
    _require_admin(authorization, x_admin_email)
    user = storage.get_user(email)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_found")
    return UserInfo(
        email=user.email,
        alias=user.alias,
        request_limit=user.request_limit,
        requests_used=user.requests_used,
        concurrency_cap=user.concurrency_cap,
        active_streams=user.active_streams,
        blocked=user.blocked,
    )


@app.delete(
    "/user/{email}",
    response_model=DeleteResponse,
    responses={403: {"model": ErrorResponse}},
)
def delete_user(email: str, authorization: str | None = Header(default=None), x_admin_email: str | None = Header(default=None)):
    if not settings.allow_registration_endpoint:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user_delete_disabled")
    _require_admin(authorization, x_admin_email)
    deleted = storage.delete_user(email)
    return DeleteResponse(deleted=deleted)


async def _stream_chat(email: str, chat_body: ChatRequest) -> AsyncIterator[bytes]:
    try:
        gemini_stream = gemini.generate_stream(
            [m.dict() for m in chat_body.messages],
            chat_body.model,
            temperature=chat_body.temperature,
            top_p=chat_body.top_p,
            top_k=chat_body.top_k,
        )
        for chunk in gemini_stream:
            text = getattr(chunk, "text", None) or getattr(chunk, "candidates", None)
            if text:
                yield (str(text) + "\n").encode("utf-8")
            await asyncio.sleep(0)  # allow event loop to switch tasks
    finally:
        storage.release_stream(email)


@app.post(
    "/chat",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
    },
)
async def chat(request: Request, chat_body: ChatRequest, authorization: str | None = Header(default=None)):
    email: str | None = None
    if authorization:
        claims = _verify_token(authorization)
        email = claims.get("email")
        if not email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token_payload")
    else:
        # Token is optional: fall back to email provided in the request body
        if not chat_body.email:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="email_required")
        email = chat_body.email.lower()

    try:
        user = storage.reserve_request(email)
    except PermissionError as exc:
        reason = str(exc)
        status_code = status.HTTP_403_FORBIDDEN if reason in {"user_not_registered", "user_blocked"} else status.HTTP_429_TOO_MANY_REQUESTS
        raise HTTPException(status_code=status_code, detail=reason)
    except Exception as exc:  # pragma: no cover - Firestore errors
        logger.exception("Failed to reserve request: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal_error")

    try:
        if chat_body.stream:
            return StreamingResponse(
                _stream_chat(email, chat_body),
                media_type="text/plain",
            )
        # Non-streaming path (one-shot)
        stream = gemini.generate_stream(
            [m.dict() for m in chat_body.messages],
            chat_body.model,
            temperature=chat_body.temperature,
            top_p=chat_body.top_p,
            top_k=chat_body.top_k,
        )
        full_text = "".join([chunk.text for chunk in stream if getattr(chunk, "text", None)])
        return JSONResponse({"text": full_text})
    except GoogleAPIError as exc:
        logger.exception("Gemini API error: %s", exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="gemini_error")
    except Exception as exc:  # pragma: no cover
        logger.exception("Unexpected chat error: %s", exc)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="internal_error")
    finally:
        if not chat_body.stream:
            storage.release_stream(email)
