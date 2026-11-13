# Propuesta de datos (previa a implementación)

- `documents`: SHA-256 del PDF, nombre, idioma y edición observados, metadatos, total de páginas, índice PDF.
- `pages`: documento + página PDF (1-based), numeración impresa nullable, tamaño en puntos PDF, texto, bloques/bboxes, tablas JSON, imagen WebP, estado y versión de ingesta.
- `entries`: ID determinista documento/página/segmento, título original y títulos DE/ES/EN (nullable si no hay traducción verificable), sección, texto, bbox en puntos, confianza, revisión.
- `figures`: recorte WebP, página y bbox, método de detección; los recortes heurísticos no se consideran figuras editoriales confirmadas.
- `dimensions`: nombre, valor, unidad, contexto literal, valor en metros solo para longitudes; no inferir mínimos ni normas.
- `tags`: tipología, espacio, uso, mobiliario; vocabulario multilingüe de reglas.
- `entries_fts`: FTS5 unicode61; título, texto y etiquetas. Sin sintaxis FTS cruda del usuario.
- `embeddings`: sqlite-vec, 384 dimensiones, modelo multilingual-e5-small; chunks de texto con prefijo passage, consultas con query; fusión RRF con BM25.
- `collections` + `collection_entries`: persistencia local independiente de los derivados. Favoritos como colección reservada.
- `review`: estado de revisión manual, separado de confianza heurística.

Las páginas se confirman por transacción tras generar sus artefactos. Un hash de fuente y una versión de pipeline evitan mezclar ediciones. Reanudar omite solo páginas completas cuyos artefactos existen. Vectores se generan después y se pueden reanudar independientemente. `/data` es relativo a la raíz del proyecto; `NEUFERT_DATA_DIR` permite otra ubicación.

API Python local (FastAPI) para SQLite, archivos privados y exportación; Next.js App Router actúa como proxy del mismo origen. Ambos servidores se enlazan a loopback. No hay publicación ni cuentas remotas.
