import logging
import datetime
import difflib
import re
import requests
from typing import Any, Dict, List, Optional, cast
from bs4 import BeautifulSoup
from .config import ALOCACAO_DOC_URL, ALOCACAO_CACHE_TTL, HEADERS
from .parsers import _parse_google_table, _parse_plain_rows_from_doc
from .utils import (
    _normalize_token,
    _cache_expired,
    _resolver_link_google_docs,
)
# The listar_docentes function is intentionally not imported here; alocacoes
# uses only internal row parsing and index lookups via higher-level callers.

logger = logging.getLogger("UFC_AGENT")

ALOCACAO_CACHE: Dict[str, Any] = {
    "timestamp": None,
    "rows": [],
    "doc_url": None,
    "error": None,
}


def _format_row_string(row: Dict[str, str]) -> str:
    partes: List[str] = []
    contexto = row.get("context")
    if contexto:
        partes.append(f"Contexto: {contexto}")
    if row.get("Dia"):
        partes.append(f"Dia: {row.get('Dia')}")
    for chave in [
        "Bloco",
        "Bloco/Sala",
        "Bloco / Sala",
        "Sala",
        "Sala/Lab",
        "Sala / Laboratório",
    ]:
        if row.get(chave):
            partes.append(f"{chave}: {row[chave]}")
    for chave in ["Horário", "Horario", "Turno", "Dia/Horário"]:
        if row.get(chave):
            partes.append(f"{chave}: {row[chave]}")
    if row.get("Professor"):
        partes.append(f"Professor: {row.get('Professor')}")
    detalhes = []
    for chave, valor in row.items():
        if chave in {
            "context",
            "_row_text",
            "Bloco",
            "Bloco/Sala",
            "Bloco / Sala",
            "Sala",
            "Sala/Lab",
            "Sala / Laboratório",
            "Horário",
            "Horario",
            "Turno",
            "Dia/Horário",
            "Dia",
            "Professor",
        }:
            continue
        if not valor:
            continue
        if chave.startswith("Coluna "):
            continue
        detalhes.append(f"{chave}: {valor}")
    if detalhes:
        partes.extend(detalhes)
    else:
        if row.get("Coluna 1"):
            partes.append(f"Disciplina: {row.get('Coluna 1')}")
        else:
            partes.append(row.get("_row_text", ""))
    return "\n".join(partes).strip()


# NOTE: _get_professor_from_row was removed as it was not referenced anywhere.
# The logic for extracting professor names is handled inline in search routines
# (e.g., in `buscar_professor_em_alocacao`) using token/fuzzy matching and
# by indexing from `listar_docentes` when a candidate segment is found.


def _extract_day_from_row(row: Dict[str, str]) -> Optional[str]:
    norm_keys = {k.lower(): k for k in row.keys() if isinstance(k, str)}
    candidate = None
    for k in norm_keys:
        if "dia" in k or "horario" in k:
            v = row.get(norm_keys[k])
            if v:
                v_norm = _normalize_token(v)
                for d in [
                    "segunda",
                    "terca",
                    "quarta",
                    "quinta",
                    "sexta",
                    "sabado",
                    "domingo",
                ]:
                    if d in v_norm:
                        return d
                candidate = v_norm
    texto = _normalize_token(row.get("_row_text", ""))
    for d in ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]:
        if d in texto:
            return d
    return candidate


def _row_matches_schedule(row: Dict[str, str], horario_parsed: Dict[str, Any]) -> bool:
    week_flag = bool(horario_parsed.get("week"))
    days_filter = cast(List[str], horario_parsed.get("days") or [])
    time_filter = cast(Optional[str], horario_parsed.get("time"))
    texto = _normalize_token(row.get("_row_text", ""))

    if not week_flag and days_filter:
        dia_field = _normalize_token(str(row.get("Dia") or ""))
        if not any(day in dia_field for day in days_filter):
            if not any(day in texto for day in days_filter):
                return False

    if not week_flag and time_filter:
        hh = str(time_filter).split(":")[0]
        time_match_ok = False
        try:
            horario_field = _normalize_token(
                str(row.get("Horário") or row.get("Horario") or row.get("Turno") or "")
            )
            if time_filter in horario_field or time_filter in texto:
                time_match_ok = True
            elif re.search(rf"\b{int(int(hh))}\b", texto):
                time_match_ok = True
            elif re.search(rf"{hh}h", texto):
                time_match_ok = True
        except Exception:
            if hh in texto:
                time_match_ok = True
        if not time_match_ok:
            return False

    return True


