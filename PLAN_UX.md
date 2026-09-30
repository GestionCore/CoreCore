# Plan de rediseño de experiencia — todas las pantallas de CoreLux

Objetivo: que cada pantalla se entienda **en 5 segundos** — cómo voy, qué tengo que hacer ahora, y dónde toco para hacerlo — con color que guíe la atención y textos cortos en **negrita** donde importa.

## 1. Diagnóstico (lo que se ve hoy, medido en la app real)

| Hallazgo | Dónde | Por qué molesta |
|---|---|---|
| **El número que importa está enterrado** | Ganancia Real: la "Ganancia neta real" aparece a ~1.200 px de scroll, detrás de la sección de reclamos; la página mide 6.670 px y tiene 13 paneles | El usuario busca "¿cuánto gané?" y tiene que cazarlo |
| **Sin acción principal** | Dashboard, Despacho, Preguntas, Ganancia Real, Embudo, Reputación, Publicidad, Logros y Monotributo no tienen ningún botón primario | La pantalla informa pero no dice qué hacer |
| **Mucho gris y violeta, poca señal** | Casi todo usa el mismo tratamiento (tarjeta oscura + etiqueta gris) | Lo urgente y lo irrelevante pesan igual |
| **Paneles vacíos o cortados** | Stock: "Resumen de hoy" es una caja vacía; el capital en stock ($5.536.103,75) se corta | Parece roto |
| **Números sin formato** | Ganancia Real: "Gasto total en Ads $1277905,96" | Se lee mal y desentona con el resto |
| **Acciones duplicadas** | Stock: "Sincronizar Todo" arriba y "Sincronizar ahora" abajo | Dos botones, mismo trabajo |
| **Texto explicativo en vez de guía** | Subtítulos largos bajo cada título | Se lee, no se actúa |
| **Páginas pesadas** | `/metricas` ~258 KB y 4,5 s en local; `/logros` ~9 s (coach de IA en cada carga) | La velocidad también es UX |

## 2. Reglas de UX (se aplican a TODAS las pantallas)

1. **Regla de los 5 segundos.** Arriba de todo, sin scroll: (a) **cómo estoy** (un número héroe con estado), (b) **qué hago ahora** (una sola acción principal). Todo lo demás es detalle.
2. **Orden por importancia.** Estado → acción → detalle → historial. El historial y las tablas largas van al final y plegados ("Ver detalle").
3. **Un botón primario por pantalla**, grande, con **verbo + objeto**: "**Reponer 12 unidades**", no "Enviar". Secundarios discretos; destructivos en rojo con confirmación.
4. **Frases de estado en negrita y con el dato adentro**: "Vendés **58,7% menos** que tu promedio", no "Rendimiento inferior".
5. **El color significa algo** (ver §3) y se usa para *llamar la atención*: lo urgente se ve antes de leerlo.
6. **Toda acción tiene respuesta visible**: "Guardando…", "✓ Guardado", errores con qué hacer después. Nunca una pantalla muda.
7. **Textos de una línea.** Si necesita un párrafo, va en un "?" o en un panel plegado.
8. **Vacío con salida**: un estado vacío siempre trae un botón ("Todavía no cargaste costos → **Cargar mi primer costo**").
9. **Celular primero**: se revisa cada pantalla a 375 px; los botones primarios se alcanzan con el pulgar.
10. **Sin cambios de identidad a escondidas**: violeta sigue siendo identidad y acción; el color nuevo entra como *estado* (§3). Antes de extenderlo a todo, se aprueba en el piloto (Fase 1).

## 3. Sistema de color con significado (propuesta)

| Color | Uso | Ejemplo |
|---|---|---|
| **Verde** `#22c55e` | Plata que entra, ganancia, "todo bien" | Ganancia neta positiva, stock sano |
| **Rojo** `#f43f5e` | Pierde plata, urgente, quiebre, reclamo | Sin stock, margen negativo |
| **Naranja** `#f0a13b` | Atención: hay que actuar pronto | Stock bajo, reputación en riesgo |
| **Violeta** `#8b5cf6` | Acción y navegación (botones, tabs, selección) | Botón primario |
| **Celeste** `#38bdf8` | Información y ayuda | Tips, explicaciones |
| **Dorado** `#f2c94c` | Logros, premium, hitos | Racha, misión cumplida |

Piezas nuevas (se construyen una vez y se usan en todas las pantallas):

