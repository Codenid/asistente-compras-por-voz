| ejecucion | paso | inicio | fin | duracion_s | tiempo_usado | avance | estado | comentario |
|---|---|---|---|---|---|---|---|---|
| 20261125-111610 | 2. Datos (catalogo, consultas, qrels) | 11:17:00 | 11:17:08 | 7.448 | 00:00:07.448 | 1 | OK | hash f9adcda4163b |
| 20261125-111610 | 3. Tienda simulada (base con semilla) | 11:17:31 | 11:17:31 | 0.063 | 00:00:00.063 | 1 | OK | hash cf45d8141aa8 |
| 20261125-111610 | 3.1 Restauracion reproducible | 11:17:31 | 11:17:31 | 0.023 | 00:00:00.023 | 1 | OK | huella afdd683c93168902 |
| 20261125-111610 | 4.1 Indice BM25 | 11:17:43 | 11:17:44 | 0.575 | 00:00:00.575 | 1 | OK |  |
| 20261125-111610 | 4.2 Modelo denso + embeddings del catalogo | 11:17:44 | 11:20:18 | 153.543 | 00:02:33.543 | 1 | OK | intfloat/multilingual-e5-base |
| 20261125-111610 | 4.3 Reranker | 11:20:18 | 11:20:20 | 2.080 | 00:00:02.080 | 1 | OK | BAAI/bge-reranker-v2-m3 |
| 20261125-111610 | 5. Evaluacion de recuperacion (ajuste dev, eval una vez) | 11:21:07 | 11:23:45 | 158.753 | 00:02:38.753 | 1 | OK | hash cb67ddbe1d7c |
