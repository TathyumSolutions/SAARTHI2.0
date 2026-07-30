"""
Authentication and Authorization Utilities
"""
import os
import time
import threading
from functools import wraps
from flask import jsonify, request
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

_redis_client = None
_redis_unavailable = False


def _get_redis_client():
    """Lazily connect to Redis (already provisioned via REDIS_URL). Falls
    back to None (triggering the in-memory limiter) if it can't connect."""
    global _redis_client, _redis_unavailable
    if _redis_client is not None or _redis_unavailable:
        return _redis_client
    try:
        import redis
        client = redis.from_url(
            os.environ.get("REDIS_URL", "redis://redis:6379/0"),
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()
        _redis_client = client
    except Exception:
        _redis_unavailable = True
        _redis_client = None
    return _redis_client


# In-memory fallback limiter: {key: (window_start_epoch, count)}. Only
# consistent within a single worker process - Redis is the real limiter
# whenever it's reachable.
_memory_buckets = {}
_memory_lock = threading.Lock()


def _rate_limit_key(scope: str) -> str:
    identity = None
    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
    except Exception:
        identity = None

    if identity:
        return f"ratelimit:{scope}:user:{identity}"

    forwarded = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "unknown")
    return f"ratelimit:{scope}:ip:{client_ip}"


def _is_rate_limited(key: str, max_requests: int, window: int) -> bool:
    client = _get_redis_client()
    if client is not None:
        try:
            count = client.incr(key)
            if count == 1:
                client.expire(key, window)
            return count > max_requests
        except Exception:
            pass  # fall through to in-memory limiter

    now = time.time()
    with _memory_lock:
        window_start, count = _memory_buckets.get(key, (now, 0))
        if now - window_start >= window:
            window_start, count = now, 0
        count += 1
        _memory_buckets[key] = (window_start, count)
        return count > max_requests


def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        identity = get_jwt_identity()
        from app.models.user import User
        user = User.query.get(int(identity)) if identity is not None else None
        if not user or user.role != "admin":
            return jsonify({"error": "Admin access required"}), 403
        return f(*args, **kwargs)
    return decorated_function


def workspace_access_required(f):
    """Decorator to check workspace access"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        verify_jwt_in_request()
        identity = get_jwt_identity()
        from app.models.user import User
        from app.models.workspace import Workspace

        user = User.query.get(int(identity)) if identity is not None else None
        if not user:
            return jsonify({"error": "User not found"}), 401

        workspace_id = kwargs.get("workspace_id")
        if workspace_id is None and request.view_args:
            workspace_id = request.view_args.get("workspace_id")
        if workspace_id is None:
            workspace_id = request.args.get("workspace_id")
        if workspace_id is None:
            body = request.get_json(silent=True) or {}
            workspace_id = body.get("workspace_id")

        if workspace_id is None:
            # No workspace scoping on this request - nothing to check access against.
            return f(*args, **kwargs)

        workspace = Workspace.query.get(workspace_id)
        if not workspace:
            return jsonify({"error": "Workspace not found"}), 404

        if user.role != "admin" and workspace.owner_id != user.id:
            return jsonify({"error": "You do not have access to this workspace"}), 403

        return f(*args, **kwargs)
    return decorated_function


def rate_limit(max_requests=60, window=60):
    """Decorator for rate limiting. Uses Redis when available (the app's
    existing REDIS_URL), otherwise falls back to a per-process in-memory
    fixed-window counter."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            key = _rate_limit_key(f.__name__)
            if _is_rate_limited(key, max_requests, window):
                return jsonify({
                    "error": "Rate limit exceeded. Please slow down and try again shortly."
                }), 429
            return f(*args, **kwargs)
        return decorated_function
    return decorator
