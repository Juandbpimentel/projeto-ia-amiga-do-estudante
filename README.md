# projeto-ia-amiga-do-estudante
Neste projeto, estudarei como criar um chatbot com a API do Gemini e como implementar RAG para coleta de dados, utilizando-os para contextualizar as respostas do modelo durante o chat.

## Estrutura
- `frontend/`: Aplicação Next.js (App Router) que expõe uma interface de chat e encaminha todas as mensagens ao backend.
- `backend/`: API FastAPI que gerencia sessões de chat, interage com a API do Gemini e implementa RAG para buscar informações em fontes externas (ex.: cardápio da RU).

## Pré-requisitos
- Node.js 24+
- Python 3.12+

## Como executar

1. **Backend**
	```pwsh
	cd backend
	copy .env.example .env  # ajuste as chaves necessárias
	docker compose up -d redis  # (opcional) start local Redis for development
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

	A interface ficará disponível em http://localhost:3000 e consumirá automaticamente o backend (via rotas internas `/api`).