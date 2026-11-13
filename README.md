# Neufert Digital

Biblioteca personal local: Next.js App Router + React + TypeScript + Tailwind, API Python/FastAPI, PyMuPDF, SQLite FTS5 y sqlite-vec con multilingual-e5-small. No se publica ni requiere cuenta.

## Fichas con visión y búsqueda por página

Procesamiento completado: 608 páginas en FTS5 y embeddings; 1.475 fichas estructuradas de 566 páginas de contenido. Se conserva el modelo `intfloat/multilingual-e5-small` de 384 dimensiones y la búsqueda anterior. El nuevo endpoint híbrido es `/api/page-search`; el informe completo está en http://127.0.0.1:3000/api/reports/structured-book . Las cotas inciertas requieren revisión manual.

Migración, comandos de cada fase, configuración de visión, trazabilidad y resultados: [pipeline/README-structured.md](pipeline/README-structured.md).

## Fuente analizada

El archivo proporcionado `Neufert-4th-edition.pdf` se copió a `data/source/neufert.pdf`. **608 páginas, 4.ª edición inglesa (2012), traducción de la 39.ª edición alemana**, según las páginas preliminares. No corresponde a la 44.ª edición alemana. Contiene escaneos con capa OCR, índice PDF de capítulos y aproximadamente 2,27 millones de caracteres. Páginas con menos de 50 caracteres: 1, 5, 13, 607, 608. El OCR presenta errores y cotas sin unidad: las medidas ambiguas no se convierten automáticamente.

Auditoría detallada privada: `data/private/source-audit.json`. Propuesta previa de datos: [docs/data-model.md](docs/data-model.md). Inspección visual y CSS de la referencia: [docs/design-audit.md](docs/design-audit.md).

## Instalación (PowerShell, desde esta carpeta)

```powershell
python -m venv .venv
./.venv/Scripts/python -m pip install -r pipeline/requirements.txt
npm --prefix app ci
```

En Linux/macOS sustituir `./.venv/Scripts/python` por `.venv/bin/python`. Python 3.11 y Node 24 usados en desarrollo. Todo `/data`, el PDF original, modelos, dependencias y claves están excluidos de Git.

## Ingesta

### Paquete base preparado (sin abrir el PDF)

El paquete aportado `neufert-digital-paquete-base/neufert` está integrado como fuente preferente de páginas, miniaturas, índice y coordenadas. Para registrarlo de nuevo:

```powershell
./.venv/Scripts/python -m pipeline.base_package neufert-digital-paquete-base
```

Se comprueban las 608 páginas, sus archivos y la correspondencia de tres muestras OCR con el documento ya registrado. Los archivos se copian a `data/private/base-package`; se conserva el paquete original, también ignorado por Git. La importación conserva favoritos, fichas, FTS5 y vectores existentes. No recalcula medidas ni les añade validación visual. La importación del paquete por sí sola conserva las fichas heurísticas; la fase de visión posterior añade fichas validadas en la tabla `fichas`.

El visor utiliza los WebP del paquete y permite **Resaltar palabras** sobre coordenadas normalizadas; el resaltado escala con el zoom. Los listados usan miniaturas de 360 px y muestran capítulo/sección. Se conserva SQLite para la búsqueda híbrida; `search_text.json` queda disponible en privado para una futura búsqueda íntegramente en el navegador. El OCR, las medidas y las figuras anteriores no se sobrescriben con el paquete.

### Ingesta desde PDF

```powershell
./.venv/Scripts/python pipeline/inspect_source.py data/source/neufert.pdf
./.venv/Scripts/python -m pipeline.ingest --ocr-language eng
./.venv/Scripts/python -m pipeline.vectors
```

Para probar pocas páginas: `--limit 20`. `--embeddings` genera vectores al terminar. `--tables` activa pdfplumber; los resultados de tablas OCR pueden necesitar revisión. Las páginas se renderizan en WebP a 150 dpi. Se extraen bloques con bbox y recortes de imágenes o regiones gráficas heurísticas. Cada ficha conserva una hoja/sección completa para mantener unidas las cotas y los dibujos; la subdivisión editorial fina requiere revisión manual. Los títulos traducidos solo se rellenan cuando coinciden con el vocabulario verificado; los demás conservan el original.

