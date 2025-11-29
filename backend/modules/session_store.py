import os
import json
import logging
from typing import List, Dict, Optional

logger = logging.getLogger("UFC_AGENT")

REDIS_URL = os.environ.get("REDIS_URL")

_redis = None
_in_memory_history: Dict[str, List[Dict[str, str]]] = {}
_in_memory_state: Dict[str, dict] = {}

if REDIS_URL:
    try:
        import redis

        _redis = redis.from_url(REDIS_URL)
        logger.info("ℹ️ [SESSION_STORE] Conectado ao Redis (REDIS_URL configurado)")
    except Exception as e:
        logger.warning(
            "Não foi possível conectar ao Redis (REDIS_URL). Irei usar fallback em memória: %s",
            e,
        )
        _redis = None


def _make_key(session_id: str) -> str:
    return f"chat:history:{session_id}"


def _make_state_key(session_id: str) -> str:
    return f"chat:state:{session_id}"


def create_session(
    session_id: str, initial_messages: Optional[List[Dict[str, str]]] = None
):
    initial_messages = initial_messages or []
    if _redis:
        _redis.set(_make_key(session_id), json.dumps(initial_messages))
    else:
        _in_memory_history[session_id] = initial_messages
    logger.debug(
        "ℹ️ [SESSION_STORE] create_session: session=%s messages=%s",
        session_id,
        len(initial_messages),
    )


def get_messages(session_id: str) -> Optional[List[Dict[str, str]]]:
    if _redis:
        raw = _redis.get(_make_key(session_id))
        if raw is None:
            return None
        try:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                return json.loads(raw) # type: ignore
        except Exception:
            return None
    result = _in_memory_history.get(session_id)
    logger.debug(
        "ℹ️ [SESSION_STORE] get_messages: session=%s found=%s", session_id, bool(result)
    )
    return result


def set_messages(session_id: str, messages: List[Dict[str, str]]):
    if _redis:
        _redis.set(_make_key(session_id), json.dumps(messages))
    else:
        _in_memory_history[session_id] = messages


def append_message(session_id: str, role: str, text: str):
    messages = get_messages(session_id)
    if messages is None:
        messages = []
    messages.append({"role": role, "content": text})
    set_messages(session_id, messages)
    logger.debug(
        "ℹ️ [SESSION_STORE] append_message: session=%s role=%s len=%s",
        session_id,
        role,
        len(messages),
    )


def delete_session(session_id: str):
    if _redis:
        _redis.delete(_make_key(session_id))
    else:
        _in_memory_history.pop(session_id, None)


def set_state(session_id: str, state: dict):
    if _redis:
        _redis.set(_make_state_key(session_id), json.dumps(state))
    else:
        _in_memory_state[session_id] = state
    logger.debug("ℹ️ [SESSION_STORE] set_state: session=%s state=%s", session_id, state)


def get_state(session_id: str) -> Optional[dict]:
    if _redis:
        raw = _redis.get(_make_state_key(session_id))
        if raw is None:
            return None
        try:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8")
                return json.loads(raw) # type: ignore
        except Exception:
            return None
    return _in_memory_state.get(session_id)


def list_sessions() -> List[str]:
    """Return list of session ids known in the store (history keys)."""
    if _redis:
        # Use scan_iter to avoid blocking server on large keyspaces
        keys = list(_redis.scan_iter(match=_make_key("*")))
        # keys are raw bytes or strings, parse and extract session id
        sessions = []
        for k in keys:
            try:
                ks = k.decode() if isinstance(k, bytes) else str(k)
                # format: chat:history:<session_id>
                parts = ks.split(":", 2)
                if len(parts) == 3:
                    sessions.append(parts[2])
            except Exception:
                continue
        return sessions
    return list(_in_memory_history.keys())


def clear_all_sessions() -> int:
    """Clear all sessions from the store (both history and state). Returns number of cleared sessions."""
    count = 0
    if _redis:
        # delete both history and state keys
        # We should use scan_iter to be safe on large sets
        for key in _redis.scan_iter(match=_make_key("*")):
            try:
                _redis.delete(key)
                count += 1
            except Exception:
                continue
        for key in _redis.scan_iter(match=_make_state_key("*")):
            try:
                _redis.delete(key)
                # don't increment again for the same session state; just count deletions
                count += 1
            except Exception:
                continue
        logger.info(
            "ℹ️ [SESSION_STORE] clear_all_sessions: deleted %s keys from Redis", count
        )
        return count
    else:
        count = len(_in_memory_history) + len(_in_memory_state)
        _in_memory_history.clear()
        _in_memory_state.clear()
        logger.info(
            "ℹ️ [SESSION_STORE] clear_all_sessions: cleared %s in-memory sessions", count
        )
        return count
