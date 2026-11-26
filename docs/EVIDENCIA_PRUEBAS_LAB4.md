# Evidencia de pruebas del Laboratorio 4

Esta carpeta documenta la ejecución local registrada el **25 de noviembre de 2026**
para el comprador `nicole` y la voz de respuesta `ana`.

## Qué queda anexado

- `output/resultados/nicole/20261125_190507/metricas_escenarios.csv`: resultado de los 20 escenarios (14 de texto y 6 de voz).
- `output/escenarios/diagnostico_texto/` y `output/escenarios/texto/`: registro y `estado_final.json` de cada escenario de texto.
- `output/escenarios/voz_audio/nicole/`: audios de entrada y respuestas de los seis escenarios de voz.
- `output/auditoria_escenarios/auditoria_turnos.csv`: transcripción, entrada ejecutada, respuesta, operaciones y resultado por turno.
- `output/auditoria_escenarios/auditoria_escenarios.csv`: consolidado por escenario, incluyendo pedidos observados, verificador y ruta del registro.
- `output/resultados/nicole/20261125_190507/metricas_asr.csv`: WER, CER y errores de entidades.
- `output/resultados/nicole/20261125_190507/metricas_tts_por_respuesta.csv`: inteligibilidad y semejanza de las respuestas de voz.
- `output/resultados/nicole/20261125_190507/latencias_por_turno.csv`: ASR, recuperación, herramientas, LLM, TTS y total por turno.
- `output/resultados/nicole/20261125_190507/escenarios_audio_vs_transcripcion_correcta.csv`: comparación de audio frente a transcripción correcta.
- `output/resultados/nicole/20261125_190507/analisis_cinco_aciertos_y_fallos.csv`: cinco aciertos y cinco fallos con diagnóstico y evidencia.
- `output/resultados/nicole/20261125_190507/evidencia.json`: evidencia detallada de operaciones, tiempos y estados finales.

## Resultado observado en los registros

La ejecución contiene los 20 escenarios, pero los archivos anexados no respaldan un
resultado de 20/20 completados. `metricas_escenarios.csv` registra **6/20 completados**
(5 de texto y 1 de voz), con **14 escenarios no completados**. Por tanto, la cifra
20/20 que aparece en documentación previa debe considerarse un resultado reportado de
otra ejecución hasta que se adjunten sus registros correspondientes.

Esta diferencia no invalida la evidencia anexada: permite revisar cada caso, localizar
las causas de fallo y separar problemas de ASR de problemas del agente mediante la
comparación con la transcripción correcta.

## Métricas disponibles

La corrida anexada contiene las salidas finales de ASR, TTS, latencia por etapa y
comparación audio/transcripción. La carga inicial de modelos se conserva por separado
en `evidencia.json`.

El análisis de casos contiene exactamente cinco aciertos y cinco fallos. Las causas no
se resumen aquí para conservar el vínculo directo con el diagnóstico y la evidencia de
cada fila del CSV.
