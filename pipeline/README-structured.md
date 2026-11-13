# SQLite y fichas con visión

## Resultado final, 2026-11-13

608 páginas y 120 entradas de índice; 566 páginas con extracción completada y 42 de referencia sin fichas. Se generaron 1.475 fichas. Búsqueda: 608 embeddings de página y 1.475 de ficha, conservando exactamente el modelo y formato existentes.

Validación automática de 11,145 cotas: 9,555 verified, 75 corrected y 1,515 uncertain. No quedan páginas fallidas. Las incidencias históricas de las páginas 15 y 66 se resolvieron; el registro histórico conserva sus intentos.

Consumo registrado, incluidos reintentos y lotes auxiliares: 1190 respuestas, 6,009,417 tokens de entrada y 1,716,804 de salida. Coste estándar estimado: 1.4593 USD; no es una factura y no aplica descuentos de caché ni recargos regionales. Los embeddings se calculan localmente.

Trazabilidad: 11.145 cotas auditadas; 5.041 usan el OCR completo de su página porque no se pudo vincular de forma fiable el candidato del modelo a un fragmento exacto. Se identifican en `ocr_traceability.csv`; sus valores no se corrigieron mediante esta vinculación.

Informe completo: http://127.0.0.1:3000/api/reports/structured-book . El CSV y resumen por capítulos están en `data/private/reports/validacion_cotas.csv` y `resumen_validacion.json`. Las páginas prioritarias para revisión son PDF 41, 171, 34, 360 y 397.

Consolidación reproducible sin nuevas llamadas de visión:

```powershell
./.venv/Scripts/python -m pipeline.ocr_traceability
./.venv/Scripts/python -m pipeline.structured embed --resume
./.venv/Scripts/python -m pipeline.structured report
./.venv/Scripts/python -m pytest pipeline/tests -q
```

## Libro completo (fase 3 aprobada)

Lotes auxiliares opcionales (durante el lote principal), con registros separados y parada antes de alcanzar el siguiente grupo; no generan informes ni vectores simultáneamente. El lote principal integra sus resultados y la consolidación final suma todos los archivos `vision-usage*.jsonl`:

```powershell
./.venv/Scripts/python -m pipeline.tail_worker --pages 400-587 --defer-at 380 --workers 2 --name tail --approved-full-run
./.venv/Scripts/python -m pipeline.tail_worker --pages 300-379 --defer-at 260 --workers 4 --name middle --approved-full-run
./.venv/Scripts/python -m pipeline.tail_worker --pages 501-587 --defer-at 460 --workers 4 --name last --approved-full-run
```

```powershell
./.venv/Scripts/python -m pipeline.structured full --approved-full-run --resume --dry-run --env-file .env
./.venv/Scripts/python -m pipeline.structured full --approved-full-run --resume --workers 4 --env-file .env
```

Procesa capítulos en orden y hasta cuatro páginas simultáneamente dentro de cada capítulo. Conserva el piloto y omite las páginas ya completadas. Preliminares, bibliografía e índice alfabético quedan como `reference_only`, consultables por búsqueda/visor, sin fichas arquitectónicas inventadas. Tras cada capítulo actualiza vectores e informes. Los fallos de página se reintentan una vez y quedan identificados; errores de autenticación o cuota interrumpen el lote. Para reanudar, repetir el comando.

Progreso: `data/private/reports/full-book-progress.json`. Fallos: `full-book-failures.jsonl` en esa misma carpeta. Log: `data/private/full-book.log`. Las llamadas y tokens siguen en `vision-usage.jsonl`. El piloto aprobado se conserva en `reports/pilot-review.html`, `pilot-resumen_validacion.json` y `pilot-validacion_cotas.csv`; los informes generales se actualizan sin reemplazar esa copia.

Trazabilidad OCR: `reports/ocr_traceability.csv` y `ocr-provenance.json` conservan el candidato transcrito por el modelo y cómo se vinculó al OCR original. `ocr_raw` se sustituye por el fragmento literal de origen cuando puede localizarse (incluyendo normalización de espacios o coma decimal). Si no hay una correspondencia, contiene el OCR completo de la página y queda marcado `full_page_fallback` en el informe: no se inventa una cita OCR. Esta comprobación no cambia los valores ni el estado de validación visual. Los embeddings de ficha usan título, resumen, etiquetas y medidas; no duplican dentro del vector el OCR completo de cada cota.

