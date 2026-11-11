# Neufert Digital

Biblioteca privada local para consultar un PDF propio. Next.js App Router + React + TypeScript, API Python/FastAPI, PyMuPDF, SQLite FTS5 y sqlite-vec. Tailwind/PostCSS están preparados; el diseño final se mantiene pendiente hasta inspeccionar la referencia real.

**Estado:** aplicación funcional comprobada con un PDF sintético. No incluye el libro. No se ha podido analizar ni ingerir el adjunto real porque supera 32 MiB y su ruta Windows no existe en esta máquina. No se ha acreditado su edición. E5 no se ha descargado por el bloqueo de Hugging Face. La referencia de diseño también está bloqueada. No se dan las tres fases por terminadas.

## Estructura

```text
app/                 Next.js, componentes e idiomas ES/EN/DE
pipeline/            análisis, extracción, ingesta, búsqueda, API, tests
scripts/             instalación, arranque, preparación E5 y prueba de navegador
data/source/         PDF privado (ignorado)
data/private/        SQLite, imágenes, recortes, análisis, OCR y modelos (ignorado)
docs/schema.md       esquema, procedencia y límites de las heurísticas
docs/design-reference.md  inspección visual pendiente, sin valores inventados
```

`/data/` está en `.gitignore`. Todos los datos derivados viven bajo `$NEUFERT_DATA_DIR/private`. El backend por defecto busca `/data`; los scripts de desarrollo usan `./data` para funcionar sin privilegios. Si hay un volumen `/data`, exportar `NEUFERT_DATA_DIR=/data` antes de ejecutar **todos** los comandos. No mezclar distintas rutas entre API e ingesta.

## Instalar (Linux / WSL / macOS)

Requisitos: Python 3.11+ con venv, Node 20.9+ (verificado con Node 24), npm, `curl`, `sha256sum`; Tesseract/PyMuPDF OCR y el modelo alemán. En macOS `sha256sum` se obtiene con coreutils. Windows nativo: usar WSL2 o adaptar los scripts a PowerShell; esta instalación no fue probada en Windows.

Desde la raíz del repositorio:

```bash
export NEUFERT_DATA_DIR="$PWD/data"  # o /data si existe ese volumen
bash scripts/setup.sh
```

Instala dependencias Python y npm con lockfile, obtiene `deu.traineddata` oficial de un commit inmutable y verifica SHA-256; ejecuta tests y build. Instala modelos/documentos solo en la carpeta privada. No instala paquetes del sistema ni requiere una API externa. No descargar el libro desde fuentes ajenas al usuario.

El entorno cloud de esta sesión ya tiene dependencias base, Tesseract alemán y dependencias CPU de E5 instaladas. Los pesos E5 siguen pendientes.

## 1. Analizar e ingerir el PDF

Copiar el archivo propio a `$NEUFERT_DATA_DIR/source/neufert.pdf`. Una ruta de Windows no da acceso al archivo desde una máquina cloud. En WSL **del mismo equipo**, la ruta podría ser:

```bash
cp '/mnt/c/Users/agust/OneDrive/Documentos/ChatGPT/ARCHITECTURE/Neufert-4th-edition.pdf' "$NEUFERT_DATA_DIR/source/neufert.pdf"
```

Esto solo sirve si OneDrive tiene el archivo descargado y WSL ve esa unidad. En cloud hay que transferir o montar el archivo; el adjunto de este chat excede el límite de descarga de la herramienta. También se acepta otra ruta con `--source`.

```bash
.venv/bin/python -m pipeline.ingest --analyze
# Revisar número de páginas, metadatos, marcadores y páginas candidatas a OCR.
.venv/bin/python -m pipeline.ingest --limit 10
# Inspeccionar fichas/recortes antes de procesar el resto.
.venv/bin/python -m pipeline.ingest
```

Es secuencial, idempotente y reanudable por página; una sola ingesta a la vez. Registra progreso en stderr y estado en SQLite. `--force` reprocesa e invalida vectores de esas páginas; repetir después el índice E5. `--ocr auto|always|never` controla OCR. `--source /ruta/documento.pdf` admite originales fuera de `source`; conservarlos accesibles para «PDF original». Ningún OCR o LLM inventa cotas: las medidas reconocidas requieren comprobar el contexto.

Se conservan texto, bloques/bbox, candidato a página impresa, páginas WebP a 150 dpi, candidatos a esquemas incrustados/vectoriales, tablas de PyMuPDF y fichas por títulos. Textos multicolumna, cotas sin unidades, pies, diagramas y numeración impresa requieren revisión. Sin título fiable se usa una ficha por página con baja confianza. Las etiquetas ES/EN son un glosario heurístico, no una traducción completa del título. Más detalles en [el esquema](docs/schema.md).

## 2. Arrancar

```bash
bash scripts/dev.sh
```

