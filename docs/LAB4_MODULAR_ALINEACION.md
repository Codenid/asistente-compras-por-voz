# Alineación de la modularización con el informe del Lab 4

La arquitectura del informe y del notebook completo se conserva. Los notebooks separan responsabilidades y reutilizan las clases Python de `src/lab4_asistente/`; no introducen un segundo diseño.

| Diseño de la presentación | Implementación modular |
|---|---|
| Whisper large-v3-turbo | `voz.py`: clase `ASR`; carga desde `runtime.py`. |
| BM25 + multilingual-e5-base + bge-reranker-v2-m3 | `recuperacion.py`; notebook `03_rag_y_ablacion.ipynb`. |
| α y β elegidos con 150 consultas dev | Notebook 03 optimiza en `dev` y guarda los parámetros para la integración. |
| Evaluación con 250 consultas test; qrels separados | Notebook 01 selecciona consultas por `query_id`, garantiza la cobertura de candidatos y mantiene qrels aparte. |
| Qwen2.5-7B-Instruct con 9 herramientas | `modelos.py`, `herramientas.py` y `agente.py`; notebook 05. |
| Memoria de presupuesto, preferencias, carrito y cotización | `Estado` en `herramientas.py`; se incorpora al contexto del agente en cada turno. |
| Tienda SQLite y pedido atómico/idempotente | `tienda.py`; notebook 04. |
| XTTS-v2 y perfiles de voz | Notebook 02 genera los `.pt`; `voz.py` carga el perfil y el WAV original asociado. |
| 20 escenarios (14 texto, 6 voz), ASR y métricas | `escenarios.py`, `evaluacion.py` y notebook 07. |
| Ablación del denso y del reranker | Notebook 03 compara las variantes sobre el mismo conjunto de consultas de evaluación, con parámetros ajustados solo en desarrollo. |

## Cambios frente a los resultados del prototipo

La presentación registra 3/20 escenarios completos y señala dos fallos concretos: el agente afirmaba confirmar sin un pedido registrado y repetía unidades al llamar de nuevo a `agregar_al_carrito`. La versión modular conserva el agente único y las nueve herramientas, pero incorpora guardas de código para esos caminos. Los resultados del PPT se tratan como referencia de la ejecución anterior; la evaluación modular debe volver a ejecutarse antes de reemplazar las métricas o actualizar las diapositivas.

El notebook de perfiles requiere la transcripción exacta en un archivo `.txt` junto al WAV. El perfil la conserva y XTTS rechaza una síntesis casi idéntica al texto de referencia. Esto documenta que la voz se sintetiza con texto nuevo.
