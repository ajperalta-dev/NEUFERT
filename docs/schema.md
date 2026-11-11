# Datos y análisis previo

## Estado del PDF real

No se ha podido abrir el libro. `/data/source/neufert.pdf` y `/ARCHITECTURE/Neufert-4th-edition.pdf` no existen en la máquina. El adjunto supera el límite de transferencia de 32 MiB. La ruta `C:\Users\agust\OneDrive\Documentos\ChatGPT\ARCHITECTURE\Neufert-4th-edition.pdf` es local a Windows y no es un montaje del entorno Linux.

No se afirma número de páginas, capítulos, edición, idioma ni calidad del texto del libro. El nombre del adjunto «4th-edition» no acredita que corresponda a la 44.ª edición alemana: verificar portada y metadatos cuando se pueda abrir.

`python -m pipeline.ingest --analyze --source /ruta/libro.pdf` informa metadatos, páginas, marcadores, longitud de texto por página y páginas candidatas a OCR. El informe se escribe al ingerir en `private/documents/<sha256>/analysis.json`. Menos de 50 caracteres es una señal heurística, no prueba de que la página sea escaneada; usar `--ocr always` o `--ocr never` tras revisarla.

## Esquema implementado

SQLite `private/neufert.sqlite3`, claves externas activadas, WAL:

| Entidad | Identificador y contenido |
| --- | --- |
| documents | SHA-256 completo, ruta local del original, total de páginas, metadatos, versión del pipeline |
| pages | (documento, página PDF desde 1), número impreso nullable, dimensiones en puntos PDF, texto, bloques JSON, imagen WebP, tablas JSON, OCR y estado |
| entries | ID estable por documento/página/segmento, títulos y etiquetas de descubrimiento DE/ES/EN, tipología, espacios, actividades, equipo, medidas, bbox, figuras, texto, confianza y revisión |
| entries_fts | FTS5 de títulos, texto y etiquetas; índice actualizado en la transacción de la página |
| entry_vectors | sqlite-vec `vec0`, vectores normalizados float32 de 384 componentes; modelo multilingual-e5-small |
| vector_metadata | Modelo de cada embedding; permite reanudar el índice semántico |
| favorites | Referencias a fichas, conservadas al reprocesar IDs estables |
| collections / collection_entries | Colecciones personales y relación muchos a muchos |

Cada medida conserva `{nombre, valor, unidad, contexto}`. Solo se extraen números con unidad explícita; nunca se deduce «mínimo», ancho, cumplimiento normativo o una cota que no exista. Filtros de longitud convierten mm/cm/m a cm y excluyen m² y grados. Rangos separados como «80–90 cm» requieren revisión: el parser conservador solo registra el número inmediatamente asociado a la unidad.

Coordenadas `[x0,y0,x1,y1]` en puntos, origen superior izquierdo, tal como las devuelve PyMuPDF. No son píxeles. Las imágenes del visor y el SVG comparten viewBox con las dimensiones de página.

## Incertidumbre y procedencia

La segmentación detecta títulos por tamaño/negrita. Sin títulos, mantiene una ficha por página y baja confianza. Diseños multicolumna, texto girado, pies y fórmulas requieren validación con el libro; no se garantiza segmentación editorial perfecta. Las figuras son candidatos de imágenes incrustadas y agrupaciones de trazos vectoriales; pueden incluir marcos o tablas y deben revisarse. Cada recorte conserva su bbox.

Las etiquetas ES/EN son un glosario de descubrimiento, **no una traducción íntegra acreditada del título alemán**. La interfaz lo indica. Textos y cifras permanecen en alemán. La confianza es una puntuación heurística, no una probabilidad calibrada. Las fichas OCR siempre quedan pendientes de revisión. La acción de revisión se conserva al reprocesar la misma ficha.

La página impresa se obtiene de etiquetas PDF distintas de la posición física o de números aislados en los márgenes. Si no se identifica, queda NULL; no se adivina un desfase.

## Idempotencia

Una sola ingesta a la vez. Hash del PDF y versión del pipeline identifican el corpus. Páginas confirmadas se omiten; cada página actualiza fichas, FTS y estado en una transacción. WebP usa escritura temporal y renombrado. `--force` reconstruye páginas y elimina sus vectores para recalcularlos; conserva favoritos, revisión y colecciones mientras se mantengan los IDs. Un cambio editorial de PDF crea otro documento. Cambios del algoritmo requieren nueva versión y reconstrucción en otra carpeta antes de migrar colecciones deliberadamente. Guardar copia de `private/` y el PDF con los procesos detenidos.

## Recuperación

FTS5 BM25 + expansión DE/ES/EN mediante glosario. Con índice E5 disponible, consulta `query:` y texto `passage:`, normalización y ranking coseno exacto sobre sqlite-vec; fusión RRF (k=60). Filtros posteriores y facetas disyuntivas antes de paginar. No se recorta el conjunto semántico antes de filtrar. Para un libro local se favorece exactitud frente a un índice ANN externo.

Si no hay modelo o índice, la API informa `mode=fts5` y una advertencia; **no se presenta como híbrida**. Las pruebas híbridas inyectan vectores deterministas para verificar ranking y filtros; no acreditan calidad semántica E5 con el libro real.

El LLM opcional recibe solo la consulta, devuelve palabras clave alemanas y una tipología validada. Fallos devuelven búsqueda local. No recibe el PDF ni genera medidas o resúmenes libres: la respuesta es extractiva y cada ficha cita la página. No se implementa enriquecimiento remoto de fichas ni traducción libre para evitar enviar páginas sin una elección explícita.