Arranca API en loopback puerto 8000 y Next en loopback puerto 3000; Ctrl+C detiene ambos. La app envía `/api/*` al backend mediante rewrite. No exponer estos servicios a Internet: es una herramienta local, sin autenticación multiusuario. Para producción local: API con `.venv/bin/python -m uvicorn pipeline.api:app --host 127.0.0.1 --port 8000`, y en otra terminal `npm run start --prefix app` después del build.

Funciones: búsqueda FTS5 y fragmentos resaltados; filtros combinables con contadores, rango de longitudes en cm, revisión manual; detalle y medidas con contexto; recortes ampliables; visor con bbox, zoom y navegación; categorías y marcadores del PDF; favoritos, colecciones y exportación Markdown/PDF con páginas y hash de documento; selector ES/EN/DE persistido. Los textos del libro permanecen en alemán. El carrusel es manual, sin autoplay. Si no hay ingesta, se muestra un estado vacío explícito.

La interfaz provisional usa HTML semántico y estilos nativos del navegador para cumplir la instrucción de no inventar CSS antes de inspeccionar CHA. **No es el diseño final responsivo solicitado**. La navegación y controles se probaron a 390 y 1280 px; faltan auditoría visual, contraste y prueba responsiva final con el diseño observado.

## 3. Activar búsqueda híbrida E5

No requiere claves LLM. Requiere acceso inicial a Hugging Face y sus redirecciones de descarga; después funciona localmente.

```bash
bash scripts/semantic-setup.sh
# Tras futuras ingestas o --force, reutilizar el modelo cacheado sin descargar:
.venv/bin/python -m pipeline.semantic
```

Modelo: `intfloat/multilingual-e5-small`, CPU, 384 dimensiones, prefijos `query:`/`passage:`, normalización; coseno exacto en sqlite-vec + BM25 mediante RRF. Los pesos y caché viven en `private/models`. Si no hay modelo/índice, la API anuncia `fts5` y la interfaz avisa de la ausencia de semántica. El glosario multilingüe mejora FTS, pero **no equivale a un embedding multilingüe**. Los tests híbridos usan vectores deterministas; falta comprobar recuperación E5 real sobre el libro.

En este cloud se guardó un borrador de dominios para `christophhesse.eu`, `www.christophhesse.eu`, `huggingface.co`, `*.huggingface.co` y `*.xethub.hf.co`. Guardar la configuración en los ajustes del entorno para aplicar acceso y luego reintentar. Publicar es una acción distinta. No se desactivan TLS, firmas ni checksums.

## LLM opcional

Exportar `ANTHROPIC_API_KEY` o `OPENAI_API_KEY` en la **terminal del backend** (o mediante secretos seguros del entorno). No introducir claves en frontend, Git ni chat; `.env.example` contiene solo nombres y el backend no lo carga automáticamente. Ante ambas claves se prefiere Anthropic. Modelos configurables con `NEUFERT_ANTHROPIC_MODEL` y `NEUFERT_OPENAI_MODEL`.

La casilla de interpretación envía **solo la consulta** al proveedor. Se validan palabras clave alemanas y tipología; timeouts o respuestas incorrectas conservan búsqueda local. No hay resumen generativo: se muestran extractos citados para impedir que se agreguen cifras no recuperadas. No se envían páginas para enriquecer fichas. No se ha probado una llamada real porque no hay claves; tests verifican el contrato con respuestas simuladas. Permitir `api.anthropic.com` o `api.openai.com` en entornos restringidos si se activa esa opción.

## Validación

```bash
.venv/bin/python -m pytest pipeline/tests -q
npm run typecheck --prefix app
npm run build --prefix app
# Python con Playwright + Chromium. Usa puertos 8000/3000 libres y datos temporales:
python3 scripts/browser-smoke.py
```

Comprobado en esta sesión: 14 tests Python, incluido OCR alemán real en un escaneo sintético, conexiones concurrentes, reanudación, búsqueda y exportaciones. TypeScript y build pasan. Chromium comprueba búsqueda → ficha → favorito → colección → visor/bbox → exportaciones e idiomas; interacción en escritorio/móvil. Los tests no usan ni redistribuyen el libro.

## Fases y pendientes concretos

- **Fase 1, funcional con datos sintéticos:** ingesta, FTS5, ficha, visor y OCR probados. Pendiente análisis/ingesta del original y ajuste de segmentación con evidencia del libro.
- **Fase 2, funcional parcial:** facetas, rangos, categorías y marcadores. Bloqueado diseño final hasta inspeccionar la referencia; Tailwind instalado, sin CSS de diseño escrito.
- **Fase 3, funcional parcial:** recuperación híbrida implementada y probada con vectores de prueba; intérprete LLM con fallback; favoritos/colecciones/exportaciones probados. Pendientes pesos E5, validación multilingüe real y llamada LLM opcional. Traducciones completas/enriquecimiento con LLM y comparador no implementados.

Para continuar: disponer del PDF en Linux, permitir acceso a la referencia y al modelo, analizar portada/edición y páginas, ingerir una muestra, revisar extracción y diseño observado, completar ingesta e indexación y probar consultas reales. No se necesita decidir nada adicional para esos pasos.
