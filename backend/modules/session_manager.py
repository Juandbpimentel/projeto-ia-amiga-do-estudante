from typing import Any, Dict, List
import logging
import asyncio
import inspect
from google import genai
from google.genai import types
from .session_store import get_messages, is_redis_available
from . import tooling

logger = logging.getLogger("UFC_AGENT")

# Local per-worker cache of chat SDK objects
chat_sessions: Dict[str, Any] = {}


def clear_local_sessions():
    chat_sessions.clear()


def get_local_chat(session_id: str) -> Any:
    return chat_sessions.get(session_id)


def ensure_chat_obj(
    client: genai.Client,
    session_id: str,
    my_tools: List[Any],
    system_instr: str,
    model_name: str = "gpt-4o-mini",
) -> Any:
    """Ensure we have a chat object for this session (create and rehydrate if needed).
    This is a synchronous wrapper that awaits async callables when needed.
    """
    if session_id in chat_sessions:
        return chat_sessions[session_id]

    # Create a fresh chat object with the same system instructions
    try:
        chat_obj = client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=system_instr,
                tools=my_tools,
                temperature=0.7,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False
                ),
            ),
        )
    except Exception as e:
        logger.exception("Erro ao criar chat SDK: %s", e)
        raise

    # Replay prior user messages to rebuild conversation context in the SDK. This makes additional
    # API requests, which can incur costs but ensures context is consistent across workers.
    messages = get_messages(session_id) or []
    logger.debug(
        "ℹ️ [SESSION_MANAGER] ensure_chat_obj: session=%s messages_loaded=%s redis=%s",
        session_id,
        len(messages),
        is_redis_available(),
    )
    for m in messages:
        if m.get("role") == "user":
            try:
                resp = chat_obj.send_message(m.get("content", ""))
                resp = tooling._await_if_needed(resp)
            except Exception:
                logger.debug("⚠️ [SISTEM]Falha ao reidratar mensagem: %s", session_id)

    chat_sessions[session_id] = chat_obj
    return chat_obj
