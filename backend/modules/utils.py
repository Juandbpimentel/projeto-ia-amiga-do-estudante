import re
import unicodedata
from typing import Any, List, Optional, Sequence
import datetime
import requests
from bs4 import BeautifulSoup, Tag
from .config import HEADERS


def _normalize_token(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^\w\s]", " ", ascii_text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold().strip()


def _cache_expired(
    timestamp: Optional[datetime.datetime], ttl: datetime.timedelta
) -> bool:
    import datetime

    if timestamp is None:
        return True
    if timestamp is None:
        return True
    return datetime.datetime.now() - timestamp > ttl


def _get_attr_value(tag: Tag, attr: str) -> str:
    value = tag.attrs.get(attr)
    if isinstance(value, (list, tuple)):
        value = value[0] if value else ""
    return str(value or "")


def fetch_html(
    url: str, *, timeout: int = 10, strip_tags: Optional[Sequence[str]] = None
) -> BeautifulSoup:
    # Keep verify=False to match previous behavior (logs a warning in main)
    resp = requests.get(url, headers=HEADERS, timeout=timeout, verify=False)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.content, "html.parser")
    if strip_tags:
        for tag in soup.find_all(strip_tags):
            tag.extract()
    return soup


def _collect_text_parts(source: Any) -> List[str]:
    texts: List[str] = []
    if source is None:
        return texts
    parts = getattr(source, "parts", None)
    if parts is None and isinstance(source, (list, tuple)):
        parts = source
    if parts is None:
        return texts
    for part in parts:
        text_value = getattr(part, "text", None)
        if isinstance(text_value, str):
            stripped = text_value.strip()
            if stripped:
                texts.append(stripped)
    return texts


def _render_response_text(response: Any) -> str:
    if response is None:
        return ""
    text = getattr(response, "text", None)
    if isinstance(text, str) and text.strip():
        return text.strip()
    collected: List[str] = []
    collected.extend(_collect_text_parts(response))
    content = getattr(response, "content", None)
    if content:
        if isinstance(content, (list, tuple)):
            for item in content:
                collected.extend(_collect_text_parts(item))
        else:
            collected.extend(_collect_text_parts(content))
    candidates = getattr(response, "candidates", None)
    if candidates:
        for candidate in candidates:
            cand_text = getattr(candidate, "text", None)
            if isinstance(cand_text, str) and cand_text.strip():
                collected.append(cand_text.strip())
            collected.extend(_collect_text_parts(candidate))
            cand_content = getattr(candidate, "content", None)
            if cand_content:
                if isinstance(cand_content, (list, tuple)):
                    for item in cand_content:
                        collected.extend(_collect_text_parts(item))
                else:
                    collected.extend(_collect_text_parts(cand_content))
    output = getattr(response, "output", None)
    if isinstance(output, (list, tuple)):
        for item in output:
            if isinstance(item, str) and item.strip():
                collected.append(item.strip())
            else:
                collected.extend(_collect_text_parts(item))
    if collected:
        seen = set()
        unique_texts: List[str] = []
        for value in collected:
            if value in seen:
                continue
            seen.add(value)
            unique_texts.append(value)
        return "\n\n".join(unique_texts)
    return ""


def _match_option_by_user_input(user_input: str, options: List[str]) -> Optional[str]:
    if not user_input or not options:
        return None
    norm_msg = _normalize_token(user_input)
    for opt in options:
        if isinstance(opt, str) and opt.casefold() == user_input.casefold():
            return opt
    for opt in options:
        if not isinstance(opt, str):
            continue
        if norm_msg == _normalize_token(opt):
            return opt
    for opt in options:
        if not isinstance(opt, str):
            continue
        opt_norm = _normalize_token(opt)
        if norm_msg in opt_norm or opt_norm in norm_msg:
            return opt
    try:
        names = [o for o in options if isinstance(o, str)]
        close = __import__("difflib").get_close_matches(
            user_input, names, n=1, cutoff=0.60
        )
        if close:
            return close[0]
    except Exception:
        pass
    return None


def extract_professor_from_row(row: Any) -> Optional[str]:
    """Extrai o nome do professor de uma linha de alocação/horário.
    Procura por chaves explícitas como 'Professor' ou heurísticas em _row_text.
    Retorna o nome como string se encontrado, caso contrário None.
    """
    if not row or not isinstance(row, dict):
        return None
    # Prefer explicit 'Professor' field
    if row.get("Professor"):
        return row.get("Professor")
    # search in keys for professor-like cells (e.g., 'Prof', 'Docente')
    for k, v in row.items():
        if isinstance(k, str) and isinstance(v, str):
            key = k.lower()
            if any(w in key for w in ["prof", "docente", "professor"]):
                if v.strip():
                    return v.strip()
    # fallback: parse _row_text segments and prefer last segment that looks like a name
    texto = row.get("_row_text") or ""
    if texto:
        parts = [p.strip() for p in re.split(r"\|+|\n+|\t+", texto) if p.strip()]
        # reverse order and pick candidate with >=2 tokens and no digits
        for part in reversed(parts):
            if len(part.split()) >= 2 and not re.search(r"\d", part):
                return part
    return None


def _resolver_link_google_docs(url: str) -> List[str]:
    candidates: List[str] = []
    match = re.search(r"/d/([\w-]+)/", url)
    if match:
        doc_id = match.group(1)
        export = f"https://docs.google.com/document/d/{doc_id}/export?format=html"
        export_txt = f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
        candidates.append(export)
        candidates.append(export + "&embedded=true")
        candidates.append(export_txt)
        candidates.append(f"https://docs.google.com/document/d/{doc_id}/preview")
        candidates.append(url)
    else:
        candidates = [url]
    return candidates
