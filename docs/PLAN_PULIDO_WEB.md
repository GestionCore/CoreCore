# Plan de pulido de la web — primero la página, después lo demás

> **2026-10-22:** el orden de trabajo ahora lo da [`docs/PLAN_MAESTRO_BETA.md`](PLAN_MAESTRO_BETA.md) (olas 0 a 5 hasta la beta). Este documento sigue valiendo como detalle de la parte visual (Ola 1 del plan maestro).

Preparado el 2026-10-22, a pedido del dueño: no gastar en suscripciones ni pruebas (WhatsApp Business, Google Workspace, tickets) hasta que la web esté para mostrarla y venderla. Se apoya en `docs/AUDITORIA_DISENO_100.md` (D1–D100) y en `PLAN_UX_200.md` (UX200#nn), que ya están medidos y priorizados: **no se vuelve a auditar, se ejecuta**.

## Por qué se siente «desprolija» (medido, no opinión)

La estructura está bien (se vio hoy en el navegador: Dashboard, Costos, Stock y Ganancia Real son claros, ordenados y consistentes entre sí). Lo que da la sensación de «falta pulir» son **detalles repetidos**, que juntos se notan:
- **Letra chica:** el 36 % del texto de escritorio mide menos de 12 px; hay 43 tamaños distintos (D12, D22).
- **Campos que no se ven:** el borde medía 1,19:1 (D13) → **ya corregido en el código, falta desplegar** (ver «Lo ya hecho»).
- **Falta de escala:** 46 sombras, 35 transiciones, 13 radios, 21 niveles de z-index, 6 «etiquetas» casi iguales (D37, D38, D42), 927 estilos escritos a mano en 53 plantillas (D39).
- **Color sin significado:** los bordes de color de las tarjetas de números no indican estado; un mismo violeta es acción, dato y decoración (D30, D92).
- **Repetición:** la misma cifra 3 veces en una pantalla, el primer KPI repite al hero (D5, D6); un botón violeta «Actualizar» en las 25 pantallas compite con el principal de cada una (D32).
- **Densidad:** páginas de 6.000–9.000 px en celular (D48); Costos apila 4 herramientas con 4 botones principales (D24).
- **Primera impresión y cuenta nueva:** pantallas vacías hasta la primera sincronización (D96), Planes sin tabla comparativa (D82), nombre de la cuenta mal escrito («Diegoarielsantiago», D79).

**Lo que está bien y no se toca:** la landing, las cifras con dígitos tabulares, «Lo que tenés que hacer hoy», el tema claro, el trabajo de celular, y **la identidad visual (grafito + violeta + dorado): nada de esto la cambia**.

## «Lista para mostrar y vender» (la vara de salida)

1. Ninguna cifra que engañe ni se repita (hecho en gran parte; falta D5/D6/D11).
2. Letra ≥ 12 px y campos visibles en todas las pantallas, con una sola escala de tamaños, sombras y radios.
3. Un botón principal por pantalla; el color significa estado.
4. **Una cuenta nueva y vacía se ve bien y guía** (estados vacíos con ejemplo), y probada con un rubro que no sea indumentaria.
5. La landing, Planes y las páginas legales se ven profesionales en celular y al compartir el link.
6. Cada dato que viene de Mercado Libre dice cuándo se actualizó y qué hacer si falla; lo reversible se puede deshacer.
7. Accesibilidad básica (encabezados, foco con teclado) y carga sin saltos.
8. **Prueba de 5 segundos con 5 personas** que no conocen CoreLux: ¿entienden qué hace y para quién?
9. Textos revisados con un solo tono (profesional, seguro, sin protestar de más).
10. Una **cuenta demo** con datos de ejemplo (otro rubro) para mostrar el producto sin exponer números reales.

## Las olas (un deploy por ola, no por arreglo)

**Ola 1 — Sistema visual (lo que más pesa en la sensación de prolijidad)**
- ✅ D13 borde de los campos (hecho, sin desplegar).
- D12 + D22: una escala de 6 tamaños de letra con piso de 12 px (junto con D39: sacar los estilos escritos a mano, pantalla por pantalla, empezando por Dashboard, Costos, Ganancia Real y Stock).
- D14, D16, D17, D18, D20: los contrastes que quedan (insignias, violeta como texto, píldora neutra, estrellas).
- D37, D38, D42: escala de z-index, sombras, radios y **una sola** etiqueta con variantes.
- D30 + D92: el color de las tarjetas de números solo cuando hay estado.
- D32: «Actualizar» deja de ser un botón violeta lleno: ícono discreto con «actualizado hace X».
- D29: las tarjetas de números que quedan huérfanas entre 1024 y 1280 px.
- D99: página interna `/ui` con todos los componentes y sus estados (guía viva; evita que vuelva la desprolijidad).

**Ola 2 — Primera impresión (lo que ve un desconocido)**
- Landing: celular (D52, D55), título y vista previa al compartir (D80, D85: imagen de 1200×630).
- Planes: tabla comparativa y «RECOMENDADO» (D82); páginas legales y de error con el mismo estilo; menú de cuenta sin «Eliminar» al lado de «Cerrar sesión» (D84).
- Entrada y cuenta nueva: onboarding, **estados vacíos con ejemplo** (D96), nombre de la cuenta bien escrito (D79).
- **Cuenta demo** (solo lectura, datos de ejemplo de otro rubro) para mostrar sin exponer números reales.

**Ola 3 — Pantallas de todos los días**
- Dashboard: perfil incompleto fuera del primer lugar (D31), el hero sin saltos (D72), una cifra una vez (D5, D6, D11), pestañas Hoy · Este mes · 14 días (D48).
- Costos: una herramienta por segmento con su botón (D24), guardar al salir del campo (D56), planilla arriba (D34).
- Ganancia Real: período que se aplica al elegir (D25).
- Día a día, Promociones (D61: una fila por modelo), Mercado (D8), Monotributo (D10), Opiniones (D20).
- Modo privacidad también en los gráficos (D7).

**Ola 4 — Respuesta y confianza**
- Esqueletos con la forma real en vez de «Cargando…» (D87, D71); «actualizado hace X» y «Reintentar» (D74); «Deshacer» en lo reversible (D73).
- Sin conexión (D53), atajos de la app instalada (D54), fundido entre pantallas (D86).

**Ola 5 — Cierre**
- Accesibilidad: encabezados `h2` y foco con teclado (D75, D76); peso de la tipografía (D43).
- Revisión de textos de todas las pantallas (D81, D89), definiciones al tocar (D94).
- **Prueba de 5 segundos con gente real**, arreglo de lo que salga, y recorrido final con la vara de arriba.

## Cómo se trabaja

- Cambios chicos, cada uno con su prueba y **medido en el navegador real** (no a ojo); antes/después en pantalla para lo visible.
- Se sube a `main` todo el tiempo; **vos desplegás una vez por ola** (`python desplegar.py`) y lo mirás en tu celular y tu PC. Lo que no te guste se corrige antes de la ola siguiente.
- Cada ola termina con una nota de qué cambió y qué se ve distinto.

## Lo que queda fuera (a pedido del dueño) y los 3 puentes que NO se pueden saltear

Diferidos: tickets a Mercado Libre, WhatsApp Business, Google Workspace con el mail del dominio. Tres cosas que **tocan la web** y hay que tener resueltas antes de mostrarla públicamente:
1. **`soporte@corelux.app` tiene que existir**: está publicado en las páginas legales. No hace falta Google Workspace: **Cloudflare Email Routing es gratis** y reenvía ese mail a tu Gmail (el dominio ya está en Cloudflare).
2. **Cobro real con Mercado Pago:** probar un cobro chico antes de publicitar (`docs/RUNBOOK.md` §9b-3). Hoy producción corre con credenciales de prueba.
3. **Textos legales al día:** la política de privacidad no menciona el código postal ni las coordenadas de destino que se guardan, y falta el plazo de retención (`docs/PROPUESTA_RETENCION_DATOS_COMPRADORES.md`). Revisión con un abogado antes de publicitar.

Y una más, **antes de publicidad masiva** (no para mostrarla a conocidos): la autorización de Mercado Libre por la cláusula 5.4 (`docs/TICKETS_MERCADO_LIBRE_BORRADOR.md`), porque Mercado Libre puede revocar el acceso a la API de toda la aplicación.

## Lo ya hecho en esta tanda

- **D13:** `--campo-borde` (oscuro `#666673`, 3,2:1 contra las tarjetas; claro `#84849c`, 3,6:1) en todos los input, select y textarea; las tarjetas conservan su borde casi invisible. `tests/test_campos_visibles.py`. Verificado en el navegador en Costos (los 218 campos se distinguen sin cambiar el estilo de la pantalla).
