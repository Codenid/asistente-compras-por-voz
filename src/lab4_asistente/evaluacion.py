"""Funciones pequeñas para resumir escenarios, ASR, voz y latencias."""
import pandas as pd

from .voz import cer, errores_entidades, wer


def tabla_escenarios(resultados):
    return pd.DataFrame([{k: r.get(k) for k in ("id", "modo", "tipo", "completado", "fallos", "incumplimientos", "pedidos")}
                         for r in resultados])


def resumen_escenarios(resultados):
    total = len(resultados)
    completos = sum(bool(r.get("completado")) for r in resultados)
    incumplimientos = sum(len([x for x in (r.get("incumplimientos") or "").split(",") if x]) for r in resultados)
    return {"total": total, "completados": completos,
            "porcentaje_completado": round(100 * completos / total, 1) if total else 0.0,
            "incumplimientos": incumplimientos}


def tabla_asr(resultados_voz):
    filas = []
    for escenario in resultados_voz:
        for turno in escenario.get("registro", []):
            if "transcripcion_asr" not in turno:
                continue
            ref, hip = turno["texto_correcto"], turno["transcripcion_asr"]
            entidades = errores_entidades(ref, hip)
            filas.append({"escenario": escenario["id"], "turno": turno["turno"],
                          "referencia": ref, "transcripcion": hip, "WER": wer(ref, hip), "CER": cer(ref, hip),
                          **entidades})
    return pd.DataFrame(filas)


def tabla_latencias(resultados):
    filas = []
    for escenario in resultados:
        for turno in escenario.get("registro", []):
            for etapa, segundos in turno.get("tiempos", {}).items():
                filas.append({"escenario": escenario["id"], "modo": escenario["modo"],
                              "turno": turno["turno"], "etapa": etapa, "segundos": segundos})
    return pd.DataFrame(filas)


def tabla_calidad_tts(resultados_voz, carpeta, asr, semejanza, referencia):
    """Mide inteligibilidad por retranscripción y coseno de semejanza por respuesta WAV."""
    from pathlib import Path
    filas = []
    for escenario in resultados_voz:
        for turno in escenario.get("registro", []):
            audio = Path(carpeta) / escenario["id"] / f"t{turno['turno']}_asistente.wav"
            if not audio.exists():
                continue
            transcripcion = asr.transcribir(audio)
            filas.append({"escenario": escenario["id"], "turno": turno["turno"],
                          "WER_inteligibilidad": wer(turno["respuesta"], transcripcion),
                          "semejanza_coseno": semejanza.coseno(referencia, audio)})
    return pd.DataFrame(filas)
