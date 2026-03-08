"""
Canvas LMS authentication store.

Manages personal access tokens for the Canvas API on a per-user basis.
Tokens are stored in memory and persisted to Supabase (canvas_tokens table)
using the service role key so RLS doesn't block backend writes.
"""

import logging
import os
import requests

logger = logging.getLogger(__name__)

CANVAS_BASE_URL = "https://byu.instructure.com"

# Per-user token store: user_id -> {token, user_name}
_tokens: dict[str, dict] = {}


def _get_supabase():
    """Create a Supabase client using the service key (bypasses RLS)."""
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if url and key:
        try:
            from supabase import create_client
            return create_client(url, key)
        except Exception as e:
            logger.warning(f"canvas_auth_store: could not create Supabase client: {e}")
    return None


def validate_token(token: str) -> tuple[bool, str]:
    """Validate a Canvas API token by calling /api/v1/users/self.

    Does not require a user_id — just validates the token against Canvas.

    Returns:
        Tuple of (is_valid, user_name_or_error_message)
    """
    try:
        resp = requests.get(
            f"{CANVAS_BASE_URL}/api/v1/users/self",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            name = data.get("name") or data.get("short_name") or "Canvas User"
            return True, name
        elif resp.status_code == 401:
            return False, "Invalid token. Please check and try again."
        else:
            return False, f"Canvas API returned status {resp.status_code}"
    except requests.exceptions.ConnectionError:
        return False, "Could not connect to Canvas. Check your network."
    except requests.exceptions.Timeout:
        return False, "Connection to Canvas timed out."
    except Exception as e:
        return False, str(e)


def set_token(user_id: str, token: str, user_name: str = ""):
    """Store a validated Canvas token for a user and persist to Supabase."""
    _tokens[user_id] = {"token": token, "user_name": user_name}

    sb = _get_supabase()
    if sb:
        try:
            from datetime import datetime, timezone
            sb.table("canvas_tokens").upsert({
                "user_id": user_id,
                "token": token,
                "user_name": user_name,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="user_id").execute()
        except Exception as e:
            logger.warning(f"canvas_auth_store: failed to persist token for {user_id}: {e}")


def get_token(user_id: str) -> str | None:
    """Get the stored Canvas token for a user.

    Checks in-memory dict first, then loads from Supabase if not found.
    """
    if user_id in _tokens:
        return _tokens[user_id].get("token")

    # Try loading from Supabase
    sb = _get_supabase()
    if sb:
        try:
            r = sb.table("canvas_tokens").select("*").eq("user_id", user_id).execute()
            if r.data:
                row = r.data[0]
                _tokens[user_id] = {
                    "token": row.get("token"),
                    "user_name": row.get("user_name") or "",
                }
                return _tokens[user_id]["token"]
        except Exception as e:
            logger.warning(f"canvas_auth_store: failed to load token for {user_id}: {e}")

    return None


def get_user_name(user_id: str) -> str | None:
    """Get the stored Canvas user name for a user."""
    if user_id not in _tokens:
        # Trigger a load from Supabase via get_token
        get_token(user_id)
    return _tokens.get(user_id, {}).get("user_name")


def clear_token(user_id: str):
    """Clear the stored token for a user (memory + Supabase)."""
    _tokens.pop(user_id, None)

    sb = _get_supabase()
    if sb:
        try:
            sb.table("canvas_tokens").delete().eq("user_id", user_id).execute()
        except Exception as e:
            logger.warning(f"canvas_auth_store: failed to delete token for {user_id}: {e}")


def is_connected(user_id: str) -> bool:
    """Check if a Canvas token is stored for a user."""
    return get_token(user_id) is not None