Modelo de visión elegido: `gpt-6-luna`. La clave local se carga explícitamente con `--env-file .env` (el archivo está excluido de Git):

```powershell
./.venv/Scripts/python -m pipeline.structured pilot --pages 39-48 --resume --env-file .env
```

El comando nunca imprime la clave. Las variables ya presentes en el entorno tienen prioridad sobre el archivo. Los tokens devueltos en cada llamada se registran en `data/private/vision-usage.jsonl`, incluso si una respuesta posterior no valida.

## Ejecución del piloto, 2026-11-12

Fase 1: 608 páginas en FTS5 y 608 vectores por página; se conservan los 2.607 chunks del índice anterior. Piloto PDF 39–48: 29 fichas y 29 vectores de ficha, 196 cotas (134 verified / 1 corrected / 61 uncertain). Prioridad de revisión: PDF 41 (59 inciertas), 45 (1), 47 (1). Son resultados de validación automática con visión; no revisión humana de todas las cotas.

Hubo un rechazo de esquema por una proporción representada como rango descendente. Se reintentó con el error explícito. La revisión de la página 46 detectó un decimal matemáticamente inferido; esa página se repitió con la regla de extraer únicamente números impresos. Se conservan las llamadas anteriores en el registro de consumo. Total: 23 llamadas con respuesta, 110.471 tokens de entrada y 39.274 de salida, coste estándar estimado de 0,0306841 USD (estimación sin recargos regionales ni descuentos de caché).

Vista de cinco fichas junto a sus páginas: http://127.0.0.1:3000/api/reports/structured-pilot . Archivos de informe en `data/private/reports/`. El piloto se aprobó y la fase 3 se completó. Pruebas actuales: 22 correctas.

Contrato conservado: `intfloat/multilingual-e5-small`, 384 dimensiones, normalización L2, float32 binario (1.536 bytes), sqlite-vec y distancia euclídea L2. Las consultas usan `query:`, documentos `passage:`. La migración comprueba el contrato con los vectores reales antes de escribir. Se guarda una copia SQLite previa en `data/private/before-structured.sqlite3`.

`pages` conserva sus columnas actuales y recibe `pdf_page`, `book_page`, `chapter`, `section`, `image_path`, `thumb_path`. `pages_fts` indexa el texto del paquete y usa BM25. `toc` conserva el índice editorial. Palabras: archivos lazy existentes, para no duplicar coordenadas ni cargar el libro completo al consultar una página.

```powershell
./.venv/Scripts/python -m pipeline.structured migrate
./.venv/Scripts/python -m pipeline.structured embed --resume
./.venv/Scripts/python -m pipeline.structured search --query "hospital corridor"
./.venv/Scripts/python -m pipeline.structured pilot --pages 39-48 --dry-run
```

Los embeddings por página cubren el texto completo: chunks con la misma segmentación de palabras del pipeline anterior, media de sus vectores y renormalización. `embeddings` conserva entidad/ID/modelo/dimensiones/vector/hash; `entity_vectors` permite KNN. Se omiten entradas con el mismo hash; un cambio de contenido reemplaza solo ese vector. Las tablas originales de búsqueda siguen intactas. RRF suma rangos de BM25 y vecinos vectoriales. La búsqueda nueva está disponible por CLI, sin sustituir el endpoint anterior de la app.

Variables de embeddings: `NEUFERT_EMBEDDING_PROVIDER=local` por defecto. Alternativa `compatible`: `NEUFERT_EMBEDDING_URL` (raíz API), `NEUFERT_EMBEDDING_API_KEY`. El proveedor debe servir exactamente el mismo modelo y devolver su nombre; se comprueban dimensiones y finitud. `NEUFERT_EMBEDDING_MODEL` solo acepta el modelo existente. `--batch-size 8` controla lotes; fallos HTTP transitorios tienen cuatro intentos con backoff.

Piloto con OpenAI:

