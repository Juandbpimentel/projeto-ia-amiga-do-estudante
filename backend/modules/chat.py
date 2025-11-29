from typing import Any, Dict, List
import os
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from google import genai
from google.genai import types
from .utils import _match_option_by_user_input, _render_response_text
from .session_store import (
    get_messages,
    append_message,
    create_session,
    get_state,
    set_state,
)

logger = logging.getLogger("UFC_AGENT")


# Minimal ChatRequest/StartResponse models to be used by main routes
class ChatRequest(BaseModel):
    message: str


class StartResponse(BaseModel):
    session_id: str
    message: str


# Holds sessions created by the Chat SDK
chat_sessions: Dict[str, Any] = {}


def start_chat(
    client: genai.Client,
    model_name: str,
    session_id: str,
    my_tools: List[Any],
    session_state: Dict[str, Dict[str, Any]],
    system_instr: str,
    logger: logging.Logger,
    temperature: float = 0.7,
) -> Dict[str, Any]:
    """Create a new chat session using the given client and register it locally.
    Returns a dictionary with session info to be returned to routes.
    """

    fname = f"contexto_{session_id}.txt"
    try:
        # Save context to disk briefly for diagnostics
        try:
            with open(fname, "w", encoding="utf-8") as f:
                f.write(system_instr)
            logger.info(f"ℹ️ [SISTEMA] Arquivo de contexto salvo: {fname}")
        except OSError as e:
            logger.error(f"❌ [ERRO] Falha ao salvar arquivo de contexto: {e}")

        chat_obj = client.chats.create(
            model=model_name,
            config=types.GenerateContentConfig(
                system_instruction=system_instr,
                tools=my_tools,
                temperature=temperature,
                automatic_function_calling=types.AutomaticFunctionCallingConfig(
                    disable=False
                ),
            ),
        )
        chat_sessions[session_id] = chat_obj
        # Initialize session state
        session_state.setdefault(session_id, {})["pending_selection"] = None

        welcome_msg = (
            "Olá! Sou o assistente virtual da UFC Quixadá. 🎓\n\n"
            "Posso ajudar com:\n\n"
            "🍛 **Cardápio do RU:** Consulte o almoço ou jantar.\n\n"
            "📅 **Feriados e Calendário:** Datas importantes, recessos e feriados.\n\n"
            "🌐 **Status dos Sistemas:** Verifique se o Sigaa ou Moodle estão online.\n\n"
            "👩‍🏫 **Professores:** Descubra e-mails, Lattes ou onde estarão em sala.\n\n"
            "Como posso ajudar você hoje?"
        )

        # Store session into a centralized store so other workers can rehydrate it later
        try:
            create_session(
                session_id,
                [
                    {"role": "system", "content": system_instr},
                    {"role": "assistant", "content": welcome_msg},
                ],
            )
            set_state(session_id, {"pending_selection": None})
        except Exception:
            # If session store not configured, ignore and fallback to in-memory
            pass

        # Context loaded into the chat SDK; remove the temp file from disk.
        try:
            if os.path.exists(fname):
                os.remove(fname)
                logger.info(f"ℹ️ [SISTEMA] Arquivo de contexto removido: {fname}")
        except Exception as exc:
            logger.warning(f"⚠️ [SISTEMA] Falha ao remover arquivo de contexto: {exc}")
        return {"session_id": session_id, "message": welcome_msg}
    except Exception as e:
        # General guard: translate SDK errors into a user-friendly message
        msg = str(e)
        logger.critical(f"❌ [ERRO CRÍTICO] Falha ao iniciar SDK do Google: {msg}")
        # Handle quota/rate limits specifically
        if (
            "RESOURCE_EXHAUSTED" in msg
            or "quota" in msg.lower()
            or "rate-limits" in msg.lower()
        ):
            logger.warning("⚠️ [SISTEMA] SDK quota/rate-limited error: %s", msg)
            # Return a friendly message to the user
            raise HTTPException(
                status_code=503,
                detail=(
                    "Erro interno temporário: limite de requisições atingido. "
                    "Tente novamente em alguns instantes."
                ),
            )
        # Default catch-all
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro interno no servidor ao iniciar o chat. Por favor, tente novamente mais tarde."
            ),
        )


