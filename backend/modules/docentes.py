from typing import Dict, List, Optional
from .utils import _normalize_token, fetch_html, _cache_expired, _get_attr_value
from .config import DOCENTES_URL, DOCENTES_CACHE_TTL

import datetime
import re
import difflib

DOCENTES_INDEX_CACHE: Dict[str, Dict[str, str]] = {}
DOCENTES_INDEX_TIMESTAMP: Optional[datetime.datetime] = None


def _is_probable_person_name(name: str) -> bool:
    if not name or not isinstance(name, str):
        return False
    lower = name.strip().casefold()
    NON_PERSON_WORDS = {
        "radio",
        "campus",
        "area",
        "area do aluno",
        "area do",
        "aluno",
        "alunos",
        "cursos",
        "servicos",
        "serviços",
        "eventos",
        "docentes",
        "docente",
        "perfil",
        "contato",
        "sobre",
        "noticias",
        "notícias",
        "home",
        "inicio",
        "programa",
    }
    for term in NON_PERSON_WORDS:
        if term in lower:
            return False
    if "@" in name or "http" in name or ".br" in name:
        return False
    tokens = [t for t in re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ']+", name) if t]
    if not tokens:
        return False
    if len(tokens) == 1:
        t = tokens[0]
        if len(t) < 3:
            return False
        if t.casefold() in NON_PERSON_WORDS:
            return False
        return True
    long_tokens = [t for t in tokens if len(t) >= 2]
    if len(long_tokens) < 2:
        return False
    stop_tokens = {"de", "do", "da", "dos", "das", "e", "a", "o"}
    meaningful = [t for t in tokens if t.casefold() not in stop_tokens]
    if len(meaningful) < 2:
        return False
    return True


def _melhor_docente(nome: str, index: Dict[str, Dict[str, str]]):
    normalized = _normalize_token(nome)
    if normalized in index:
        return index[normalized]
    for key, data in index.items():
        if normalized in key or key in normalized:
            return data
    tokens = [token for token in normalized.split() if token]
    for key, data in index.items():
        if tokens and all(token in key for token in tokens):
            return data
    try:
        keys = list(index.keys())
        close = difflib.get_close_matches(normalized, keys, n=1, cutoff=0.75)
        if close:
            return index.get(close[0])
    except Exception:
        pass
    return None


def listar_docentes() -> Dict[str, Dict[str, str]]:
    global DOCENTES_INDEX_CACHE, DOCENTES_INDEX_TIMESTAMP
    if DOCENTES_INDEX_CACHE and not _cache_expired(
        DOCENTES_INDEX_TIMESTAMP, DOCENTES_CACHE_TTL
    ):
        return DOCENTES_INDEX_CACHE
    try:
        soup = fetch_html(DOCENTES_URL, strip_tags=["script", "style", "iframe"])
    except Exception:
        return DOCENTES_INDEX_CACHE
    article = soup.select_one("article") or soup
    index: Dict[str, Dict[str, str]] = {}
    for heading in article.find_all(["h1", "h2", "h3"]):
        name = heading.get_text(strip=True)
        if not name:
            continue
        if not _is_probable_person_name(name):
            continue
        target_link = heading.find("a", href=True)
        if not target_link:
            link = heading.find_next("a", href=True)
            while link:
                link_text = _normalize_token(link.get_text(strip=True))
                if "perfil" in link_text:
                    target_link = link
                    break
                link = link.find_next("a", href=True)
        if not target_link:
            link = heading.find_next("a", href=True)
            while link:
                href_candidate = _get_attr_value(link, "href").strip()
                if "/docente/" in href_candidate:
                    target_link = link
                    break
                link = link.find_next("a", href=True)
        if not target_link:
            continue
        href = _get_attr_value(target_link, "href").strip()
        if href and href.startswith("/"):
            href = "https://www.quixada.ufc.br" + href
        if "/docente/" not in href:
            continue
        key = _normalize_token(name)
        index.setdefault(key, {"nome": name, "url": href})
        tokens = [t for t in key.split() if t]
        for i in range(len(tokens) - 1):
            left = tokens[i]
            right = tokens[i + 1]
            if len(left) < 2 or len(right) < 2:
                continue
            pair = f"{left} {right}"
            index.setdefault(pair, {"nome": name, "url": href})
        if len(tokens) > 1:
            last = tokens[-1]
            if len(last) >= 2 and last not in {"de", "do", "da", "dos", "das"}:
                index.setdefault(last, {"nome": name, "url": href})
    DOCENTES_INDEX_CACHE = index
    DOCENTES_INDEX_TIMESTAMP = datetime.datetime.now()
    return index


def _resolver_nome_professor(nome: str) -> Optional[Dict[str, str]]:
    index = listar_docentes()
    if not index:
        return None
    entry = _melhor_docente(nome, index)
    if not entry:
        try:
            keys = list(index.keys())
            close = difflib.get_close_matches(
                _normalize_token(nome), keys, n=5, cutoff=0.5
            )
            if close:
                pass  # debug logging may be added
        except Exception:
            pass
    return entry


def _sugerir_docentes(nome: str, limit: int = 5) -> List[Dict[str, str]]:
    index = listar_docentes()
    if not index:
        return []
    nome_norm = _normalize_token(nome)
    tokens = [t for t in nome_norm.split() if len(t) >= 3]
    candidatos: Dict[str, tuple[float, Dict[str, str]]] = {}
    for data in index.values():
        unique_id = data.get("url") or data.get("nome") or ""
        if not unique_id:
            continue
        base_norm = _normalize_token(data.get("nome", ""))
        score = 0.0
        if nome_norm and nome_norm in base_norm:
            score += 3.0
        for token in tokens:
            if token in base_norm:
                score += 1.5
        if not score and tokens:
            ratio = difflib.SequenceMatcher(None, nome_norm, base_norm).ratio()
            if ratio >= 0.5:
                score += ratio
        if score:
            prev = candidatos.get(unique_id)
            if prev is None or score > prev[0]:
                candidatos[unique_id] = (score, data)
    ordered = sorted(candidatos.values(), key=lambda item: item[0], reverse=True)
    return [entry for _, entry in ordered[:limit]]


def _formatar_sugestoes_docentes(sugestoes: List[Dict[str, str]]) -> str:
    if not sugestoes:
        return ""
    linhas = ["Sugestões de docentes:"]
    for entry in sugestoes:
        linha = f"- {entry.get('nome', 'Sem nome')}"
        if entry.get("url"):
            linha += f": {entry['url']}"
        linhas.append(linha)
    return "\n".join(linhas)


def obter_dados_docente(nome: str) -> Optional[Dict[str, str]]:
    index = listar_docentes()
    if not index:
        return None
    entry = _melhor_docente(nome, index)
    if not entry:
        return None
    try:
        soup = fetch_html(entry["url"], strip_tags=["script", "style", "iframe"])
    except Exception:
        return {"nome": entry["nome"], "url": entry["url"]}
    article = soup.select_one("article") or soup
    content = article.select_one(".entry-content") or article
    emails: List[str] = []
    for link in content.select("a[href^='mailto:']"):
        href_value = _get_attr_value(link, "href")
        email = href_value.split("mailto:")[-1].split("?")[0].strip()
        if email and email not in emails:
            emails.append(email)

    # Cloudflare frequentemente protege e-mails em spans com data-cfemail ou âncoras
    # apontando para /cdn-cgi/l/email-protection. Decodificamos esses formatos.
    def _decode_cfemail(encoded: str) -> Optional[str]:
        try:
            if not encoded:
                return None
            key = int(encoded[:2], 16)
            chars = [
                chr(int(encoded[i : i + 2], 16) ^ key)
                for i in range(2, len(encoded), 2)
            ]
            return "".join(chars)
        except Exception:
            return None

    for tag in content.select("[data-cfemail]"):
        decoded = _decode_cfemail(_get_attr_value(tag, "data-cfemail"))
        if decoded and decoded not in emails:
            emails.append(decoded)

    for link in content.select("a[href*='/cdn-cgi/l/email-protection']"):
        href_value = _get_attr_value(link, "href")
        encoded = href_value.split("#")[-1]
        decoded = _decode_cfemail(encoded)
        if decoded and decoded not in emails:
            emails.append(decoded)
    # Alguns perfis exibem e-mail apenas como texto, sem link mailto.
    # Capturamos padrões comuns para complementar o resultado.
    raw_text = content.get_text(" ", strip=True)
    if raw_text:
        pattern = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        for match in pattern.findall(raw_text):
            normalized = match.strip()
            if normalized and normalized not in emails:
                emails.append(normalized)
    lattes = None
    sigaa = None
    for link in content.find_all("a", href=True):
        href = link["href"]
        if "lattes.cnpq.br" in href and not lattes:
            lattes = href
        if "si3.ufc.br" in href and not sigaa:
            sigaa = href
    paragraphs = [
        p.get_text(" ", strip=True)
        for p in content.find_all("p")
        if p.get_text(strip=True)
    ]
    bio = " ".join(paragraphs[:2])[:800]
    payload = {
        "nome": entry["nome"],
        "url": entry["url"],
        "emails": emails,
        "lattes": lattes,
        "sigaa": sigaa,
        "bio": bio,
    }
    return payload


def buscar_dados_professores(
    nome_professor: str,
    horario: Optional[str] = None,
    procurandoProfessor: Optional[bool] = False,
    procurandoEmailProfessor: Optional[bool] = False,
) -> str:
    """Busca informações do professor e alocação (integra docentes + alocacoes).
    Retorna texto formatado com currículo e/ou horários.
    """
    from .alocacoes import buscar_professor_em_alocacao, _parse_horario_param

    nome = (nome_professor or "").strip()
    if not nome:
        return "Informe o nome do professor para continuar."

    resolved_entry = _resolver_nome_professor(nome)
    resolved_name = resolved_entry["nome"] if resolved_entry else nome
    suggestions: List[Dict[str, str]] = []
    if not resolved_entry:
        suggestions = _sugerir_docentes(nome)

    def _append_suggestions(base: str) -> str:
        complemento = _formatar_sugestoes_docentes(suggestions)
        if complemento:
            return f"{base}\n\n{complemento}"
        return base

    if procurandoEmailProfessor:
        dados = obter_dados_docente(resolved_name)
        if not dados:
            msg = f"Não encontrei informações públicas para o(a) professor(a) {nome}."
            return _append_suggestions(msg)

        linhas = [dados.get("nome", resolved_name)]
        if resolved_entry and resolved_entry["nome"].casefold() != nome.casefold():
            linhas.append(f"(Busca ajustada para {resolved_entry['nome']})")
        emails = dados.get("emails") or []
        if emails:
            linhas.append("E-mail(s): " + ", ".join(emails))
        if dados.get("lattes"):
            linhas.append(f"Currículo Lattes: {dados['lattes']}")
        if dados.get("sigaa"):
            linhas.append(f"Portal SIGAA: {dados['sigaa']}")
        if dados.get("bio"):
            linhas.append(f"Resumo: {dados['bio']}")
        linhas.append(f"Perfil completo: {dados.get('url', DOCENTES_URL)}")
        return "\n".join(linhas)

    if procurandoProfessor:
        horario_parsed = _parse_horario_param(horario)
        week_flag = bool(horario_parsed.get("week"))
        overview_requested = week_flag or bool(
            horario_parsed.get("all_times")
            or (horario_parsed.get("days") and not horario_parsed.get("time"))
        )
        if overview_requested:
            formatted = buscar_professor_em_alocacao(nome, horario, group_by_day=True)
            if not formatted and resolved_entry:
                formatted = buscar_professor_em_alocacao(
                    resolved_name, horario, group_by_day=True
                )
            if not formatted:
                complemento = " para a semana inteira" if week_flag else ""
                msg = (
                    f"Não localizei {nome} no documento de alocação{complemento}. "
                    "Verifique o nome completo ou se o arquivo foi atualizado."
                )
                return _append_suggestions(msg)
            try:
                import json

                return json.dumps(formatted, ensure_ascii=False, indent=2)
            except Exception:
                return (
                    "\n\n".join(list(formatted))
                    if isinstance(formatted, list)
                    else str(formatted)
                )

        # otherwise check raw matches and prefer search by document short name first
        results = buscar_professor_em_alocacao(nome, horario)
        if not results and resolved_entry:
            results = buscar_professor_em_alocacao(resolved_name, horario)
        if not results:
            msg = (
                f"Não localizei {nome} no documento de alocação. "
                "Verifique o nome completo ou se o arquivo foi atualizado."
            )
            return _append_suggestions(msg)
        if isinstance(results, list):
            # Return formatted text with top matches
            return "\n\n".join(results[:6])
            return str(results)

    # default behavior: search for schedule matches and return best formatted hits
    default_results = buscar_professor_em_alocacao(nome, horario)
    if not default_results and resolved_entry:
        default_results = buscar_professor_em_alocacao(resolved_name, horario)
    if isinstance(default_results, list):
        return "\n\n".join(default_results[:6])
    if default_results:
        return str(default_results)
    msg = f"Não encontrei dados recentes para {nome}."
    return _append_suggestions(msg)
