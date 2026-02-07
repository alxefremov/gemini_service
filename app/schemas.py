from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserSpec(BaseModel):
    email: EmailStr
    alias: Optional[str] = Field(default=None, max_length=120)
    request_limit: Optional[int] = Field(default=None, ge=1)
    concurrency_cap: Optional[int] = Field(default=None, ge=1)


class RegisterRequest(BaseModel):
    users: List[UserSpec]


class TokenRequest(BaseModel):
    email: EmailStr


class TokenResponse(BaseModel):
    token: str
    expires_at: datetime
    request_limit: int
    requests_used: int
    concurrency_cap: int
    alias: Optional[str] = None


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    email: Optional[EmailStr] = None  # token optional; email may be provided instead
    messages: List[ChatMessage]
    model: str = "gemini-2.0-flash-001"
    stream: bool = True
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    top_k: Optional[int] = Field(default=None, ge=1, le=200)


class HealthResponse(BaseModel):
    status: str = "ok"


class UserInfo(BaseModel):
    email: EmailStr
    alias: Optional[str] = None
    request_limit: int
    requests_used: int
    concurrency_cap: int
    active_streams: int
    blocked: bool


class DeleteResponse(BaseModel):
    deleted: bool
