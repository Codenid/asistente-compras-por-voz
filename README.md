# Asistente de compras por voz

Nuestra solución convierte una consulta hablada en español en una recomendación sustentada en el catálogo, conserva las restricciones de la conversación y puede preparar y registrar una compra en una tienda simulada. La respuesta se sintetiza con XTTS-v2 usando un perfil de voz propio o autorizado.

## Estructura de ejecución

La implementación está dividida en notebooks cortos que comparten clases sencillas de Python en `src/lab4_asistente/`. Ejecutamos los notebooks en este orden:

1. [Datos y catálogo](notebooks/01_datos_y_catalogo.ipynb): preparar catálogo, consultas y anotaciones.
2. [Perfil de voz](notebooks/02_preparar_perfil_de_voz.ipynb): generar un perfil `.pt` desde una grabación autorizada.
3. [RAG y ablación](notebooks/03_rag_y_ablacion.ipynb): evaluar recuperación y ajustar parámetros en desarrollo.
4. [Tienda SQLite](notebooks/04_tienda_sqlite.ipynb): comprobar carrito, cotización y pedidos.
5. [Agente y memoria](notebooks/05_agente_y_memoria.ipynb): integrar herramientas y restricciones.
6. [Integración de voz y compra](notebooks/06_integracion_voz_y_compra.ipynb): probar el flujo hablado.
7. [Pruebas y resultados](notebooks/07_pruebas_y_resultados.ipynb): ejecutar escenarios y generar métricas.

Consulta también la [guía de notebooks](notebooks/README.md). La tienda usa precios y existencias simulados; no realiza compras reales.

## Preparación del entorno

Usa Python 3.11 y el entorno CUDA del proyecto. En la carpeta raíz del repositorio:

```bash
python3.11 -m venv .venv-dl-cuda
source .venv-dl-cuda/bin/activate
python -m pip install --upgrade pip
python -m pip install torch==2.7.1 torchaudio==2.7.1 --index-url https://download.pytorch.org/whl/cu128
python -m pip install -r requirements-lab4-modular.txt
python -m pip install ipykernel
python -m ipykernel install --user --name lab4-voz --display-name "Python (Lab4 voz)"
```

En VS Code selecciona **Python (Lab4 voz)** como kernel. Comprueba CUDA antes de abrir los notebooks:

```bash
python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available()); print(torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'GPU no disponible')"
```

La integración usa una política fija para la GPU local de 12 GB: Qwen2.5-7B corre en CUDA con cuantización de 4 bits; recuperación, Whisper y XTTS corren en CPU durante la integración. Así no compiten simultáneamente por VRAM. El notebook 02 prepara perfiles XTTS en GPU y el notebook 03 ejecuta recuperación en GPU cuando Qwen no está cargado. **Cierra o apaga el kernel de cada notebook pesado antes de abrir el siguiente**, para que sus modelos no se queden ocupando memoria.

Si CUDA falla, la solución se detiene con una instrucción; Qwen no pasa silenciosamente a CPU. Cierra otras aplicaciones que usen GPU, reinicia el kernel y revisa `torch.cuda.is_available()` y la VRAM libre.

Los modelos se ejecutan localmente, sin APIs externas de inferencia. La primera carga necesita descargarlos.

## Datos y perfiles privados

Descarga los dos archivos de la versión small ESCI y guárdalos en `data/raw/`:

- `shopping_queries_dataset_products.parquet`
- `shopping_queries_dataset_examples.parquet`

No se suben los Parquet al repositorio. El notebook 01 valida el tamaño del catálogo, la separación por `query_id` y la cobertura completa de los productos anotados.

El notebook 02 acepta una grabación propia/autorizada en `data/voice_samples/<voz>.wav`. El menú permite elegir el perfil. Las grabaciones y perfiles contienen información de voz. Los WAV no se suben; el `.gitignore` protege nuevas grabaciones, perfiles generados y audios de escenario. El repositorio ya incluye perfiles `.pt` versionados: si esos perfiles no deben ser públicos, hay que retirarlos y limpiar también su historial antes de compartirlo.

Los audios de los seis escenarios se buscan en `data/scenario_audio/<voz>/`. Si faltan, el notebook 07 enumera los nombres requeridos. Cada turno conserva transcripción, operaciones, estado final, audio de entrada y respuesta generada bajo `output/`.

## Corrida integral del notebook 07

Reinicia el kernel y configura la primera celda antes de seleccionar **Ejecutar todo**:

```python
EJECUTAR_TEXTO = True
EJECUTAR_VOZ = True
EJECUTAR_REPLAY_TEXTO = True
SINTETIZAR_TTS = True
EVALUAR_TTS = True
GUARDAR_INFORME = True
PERSONA = 'diego'  # Audios del comprador.
VOICE_ID = 'ana'   # Perfil de síntesis del asistente.
```

El replay compara los escenarios de audio con su transcripción correcta. TTS puede tardar bastante en CPU. Para diagnosticar compras más rápido, desactiva `SINTETIZAR_TTS` y `EVALUAR_TTS`.

Para leer resultados guardados, desactiva los cinco indicadores de ejecución y voz. Deben existir los registros correspondientes. Cada nueva ejecución sobrescribe los registros por escenario; el informe se guarda en una carpeta fechada.

## Resultados revisados

Las corridas revisadas alcanzaron 14/14 escenarios de texto y 6/6 de audio con los criterios actuales. Revisa también las interacciones: el porcentaje aprobado no evalúa todos los detalles de calidad. Para una nueva corrida integral, el objetivo es 20/20 aprobados y cero incumplimientos.

Los registros JSON ya versionados se incluyen en el repositorio; `.gitignore` excluye nuevos resultados, datos y audios locales. Los informes fechados se generan en `output/resultados/<persona>/<fecha>/`.

## Evidencia producida

El notebook 03 guarda los parámetros ajustados solo en desarrollo y reporta nDCG@10 de BM25, sistema completo y ablaciones con las mismas consultas de evaluación. El notebook 07 produce porcentaje de escenarios completados, incumplimientos, WER/CER y errores de entidades ASR, comparación con transcripción correcta, inteligibilidad/semejanza TTS, latencias por etapa y carga inicial separada. También genera cinco aciertos y cinco fallos con el diagnóstico del verificador y operaciones como evidencia.

El informe final y la evidencia de la corrida aprobada están en [`docs/INFORME_FINAL_LAB4.md`](docs/INFORME_FINAL_LAB4.md). Los resultados se conservan en `output/resultados/` y `output/escenarios/`.
