"""Carga de los componentes necesarios para la integración final."""
import json
import time

import pandas as pd
import torch

from . import config as C
from .agente import Agente
from .escenarios import Sistema
from .modelos import LLMLocal
from .recuperacion import Recuperador
from .tienda import Tienda


def detectar_dispositivo():
    """Usa CUDA solo si el runtime puede ejecutar un kernel básico."""
    if not torch.cuda.is_available():
        return "cpu"
    try:
        torch.arange(1, device="cuda")
        return "cuda"
    except RuntimeError as exc:
        print(f"CUDA no puede ejecutar este modelo de PyTorch; se usará CPU: {exc}")
        return "cpu"


def cargar_sistema(cargar_llm=True):
    """Carga catálogo, recuperación, tienda y agente; registra por separado tiempos de carga."""
    C.RUTA_RESULTADOS.mkdir(parents=True, exist_ok=True)
    catalogo = pd.read_parquet(C.RUTA_DATOS / "catalogo.parquet")
    consultas = pd.read_parquet(C.RUTA_DATOS / "consultas.parquet")
    qrels = pd.read_parquet(C.RUTA_EVAL / "qrels.parquet")
    dispositivo = detectar_dispositivo()
    cargas = {}

    t0 = time.perf_counter()
    recuperador = Recuperador(catalogo)
    recuperador.cargar_denso(C.MODELO_EMB, dispositivo, C.RUTA_CACHE)
    recuperador.cargar_reranker(C.MODELO_RERANK, dispositivo)
    cargas["recuperacion"] = time.perf_counter() - t0

    parametros_path = C.RUTA_RESULTADOS / "recuperacion_parametros.json"
    parametros = json.loads(parametros_path.read_text()) if parametros_path.exists() else {"alpha": 0.7, "beta_sistema": 0.8}
    recuperador.alpha = float(parametros.get("alpha", 0.7))
    recuperador.beta = float(parametros.get("beta_sistema", 0.8))

    C.RUTA_TIENDA.mkdir(parents=True, exist_ok=True)
    base = C.RUTA_TIENDA / "tienda_base.sqlite"
    trabajo = C.RUTA_TIENDA / "tienda.sqlite"
    if not base.exists():
        Tienda.crear_base(base, catalogo.product_id, C.SEMILLA, *C.PRECIO_LOGNORMAL,
                          C.PRECIO_RANGO, C.PROB_AGOTADO, C.STOCK_MAX)
    tienda = Tienda(base, trabajo, C.CANTIDAD_MAX)
    tienda.restaurar()

    llm = None
    if cargar_llm:
        t0 = time.perf_counter()
        try:
            llm = LLMLocal(C.MODELO_LLM, cuatro_bits=True, dispositivo=dispositivo)
        except ValueError as exc:
            falta_vram = dispositivo == "cuda" and (
                "Some modules are dispatched on the CPU or the disk" in str(exc)
                or "enough GPU RAM" in str(exc)
            )
            if not falta_vram:
                raise
            print("VRAM insuficiente para Qwen en 4 bits; se cargará el modelo en CPU.")
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            llm = LLMLocal(C.MODELO_LLM, cuatro_bits=False, dispositivo="cpu")
            dispositivo = "cpu"
        cargas["llm"] = time.perf_counter() - t0

    sistema = Sistema(catalogo, recuperador, tienda, llm, C.K_RESULTADOS,
                      C.MAX_PASOS_AGENTE, C.TURNOS_HISTORIAL)
    return {"catalogo": catalogo, "consultas": consultas, "qrels": qrels,
            "recuperador": recuperador, "tienda": tienda, "llm": llm,
            "sistema": sistema, "cargas": cargas, "dispositivo": dispositivo,
            "parametros_recuperacion": parametros}


def cargar_modelos_voz(voice_id, dispositivo=None):
    """Carga ASR y TTS; usa el perfil .pt preparado en el notebook de voz."""
    from .voz import ASR, TTSClonado
    dispositivo = dispositivo or ("cuda" if torch.cuda.is_available() else "cpu")
    voice_id = str(voice_id)
    referencia = C.RUTA_VOICE_SAMPLES / f"{voice_id}.wav"
    perfil = C.RUTA_VOICE_PROFILES / f"{voice_id}.pt"
    if not referencia.exists() or not perfil.exists():
        raise FileNotFoundError(f"Se requieren {referencia} y {perfil}")
    asr_device = 0 if dispositivo == "cuda" else -1
    t0 = time.perf_counter()
    asr = ASR(C.MODELO_ASR, asr_device)
    carga_asr = time.perf_counter() - t0
    t0 = time.perf_counter()
    tts = TTSClonado(C.MODELO_TTS, perfil, referencia, dispositivo)
    carga_tts = time.perf_counter() - t0
    return asr, tts, {"asr": carga_asr, "tts": carga_tts}
