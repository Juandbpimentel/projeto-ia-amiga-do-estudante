# projeto-ia-amiga-do-estudante
Neste projeto, estudarei como criar um chatbot com a API do Gemini e como implementar RAG para coleta de dados, utilizando-os para contextualizar as respostas do modelo durante o chat.

## Estrutura
- `frontend/`: Aplicação Next.js (App Router) que expõe uma interface de chat e encaminha todas as mensagens ao backend.
- `backend/`: API FastAPI que gerencia sessões de chat, interage com a API do Gemini e implementa RAG para buscar informações em fontes externas (ex.: cardápio da RU).

## Pré-requisitos
- Node.js 24+
- Python 3.12+
 - Docker (para iniciar um Redis localmente, opcional em dev)

## Como executar

1. **Backend**
	```pwsh
	cd backend
	copy .env.example .env  # ajuste as chaves necessárias
	# Inicie o Redis local para suportar sessões em múltiplos workers (opcional)
	# - use `docker compose up -d` ou `docker-compose up -d` caso seu Docker CLI use a versão antiga
	# - este comando irá expor o Redis na porta padrão 6379
	docker compose up -d redis
	pip install -r requirements.txt
	uvicorn main:app --reload --host 0.0.0.0 --port 8000
	```

2. **Frontend**
	```pwsh
	cd frontend
	copy .env.example .env.local
	npm install
	npm run dev
	```

## Variáveis de ambiente (importante)

O backend exige algumas variáveis de ambiente para funcionar corretamente, a mais importante é a chave da API do Gemini (Google GenAI). Você pode prover **uma** das opções abaixo:

- `GOOGLE_API_KEY`: chave de API simples (recomendado para testes simples).
- `GOOGLE_SERVICE_ACCOUNT_JSON`: o conteúdo JSON do Service Account (se preferir passar como conteúdo na variável de ambiente).
- `GOOGLE_APPLICATION_CREDENTIALS`: caminho para um arquivo JSON de credenciais (ex.: `C:\path\to\service_account.json`).

Além disso, para manter sessões entre workers (multi-worker) e compartilhar histórico, configure o Redis e defina a variável `REDIS_URL`.

Exemplo de valores e como gerar o `REDIS_URL` quando o Redis estiver rodando localmente via Docker Compose:

- Se estiver usando Docker Compose e a porta 6379 estiver mapeada para a sua máquina local, o `REDIS_URL` pode ser:
	- `redis://localhost:6379/0`

- Se você estiver usando Docker Compose em uma rede interna e quer que outros containers se conectem, use o hostname do serviço dentro do compose, ex.:
	- `redis://redis:6379/0`

Exemplo `.env` (backend/.env) mínimo:

```env
# GOOGLE API
GOOGLE_API_KEY=AIza...xxxxxxxxxxxxxxxx
# opcionalmente: GOOGLE_APPLICATION_CREDENTIALS=C:\path\to\account.json

# Redis (usado por session_store)
REDIS_URL=redis://localhost:6379/0

# Outras variáveis utilitárias
ALLOW_ORIGINS=http://localhost:3000
REQUIRE_GOOGLE_CREDENTIALS=true
MODEL_NAME=gpt-4o-mini
```

### Observações importantes
- Se `REDIS_URL` não estiver configurada, as sessões serão armazenadas em memória local por worker. Em ambientes com múltiplos workers (ex.: deploy em Render/Heroku com scale > 1), isso impedirá que as sessões sejam reidratadas corretamente entre workers.
- Garanta que a conta/KEY que você usa para o Gemini tenha permissões e cota suficientes.
- Em produção, não exponha as credenciais no repositório; use secrets/variáveis de ambiente oferecidas pela sua plataforma de deploy.

## Testes e validação rápida

- Verifique se o backend está respondendo:
	- <http://localhost:8000/health>
- Inicie uma sessão via POST em `/start-chat` e chame `/chat/<session_id>` enviando mensagens. Se você perguntar sobre o status do Moodle ou Sigaa, o backend tentará executar a ferramenta `verifica_status_sites_para_os_estudantes`.


	A interface ficará disponível em http://localhost:3000 e consumirá automaticamente o backend (via rotas internas `/api`).