from typing import Dict, List, OrderedDict, Union, Optional
import logging
import datetime
import re
from bs4 import BeautifulSoup, Tag
from .utils import _normalize_token, fetch_html
from .config import SECTION_LABELS

logger = logging.getLogger("UFC_AGENT")


def extract_cardapio_sections(
    content: Union[BeautifulSoup, Tag],
) -> Dict[str, OrderedDict[str, List[str]]]:
    lines = [
        line.strip()
        for line in content.get_text(separator="\n").splitlines()
        if line.strip()
    ]
    sections: Dict[str, OrderedDict[str, List[str]]] = {}
    current_section = None
    current_category = None

    for raw_line in lines:
        token = _normalize_token(raw_line)
        if token in SECTION_LABELS:
            label = SECTION_LABELS[token]
            current_section = label
            sections.setdefault(label, OrderedDict())
            current_category = None
            continue

        if current_section is None:
            continue

        category = None
        value = None
        if "\t" in raw_line:
            category, value = [part.strip() for part in raw_line.split("\t", 1)]
        elif ":" in raw_line:
            category, value = [part.strip() for part in raw_line.split(":", 1)]
        elif "  " in raw_line:
            parts = [part.strip() for part in raw_line.split("  ", 1)]
            if len(parts) == 2:
                category, value = parts

        if category:
            current_category = category
            bucket = sections[current_section].setdefault(category, [])
            if value:
                bucket.append(value)
            continue

        if not raw_line:
            continue

        if current_category:
            sections[current_section][current_category].append(raw_line.strip())
        else:
            sections[current_section].setdefault("Itens", []).append(raw_line.strip())

    # remove empty categories for clarity
    for data in sections.values():
        empty_keys = [key for key, values in data.items() if not values]
        for key in empty_keys:
            data[key] = ["Não informado"]

    return sections


def format_cardapio_sections(
    data_iso: str, sections: Dict[str, OrderedDict[str, List[str]]]
) -> str:
    lines = [f"--- CARDÁPIO ({data_iso}) ---"]
    for section in ("Desjejum", "Almoço", "Jantar"):
        if section not in sections:
            continue
        lines.append(section)
        for category, values in sections[section].items():
            for idx, value in enumerate(values):
                prefix = f"{category}\t" if idx == 0 else "\t"
                lines.append(f"{prefix}{value}")
    return "\n".join(lines)


def buscar_cardapio_ru(data_iso: str) -> str:
    """Busca cardápio do RU para a data no formato YYYY-MM-DD."""
    url = f"https://www.ufc.br/restaurante/cardapio/5-restaurante-universitario-de-quixada/{data_iso}"
    logger.info(f"🤖 [IA DEBUG] A IA solicitou busca de cardápio: {url}")

    try:
        soup = fetch_html(url, strip_tags=["script", "style", "nav"])
        content = soup.select_one("#content-section") or soup.body
        if content is not None:
            sections = extract_cardapio_sections(content)
            if sections:
                return format_cardapio_sections(data_iso, sections)
            text = content.get_text(separator="\n").strip()
            return f"--- CARDÁPIO ({data_iso}) ---\n{text[:3000]}"
        logger.warning(f"⚠️ [SISTEMA] Conteúdo HTML não encontrado para {data_iso}")
        return f"--- CARDÁPIO ({data_iso}) ---\nConteúdo não encontrado."
    except Exception as e:
        logger.error(f"❌ [ERRO] Falha ao buscar cardápio (processamento): {e}")
        return f"Erro cardápio: {e}"


def _get_next_weekday(
    start: datetime.date, target_weekday_index: int, include_today: bool = True
) -> datetime.date:
    days_ahead = (target_weekday_index - start.weekday() + 7) % 7
    if days_ahead == 0 and not include_today:
        days_ahead = 7
    return start + datetime.timedelta(days=days_ahead)