```powershell
$env:OPENAI_API_KEY = 'configurar localmente'
$env:NEUFERT_VISION_PROVIDER = 'openai'
$env:NEUFERT_VISION_MODEL = 'gpt-6-luna'
./.venv/Scripts/python -m pipeline.structured pilot --pages 39-48 --resume
```

La clave se obtiene del entorno o de un archivo local indicado explícitamente mediante `--env-file .env`. La interfaz `VisionProvider.generate` admite un servidor compatible mediante `NEUFERT_VISION_URL`; otro proveedor requiere implementar esa interfaz. Cada página recibe dos llamadas independientes: extracción con imagen+OCR y contraste de cada cota con la imagen. Pydantic valida antes de persistir. Se conserva el OCR fuente y el candidato del modelo mediante la auditoría de trazabilidad descrita arriba; las cotas inciertas conservan el valor numérico inicial. Se registran motivos de validación y consumo devuelto por el proveedor. El segundo paso es validación automática por visión, no revisión humana.

Salidas privadas: `fichas/pNNN.json`, `fichas/pNNN.validation.json`, `reports/validacion_cotas.csv`, `reports/resumen_validacion.json` y `reports/piloto.html` (cinco fichas junto a su imagen). `python -m pipeline.structured schema` emite el esquema JSON. El vocabulario extensible está en `ficha_schema.TAGS`. Los límites plausibles son alertas conservadoras; no corrigen ni confirman cotas por sí solos.

`--chapter` filtra parte/sección; `--pages` acepta `39-48,50`. El piloto rechaza páginas fuera de 39–48. El procesamiento completo requiere aprobación del usuario y después `--approved-full-run`; no se ejecuta automáticamente. El dry-run no hace llamadas ni crea fichas: ofrece estimaciones de tokens, no una cotización. El coste requiere las tarifas del modelo elegido y las llamadas reintentadas también pueden facturarse. No hay un límite monetario automático.


## Segunda pasada de cotas pendientes

`python -m pipeline.verify_pass2 --pages 39-48 --dry-run` cuenta cotas y localizadores sin llamadas. El piloto autorizado se ejecuta con `--pages 39-48 --resume --env-file .env`. La ejecución completa requiere aprobación y `--approved-full-run`. Filtros: `--chapter`, `--pages`; `--force` repite cotas ya registradas. `--include-verified-sample N` está desactivado por defecto.

El original `data/source/neufert.pdf` genera los recortes PNG a 300 ppi. Se guardan en `data/private/crops`. La lectura recibe etiqueta/contexto con números ocultos y nunca recibe el valor candidato. `NEUFERT_VERIFY_MODEL` selecciona el modelo; si no se configura, se reutiliza Luna y el informe muestra esa limitación. La tabla `verification_pass2`, el historial y la copia `before-pass2.sqlite3` conservan la auditoría. Los informes `primera_pasada_*` preservan los resultados anteriores.

Tras completar el lote, ejecutar `python -m pipeline.pass2_report` para generar `segunda_pasada.csv`, resumen por capítulo y cinco recortes en `segunda_pasada.html`; actualiza los informes generales y omite embeddings cuyo texto/medidas no cambiaron. Vista: http://127.0.0.1:3000/api/reports/pass2 . El consumo se registra en `vision-usage-pass2.jsonl`, incluido en el total general.

La biblioteca nueva consulta `/api/search` (BM25 + E5 + RRF). Admite `chapter`, `result_type=all|page|ficha`, `include_uncertain` y `limit`. `/api/v1/search` conserva el comportamiento anterior para la sección desplegable de búsqueda anterior y colecciones. Las cotas muestran etiquetas de IA, motivo de incertidumbre y enlace a la página con bbox cuando se pudo localizar. Ocho consultas reales (cinco EN y tres ES) quedan en `reports/pass2-search-queries.json`.

Piloto completado: 62 cotas (61 uncertain + 1 corrected) → 1 verified + 61 uncertain. Se mantuvieron intactas las 9.555 verified originales y todo `ocr_raw`. 62 recortes, 123 respuestas API; coste adicional estimado 0.03908 USD. Reanudación: cero cotas pendientes en PDF 39–48. El resto requiere aprobación. 26 pruebas correctas y compilación Next.js correcta.


## Comparación aislada Luna / Sol 6.1

