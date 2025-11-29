import datetime

# Config and constants used across the project
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

DOCENTES_URL = "https://www.quixada.ufc.br/docente/"
ALOCACAO_URL = "https://www.quixada.ufc.br/alocacao/"
ALOCACAO_DOC_URL = "https://docs.google.com/document/d/13SWDptyEIPhQJAc8zgbS6HRIJdId56C_dNxwEWs_e7g/edit?tab=t.0"

DOCENTES_CACHE_TTL = datetime.timedelta(hours=12)
DOCENTE_PROFILE_TTL = datetime.timedelta(hours=12)
ALOCACAO_CACHE_TTL = datetime.timedelta(minutes=30)

TOKEN_FUZZY_CUTOFF = float(0.70)
FULL_FUZZY_CUTOFF = float(0.65)

SECTION_LABELS = {
    "desjejum": "Desjejum",
    "almoco": "Almoço",
    "almoço": "Almoço",
    "jantar": "Jantar",
}

MODEL_NAME = "gemini-2.5-flash"

# selection ttl default
SELECTION_TTL_MINUTES = 3
SELECTION_TTL = datetime.timedelta(minutes=SELECTION_TTL_MINUTES)
