from typing import Any, Dict, List, Optional, Callable, Tuple
import logging
import json
import asyncio
import inspect

logger = logging.getLogger("UFC_AGENT")


def find_tool_by_name(my_tools: List[Any], func_name: str) -> Optional[Any]:
    """Return the tool matching func_name using multiple tolerant checks.

    Supports: __name__, __qualname__, module-prefixed names, decorated/wrapped functions,
    and case-insensitive matches. Returns None when not found.
    """
    if not my_tools or not func_name:
        return None
    key = func_name.casefold()
    tools_map: Dict[str, Any] = {}
    for t in my_tools:
        # try to find a readable name for the tool
        name_candidates = []
        n = getattr(t, "__name__", None)
        if n:
            name_candidates.append(n)
        q = getattr(t, "__qualname__", None)
        if q and q != n:
            name_candidates.append(q)
        # unwrap decorated callables if present
        wrapped = getattr(t, "__wrapped__", None)
        if wrapped:
            wn = getattr(wrapped, "__name__", None)
            if wn and wn not in name_candidates:
                name_candidates.append(wn)
            wq = getattr(wrapped, "__qualname__", None)
            if wq and wq not in name_candidates:
                name_candidates.append(wq)

        # also register module-qualified name
        mod_key = f"{getattr(t, '__module__', '')}.{getattr(t, '__name__', '')}"
        for cand in name_candidates:
            tools_map[cand.casefold()] = t
            tools_map[f"{getattr(t, '__module__', '')}.{cand}".casefold()] = t
        if mod_key:
            tools_map[mod_key.casefold()] = t

    # try direct match
    target = tools_map.get(key)
    if target:
        return target
    # try stripping module prefixes
    short = func_name.split(".")[-1].casefold()
    target = tools_map.get(short)
    if target:
        return target
    # fallback: search for a tool whose function name contains the key fragment
    for k, t in tools_map.items():
        if key in k:
            return t
    return None


def is_status_query(text: str) -> bool:
    """Return True if the user's message appears to be asking for site status (Sigaa/Moodle)."""
    if not text or not isinstance(text, str):
        return False
    import re

    pattern = r"\bsigaa\b|\bmoodle\b|status do (sigaa|moodle)|est[áa]\s*online|est[áa]\s*funcion(a|ando)|funciona(n|ndo)|(moodle|sigaa)\s*funcion"
    return bool(re.search(pattern, text, flags=re.IGNORECASE))


def safe_call_tool(target: Any, kwargs: Optional[dict]) -> Tuple[bool, str]:
    try:
        res = target(**(kwargs or {}))
        # If the target returns a coroutine, await it to get the final result
        res = _await_if_needed(res)
        if isinstance(res, (dict, list)):
            try:
                res = json.dumps(res, ensure_ascii=False, indent=2)
            except Exception:
                res = str(res)
        return True, str(res or "")
    except Exception as e:
        logger.exception(
            "Erro ao executar ferramenta %s: %s",
            getattr(target, "__name__", str(target)),
            e,
        )
        return False, f"Erro ao executar ferramenta: {e}"


def _await_if_needed(obj: Any) -> Any:
    if inspect.isawaitable(obj):
        try:
            return asyncio.get_event_loop().run_until_complete(obj)
        except RuntimeError:

            async def _await_coro(r):
                return await r

            return asyncio.run(_await_coro(obj))
    return obj


def append_tool_and_ask_model(
    chat_obj: Any,
    session_id: str,
    append_message: Callable[[str, str, str], None],
    target_name: str,
    result_text: str,
    format_prompt: Optional[str] = None,
) -> Tuple[str, bool]:
    """Append the raw tool output and ask the model to format it.
    Returns (reply_text, True) on success or (fallback_text, False).
    """
    # persist the tool result to the shared history first
    try:
        append_message(session_id, "tool", f"{target_name} output:\n{result_text}")
    except Exception:
        pass

    if not format_prompt:
        format_prompt = (
            "Use os dados gerados pela ferramenta acima e responda de forma curta e amigável "
            "ao usuário. Apenas retorne a resposta final em Português."
        )

    # To ensure the model sees the actual tool output in this request (SDK history might not
    # be in sync with the persisted session store), we include the result_text inline in the
    # prompt we send to the model so it can format the provided output.
    try:
        combined_prompt = f"{target_name} output:\n{result_text}\n\n{format_prompt}"
        followup = chat_obj.send_message(combined_prompt)
        followup = _await_if_needed(followup)
        # Render back in calling code using the SDK's render utils; return raw text
        # We return the followup object for the caller to render if needed.
        return followup, True
    except Exception as e:
        logger.debug("Falha ao formatar pelo modelo: %s", e)
        return result_text, False


