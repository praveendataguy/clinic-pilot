"""Checks every request to the MCP server.

A request must carry "Authorization: Bearer <session token>". For each tool call the
user's role is checked against permissions.py. A refused tool call comes back to the AI as
a normal tool error, so it can tell the receptionist why.
"""
import json

from auth import verify_token
from permissions import ROLE_LABELS, allowed


def _bearer(scope):
    for k, v in scope.get("headers", []):
        if k == b"authorization":
            parts = v.decode("latin-1").split(None, 1)
            if len(parts) == 2 and parts[0].lower() == "bearer":
                return parts[1].strip()
    return ""


async def _reply(send, status, payload):
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def _read_body(receive):
    chunks, more = [], True
    while more:
        msg = await receive()
        if msg["type"] == "http.disconnect":
            break
        chunks.append(msg.get("body", b""))
        more = msg.get("more_body", False)
    return b"".join(chunks)


def _replay(body, receive):
    sent = False

    async def r():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return await receive()
    return r


def _refusal(body, user):
    """Return a reply to send back if a tool call is not allowed, else None."""
    try:
        data = json.loads(body)
    except Exception:
        return None  # not JSON: let the MCP server complain in its own way
    messages = data if isinstance(data, list) else [data]
    for m in messages:
        if isinstance(m, dict) and m.get("method") == "tools/call":
            tool = (m.get("params") or {}).get("name", "")
            if not allowed(user["role"], tool):
                text = (f"Permission denied: the {ROLE_LABELS.get(user['role'], user['role'])} role "
                        f"cannot use '{tool}'. Tell the receptionist this action is not allowed for their account.")
                if isinstance(data, list):
                    return 403, {"error": text}
                return 200, {"jsonrpc": "2.0", "id": m.get("id"),
                             "result": {"content": [{"type": "text", "text": text}], "isError": True}}
    return None


class AuthGuard:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":          # lifespan etc. go straight through
            return await self.app(scope, receive, send)
        user = verify_token(_bearer(scope))
        if user is None:
            return await _reply(send, 401, {"error": "Please log in again."})
        if scope["method"] != "POST":
            return await self.app(scope, receive, send)
        body = await _read_body(receive)
        refused = _refusal(body, user)
        if refused:
            return await _reply(send, *refused)
        return await self.app(scope, _replay(body, receive), send)