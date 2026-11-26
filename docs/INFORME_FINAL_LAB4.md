# Informe final — Laboratorio 4

## 1. Solución

Se implementó un asistente de compras por voz en español que recibe consultas por texto
o audio, busca productos con RAG, conserva el estado de la conversación, solicita
aclaraciones y opera sobre una tienda SQLite. El código valida stock, precios,
presupuesto, consentimiento y pedidos duplicados. Las respuestas pueden generarse con
una voz autorizada mediante TTS.

## 2. Datos y recuperación

- Catálogo: **10 688 productos**.
- Consultas de desarrollo: **150**.
- Consultas de evaluación: **250**.
- Se evaluaron BM25, el sistema, una variante híbrida y un reranker.

| Variante | nDCG@10 sobre candidatos anotados |
|---|---:|
| BM25 | 0.6925 |
| Sistema | 0.7656 |
| Híbrido | 0.7323 |
| BM25 + reranker | 0.7687 |

Las etiquetas ESCI se usan para evaluar y ajustar en desarrollo, pero no se exponen al
agente durante la consulta.

## 3. Pruebas funcionales

La corrida final registrada en `output/resultados/diego/20261125_234024/` contiene:

- **20/20 escenarios aprobados**.
- **14 escenarios de texto** y **6 de voz**.
- **0 incumplimientos** de las restricciones verificadas.
- Casos de compra, aclaración, cambio de cantidad, producto agotado, corrección ASR,
  cambio de stock y confirmación repetida.

Los registros y estados finales están en `output/escenarios/`. El resumen está en
`metricas_escenarios.csv` y la evidencia detallada en `evidencia.json`.

## 4. Voz y latencia

En los 6 escenarios de voz se registraron 22 turnos:

- WER medio: **0.1347**.
- CER medio: **0.0819**.
- Errores de cantidades: **0**.
- Errores de importes: **0**.
- Errores de productos: **6**.
- Latencia total por turno: media **18.54 s**, mediana **12.47 s**, máximo **39.86 s**.

El desglose está en `latencias_por_turno.csv` y la comparación de audio con la
transcripción correcta en `audio_vs_transcripcion.csv`.

La corrida final no incluye una métrica TTS cuantitativa porque esa evaluación estaba
desactivada. La generación de respuestas habladas sí está integrada en el código y en el
notebook de pruebas.

## 5. Análisis de casos

El notebook 7 genera el análisis de aciertos y fallos a partir de los registros reales.
La salida está en `analisis_aciertos_fallos.csv`; el diagnóstico usa las operaciones
ejecutadas y el estado final de la tienda.

## 6. Código y ejecución

Los notebooks finales están en `notebooks/`:

```text
01_datos_y_catalogo.ipynb
02_preparar_perfil_de_voz.ipynb
03_rag_y_ablacion.ipynb
04_tienda_sqlite.ipynb
05_agente_y_memoria.ipynb
06_integracion_voz_y_compra.ipynb
07_pruebas_y_resultados.ipynb
```

El notebook 7 puede revisar los registros guardados sin repetir los escenarios. Para
crear una copia fechada de los resultados se activa `GUARDAR_INFORME = True`.

## 7. Limitaciones

- La ejecución registrada se realizó localmente; para la entrega se asume cumplido el
  requisito de entorno indicado por el curso.
- Los atributos ausentes del catálogo se tratan como desconocidos.
- Los audios y perfiles de voz deben contar con autorización para su distribución.
- La métrica TTS cuantitativa debe añadirse si el docente la exige como resultado
  separado de la generación de voz.

## 8. Evidencia principal

- `output/resultados/diego/20261125_234024/metricas_escenarios.csv`
- `output/resultados/diego/20261125_234024/metricas_asr.csv`
- `output/resultados/diego/20261125_234024/latencias_por_turno.csv`
- `output/resultados/diego/20261125_234024/audio_vs_transcripcion.csv`
- `output/resultados/diego/20261125_234024/analisis_aciertos_fallos.csv`
- `output/escenarios/`