def _parse_horario_param(horario: Optional[str]) -> Dict[str, object]:
    res: Dict[str, object] = {
        "week": False,
        "days": [],
        "time": None,
        "all_times": False,
        "raw": "",
    }
    if not horario:
        return res
    norm = _normalize_token(horario)
    res["raw"] = norm
    if "semana" in norm or "semana inteira" in norm or "semana todo" in norm:
        res["week"] = True
    all_time_tokens = [
        "dia todo",
        "dia inteiro",
        "turno todo",
        "turno inteiro",
        "turno completo",
        "todos os horarios",
        "todos os horários",
        "todos horarios",
        "todos os turnos",
        "horario integral",
        "horário integral",
    ]
    if any(token in norm for token in all_time_tokens):
        res["all_times"] = True
    hoje = datetime.date.today()
    days_pt = ["segunda", "terca", "quarta", "quinta", "sexta", "sabado", "domingo"]
    if "hoje" in norm:
        res["days"] = [days_pt[hoje.weekday()]]
    if "amanha" in norm or "amanhã" in norm:
        tomorrow = hoje + datetime.timedelta(days=1)
        res["days"] = [days_pt[tomorrow.weekday()]]
    weekday_map = {
        "segunda": "segunda",
        "segunda-feira": "segunda",
        "terca": "terca",
        "terça": "terca",
        "terca-feira": "terca",
        "quarta": "quarta",
        "quarta-feira": "quarta",
        "quinta": "quinta",
        "quinta-feira": "quinta",
        "sexta": "sexta",
        "sexta-feira": "sexta",
        "sabado": "sabado",
        "sábado": "sabado",
        "domingo": "domingo",
    }
    days_found: List[str] = []
    for token in weekday_map:
        if token in norm:
            days_found.append(weekday_map[token])
    if days_found:
        res["days"] = days_found
    time_match = re.search(r"(\d{1,2}[:hH]?\d{0,2})", horario)
    if time_match:
        t = time_match.group(1)
        t = t.replace("h", ":").replace("H", ":")
        if ":" not in t:
            t = f"{int(t):02d}:00"
        else:
            parts = t.split(":")
            if len(parts) == 1:
                t = f"{int(parts[0]):02d}:00"
            else:
                hh = int(parts[0])
                mm = int(parts[1]) if parts[1] else 0
                t = f"{hh:02d}:{mm:02d}"
        res["time"] = t
    return res


