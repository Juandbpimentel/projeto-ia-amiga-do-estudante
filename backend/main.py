import datetime
import logging
import uuid
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from google import genai
from pydantic import BaseModel

from modules import (
    alocacoes as alocacoes_mod,
    cardapio as cardapio_mod,
    chat as chat_mod,
    docentes as docentes_mod,
    feriados as feriados_mod,
)
from modules.config import MODEL_NAME
import os
import glob

load_dotenv()

logger = logging.getLogger("UFC_AGENT")
app = FastAPI()

# Remove any leftover context files from previous sessions on startup
try:
    backend_dir = os.path.dirname(__file__)
    for f in glob.glob(os.path.join(backend_dir, "contexto_*.txt")):
        try:
            os.remove(f)
            logger.info(f"ℹ️ [SISTEMA] Removido arquivo de contexto antigo: {f}")
        except Exception as e:
            logger.warning(f"⚠️ [SISTEMA] Falha ao remover arquivo de contexto {f}: {e}")
except Exception:
    # Avoid startup crash if cleanup fails
    pass

# Configure CORS to allow frontend origins, set via env var `ALLOW_ORIGINS` (comma-separated)
# If ALLOW_ORIGINS is empty or not provided, no CORS is enabled (secure default).
allow_origins_raw = os.environ.get("ALLOW_ORIGINS", "")
allow_origins = [o.strip() for o in allow_origins_raw.split(",") if o.strip()]
if allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

SESSION_STATE: Dict[str, Dict[str, object]] = {}

# Verify Google credentials presence (either GOOGLE_API_KEY or a Google Service Account JSON via GOOGLE_SERVICE_ACCOUNT_JSON/
# GOOGLE_APPLICATION_CREDENTIALS). This helps surface missing env issues earlier and with clearer instructions.
missing_google_key = False
has_api_key = bool(os.environ.get("GOOGLE_API_KEY"))
has_service_json = bool(os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON"))
has_application_creds = bool(
    os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
) and os.path.exists(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))

# Allow developers to bypass the strict requirement in non-production environments by setting
# REQUIRE_GOOGLE_CREDENTIALS=false. By default, we require credentials (for production deployments).
require_creds = os.environ.get("REQUIRE_GOOGLE_CREDENTIALS", "true").lower() in (
    "1",
    "true",
    "yes",
)

if require_creds and not (has_api_key or has_service_json or has_application_creds):
    logger.critical(
        "❌ [SISTEMA] Nenhuma credencial Google detectada. Defina `GOOGLE_API_KEY` ou `GOOGLE_SERVICE_ACCOUNT_JSON`/`GOOGLE_APPLICATION_CREDENTIALS` no ambiente."
    )
    # Raise early with a friendly message so Render logs show guidance
    raise RuntimeError(
        "Missing Google credentials. Provide GOOGLE_API_KEY or GOOGLE_SERVICE_ACCOUNT_JSON/GOOGLE_APPLICATION_CREDENTIALS. See DEPLOY.md for instructions."
    )
elif not require_creds and not (
    has_api_key or has_service_json or has_application_creds
):
    logger.warning(
        "⚠️ [SISTEMA] Nenhuma credencial Google detectada, mas REQUIRE_GOOGLE_CREDENTIALS=false, iniciando sem conexão GenAI."
    )

try:
    client = genai.Client()
except Exception as exc:
    logger.error("❌ [SISTEMA] Falha ao inicializar o cliente GenAI: %s", exc)
    raise

carregar_alocacoes = alocacoes_mod.carregar_alocacoes
buscar_dados_professores = docentes_mod.buscar_dados_professores


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/debug/docentes", include_in_schema=False)
async def debug_docentes():
    try:
        index = docentes_mod.listar_docentes()
        return {
            "count": len(index),
            "sample": list(index.keys()),
        }
    except Exception as e:
        logger.exception("Erro debug listar_docentes: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/debug/alocacoes", include_in_schema=False)
async def debug_alocacoes():
    try:
        cache = carregar_alocacoes()
        rows_raw = cache.get("rows")
        if isinstance(rows_raw, list):
            rows = rows_raw
        else:
            rows = []
        return {
            "count": len(rows),
            "doc_url": cache.get("doc_url"),
            "error": cache.get("error"),
            "sample_rows": rows,
        }
    except Exception as e:
        logger.exception("Erro debug carregar_alocacoes: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health", include_in_schema=False)
async def health():
    """Health endpoint used by Render or other platforms to validate service availability.
    Returns simple JSON with `ok` and timestamp. Configure this to the platform health check.
    """
    return {"ok": True, "timestamp": datetime.datetime.utcnow().isoformat()}