def handle_chat_message(
    client: genai.Client,
    session_id: str,
    message: str,
    session_state: Dict[str, Dict[str, Any]],
    logger: logging.Logger,
    my_tools: List[Any] = None,
) -> Dict[str, Any]:
    """Handle a chat message: process pending selection or forward to the chat SDK.
    Returns a dictionary with the final text to reply.
    """
    # Prefer messages from the shared session store; if no messages exist, the session is invalid.
    messages = get_messages(session_id)
    if messages is None:
        logger.warning(
            f"⚠️ [SISTEMA] Tentativa de acesso a sessão inválida: {session_id}"
        )
        raise HTTPException(status_code=404, detail="Sessão inválida")

    # If a local chat object isn't available (e.g., another worker created the session), rehydrate it.
    chat_obj = chat_sessions.get(session_id)
    if chat_obj is None:
        logger.info(
            "ℹ️ [SISTEMA] Rehidratando sessão de chat (session=%s) usando histórico compartilhado",
            session_id,
        )
        try:
            # Create a fresh chat object with the same system instructions and replay the conversation
            chat_obj = client.chats.create(
                model=os.environ.get("MODEL_NAME", "gpt-4o-mini"),
                config=types.GenerateContentConfig(
                    system_instruction=messages[0]["content"] if messages else "",
                    tools=my_tools,
                    temperature=0.7,
                    automatic_function_calling=types.AutomaticFunctionCallingConfig(
                        disable=False
                    ),
                ),
            )
            # Replay prior user messages to rebuild conversation context in the SDK. This makes additional
            # API requests, which can incur costs but ensures context is consistent across workers.
            for m in messages:
                if m.get("role") == "user":
                    try:
                        chat_obj.send_message(m.get("content", ""))
                    except Exception:
                        # Don't let replay failures stop the request; the chat will proceed with the new message.
                        logger.debug(
                            "⚠️ [SISTEMA] Falha ao reidratar mensagem do histórico (session=%s)",
                            session_id,
                        )
            # store for this worker for faster subsequent requests
            chat_sessions[session_id] = chat_obj
        except Exception as exc:
            logger.exception("Falha ao reidratar sessão: %s", exc)
            raise HTTPException(
                status_code=500, detail="Erro ao reidratar sessão do chat"
            )

    # If there's pending selection, try to interpret user message as a selection.
    # Load persisted state (from Redis/fallback store) to support multi-worker environments.
    persisted_state = get_state(session_id) or {}
    pending = persisted_state.get("pending_selection") or session_state.get(
        session_id, {}
    ).get("pending_selection")
    if pending:
        options: List[str] = pending.get("options", [])
        queries: List[str] = pending.get("queries", [])
        msg = (message or "").strip()
        chosen = None
        if msg.isdigit():
            idx = int(msg) - 1
            if 0 <= idx < len(options):
                chosen_query = queries[idx] if idx < len(queries) else options[idx]
                chosen = chosen_query
        if not chosen:
            matched_display = _match_option_by_user_input(msg, options)
            if matched_display:
                try:
                    idx = options.index(matched_display)
                    chosen_query = (
                        queries[idx] if idx < len(queries) else matched_display
                    )
                    chosen = chosen_query
                except ValueError:
                    chosen = matched_display
        if chosen:
            # clear pending selection in both local and persisted state
            session_state.setdefault(session_id, {})["pending_selection"] = None
            try:
                set_state(session_id, {**persisted_state, "pending_selection": None})
            except Exception:
                pass
            # log and return the chosen query as a simple text response
            logger.debug(
                "ℹ️ [CHAT] Seleção confirmada: %s -> %s (session=%s)",
                message,
                chosen,
                session_id,
            )
            return {"message": f"Confirmado: {chosen}", "selected_query": chosen}

    # otherwise, forward to SDK
    try:
        # Append user message to the centralized history before calling the SDK
        try:
            append_message(session_id, "user", message)
        except Exception:
            pass

        response = chat_obj.send_message(message)
        text = _render_response_text(response)
        if not text or not str(text).strip():
            logger.error("❌ [ERRO] Resposta vazia do modelo (session=%s)", session_id)
            # Return friendly message
            raise HTTPException(
                status_code=500,
                detail="Erro interno no servidor: resposta vazia do modelo. Tente novamente mais tarde.",
            )
        # persist assistant response back to the shared history
        try:
            append_message(session_id, "assistant", text)
        except Exception:
            pass
        return {"message": text}
    except Exception as e:
        msg = str(e)
        logger.exception("Erro ao enviar mensagem para SDK: %s", e)
        if (
            "RESOURCE_EXHAUSTED" in msg
            or "quota" in msg.lower()
            or "rate-limits" in msg.lower()
        ):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Erro interno temporário: limite de requisições atingido. "
                    "Tente novamente em alguns instantes."
                ),
            )
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro interno no servidor ao processar sua mensagem. Por favor, tente novamente mais tarde."
            ),
        )
