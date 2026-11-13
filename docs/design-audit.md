# Inspección de christophhesse.eu

Fecha: 2026-11-12. Fuente: https://www.christophhesse.eu/ . HTML y CSS descargados a `data/private/reference.html` y `reference.css`. La conexión inicial a Chrome falló por timeout CDP; después se abrió en el navegador integrado y se comprobó visualmente la composición (fondo blanco, texto negro, cabecera mínima y grandes imágenes de dibujos). Los valores numéricos proceden del CSS servido; no se atribuyen animaciones computadas no verificadas.

Valores verificados antes de escribir CSS:

| Elemento | Evidencia CSS | Valor |
|---|---|---|
| Texto | preset 16wpot4 / token 42f80aff | #141414 |
| Texto secundario | token f1811bb7 | #1f1f1f |
| Fondo | reglas de página | #fff |
| Familia principal | presets de texto | Funnel Sans, sans-serif |
| Texto/navegación | preset 16wpot4 | 20px, peso 500, tracking -.04em, línea 1.2 |
| Secciones | preset 9wuu6m | 28px, 500, -.02em, línea 120% |
| Título | preset 1abt6ll | 44px, 700, -.02em, línea 1.2; variante móvil 24px |
| Metadatos | preset y1hctm | 14px, 400 |
| Cabecera | framer-1kat36o | padding 12px 28px 12px 29px |
| Contenedor | framer-yfnwk | padding 0 28px 80px; gap 96px; min-height 100vh |
| Grid | framer-1mrlvxt | gap 24px; variante una columna |
| Breakpoints | media queries | 810px y 1200px |
| Hover enlaces | preset 1crf5n6 | #1f1f1f66 |
| Transición encontrada | estilos inline | opacity 0.2s (no prueba de transición global) |

Adaptaciones del producto: grid de resultados 1/2/3 columnas, imágenes con object-fit contain para no cortar cotas, controles con mínimo 44px, foco negro de 2px, subrayado en hover para conservar contraste (el alpha .4 observado no se aplica al texto de controles). Estos son valores de adaptación, no mediciones atribuidas al sitio. El carrusel es manual, sin movimiento automático. Fuente distribuida localmente mediante @fontsource, no copiada del sitio.
