# Neufert Digital — paquete base (Architects' Data, 4ª ed., 608 páginas)

Origen: Neufert-4th-edition.pdf (escaneo 300 ppi con capa OCR). Edición en inglés.

## Estructura
- `pages/pNNN.webp`   página completa, gris, 150 ppi, WebP sin pérdida (~1250×1762 px). NNN = página del PDF (001–608).
- `thumbs/pNNN.webp`  miniatura 360 px de ancho, para listados y resultados.
- `text/pNNN.txt`     texto OCR de la página (orden de lectura).
- `words/pNNN.json`   palabras con coordenadas normalizadas 0–1: [texto, x0, y0, x1, y1]. Sirve para resaltar resultados de búsqueda sobre la imagen.
- `search_text.json`  todo el texto en un solo archivo: [{p, t}, ...] (2,3 MB) para construir el índice de búsqueda en el cliente.
- `toc.json`          índice del libro (120 entradas, niveles 0 = parte, 1 = capítulo) con pdf_page, pdf_end, book_page.
- `pages_index.json`  por página: pdf_page, book_page, chapter, section, chars, rutas a imagen y miniatura.

## Numeración
Página impresa del libro = página del PDF − 13 (verificado en varias partes del libro). Las páginas 1–13 del PDF son portada y preliminares (book_page = null).

## Limitaciones conocidas
- El OCR es bueno en párrafos pero ruidoso en cotas, leyendas y pies de dibujo. Las fichas con medidas deben validarse contra la imagen.
- Páginas sin texto útil: 1, 5, 13, 607, 608.
- Aún no hay fichas estructuradas (tipología, espacios, dimensiones, mobiliario). Es el paso siguiente.
