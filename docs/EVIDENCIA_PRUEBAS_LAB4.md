# Evidencia de pruebas del Laboratorio 4

Esta carpeta documenta la ejecución local registrada el **25 de noviembre de 2026**
para el comprador `diego` y la voz de respuesta `ana`.

## Qué queda anexado

- `output/resultados/diego/20261125_234024/metricas_escenarios.csv`: resultado de los 20 escenarios (14 de texto y 6 de voz).
- `output/escenarios/diagnostico_texto/` y `output/escenarios/texto/`: registro y `estado_final.json` de cada escenario de texto.
- `output/escenarios/voz_audio/diego/`: audios de entrada de los seis escenarios de voz.
- `output/resultados/diego/20261125_234024/metricas_asr.csv`: WER, CER y errores de entidades.
- `output/resultados/diego/20261125_234024/latencias_por_turno.csv`: ASR, recuperación, herramientas, LLM y total por turno.
- `output/resultados/diego/20261125_234024/audio_vs_transcripcion.csv`: comparación de audio frente a transcripción correcta.
- `output/resultados/diego/20261125_234024/analisis_aciertos_fallos.csv`: análisis de aciertos y fallos.
- `output/resultados/diego/20261125_234024/evidencia.json`: evidencia detallada de operaciones, tiempos y estados finales.

## Resultado observado en los registros

La ejecución anexada registra **20/20 escenarios completados** (14 de texto y 6 de voz)
y **0 incumplimientos**.

## Métricas disponibles

La corrida anexada contiene las salidas finales de ASR, latencia por etapa y comparación
audio/transcripción. La carga inicial de modelos se conserva por separado en
`evidencia.json`.

El análisis de casos conserva el diagnóstico y la evidencia de cada fila del CSV.