La ingesta es reanudable: mismo hash/version y artefactos existentes omiten páginas completas. Cada página se confirma en una transacción. Los vectores se reanudan por ficha y chunk; ejecutar vectores **después** de la ingesta completa. Logs: `data/private/ingest.log`. No cambiar de edición sobre una base existente: usar otro `NEUFERT_DATA_DIR` para mantener bibliotecas separadas.

OCR: instalar Tesseract y sus datos de idioma. El PDF actual usa `eng`; para una fuente alemana usar `--ocr-language deu` y disponer de `deu.traineddata`. Solo se aplica OCR adicional a páginas sin texto suficiente. En esta máquina Tesseract tiene `eng` y `osd`; `deu` debe instalarse para una futura fuente alemana. `NEUFERT_DATA_DIR` permite elegir la raíz de datos (por defecto `./data`).

## Ejecutar

Dos terminales, desde la raíz:

```powershell
./.venv/Scripts/python -m uvicorn pipeline.api:app --host 127.0.0.1 --port 8000
```

```powershell
npm --prefix app run dev
```

Abrir http://127.0.0.1:3000 . El proxy de Next sirve los datos privados sin copiarlos a `public`. API y frontend se enlazan a loopback. Para producción local: `npm --prefix app run build` y `npm --prefix app start`. El script `start-local.ps1` arranca ambos servidores y los detiene al cerrar con Ctrl+C.

## Funciones y fases

1. Ingesta, búsqueda FTS5, ficha con texto/cotas y visor de páginas con zoom y bbox.
2. Facetas combinables con contadores, índice del libro, estilos basados en valores inspeccionados de christophhesse.eu, interfaz ES/EN/DE y revisión manual.
3. Fusión RRF de BM25 y vectores locales, expansión léxica ES/EN/DE, endpoint `/api/ask`, favoritos/colecciones SQLite, Markdown y vista de impresión para guardar como PDF con referencias. El comparador queda fuera de esta entrega opcional.

Los embeddings se descargan una vez a `data/private/models`; después funcionan localmente. Si aún no se generaron, la API mantiene FTS5 y expansión léxica; `/api/status` informa la cantidad de chunks vectoriales.

Opcionalmente definir `OPENAI_API_KEY` o `ANTHROPIC_API_KEY` en el entorno de la API. Se usa OpenAI Chat Completions o Anthropic Messages para reformular/filtros y seleccionar evidencia recuperada. Modelos configurables mediante `OPENAI_MODEL` y `ANTHROPIC_MODEL`. Con claves, se envían la consulta y fragmentos recuperados al proveedor. Sin claves no hay llamadas a LLM. Los extractos devueltos se validan como citas literales del texto recuperado y reciben página desde SQLite; respuestas no verificables se descartan. Un fallo remoto conserva la búsqueda local. No se ejecuta texto devuelto por modelos ni se aceptan filtros fuera del vocabulario.

## Verificación

```powershell
./.venv/Scripts/python -m pytest pipeline/tests -q
npm --prefix app run build
```

Las pruebas usan PDF sintético para no versionar contenido del libro. Cubren extracción, segmentación, numeración, unidades/contexto, filtros y consultas multilingües. La extracción heurística, las tablas y las normas históricas del libro deben contrastarse en el original. El estado «revisada» no cambia la confianza estimada por el extractor.

Resultado de la ejecución completa y límites de verificación: [docs/verification.md](docs/verification.md).

## Segunda pasada de unidades (Luna, v2)

La segunda pasada versionada usa exclusivamente `gpt-6-luna`. `.env` debe contener `NEUFERT_VERIFY_MODEL=gpt-6-luna` y `NEUFERT_VISION_MODEL=gpt-6-luna`; el comando se detiene si cualquiera selecciona otro modelo.

```powershell
./.venv/Scripts/python -m pipeline.verify_pass2_units --dry-run
# Solo después de la aprobación explícita:
./.venv/Scripts/python -m pipeline.verify_pass2_units --approved-full-run
```

El dry-run no llama a modelos y escribe `data/private/reports/segunda_pasada_unidad_contexto_v2_dry_run.json`. La corrida aprobada guarda estados y auditoría en un ledger v2 independiente; no reescribe valores, OCR ni el piloto histórico. Las cotas con unidad explícita en el recorte pueden quedar `verified`; una unidad inferida del contexto conserva cita literal y bbox, pero queda `verified_unit_inferred`.