- **Banner de estado**: franja con fondo tintado, borde grueso a la izquierda, ícono en círculo sólido, frase en **negrita** y botón de acción a la derecha. Variantes verde / naranja / rojo / celeste.
- **Barra "Lo que tenés que hacer hoy"**: las 1–3 acciones más valiosas de esa pantalla, cada una con botón.
- **KPI con delta**: número grande coloreado por estado + ▲▼ contra el período anterior.
- **Badges sólidos** (no solo contorno) para estados; **filas de tabla resaltadas** por estado (ej. fila roja = sin stock).
- **Secciones plegables** ("Ver detalle") para bajar la densidad sin perder información.
- **Botón primario grande con ícono**, secundario *ghost*, destructivo rojo.
- **Barra de acción fija** en pantallas de edición (Stock masivo, Costos): "3 cambios sin guardar → **Guardar**".
- **Estados vacíos y de carga** consistentes (skeleton + mensaje de qué está pasando).

## 4. Método por pantalla (el mismo ciclo que se usó en Tendencias)

1. **Probar de verdad** con datos reales, en escritorio y celular. Anotar hallazgos por impacto.
2. **Rediseñar** con las reglas y piezas de arriba (se reescribe la plantilla; se toca el backend si hace falta un dato o la pantalla es lenta).
3. **Verificar** en el navegador: errores de consola, red, 375/768/escritorio, contraste.
4. **Un commit por pantalla**, con antes/después.

Criterios de aceptación ("pasa el test de 5 segundos"): el estado y la acción principal se ven sin scroll · un solo botón primario · máximo 3 colores de atención a la vez · ninguna frase de más de una línea en el bloque superior · ningún panel vacío sin explicación · se usa bien a 375 px.

## 5. Orden de trabajo

### Fase 0 — Cimientos (una vez)
- Terminar y verificar lo pendiente de Logros (coach de IA asíncrono y cacheado: hoy frena Logros y el Dashboard).
- Construir las piezas de §3 en `style.css` + macros Jinja reutilizables (`banner_estado`, `kpi`, `barra_accion`, `seccion_plegable`, `estado_vacio`).
- Formateadores únicos de plata y porcentajes (fin de "$1277905,96").

### Fase 1 — Piloto: las dos pantallas que más se miran
- **Dashboard**: hero de ganancia con estado por color, franja "**Lo que tenés que hacer hoy**" (reclamos activos, stock por agotarse, pregunta sin responder), accesos directos.
- **Ganancia Real**: la ganancia neta del período **arriba de todo**, con la cascada (facturado → comisiones → envíos → publicidad → costo → **ganancia**) y delta contra el período anterior; reclamos pasan a banner; el resto en secciones plegables y carga diferida (baja el peso de la página).
- 👉 **Acá se aprueba el look.** Si no te convence, se ajusta antes de tocar las otras 20.

### Fase 2 — Operación diaria
**Stock** (arreglar "Resumen de hoy", KPIs que no se cortan, filas por estado, un solo botón de sincronizar) · **Despacho** (modo de trabajo: lista grande, un toque por pedido) · **Preguntas** (cola con la más vieja primero y responder en línea) · **Stock masivo** (barra de cambios sin guardar).

### Fase 3 — Plata y números
**Facturación** · **Costos** (+ costos por chat) · **Monotributo** (estado claro y sugerencia de confirmar con contador) · **Reporte fiscal** · **Calculadora** (resultado enorme y legible) · **Ventas fuera de MeLi** · **Historial de precios**.

### Fase 4 — Crecimiento
**Promociones** · **Publicidad** (qué campaña apagar/subir, en rojo/verde) · **Reputación** (semáforo) · **Embudo** · **Logros** (misiones como tarjetas con botón) · **Tendencias** (segunda pasada) · **Competencia**.

### Fase 5 — Puertas de entrada y cuenta
**Landing** · **Onboarding** · **Planes / Suscripción / Referidos** · **Conectar / Reconectar** · **Sincronizando** · pantallas de error.

### Fase 6 — Transversal
Navegación y buscador (Ctrl K), tour guiado, atajos, accesibilidad de contraste, rendimiento de las páginas más pesadas, revisión final en celular de todo.

## 6. Pendientes técnicos que se resuelven en el camino
- Stock: números de "Resumen de hoy" (cosas.txt).
- Flex: campo para cargar costo de entrega por zona (feature nuevo).
- Reclamos: mapeo real del motivo (falta ver logs de una sincronización real).
- `/metricas` y `/logros`: tiempos de carga.
- Despliegue a Fly.io de todo lo ya subido (calculadora, header móvil, Competencia).