def build_status_report(
    title: str,
    urls: Dict[str, str],
    log_context: str = "ℹ️ [SISTEMA] Verificando status de",
) -> str:
    from modules.feriados import build_status_report as _build

    return _build(title, urls, log_context)


def buscar_cardapio_ru(data_iso: str):
    """Wrapper delegando para aiamiga.cardapio.buscar_cardapio_ru."""
    return cardapio_mod.buscar_cardapio_ru(data_iso)


def buscar_feriados(
    ano: int,
    mes: Optional[int] = None,
    dia: Optional[int] = None,
    verificar_semana: bool = False,
) -> str:
    if verificar_semana and dia is None:
        hoje = datetime.date.today()
        if hoje.weekday() == 0:
            dias_ate_proxima_segunda = 7
        else:
            dias_ate_proxima_segunda = 7 - hoje.weekday()
        segunda_proxima = hoje + datetime.timedelta(days=dias_ate_proxima_segunda)
        ano, mes, dia = (
            segunda_proxima.year,
            segunda_proxima.month,
            segunda_proxima.day,
        )

    if verificar_semana and dia:
        foco = f"Semana do dia {dia}/{mes}/{ano}"
    elif mes:
        foco = f"Mês {mes}/{ano}"
    else:
        foco = f"Ano Completo {ano}"

    logger.info(f"🤖 [IA DEBUG] A IA solicitou busca de feriados. Foco: {foco}")

    return feriados_mod.buscar_feriados(ano, mes, dia, verificar_semana)


def check_system_status() -> str:
    urls = {
        "Site UFC": "https://www.ufc.br",
        "Sigaa": "https://si3.ufc.br/sigaa/verTelaLogin.do",
    }
    return build_status_report("=== STATUS INICIAL ===", urls)


def verifica_status_sites_para_os_estudantes() -> str:
    return feriados_mod.verifica_status_sites_para_os_estudantes()


my_tools = [
    cardapio_mod.buscar_cardapio_ru_resolver,
    feriados_mod.buscar_feriados,
    feriados_mod.verifica_status_sites_para_os_estudantes,
    buscar_dados_professores,
]


class ChatRequest(BaseModel):
    message: str


class StartResponse(BaseModel):
    session_id: str
    message: str


