"""
Server-session binding for login tokens.

Every access token carries the id of the server run that issued it (the
`srv` claim). When the app is restarted - `docker compose restart web`,
`docker compose up` recreating the container, a host reboot, or a plain
restart of the dev server - the id changes, every token issued before the
restart fails verification with 401, and the frontend's authFetch() sends
the user back to the login page.

The id must be the same in every gunicorn worker of one run, otherwise
users would be signed out at random depending on which worker served the
request. Inside a container it is therefore derived from PID 1 (the
container's entrypoint, i.e. the gunicorn master): its start time changes
on every container (re)start but is identical for all workers. Outside a
container a random id per process is used, which is fine for the
single-process dev server (`python run.py`).

Set SESSION_EPOCH explicitly to override this (e.g. to keep users signed
in across restarts, or to share sessions across several replicas).
"""
from __future__ import annotations

import hashlib
import os
import uuid
from functools import lru_cache

CLAIM_NAME = "srv"
_ENV_OVERRIDE = "SESSION_EPOCH"


def _running_in_container() -> bool:
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    try:
        with open("/proc/1/cgroup", encoding="utf-8") as fh:
            content = fh.read()
        return any(marker in content for marker in ("docker", "containerd", "kubepods", "podman"))
    except OSError:
        return False


def _container_run_id() -> str | None:
    """Host boot time + PID 1 start time: unique per container start,
    shared by every process in the container."""
    try:
        with open("/proc/1/stat", encoding="utf-8") as fh:
            stat = fh.read()
        # Field 22 (starttime). The command name (field 2) may contain
        # spaces, so split after its closing parenthesis.
        fields_after_comm = stat.rsplit(")", 1)[1].split()
        pid1_start_ticks = fields_after_comm[19]

        boot_time = ""
        with open("/proc/stat", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("btime "):
                    boot_time = line.split()[1]
                    break
        return f"{boot_time}:{pid1_start_ticks}"
    except (OSError, IndexError):
        return None


@lru_cache(maxsize=1)
def current_server_epoch() -> str:
    """Opaque id of the current server run (cached for the process)."""
    override = os.getenv(_ENV_OVERRIDE, "").strip()
    if override:
        raw = f"env:{override}"
    else:
        container_id = _container_run_id() if _running_in_container() else None
        raw = f"ctr:{container_id}" if container_id else f"proc:{uuid.uuid4()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def session_claims() -> dict:
    """Extra claims to embed in every access token at login."""
    return {CLAIM_NAME: current_server_epoch()}


def register_jwt_session_checks(jwt_manager) -> None:
    """Rejects tokens issued before the current server run with 401."""
    from flask import jsonify

    @jwt_manager.token_verification_loader
    def _token_is_from_this_run(_jwt_header, jwt_data):
        return jwt_data.get(CLAIM_NAME) == current_server_epoch()

    @jwt_manager.token_verification_failed_loader
    def _token_from_previous_run(_jwt_header, _jwt_data):
        return jsonify({
            "status": "error",
            "reason": "session_expired",
            "message": "The server was restarted. Please sign in again.",
        }), 401
