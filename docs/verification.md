# Verificación local — 2026-11-12

- Ingesta completa: 608 páginas y 608 fichas JSON privadas.
- 4.085 recortes; 3.263 medidas con unidad explícita; numeración impresa detectada en 579 páginas.
- 2.607 chunks vectoriales multilingual-e5-small, correspondientes a las 608 fichas.
- Reejecución de ingesta: 608 páginas completas omitidas. Prueba adicional elimina un artefacto sintético y confirma su regeneración sin duplicados.
- SQLite `PRAGMA integrity_check`: `ok`.
- `python -m pytest pipeline/tests -q`: 10 passed.
- `npm --prefix app run build`: compilación y TypeScript correctos; rutas `/` y `/print`.
- Frontend local HTTP 200 en http://127.0.0.1:3000 . API en loopback puerto 8000.
- Consulta híbrida real «pasillo de hospital»: primeros resultados HOSPITALS, páginas PDF 319, 307 y 309.
- Colección temporal: crear, añadir, exportar Markdown, filtrar y retirar verificados por HTTP; colección de prueba eliminada.
- Navegador: búsqueda «escaleras para viviendas», apertura de ficha y visor de página original con bbox comprobados visualmente.
- LLM remoto: validación y fallback probados con respuestas simuladas; no se consumió una clave API. PDF: se ofrece vista de impresión del navegador, no un motor PDF independiente.

Límites de la extracción actual: una ficha por hoja/sección, recortes heurísticos y títulos originales cuando no existe una traducción del vocabulario. Requieren revisión editorial para subdividir hojas o confirmar cotas OCR. No se implementó el comparador opcional.