@app.post("/start-chat", response_model=StartResponse)
async def start_chat():
    session_id = str(uuid.uuid4())
    now = datetime.datetime.now()

    logger.info(
        f"🚀 [SISTEMA] Iniciando nova sessão de chat (COM HISTÓRICO): {session_id}"
    )

    status = check_system_status()

    system_instr = f"""
    DATA ATUAL DO SISTEMA: {now.strftime("%Y-%m-%d")} ({now.strftime("%A")}).
    HORA: {now.strftime("%H:%M")}.
    ANO ATUAL: {now.year}.

    Você é um assistente virtual da UFC Campus Quixadá.

    {status}

    SUAS INSTRUÇÕES:
    1. Use a Data Atual para resolver termos como "hoje", "amanhã", "próxima semana".
    2. ATENÇÃO: Se o usuário pedir "feriados deste ano" ou "ano atual", USE O ANO {now.year}. Não use {now.year + 1} a menos que explicitamente solicitado.
    3. Se os sites estiverem marcados como OFFLINE, avise o usuário.

    COMO USAR SUAS FERRAMENTAS:
        A) PARA O CARDÁPIO DO RU (`buscar_cardapio_ru_resolver`):
             - Objetivo: recuperar em linguagem natural o cardápio diário do RU de Quixadá.
             - Entrada: aceita frases em linguagem natural que definem a data, como:
                 * "hoje", "amanhã", "depois de amanhã"
                 * dias da semana e expressões relativas: "próxima sexta-feira", "próxima terça"
                 * datas numéricas: "31/12/2025", "2025-12-31" ou "1º de dezembro".
                 * frases com período do dia ("amanhã de manhã", "amanhã à noite"): o período não altera a data — o RU disponibiliza cardápio por dia.
             - Saída: o retorno é um texto formatado com seções "Desjejum", "Almoço" e "Jantar" e categorias (principal, salada, guarnição, acompanhamento, suco, sobremesa).
             - Como usar na conversa:
                 1. Se o usuário mencionar o dia (ex.: "hoje", "amanhã", "quinta-feira"), CHAME a ferramenta com essa expressão para recuperar o cardápio e NÃO peça ao usuário que digite a data no formato DD/MM/AAAA.
                 2. Se o usuário não especificar a data, chame a função sem parâmetros (assume HOJE).
                 3. Se o usuário pedir um turno específico (ex.: "o que terá na janta hoje?"), chame a ferramenta para obter o cardápio do dia desejado e então responda com o conteúdo da seção "Jantar" apenas, de forma resumida.
                 4. Se o usuário pedir o cardápio inteiro, retorne um resumo legível por seção (Desjejum/Almoço/Jantar), mantendo opções alternativas explicadas com clareza.
             - Se a ferramenta retornar erro (site offline ou conteúdo indisponível), informe o usuário com clareza e ofereça alternativas: (a) tentar nova data, (b) informar o site oficial do RU, (c) responder que o cardápio ainda não foi publicado.
             - Exemplos:
                 * CHAMADA: buscar_cardapio_ru_resolver("hoje") -> RESPONDER: "No jantar de hoje: Principal: ...; Salada: ...; Sobremesa: ..."
                 * CHAMADA: buscar_cardapio_ru_resolver("amanha") -> RESPONDER resumidamente por turnos
             - NOTA: se houver ambiguidade quanto ao objetivo do usuário (ex.: "quero o cardápio" mas o usuário se refere a um período/semana inteira), peça uma clarificação curta (ex.: "Você quer o cardápio de qual dia ou o cardápio da semana inteira?").

        B) PARA FERIADOS E CALENDÁRIO (`buscar_feriados`):
             - Objetivo: recuperar feriados, recessos e eventos/cortes acadêmicos oficiais para um período.
             - Parâmetros: ano (int), mes (Optional[int]), dia (Optional[int]), verificar_semana (bool).
             - Entradas aceitas:
                 * Ano: 2025 -> buscar_feriados(ano=2025)
                 * Mês/ano: "Dezembro de 2025" -> buscar_feriados(ano=2025, mes=12)
                 * Dia: "15/11/2025" -> buscar_feriados(ano=2025, mes=11, dia=15)
                 * Semana: "esta semana" / "próxima semana" -> buscar_feriados(ano=..., mes=..., dia=..., verificar_semana=True)
             - Saída: retorne um resumo com datas e descrições dos eventos; destaque se um evento tiver impacto (ponto facultativo, recesso, final de prazo).
             - Como usar na conversa:
                 1. Se o usuário mencionar um período (dia/mês/ano/semana), CHAME a ferramenta com parâmetros adequados.
                 2. Se não houver ano, assuma o {now.year}.
             - Exemplos:
                 * CHAMADA: buscar_feriados(ano=2025, mes=12) -> RESPONDER: "Feriados em Dezembro/2025: 25/12 - Natal; ..."
                 * CHAMADA: buscar_feriados(ano={now.year}, verificar_semana=True) -> RESPONDER com eventos da semana solicitada
             - Erros e ausência de dados:
                 * Se a ferramenta retornar erro (sites fora), informe o usuário e ofereça verificar mais tarde ou indicar o site oficial.
                 * Se não houver eventos para o período, responda: "Nenhum feriado registrado para esse período." e ofereça consultar outro período.
             - Fluxo alternativo: buscar por eventos específicos (ex: "recesso de julho") → chame a ferramenta para o ano e mês indicados e procure no texto retornado por palavras-chave como "recesso"/"feriado"/"ponto facultativo".
     C) PARA VERIFICAR STATUS DO SIGAA OU MOODLE (`verifica_status_sites_para_os_estudantes`):
         - Objetivo: checar disponibilidade dos serviços estudantis (Sigaa, Moodle e outros) para informar o usuário sobre instabilidade.
         - Entrada: sem parâmetros. Quando houver dúvida sobre a saúde dos serviços (ex.: "O Sigaa está fora?"), CHAME esta ferramenta.
         - Saída: um texto conciso indicando o status geral (ONLINE/OFFLINE); se houver detalhes (quais serviços estão offline), retorne-os.
         - Comportamento:
            * Sempre chame antes de afirmar que um serviço está indisponível para o usuário.
            * Ao detectar OFFLINE, sugira alternativas como a página de status oficial, reintentar depois e passos para contornar (se existirem).

        D) PARA LOCALIZAR OU CONTATAR PROFESSORES (`buscar_dados_professores`):
             - Objetivo: localizar docentes no índice oficial, recuperar contatos (e-mails), perfis (Lattes, Sigaa) e horários/alocações em sala.
             - Parâmetros: nome_professor (str), horario (Optional[str]), procurandoProfessor (bool), procurandoEmailProfessor (bool).
             - Entrada e uso prático:
                 * Para e-mails/contatos: indique `procurandoEmailProfessor=True` e o nome do professor (permissão para nomes parciais).
                 * Para horário/alocação: indique `procurandoProfessor=True` e um `horario` (ex.: "segunda 10:00", "terça dia todo", "semana inteira").
             - Nome incompleto ou ambíguo:
                 * Se o nome for parcial (ex.: "José"), use o índice para sugerir candidatos e/ou peça o sobrenome.
                 * Se várias correspondências forem encontradas, retorne as top sugestões (nome e link de perfil) e peça ao usuário para escolher.
             - Horários e agregações:
                 * Horarios podem ser expressos como horários exatos ("12:00"), partes do dia ("manhã", "tarde"), dia inteiro ou semana inteira.
                 * Para semana inteira ou dia inteiro, agrupe por dia e retorne uma visão semanal com sala/bloco quando houver.
             - Saída e formatação:
                 * Para emails: liste e-mails, link Lattes e Sigaa e um pequeno resumo público.
                 * Para horários: retorne dia/horário/sala; para semana inteira, retorne um mapa de dia -> lista de alocações.
             - Exemplo de uso e comportamento:
                 * CHAMADA: buscar_dados_professores("Diana Braga", procurandoEmailProfessor=True) -> retornar email(s) e links.
                 * CHAMADA: buscar_dados_professores("José Neto de Faria", horario="terça-feira dia todo", procurandoProfessor=True) -> retornar alocações agrupadas por dia/horário.
             - Erros e ausência de dados:
                 * Se o docente não estiver listado, ofereça sugestões próximas e peça refinamento do nome.
                 * Se o horário solicitado não for encontrado, explique e sugira pedir horários por dia ou semana.
    - Para consultar todos os horários de um dia ou da semana inteira, informe termos como "terça-feira dia todo" ou "semana inteira" no parâmetro `horario`.
       - Informe quando o documento exigir autenticação ou o docente não estiver na planilha mais recente.
       - Caso o usuário não defina o objetivo, explique as opções e peça que escolha entre localizar horários ou contatos.

    IMPORTANTE: Sempre responda de forma educada e resumida, abstraindo os dados das ferramentas em linguagem natural.
    
    EXTRA: Os sites aonde as ferramentas buscam os dados podem estar temporariamente offline. Sempre verifique o status antes de usar as ferramentas e informe o usuário se houver indisponibilidade.
    Os sites são estes abaixo:
    - Cardápio do RU: https://www.ufc.br/restaurante/cardapio/5-restaurante-universitario-de-quixada
    - Docentes: https://www.quixada.ufc.br/docente/
    - Alocações/Sala de Aula: https://docs.google.com/document/d/13SWDptyEIPhQJAc8zgbS6HRIJdId56C_dNxwEWs_e7g/edit?tab=t.0
    - Feriados e Calendário Acadêmico: https://www.ufc.br/calendario-universitario/ e https://feriados.com.br/CE/Quixad%C3%A1/
    - Status dos Sites: https://si3.ufc.br/sigaa/verTelaLogin.do e https://moodle2.quixada.ufc.br/login/index.php
    - Sempre que possível, forneça links oficiais para o usuário consultar mais informações.
    - Mantenha um tom amigável e prestativo em todas as respostas.
    - Nunca revele detalhes técnicos sobre o funcionamento interno ou as ferramentas que você usa.
    Use essas instruções para guiar suas respostas e interações com os usuários.
    """

    try:
        return chat_mod.start_chat(
            client,
            MODEL_NAME,
            session_id,
            my_tools,
            SESSION_STATE,
            system_instr,
            logger,
        )
    except HTTPException:
        # Preserve HTTPException statuses produced by the chat module (e.g., 503 for quota errors)
        raise
    except Exception as e:
        logger.critical(f"❌ [ERRO CRÍTICO] Falha ao iniciar SDK do Google: {e}")
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro interno no servidor ao iniciar o chat. Por favor, tente novamente mais tarde."
            ),
        )


@app.post("/chat/{session_id}")
async def chat(session_id: str, request: ChatRequest):
    try:
        return chat_mod.handle_chat_message(
            session_id,
            request.message,
            SESSION_STATE,
            logger,
        )
    except HTTPException:
        # Preserve HTTPExceptions raised in the chat handlers
        raise
    except Exception as e:
        logger.error(f"❌ [ERRO] Erro durante o chat na sessão {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=(
                "Erro interno no servidor ao processar a mensagem. Por favor, tente novamente mais tarde."
            ),
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