```powershell
$env:NEUFERT_VERIFY_MODEL = 'gpt-6.1-sol'
./.venv/Scripts/python -m pipeline.compare_pass2 --resume --env-file .env
```

Este comando solo permite el piloto PDF 39–48. Reconstruye las 62 entradas anteriores a Luna desde `verification_pass2.before`; conserva una copia de Luna, sus recortes, uso y palabras OCR en `data/private/pass2-runs/sol61-pilot-39-48/luna-frozen/`. Guarda Sol en una SQLite independiente `run.sqlite3`, sin aplicar decisiones a `fichas`, sin tocar vectores ni reemplazar informes de Luna. La reanudación omite cotas completadas. `--dry-run` no llama al proveedor.

`comparison.html`, `comparison.json` y `comparison.csv` contienen transiciones, causas, evidencias y proyección de coste. Vista HTTP: `/api/reports/pass2-comparison`. El análisis semántico adicional de causas lo realiza Sol sobre los recortes de ambas corridas y tiene consumo separado; no es una segunda verdad independiente. `not_a_dimension` es únicamente una propuesta, nunca una mutación en esta corrida. `integrity.json` comprueba los hashes de las tablas originales y de todos los archivos congelados de Luna.

Costes: tarifas Standard verificadas en las páginas oficiales de cada modelo; se ofrecen una estimación sin descuentos y otra con caché observada. La proyección del libro usa las 1.590 cotas elegibles de la copia previa a Luna; incluye una sensibilidad orientativa porque PDF 41 concentra casi toda la muestra. El comando no implementa una ejecución completa y no puede iniciarla por accidente.

Resultado de la comparación: Luna 1/61 inciertas confirmadas, Sol 0/61; la corregida inicial quedó incierta en ambas. Causas (a/b/c/d): Luna 5/40/16/0; Sol 5/46/11/0. En b se distinguen lecturas incompletas por unidad no visible; 35 cifras de Luna y 40 de Sol coinciden literalmente pero carecen de unidad confirmada. No se propone reclasificar ninguna ficha de este piloto como not_a_dimension.

Costes Standard de verificación sin descuentos: Luna 0,0390849 USD y Sol 0,560148 USD. Con caché observada: 0,03842826 y 0,5462856 USD. El análisis adicional de causas costó 0,332316 USD con Sol. Proyección lineal de verificación (sin ese análisis adicional): cola completa de 1.590 cotas ≈1,00 USD Luna / 14,37 USD Sol; resto de 1.528 cotas ≈0,96 / 13,80 USD. Las diferencias de densidad y localización limitan esta extrapolación. 28 pruebas correctas, reanudación comprobada sin llamadas nuevas y hashes de producción/Luna intactos.

## Segunda pasada con unidad contextual (v2, solo Luna)

Para el nuevo flujo, fija ambas variables en `gpt-6-luna`. El código falla antes de cualquier llamada si encuentra otro valor:

```powershell
$env:NEUFERT_VERIFY_MODEL = 'gpt-6-luna'
$env:NEUFERT_VISION_MODEL = 'gpt-6-luna'
./.venv/Scripts/python -m pipeline.verify_pass2_units --dry-run
```

El dry-run usa la copia previa al piloto y el registro histórico de Luna; no inicia llamadas ni altera fichas. Sus resultados y el registro por llamada quedan en `data/private/reports/segunda_pasada_unidad_contexto_v2_dry_run.json`. Solo tras aprobación se ejecuta `./.venv/Scripts/python -m pipeline.verify_pass2_units --approved-full-run`. Esta corrida usa un ledger separado (`verification_pass2_units_v2`), reanuda desde las cotas ya registradas, mantiene los valores y `ocr_raw` originales, y escribe el informe en `data/private/reports/segunda_pasada_unidad_contexto_v2.json`.

El estado `number_confirmed_unit_pending` confirma solo el número del recorte. Una unidad contextual inequívoca, con cita literal, bbox y plausibilidad aceptada, se guarda como `verified_unit_inferred`; nunca como `verified`. Las declaraciones ambiguas o implausibles quedan pendientes y se detallan en el informe. La interfaz conserva el aviso «Validación automática por IA, no revisión humana».
