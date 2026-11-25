# Laboratorio 4 — Asistente de compras por voz

Este paquete modulariza la solución completa del notebook y la presentación compartidos. Conserva los modelos y componentes definidos en ellos:

- Whisper large-v3-turbo para ASR en español.
- BM25 como baseline y recuperación híbrida con multilingual-e5-base y bge-reranker-v2-m3.
- Qwen2.5-7B-Instruct con un único agente y nueve herramientas explícitas.
- Tienda simulada en SQLite, con carrito, cotización y pedido atómico.
- XTTS-v2 con perfiles `.pt` generados desde una voz propia o autorizada.

La presentación refleja una ejecución anterior: **3 de 20 escenarios completados**. Esta organización conserva los resultados como referencia histórica, corrige dos causas raíz observadas (confirmación que el LLM anunciaba sin registrar y cantidades que se sumaban al repetir una herramienta) y obliga a volver a ejecutar la evaluación. No se presentan métricas nuevas hasta correrla.

## Preparación en Google Colab

1. Sube el ZIP del proyecto a tu Google Drive y descomprímelo, o clona el repositorio en Colab.
2. Abre Colab en la carpeta del proyecto; los notebooks localizan `src/` buscando la raíz.
3. Copia los Parquet a `input/` y las grabaciones privadas a `data/voice_samples/`.
4. Activa una GPU compatible en **Entorno de ejecución → Cambiar tipo de entorno de ejecución**.

## Orden de ejecución

1. `01_datos_y_catalogo.ipynb`
2. `02_preparar_perfil_de_voz.ipynb`
3. `03_rag_y_ablacion.ipynb`
4. `04_tienda_sqlite.ipynb`
5. `05_agente_y_memoria.ipynb`
6. `06_integracion_voz_y_compra.ipynb`
7. `07_pruebas_y_resultados.ipynb`

Los notebooks deben ejecutarse en Google Colab, desde la raíz del proyecto. El runtime debe tener GPU habilitada para que quepan los modelos de la solución. El paquete no llama a APIs externas de inferencia. `requirements-lab4-modular.txt` conserva NumPy 1.26 y PyArrow 20 para evitar el conflicto observado al importar versiones recientes de PyArrow con NumPy 1.x; PyTorch lo provee el runtime.

## Datos y voz

- Coloca los Parquet de la versión reducida ESCI en `input/` o `data/raw/`.
- Coloca una grabación de referencia por persona en `data/voice_samples/<voice_id>.wav`. Su transcripción en `<voice_id>.txt` es opcional: los perfiles se generan también cuando falta o está vacía.
- El notebook 02 produce `data/voice_profiles/<voice_id>.pt`.
- Los audios de escenario se guardan en `data/scenario_audio/<voice_id>/` como `E01_t1.wav` … `E06_tN.wav`. El notebook final muestra los nombres requeridos.

No subas perfiles o audios de voz a repositorios públicos sin autorización explícita de la persona.

## Propósito de cada notebook

- **01:** prepara catálogo, consultas y qrels separados; valida cobertura de candidatos.
- **02:** calcula y persiste perfiles XTTS reutilizables.
- **03:** compara BM25 con el sistema, ajusta α/β usando desarrollo y reporta ablaciones.
- **04:** muestra la tienda SQLite y las garantías transaccionales.
- **05:** prueba memoria, selección de herramientas y guardas de compra.
- **06:** conecta voz, agente, recuperación y tienda.
- **07:** ejecuta 20 escenarios, reproduce las seis pruebas de voz con transcripción correcta y conserva métricas/evidencias.
