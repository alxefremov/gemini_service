# Gemini Workshop Gateway API

Base URL: `https://<SERVICE_URL>` (Cloud Run).

Auth: Bearer JWT from `/token`, **or** just provide `email` in the `/chat` body (no token required for students).

## Health
- `GET /health` → `{"status":"ok"}`

## User management (requires `APP_ALLOW_REGISTRATION_ENDPOINT=true`)
Admin auth: pass either an admin Bearer token or header `X-Admin-Email` from `APP_ADMIN_EMAILS` (default `btc.esmt.workshop@gmail.com`).

### Create / update users
- `POST /register`
```json
{
  "users": [
    {"email": "alice@uni.de", "alias": "Alice", "request_limit": 15000, "concurrency_cap": 1},
    {"email": "bob@uni.de"}  // alias/limits optional, defaults apply
  ]
}
```
- Response: `{"registered": <count>}`

### Get user
- `GET /user/{email}`
- Response:
```json
{
  "email": "alice@uni.de",
  "alias": "Alice",
  "request_limit": 15000,
  "requests_used": 12,
  "concurrency_cap": 1,
  "active_streams": 0,
  "blocked": false
}
```

### Delete user
- `DELETE /user/{email}`
- Response: `{"deleted": true}` (or false if not found)

## Token (optional flow)
- `POST /token`
```json
{"email": "student@uni.de"}
```
- Response:
```json
{
  "token": "...",
  "expires_at": "2026-02-07T13:32:00Z",
  "request_limit": 15000,
  "requests_used": 12,
  "concurrency_cap": 1,
  "alias": "Alice"
}
```

## Call the model
- `POST /chat`
- Auth: either `Authorization: Bearer <token>` **or** provide `email` in the body.
```json
{
  "email": "student@uni.de",
  "messages": [
    {"role": "user", "content": "Hello Gemini!"}
  ],
  "model": "gemini-2.0-flash-001",
  "stream": true,
  "temperature": 0.4,
  "top_p": 0.95,
  "top_k": 40
}
```
- With `stream=true` the response is a text stream (lines). With `stream=false`:
```json
{"text": "<full model response>"}
```

### Python example (get token and call model)
```python
import requests

SERVICE_URL = "https://<SERVICE_URL>"
EMAIL = "student@uni.de"

# 1) get token (optional, you can skip and pass email in /chat)
token_resp = requests.post(f"{SERVICE_URL}/token", json={"email": EMAIL}, timeout=20)
token_resp.raise_for_status()
token = token_resp.json()["token"]

# 2) call chat without streaming
chat_resp = requests.post(
    f"{SERVICE_URL}/chat",
    json={
        "email": EMAIL,  # omit if using the token header instead
        "messages": [{"role": "user", "content": "Hello Gemini!"}],
        "model": "gemini-2.0-flash-001",
        "stream": False,
        "temperature": 0.3,
        "top_p": 0.95,
        "top_k": 40,
    },
    timeout=60,
)
chat_resp.raise_for_status()
print(chat_resp.json()["text"])
```

## Admin helpers (Python)
Requires `APP_ALLOW_REGISTRATION_ENDPOINT=true` and admin access.

### Add/update users
```python
import requests

SERVICE_URL = "https://<SERVICE_URL>"

users = [
    {"email": "alice@uni.de", "alias": "Alice", "request_limit": 15000, "concurrency_cap": 1},
    {"email": "bob@uni.de"}
]

resp = requests.post(f"{SERVICE_URL}/register", json={"users": users}, timeout=15)
resp.raise_for_status()
print(resp.json())  # {"registered": 2}
```

### Delete user
```python
import requests

SERVICE_URL = "https://<SERVICE_URL>"
email = "alice@uni.de"

resp = requests.delete(f"{SERVICE_URL}/user/{email}", timeout=10)
resp.raise_for_status()
print(resp.json())  # {"deleted": true}
```

## Limits and errors
- Defaults via env: `APP_DEFAULT_REQUEST_LIMIT`, `APP_DEFAULT_CONCURRENCY_CAP`.
- Possible `detail`: `user_not_registered`, `user_blocked`, `quota_exhausted`, `concurrency_exceeded`, `token_expired`, `invalid_token`, `gemini_error`.

## Status codes
- 200/201 — success
- 401 — token/email issues
- 403 — user not registered/blocked or admin endpoints disabled
- 429 — quota or concurrency exceeded
- 502 — Gemini error
- 500 — internal error
