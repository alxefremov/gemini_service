from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from google.cloud import firestore

from .config import get_settings


settings = get_settings()
db = firestore.Client(project=settings.project_id)


@dataclass
class UserRecord:
    email: str
    alias: Optional[str]
    request_limit: int
    requests_used: int
    concurrency_cap: int
    active_streams: int
    blocked: bool
    updated_at: datetime

    @classmethod
    def from_dict(cls, email: str, data: Dict) -> "UserRecord":
        return cls(
            email=email,
            alias=data.get("alias"),
            request_limit=int(data.get("request_limit", settings.default_request_limit)),
            requests_used=int(data.get("requests_used", 0)),
            concurrency_cap=int(
                data.get("concurrency_cap", settings.default_concurrency_cap)
            ),
            active_streams=int(data.get("active_streams", 0)),
            blocked=bool(data.get("blocked", False)),
            updated_at=data.get("updated_at", datetime.now(timezone.utc)),
        )

    def to_dict(self) -> Dict:
        return {
            "alias": self.alias,
            "request_limit": self.request_limit,
            "requests_used": self.requests_used,
            "concurrency_cap": self.concurrency_cap,
            "active_streams": self.active_streams,
            "blocked": self.blocked,
            "updated_at": datetime.now(timezone.utc),
        }


def _users_collection():
    return db.collection("users")


def register_users(
    users: List[Dict[str, object]]
) -> int:
    batch = db.batch()
    now = datetime.now(timezone.utc)
    count = 0
    for user in users:
        email = str(user["email"]).lower()
        alias = user.get("alias")
        req_limit = user.get("request_limit")
        conc_cap = user.get("concurrency_cap")
        doc_ref = _users_collection().document(email)
        data = {
            "alias": alias,
            "request_limit": int(req_limit or settings.default_request_limit),
            "concurrency_cap": int(conc_cap or settings.default_concurrency_cap),
            "requests_used": 0,
            "active_streams": 0,
            "blocked": False,
            "updated_at": now,
        }
        batch.set(doc_ref, data, merge=True)
        count += 1
    batch.commit()
    return count


def get_user(email: str) -> Optional[UserRecord]:
    snap = _users_collection().document(email.lower()).get()
    if not snap.exists:
        return None
    return UserRecord.from_dict(email.lower(), snap.to_dict())


@firestore.transactional
def _reserve_transaction(transaction, email: str) -> UserRecord:
    doc_ref = _users_collection().document(email.lower())
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        raise PermissionError("user_not_registered")
    data = snapshot.to_dict()
    user = UserRecord.from_dict(email.lower(), data)
    if user.blocked:
        raise PermissionError("user_blocked")
    if user.requests_used >= user.request_limit:
        raise PermissionError("quota_exhausted")
    if user.active_streams >= user.concurrency_cap:
        raise PermissionError("concurrency_exceeded")
    user.requests_used += 1
    user.active_streams += 1
    transaction.set(doc_ref, user.to_dict(), merge=True)
    _log_usage(transaction, email, "reserve")
    return user


def reserve_request(email: str) -> UserRecord:
    return _reserve_transaction(db.transaction(), email)


@firestore.transactional
def _release_transaction(transaction, email: str):
    doc_ref = _users_collection().document(email.lower())
    snapshot = doc_ref.get(transaction=transaction)
    if not snapshot.exists:
        return
    data = snapshot.to_dict()
    user = UserRecord.from_dict(email.lower(), data)
    user.active_streams = max(0, user.active_streams - 1)
    transaction.set(doc_ref, user.to_dict(), merge=True)
    _log_usage(transaction, email, "release")


def release_stream(email: str):
    _release_transaction(db.transaction(), email)


def delete_user(email: str) -> bool:
    doc_ref = _users_collection().document(email.lower())
    if not doc_ref.get().exists:
        return False
    doc_ref.delete()
    return True


def _log_usage(transaction, email: str, action: str):
    log_ref = db.collection("usage_log").document()
    transaction.set(
        log_ref,
        {
            "email": email.lower(),
            "action": action,
            "ts": datetime.now(timezone.utc),
        },
    )
