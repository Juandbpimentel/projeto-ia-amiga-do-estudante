from typing import Any, Dict, List
import inspect
import asyncio
import os
import logging
from fastapi import HTTPException
from pydantic import BaseModel
from google import genai

# types from google.genai used by session_manager if needed; not directly in chat.py
from .utils import _match_option_by_user_input, _render_response_text
from .tooling import (
    handle_tool_invocation,
    parse_tool_call_from_text,
    extract_function_call_from_response,
)
from .session_manager import ensure_chat_obj, get_local_chat

from .session_store import (
    get_messages,
    append_message,
    create_session,
    get_state,
    set_state,
)

logger = logging.getLogger("UFC_AGENT")


def _parse_tool_call_from_text(text: str):
    return parse_tool_call_from_text(text)


def _extract_function_call_from_response(response: Any):
    return extract_function_call_from_response(response)


# Minimal ChatRequest/StartResponse models to be used by main routes
class ChatRequest(BaseModel):
    message: str


class StartResponse(BaseModel):
    session_id: str
    message: str


# Holds sessions created by the Chat SDK
# note: chat_sessions is managed by `session_manager` module


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

        # Create/retrieve the chat_obj and store it via session_manager
        # Ensure the chat object is created and rehydrated for this session
        _ = ensure_chat_obj(client, session_id, my_tools, system_instr, model_name)
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
            logger.debug("ℹ️ [SESSION] Persistida nova sessão: %s", session_id)
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
    my_tools: List[Any] = None,  # type: ignore
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

    # Ensure we have a local chat object; delegate rehydration to session_manager
    chat_obj = get_local_chat(session_id)
    if chat_obj is None:
        logger.info(
            "ℹ️ [SISTEMA] Rehidratando sessão de chat (session=%s) usando histórico compartilhado",
            session_id,
        )
        try:
            chat_obj = ensure_chat_obj(
                client,
                session_id,
                my_tools,
                messages[0]["content"] if messages else "",
                os.environ.get("MODEL_NAME", "gpt-4o-mini"),
            )
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

        # delegate tool handling to `modules.tooling.handle_tool_invocation`

        # Quick heuristic: if user directly asks about Sigaa/Moodle status, call the tool
        import re

        if re.search(
            r"\bsigaa\b|\bmoodle\b|status do (sigaa|moodle)|est[áa] online",
            message,
            flags=re.IGNORECASE,
        ):
            # find the function in my_tools quickly
            target = None
            for t in my_tools or []:
                if hasattr(t, "__name__") and t.__name__.casefold().endswith(
                    "verifica_status_sites_para_os_estudantes"
                ):
                    target = t
                    break
            if target:
                out = handle_tool_invocation(
                    chat_obj,
                    my_tools,
                    getattr(
                        target, "__name__", "verifica_status_sites_para_os_estudantes"
                    ),
                    {},
                    session_id,
                    message,
                    append_message,
                    _render_response_text,
                )
                if out:
                    return out
                # else continue to SDK fallback

        response = chat_obj.send_message(message)
        # If SDK returned an awaitable (async variant), await it synchronously
        try:
            if inspect.isawaitable(response):
                try:
                    response = asyncio.get_event_loop().run_until_complete(response)
                except RuntimeError:
                    # If there's an already running event loop, fallback to asyncio.run
                    async def _await(resp):
                        return await resp

                    response = asyncio.run(_await(response))
        except Exception:
            # If the check or awaiting failed, continue and let logging handle the error.
            pass
        # Ensure we work with a resolved response object for type checking
        resolved_response: Any = response
        # Debug: log response structure to help diagnose empty responses
        try:
            resp_type = type(resolved_response)
            cand_len = (
                len(resolved_response.candidates)
                if hasattr(resolved_response, "candidates")
                and resolved_response.candidates
                else 0
            )
            first_candidate = None
            if cand_len > 0:
                cand0 = resolved_response.candidates[0]
                raw_value = getattr(cand0, "content", None) or getattr(
                    cand0, "text", None
                )
                if isinstance(raw_value, (list, tuple)):
                    # pick the first textual part
                    first_candidate = str(raw_value[0]) if raw_value else None
                else:
                    first_candidate = str(raw_value) if raw_value is not None else None
            logger.debug(
                "ℹ️ [CHAT] SDK response: type=%s candidates=%s first_cand_preview=%s",
                resp_type,
                cand_len,
                (first_candidate[:200] if first_candidate else None),
            )
        except Exception as e:
            logger.debug("⚠️ [CHAT] Falha ao logar detalhes da response SDK: %s", e)
        # If the model returned an instruction to call a tool (e.g., printed a code snippet),
        # try to detect it and execute the corresponding Python function if available.
        # Render text from the resolved response (after awaiting async variants)
        text = _render_response_text(resolved_response)
        if not text or not str(text).strip():
            # Keep text empty for now and rely on other logic
            pass

        # Try to detect structured function_call in the SDK response
        try:
            func_name, kwargs = _extract_function_call_from_response(resolved_response)
            if func_name and my_tools:
                # Build a tolerant tools map: key by name lower-case and with/without module prefixes
                tools_map = {}
                for t in my_tools:
                    if not hasattr(t, "__name__"):
                        continue
                    name_key = t.__name__.casefold()
                    tools_map[name_key] = t
                    # also register with full module name if present
                    mod_key = f"{t.__module__}.{t.__name__}".casefold()
                    tools_map[mod_key] = t
                target = tools_map.get((func_name or "").casefold())
                if target is None:
                    # try strip prefixes like 'default_api.' or 'api.'
                    target = tools_map.get(func_name.split(".")[-1].casefold())
                if target:
                    logger.info(
                        "ℹ️ [CHAT] Executando ferramenta (struct) '%s' com args=%s (session=%s)",
                        func_name,
                        kwargs,
                        session_id,
                    )
                    out = handle_tool_invocation(
                        chat_obj,
                        my_tools,
                        func_name,
                        kwargs,
                        session_id,
                        message,
                        append_message,
                        _render_response_text,
                    )
                    if out:
                        return out
        except Exception as err:
            logger.debug(
                "⚠️ [CHAT] Falha ao extrair função estruturada do response: %s", err
            )

        # Try to detect tool invocation inside textual output (printed code)
        try:
            func_name, kwargs = _parse_tool_call_from_text(text or "")
            if func_name and my_tools:
                # Build tolerant mapping for textual tool calls too
                tools_map = {}
                for t in my_tools:
                    if not hasattr(t, "__name__"):
                        continue
                    name_key = t.__name__.casefold()
                    tools_map[name_key] = t
                    mod_key = f"{t.__module__}.{t.__name__}".casefold()
                    tools_map[mod_key] = t
                target = tools_map.get(func_name.casefold())
                if target is None:
                    target = tools_map.get(func_name.split(".")[-1].casefold())
                if target:
                    logger.info(
                        "ℹ️ [CHAT] Executando ferramenta '%s' com args=%s (session=%s)",
                        func_name,
                        kwargs,
                        session_id,
                    )
                    out = handle_tool_invocation(
                        chat_obj,
                        my_tools,
                        func_name,
                        kwargs,
                        session_id,
                        message,
                        append_message,
                        _render_response_text,
                    )
                    if out:
                        return out
        except Exception as parse_exc:
            logger.debug(
                "⚠️ [CHAT] Falha ao analisar chamada de ferramenta do texto: %s",
                parse_exc,
            )
        if not text or not str(text).strip():
            # Log and retry once
            logger.warning(
                "⚠️ [CHAT] Modelo retornou resposta vazia (session=%s). Tentando retry 1x",
                session_id,
            )
            try:
                response = chat_obj.send_message(message)
                text = _render_response_text(response)
            except Exception as retry_exc:
                logger.debug("⚠️ [CHAT] Retry falhou ao chamar modelo: %s", retry_exc)
        if not text or not str(text).strip():
            logger.error(
                "❌ [ERRO] Resposta vazia do modelo após retry (session=%s)", session_id
            )
            raise HTTPException(
                status_code=500,
                detail=(
                    "Erro interno no servidor: resposta vazia do modelo. Tente novamente mais tarde."
                ),
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
