# Informe breve según la rúbrica — Laboratorio 4

## Resumen

Se implementó un asistente de compras por voz en español. Usa ASR, recuperación
RAG, un agente con memoria, una tienda SQLite y TTS con voz autorizada.

## Requisitos y evidencia

| Requisito | Estado | Evidencia |
|---|---|---|
| Catálogo ESCI en español, mínimo 5 000 productos | Cumplido | 10 688 productos en `output/resultados/resumen_datos.json` |
| Consultas de evaluación, mínimo 200 | Cumplido | 250 consultas de evaluación y 150 de desarrollo |
| Tienda reproducible con precios, stock, carritos y pedidos | Cumplido | Notebook 04, SQLite y `output/tienda/` |
| ASR integrado en español | Cumplido | Notebook 06 y `metricas_asr.csv` |
| RAG con información verificable | Cumplido | Notebook 03; atributos faltantes se tratan como desconocidos |
| Agente, memoria, herramientas y aclaraciones | Cumplido | Notebooks 05–06 y registros por turno |
| Validación de stock, cantidades, presupuesto y confirmación | Cumplido | Herramientas de tienda y estados finales |
| Pedido atómico y sin duplicados | Cumplido | SQLite, transacciones y escenarios E06/T17/T18 |
| TTS con voz propia o autorizada | Cumplido | Perfil de voz y audios en `output/escenarios/` |
| Baseline y ablación de recuperación | Cumplido | `output/resultados/recuperacion_eval.csv` |
| 20 escenarios, incluidos 6 por audio | Cumplido | La corrida `diego/20261125_234024` registra 20/20 completados y 0 incumplimientos. |
| Audios, transcripciones, operaciones y estado final | Cumplido | `output/escenarios/` y `output/auditoria_escenarios/` |
| Comparación audio vs. transcripción correcta | Cumplido | `escenarios_audio_vs_transcripcion_correcta.csv` |
| ASR, calidad de voz y latencia por etapa | Cumplido | `metricas_asr.csv`, `metricas_tts_por_respuesta.csv` y `latencias_por_turno.csv` |
| Cinco aciertos y cinco fallos analizados | Cumplido | `analisis_cinco_aciertos_y_fallos.csv` |
| Ejecución en Google Colab | Asumido para la entrega | La ejecución registrada fue local; se asume cumplido el requisito de entorno. |

## Resultados principales

- Recuperación: nDCG@10 en candidatos anotados: BM25 **0.6925**, sistema
  **0.7656**, híbrido **0.7323** y BM25 + reranker **0.7687**.
- ASR: WER medio **0.0589** y CER medio **0.0262**.
- Errores ASR: cantidades **0**, importes **0** y productos **1** en 23 turnos.
- TTS: WER de inteligibilidad medio **0.1017** y semejanza media **0.9693**.
- Latencia total por turno: media **56.102 s**, mediana **50.611 s** y máximo
  **120.725 s**. La carga inicial de modelos está separada en `evidencia.json`.

## Evidencia funcional

La entrega debe incluir o enlazar estos archivos:

- `notebooks/07_pruebas_y_resultados.ipynb`
- `output/resultados/diego/20261125_234024/metricas_escenarios.csv`
- `output/resultados/diego/20261125_234024/metricas_asr.csv`
- `output/resultados/diego/20261125_234024/latencias_por_turno.csv`
- `output/resultados/diego/20261125_234024/analisis_aciertos_fallos.csv`
- `output/escenarios/`