def carregar_alocacoes() -> Dict[str, object]:
    global ALOCACAO_CACHE
    cache_timestamp = ALOCACAO_CACHE.get("timestamp")
    if not isinstance(cache_timestamp, datetime.datetime):
        cache_timestamp = None
    if ALOCACAO_CACHE["rows"] and not _cache_expired(
        cache_timestamp, ALOCACAO_CACHE_TTL
    ):
        return ALOCACAO_CACHE

    now = datetime.datetime.now()
    doc_link = ALOCACAO_DOC_URL
    if not doc_link:
        ALOCACAO_CACHE = {
            "timestamp": now,
            "rows": [],
            "doc_url": None,
            "error": "Link do documento de alocação não configurado.",
        }
        logger.error("❌ [ALOCACAO] Link do documento não configurado.")
        return ALOCACAO_CACHE

    doc_html = None
    accepted_candidate: Optional[str] = None
    last_error = None
    for candidate in _resolver_link_google_docs(doc_link):
        try:
            logger.debug("ℹ️ [ALOCACAO] Tentando baixar documento: %s", candidate)
            resp = requests.get(candidate, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            if "accounts.google.com" in resp.url:
                last_error = "Documento requer autenticação."
                logger.warning(
                    "⚠️ [ALOCACAO] Conteúdo solicitando autenticação para: %s", candidate
                )
                continue
            tmp_soup = BeautifulSoup(resp.text, "html.parser")
            table_count = len(tmp_soup.find_all("table"))
            logger.debug(
                "ℹ️ [ALOCACAO] Candidate %s retornou %s tables", candidate, table_count
            )
            if table_count < 1:
                last_error = f"Nenhuma tabela encontrada no candidato: {candidate}"
                logger.warning(
                    "⚠️ [ALOCACAO] %s - Tentando candidato alternativo...", last_error
                )
                continue
            doc_html = resp.text
            accepted_candidate = candidate
            break
        except Exception as exc:
            last_error = str(exc)
            continue

    if doc_html is None:
        ALOCACAO_CACHE = {
            "timestamp": now,
            "rows": [],
            "doc_url": doc_link,
            "error": last_error,
        }
        logger.error("❌ [ALOCACAO] Falha ao baixar documento: %s", last_error)
        return ALOCACAO_CACHE

    doc_soup = BeautifulSoup(doc_html, "html.parser")
    rows: List[Dict[str, str]] = []
    for table in doc_soup.find_all("table"):
        rows.extend(_parse_google_table(table))
    if not rows:
        logger.debug(
            "ℹ️ [ALOCACAO] Nenhuma tabela encontrada, tentando parsear linhas sem tabela."
        )
        rows = _parse_plain_rows_from_doc(doc_soup)

    ALOCACAO_CACHE = {
        "timestamp": now,
        "rows": rows,
        "doc_url": accepted_candidate or doc_link,
        "error": None,
    }
    logger.info("ℹ️ [ALOCACAO] %s entradas processadas.", len(rows))
    if len(rows) < 1:
        logger.warning(
            "⚠️ [ALOCACAO] Nenhuma linha encontrada no documento de alocação (ou formato incomum)."
        )
    return ALOCACAO_CACHE


def buscar_professor_em_alocacao(
    nome_professor: str,
    horario: Optional[str] = None,
    *,
    return_rows: bool = False,
    group_by_day: bool = False,
) -> Any:
    cache = carregar_alocacoes()
    if cache.get("error"):
        return [
            "Não consegui acessar o documento de alocação no momento. "
            + str(cache.get("error")),
        ]

    rows: List[Dict[str, str]] = cache.get("rows", [])  # type: ignore[arg-type]
    if not rows:
        return []

    nome_norm = _normalize_token(nome_professor)
    horario_norm = _normalize_token(horario) if horario else None
    resultados: List[str] = []
    matched_rows: List[Dict[str, str]] = []
    scored_matches: List[tuple] = []  # (score, row)

    exclude_tokens = {
        "de",
        "da",
        "do",
        "dos",
        "das",
        "prof",
        "profa",
        "dr",
        "dra",
        "prof.",
    }
    tokens = [t for t in nome_norm.split() if len(t) > 2 and t not in exclude_tokens]
    logger.debug(
        "ℹ️ [ALOCACAO] Procurando por '%s' (norm=%s) tokens=%s, horario=%s",
        nome_professor,
        nome_norm,
        tokens,
        horario_norm,
    )

    horario_parsed = _parse_horario_param(horario)
    logger.debug("ℹ️ [ALOCACAO] Horario parse: %s", horario_parsed)

    for row in rows:
        texto = _normalize_token(row.get("_row_text", ""))
        if not _row_matches_schedule(row, horario_parsed):
            continue

        match_type: Optional[str] = None
        score = 0
        if nome_norm in texto:
            match_type = "substring"
            score = 80
        elif tokens and all(token in texto for token in tokens):
            match_type = "tokens_all"
            score = 100
        else:
            if tokens:
                text_words = re.findall(r"\w+", texto)
                matched_all = True
                for token in tokens:
                    if token in text_words:
                        continue
                    close = difflib.get_close_matches(
                        token, text_words, n=1, cutoff=float(0.70)
                    )
                    if close:
                        continue
                    matched_all = False
                    break
                if matched_all:
                    match_type = "tokens_fuzzy"
                    score = 90
            if not match_type and tokens and len(tokens) == 1 and tokens[-1] in texto:
                match_type = "last_name"
                score = 50
            if not match_type:
                ratio = difflib.SequenceMatcher(None, nome_norm, texto).ratio()
                if ratio > float(0.65):
                    match_type = f"fuzzy({ratio:.2f})"
                    score = int(75 + ratio * 25)

        if not match_type:
            continue

        partes: List[str] = []
        contexto = row.get("context")
        if contexto:
            partes.append(f"Contexto: {contexto}")

        for chave in [
            "Bloco",
            "Bloco/Sala",
            "Bloco / Sala",
            "Sala",
            "Sala/Lab",
            "Sala / Laboratório",
        ]:
            if row.get(chave):
                partes.append(f"{chave}: {row[chave]}")

        for chave in ["Horário", "Horario", "Turno", "Dia/Horário"]:
            if row.get(chave):
                partes.append(f"{chave}: {row[chave]}")

        detalhes = []
        for chave, valor in row.items():
            if chave in {
                "context",
                "_row_text",
                "Bloco",
                "Bloco/Sala",
                "Bloco / Sala",
                "Sala",
                "Sala/Lab",
                "Sala / Laboratório",
                "Horário",
                "Horario",
                "Turno",
                "Dia/Horário",
            }:
                continue
            if not valor:
                continue
            if chave.startswith("Coluna "):
                continue
            detalhes.append(f"{chave}: {valor}")

        if detalhes:
            partes.extend(detalhes)
        else:
            partes.append(row.get("_row_text", ""))

        logger.debug(
            'ℹ️ [ALOCACAO] Match tipo=%s para "%s" -> %s',
            match_type,
            nome_professor,
            row.get("_row_text", "")[:100],
        )
        matched_rows.append(row)
        scored_matches.append((score, row))
        if len(matched_rows) >= 6:
            break

    if return_rows:
        return matched_rows

    if group_by_day:
        days_order = [
            "segunda",
            "terca",
            "quarta",
            "quinta",
            "sexta",
            "sabado",
            "domingo",
        ]
        grouped: Dict[str, List[Dict[str, Any]]] = {d: [] for d in days_order}
        grouped["sem_data"] = []
        for row in matched_rows:
            day = _extract_day_from_row(row)
            if day:
                grouped.setdefault(day, []).append(row)
            else:
                grouped["sem_data"].append(row)
        week_struct: Dict[str, Any] = {"professor": nome_professor, "week": {}}
        for d in days_order:
            if grouped.get(d):
                week_struct["week"][d] = grouped[d]
        if grouped.get("sem_data"):
            week_struct["week"]["sem_data"] = grouped["sem_data"]
        return week_struct

    if scored_matches:
        scored_matches.sort(key=lambda x: x[0], reverse=True)
        resultados = [_format_row_string(r) for _, r in scored_matches]
    return resultados
