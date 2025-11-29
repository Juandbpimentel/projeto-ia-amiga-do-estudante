from typing import Dict
import datetime
import logging
import requests
from .utils import fetch_html
from .config import HEADERS

logger = logging.getLogger("UFC_AGENT")


def build_status_report(
    title: str,
    urls: Dict[str, str],
    log_context: str = "ℹ️ [SISTEMA] Verificando status de",
) -> str:
    lines = [title]
    for name, url in urls.items():
        try:
            logger.info("%s: %s", log_context, name)
            # timeout shorter because we need fast responses during chat
            resp = requests.get(url, headers=HEADERS, timeout=3, verify=False)
            status = "ONLINE" if resp.status_code == 200 else "OFFLINE"
        except requests.exceptions.RequestException as exc:
            status = "OFFLINE"
            logger.warning("⚠️ [REDE] Falha ao conectar em %s: %s", name, exc)
        # Keep each line reasonably short to avoid huge tool output
        line = f"- {name}: {status}"
        if len(line) > 200:
            line = f"- {name}: {status} (truncated)"
        lines.append(line)
    report = "\n".join(lines)
    # Defensive: cap total length to avoid extreme outputs to the chat SDK
    max_len = 2000
    if len(report) > max_len:
        logger.warning(
            "⚠️ [SISTEMA] Status report too large; truncating to %d chars", max_len
        )
        report = report[:max_len] + "... (truncated)"
    # Log a short preview of the report for diagnostics
    logger.debug("ℹ️ [SISTEMA] Relatório de status (preview): %s", report[:200])
    return report


def verifica_status_sites_para_os_estudantes() -> str:
    urls = {
        "Sigaa": "https://si3.ufc.br/sigaa/verTelaLogin.do",
        "Moodle UFC Quixadá": "https://moodle2.quixada.ufc.br/login/index.php",
    }
    logger.info("🤖 [IA DEBUG] A IA solicitou verificação de status em tempo real.")
    report = build_status_report(
        "=== STATUS DOS SITES PRINCIPAIS (Tempo Real) ===",
        urls,
        log_context="ℹ️ [TEMPO REAL] Verificando status de",
    )
    logger.info("ℹ️ [SISTEMA] Verificação de status executada: %s chars", len(report))
    return report


def format_status_report(report: str, focus: str | None = None) -> str:
    """Transforma um relatório de status em resposta humana concisa.
    Se `focus` for fornecido (ex.: 'Moodle' ou 'Sigaa'), responde focando nesse serviço.
    """
    if not report:
        return "Status dos sites temporariamente indisponível."
    import re

    lines = [line.strip() for line in report.splitlines() if line.strip()]
    # Extract entries like 'Sigaa: ONLINE' or 'Moodle UFC Quixadá: ONLINE'
    statuses = {}
    for line in lines:
        m = re.search(r"([A-Za-zÀ-ÖØ-öø-ÿ0-9\s]+):\s*(ONLINE|OFFLINE)", line, re.I)
        if m:
            name = m.group(1).strip()
            status = m.group(2).upper()
            statuses[name] = status

    if not statuses:
        return report

    # Normalize focus matching
    focus_key = None
    if focus:
        for k in statuses:
            if focus.casefold() in k.casefold():
                focus_key = k
                break

    online = [k for k, v in statuses.items() if v == "ONLINE"]
    offline = [k for k, v in statuses.items() if v == "OFFLINE"]

    if focus_key:
        st = statuses.get(focus_key)
        if st == "ONLINE":
            return f"Sim — o {focus_key} está online."
        else:
            return f"Parece que o {focus_key} está offline (status: {st})."

    if online and not offline:
        if len(online) == 1:
            return f"Sim — {online[0]} está online."
        return f"Sim — {', '.join(online)} estão online."
    if offline and not online:
        return f"Nenhum dos serviços está online no momento: {', '.join(offline)}."
    # Mixed
    parts = []
    if online:
        parts.append(f"Online: {', '.join(online)}")
    if offline:
        parts.append(f"Offline: {', '.join(offline)}")
    details = "; ".join(parts)
    return f"Status resumido — {details}."


def buscar_feriados(
    ano: int,
    mes: int | None = None,
    dia: int | None = None,
    verificar_semana: bool = False,
) -> str:
    if verificar_semana and dia is None:
        hoje = datetime.date.today()
        if hoje.weekday() == 0:
            dias_ate_proxima_segunda = 7
        else:
            dias_ate_proxima_segunda = 7 - hoje.weekday()
        segunda_proxima = hoje + datetime.timedelta(days=dias_ate_proxima_segunda)
        ano, mes, dia = segunda_proxima.year, segunda_proxima.month, segunda_proxima.day

    res = []
    if verificar_semana and dia:
        foco = f"Semana do dia {dia}/{mes}/{ano}"
    elif mes:
        foco = f"Mês {mes}/{ano}"
    else:
        foco = f"Ano Completo {ano}"

    res.append(f"--- INFO FERIADOS (Foco: {foco}) ---")
    logger.info("🤖 [IA DEBUG] A IA solicitou busca de feriados. Foco: %s", foco)

    try:
        url_ufc = f"https://www.ufc.br/calendario-universitario/{ano}"
        soup = fetch_html(url_ufc, strip_tags=["script", "style"])
        res.append(f"CALENDÁRIO UFC ({ano}):\n{soup.get_text(separator='\n')}")
    except Exception as e:
        logger.error("❌ [ERRO] Falha ao ler UFC: %s", e)
        res.append(f"Erro ao ler UFC (rede): {e}")

    try:
        if mes:
            url_feriados = f"https://feriados.com.br/CE/Quixad%C3%A1/{ano}/{mes}"
        else:
            url_feriados = f"https://feriados.com.br/CE/Quixad%C3%A1/{ano}"
        soup = fetch_html(url_feriados, strip_tags=["script", "style", "iframe"])
        res.append(f"FERIADOS MUNICIPAIS ({foco}):\n{soup.get_text()}")
    except Exception as e:
        logger.error("❌ [ERRO] Falha ao ler Feriados Municipais: %s", e)
        res.append(f"Erro ao ler Feriados Municipais (rede): {e}")

    return "\n".join(res)