def handle_tool_invocation(
    chat_obj: Any,
    my_tools: List[Any],
    func_name: str,
    kwargs: Optional[dict],
    session_id: str,
    message_text: str,
    append_message_fn: Callable[[str, str, str], None],
    render_fn: Callable[[Any], str],
) -> Optional[Dict[str, str]]:
    """Attempts to find and run a tool by name (structured or textual). If found,
    calls the tool, appends the tool output, asks the model to format it and returns the final
    assistant message dict { 'message': text } or None if not a matching tool.
    """
    target = find_tool_by_name(my_tools, func_name)
    if not target:
        return None
    logger.debug(
        "ℹ️ [TOOLING] Invoking tool: %s (resolved=%s)",
        func_name,
        getattr(target, "__name__", str(target)),
    )
    ok, result_text = safe_call_tool(target, kwargs)
    if not ok:
        # Return friendly fallback
        return {"message": result_text}
    # Append and ask the model to format the output
    followup, formatted = append_tool_and_ask_model(
        chat_obj,
        session_id,
        append_message_fn,
        getattr(target, "__name__", func_name),
        result_text,
    )
    if formatted:
        # render followup object text using provided render function
        try:
            msg = render_fn(followup)
            if msg:
                try:
                    append_message_fn(session_id, "assistant", msg)
                except Exception:
                    pass
                return {"message": msg}
        except Exception:
            pass
    # fallback return raw tool output
    try:
        append_message_fn(session_id, "assistant", result_text)
    except Exception:
        pass
    return {"message": result_text}


def parse_tool_call_from_text(text: str):
    """Try to detect a tool call represented as text like `default_api.find_prof(name="X")`.
    Returns (func_name, kwargs) or (None, None).
    """
    import re

    if not text or not isinstance(text, str):
        return None, None
    lowered = text.casefold()
    # Heuristics: skip if the model is giving code examples or the text includes example markers
    if (
        "exemplo" in lowered
        or "ex:" in lowered
        or "```" in text
        or "```python" in lowered
    ):
        return None, None
    # Look for a bare function-like invocations; prefer matches at the start of a line to
    # avoid matching textual examples embedded inside the model output.
    m = re.search(r"^\s*([\w\.]+)\s*\((.*)\)", text, flags=re.M)
    if not m:
        return None, None
    full_name = m.group(1).strip()
    args_str = m.group(2).strip()
    func_name = full_name.split(".")[-1]
    kwargs = {}
    parts = []
    curr = []
    depth = 0
    in_quote = False
    quote_char = None
    for ch in args_str:
        if ch in ('"', "'"):
            if in_quote and ch == quote_char:
                in_quote = False
                quote_char = None
            elif not in_quote:
                in_quote = True
                quote_char = ch
        if not in_quote:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(curr).strip())
                curr = []
                continue
        curr.append(ch)
    if curr:
        parts.append("".join(curr).strip())
    for part in parts:
        if not part or "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        v = v.strip().rstrip(",")
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            val = v[1:-1]
        elif v.lower() in ("true", "false"):
            val = v.lower() == "true"
        else:
            try:
                val = int(v)
            except Exception:
                try:
                    val = float(v)
                except Exception:
                    val = v
        kwargs[k] = val
    return func_name, kwargs


def extract_function_call_from_response(response: Any):
    """Extract structured function call from SDK response objects.
    Returns (func_name, kwargs) or (None, None)
    """
    try:
        fc = getattr(response, "function_call", None)
        if fc:
            name = getattr(fc, "name", None)
            args_raw = getattr(fc, "arguments", None)
            if args_raw and isinstance(args_raw, str):
                try:
                    args = json.loads(args_raw)
                except Exception:
                    args = {}
            elif isinstance(args_raw, dict):
                args = args_raw
            else:
                args = {}
            return name, args
    except Exception:
        pass
    candidates = getattr(response, "candidates", None)
    if candidates:
        for cand in candidates:
            fc = getattr(cand, "function_call", None) or getattr(cand, "tool", None)
            if fc:
                name = getattr(fc, "name", None)
                args_raw = getattr(fc, "arguments", None)
                try:
                    args = (
                        json.loads(args_raw)
                        if isinstance(args_raw, str)
                        else args_raw or {}
                    )
                except Exception:
                    args = {}
                return name, args
            content = getattr(cand, "content", None)
            if isinstance(content, dict) and (
                content.get("name") or content.get("arguments")
            ):
                name = content.get("name")
                args = content.get("arguments") or {}
                return name, args
    return None, None