def _resolve_cardapio_date(data_texto: Optional[str]) -> str:
    # Normalize/clean
    today = datetime.date.today()
    if not data_texto:
        return today.isoformat()

    text = data_texto.strip().lower()
    if not text:
        return today.isoformat()

    # Normalize accented common tokens and remove phrases that don't affect date resolution
    text = text.replace("depois de amanhã", "depois_de_amanha")
    text = (
        text.replace("ã", "a")
        .replace("á", "a")
        .replace("â", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
    )

    # common keywords
    keyword_map = {
        "hoje": 0,
        "amanha": 1,
        "depois_de_amanha": 2,
        "ontem": -1,
    }
    for key, delta in keyword_map.items():
        if key in text:
            target = today + datetime.timedelta(days=delta)
            return target.isoformat()

    # ignore time-of-day hints as they don't change the date
    for tok in [
        "manha",
        "manhã",
        "de manha",
        "de manhã",
        "tarde",
        "noite",
        "de tarde",
        "a noite",
    ]:
        text = text.replace(tok, "")

    # YYYY-MM-DD
    iso_match = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso_match:
        year, month, day = map(int, iso_match.groups())
        return datetime.date(year, month, day).isoformat()

    # DD/MM/YYYY or DD/MM
    numeric_match = re.fullmatch(r"(\d{1,2})[\/.-](\d{1,2})(?:[\/.-](\d{2,4}))?", text)
    if numeric_match:
        day, month, year = numeric_match.groups()
        day_i = int(day)
        month_i = int(month)
        if year:
            year_i = int(year)
            if year_i < 100:
                year_i += 2000
        else:
            year_i = today.year
            if month_i < today.month - 6:
                year_i += 1
        target = datetime.date(year_i, month_i, day_i)
        return target.isoformat()

    # Month name + day: '1 de dezembro' or '1º de dezembro' or '1 dezembro 2025'
    months = {
        "janeiro": 1,
        "fevereiro": 2,
        "marco": 3,
        "abril": 4,
        "maio": 5,
        "junho": 6,
        "julho": 7,
        "agosto": 8,
        "setembro": 9,
        "outubro": 10,
        "novembro": 11,
        "dezembro": 12,
    }
    for nome, mes in months.items():
        if nome in text:
            numeros = re.findall(r"\d{1,2}", text)
            if numeros:
                dia_i = int(numeros[0])
                year_match = re.search(r"\b(\d{4})\b", text)
                year_i = int(year_match.group(1)) if year_match else today.year
                target = datetime.date(year_i, mes, dia_i)
                return target.isoformat()

    # Weekday names handling
    weekday_map = {
        "segunda": 0,
        "segunda-feira": 0,
        "terca": 1,
        "terca-feira": 1,
        "terça": 1,
        "quarta": 2,
        "quarta-feira": 2,
        "quinta": 3,
        "quinta-feira": 3,
        "sexta": 4,
        "sexta-feira": 4,
        "sabado": 5,
        "sabado-feira": 5,
        "sábado": 5,
        "domingo": 6,
    }
    proxima_tokens = ["proxima", "proximo"]
    is_proxima = any(tok in text for tok in proxima_tokens)
    for wk_name, wk_idx in weekday_map.items():
        if wk_name in text:
            target = _get_next_weekday(today, wk_idx, include_today=not is_proxima)
            return target.isoformat()

    raise ValueError(
        f"Não consegui interpretar a data '{data_texto}'. Informe DD/MM/AAAA ou termos como 'hoje'."
    )


def buscar_cardapio_ru_resolver(data: Optional[str] = None) -> str:
    """Resolve natural-language date expressions into an ISO date and return the menu.

    Args:
        data: Optional string containing the date expression the user provided.
            Examples: "hoje", "amanha", "amanha de manha", "proxima sexta",
            "23/11/2025" or "2025-11-23", "1 de dezembro".

    Behavior:
        - Uses `_resolve_cardapio_date` to convert `data` into an ISO date.
        - Delegates to `buscar_cardapio_ru` with the resolved date (which expects YYYY-MM-DD).
        - If parsing fails, an error message explaining the expected formats is returned
          rather than raising an unhandled exception (this keeps tool usage safer for the chat).

    Returns:
        The formatted cardápio text for the requested day, or a short error message if
        the input could not be parsed.
    """
    try:
        data_iso = _resolve_cardapio_date(data)
    except ValueError as exc:
        return str(exc)
    return buscar_cardapio_ru(data_iso)
