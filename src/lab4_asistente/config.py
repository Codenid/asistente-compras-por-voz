"""Rutas y parámetros comunes del Laboratorio 4."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUTA_INPUT = ROOT / "input"
if not (RUTA_INPUT / "shopping_queries_dataset_products.parquet").exists():
    RUTA_INPUT = ROOT / "data" / "raw"

RUTA_OUTPUT = ROOT / "output"
RUTA_DATOS = RUTA_OUTPUT / "datos"
RUTA_EVAL = RUTA_DATOS / "evaluacion"
RUTA_CACHE = RUTA_OUTPUT / "indice"
RUTA_TIENDA = RUTA_OUTPUT / "tienda"
RUTA_ESCENARIOS = RUTA_OUTPUT / "escenarios"
RUTA_RESULTADOS = RUTA_OUTPUT / "resultados"
RUTA_VOICE_SAMPLES = ROOT / "data" / "voice_samples"
RUTA_VOICE_PROFILES = ROOT / "data" / "voice_profiles"
RUTA_AUDIO_ESCENARIOS = ROOT / "data" / "scenario_audio"

SEMILLA = 2026
N_CONSULTAS_EVAL = 250
N_CONSULTAS_DEV = 150
MIN_CATALOGO = 5000
GANANCIAS = {"E": 1.0, "S": 0.1, "C": 0.01, "I": 0.0}

MODELO_EMB = "intfloat/multilingual-e5-base"
MODELO_RERANK = "BAAI/bge-reranker-v2-m3"
MODELO_LLM = "Qwen/Qwen2.5-7B-Instruct"
MODELO_ASR = "openai/whisper-large-v3-turbo"
MODELO_TTS = "tts_models/multilingual/multi-dataset/xtts_v2"
MODELO_SEMEJANZA = "microsoft/wavlm-base-plus-sv"

TOP_CANDIDATOS = 50
TOP_RERANK = 30
K_RESULTADOS = 5
K_NDCG = 10
MAX_PASOS_AGENTE = 8
TURNOS_HISTORIAL = 6
CANTIDAD_MAX = 20
PRECIO_LOGNORMAL = (3.0, 0.8)
PRECIO_RANGO = (1.99, 399.99)
PROB_AGOTADO = 0.08
STOCK_MAX = 25
GRID = [i / 10 for i in range(11)]
