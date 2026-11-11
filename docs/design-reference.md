# Inspección de christophhesse.eu

Intentos: HTTPS a `www.christophhesse.eu` y `christophhesse.eu`, con proxy y verificación TLS del entorno. Resultado: HTTP CONNECT 403, destino no permitido por la política activa. El borrador contiene los dominios, pero no está aplicado ni publicado. Las herramientas de escritorio Chrome no se exponen en esta sesión; hay Chromium/Playwright disponible para pruebas locales.

**No hay observaciones válidas de CSS calculado.** No se atribuyen colores, familias, tamaños, márgenes, grid ni transiciones a la referencia. Tampoco se ha escrito CSS de diseño o activado el reset de Tailwind: la interfaz funcional conserva el estilo nativo y el foco del navegador. Tailwind y PostCSS están instalados y configurados para la siguiente fase.

Pendiente cuando el dominio esté permitido:

1. Abrir el sitio real con Chromium, en móvil y escritorio.
2. Guardar capturas y medidas de `getComputedStyle` de navegación, hero, encabezados, textos y enlaces.
3. Registrar valores exactos de colores/fuentes/tamaños, márgenes, gaps, columnas, breakpoints y transiciones de hover/foco.
4. Implementar tokens Tailwind a partir de esos datos, carrusel a pantalla completa y grillas responsivas; conservar foco visible, navegación por teclado, alt text y controles sin autoplay.
5. Probar contraste, ampliación al 200%, teclado, reducción de movimiento y anchos móviles.

Los tamaños HTML de miniaturas y los atributos SVG actuales son provisionales para lectura y coordenadas, no una reproducción del diseño de CHA. No se declara terminada la fase visual ni validada la adaptación móvil final.
