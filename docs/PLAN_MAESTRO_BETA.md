# Plan maestro para entrar en beta (2026-10-22)

A pedido del dueño: «analizá completamente el programa, código y visual, comparando con programas similares; todo lo que haya que pulir, agregar y quitar; necesitamos entrar en beta lo antes posible». Este documento **junta en un solo lugar** lo que ya estaba pensado (`PLAN_UX_200.md`, `docs/AUDITORIA_DISENO_100.md` = D, `docs/AUDITORIA_TECNICA_100.md` = T, `PLAN_MEJORAS.md` = PM, `PLAN_BETA.md`, `docs/PLAN_PULIDO_WEB.md`, `docs/PLAN_INTELIGENCIA_MERCADO.md`) con lo nuevo de hoy (= **N**), y lo ordena para llegar a una **beta cerrada**. Reemplaza el orden de olas de `docs/PLAN_PULIDO_WEB.md` (ese documento sigue valiendo como detalle de la parte visual).

**Qué se hizo para armarlo (hoy):** recorrido automático de **33 pantallas** con la cuenta real (solo lectura): todas responden 200, **0 pedidos fallidos y 0 textos de error**; capturas en escritorio y celular de las principales; páginas públicas en producción sin sesión; medición del código (114 módulos, 26.139 líneas, 1.790 pruebas en verde); consultas de solo lectura a producción (usuarios, planes, secretos configurados); búsqueda de las herramientas parecidas que usan los vendedores de Mercado Libre en Argentina.

---

## 1. Dónde estamos, en simple

**La base está bien.** Las cuentas de plata cuadran con lo depositado (99,7 %), las pantallas no se rompen, hay 1.790 pruebas, el deploy vuelve solo atrás si falla y las dos máquinas de producción están sanas. Lo que da la sensación de «falta mucho» no es que falten funciones (hay de sobra: 23 pantallas en el menú y 148 rutas), sino tres cosas:
1. **Terminación:** detalles visuales repetidos (letra chica, escalas sueltas, colores sin significado, cifras repetidas). Ver `docs/PLAN_PULIDO_WEB.md`.
2. **Lo que vive alguien nuevo:** todo se probó con una sola persona (vos). Una cuenta nueva, de otro rubro, sin costos cargados, todavía no tiene un camino guiado, y algunas puertas de entrada (Planes, prueba vencida) están armadas para «cobrar», no para «probar».
3. **Demasiada superficie:** hay pantallas que se pisan (Tendencias y Mercado), pantallas huérfanas y funciones a medio camino. Para la beta conviene **menos y mejor**.

**Puntaje por área** (estimación; misma escala que `PLAN_BETA.md` del 2 de octubre):

| Área | 2 oct | Hoy | Para la beta | Para vender |
|---|---|---|---|---|
| Exactitud del cálculo de plata | 85 | 92 | 94 | 97 |
| Experiencia de uso y primeros minutos | 55 | 70 | 85 | 92 |
| Confiabilidad en producción | 45 | 80 | 85 | 95 |
| Que le sirva a otros vendedores | 45 | 70 | 80 | 90 |
| Capacidad para crecer | 45 | 60 | 65 | 85 |
| Listo para cobrar | 25 | 45 | — | 90 |
| Seguridad y privacidad | 75 | 86 | 90 | 95 |

**Qué es «la beta» en este plan:** una **beta cerrada y gratis** con **5 a 10 vendedores invitados** de rubros distintos (no solo indumentaria), durante 2 a 4 semanas, para aprender qué usan, qué no entienden y qué falla. **No** es salir a publicitar ni cobrar.

---

## 2. Comparación con herramientas parecidas

Fuentes: los sitios y artículos de cada herramienta (son comerciales: sirven de referencia, no de prueba). Precios en pesos argentinos por mes, tal como los publican.

| Herramienta | Qué es | Precio publicado | Lo que tienen que nosotros no | Lo que tenemos y ellos no dicen tener |
|---|---|---|---|---|
| **Jaguar Sheet** | Complemento de Google Sheets: ventas (44 columnas), publicaciones, promociones, publicidad; se actualiza cada hora; explorador de categorías, tendencias y **«top 20 más vendidos por categoría»**; tiempo de respuesta a preguntas por franja | $25.000 (1 cuenta) / $51.700 (varias cuentas); 14 días de prueba | Planilla editable propia; **acceso a «más vendidos»** (a nosotros Mercado Libre nos da 403: sugiere acceso de partner) | Pantallas listas sin armar fórmulas; conciliación con lo depositado; Día a día operativo; asistente |
| **SpomBridge** | Gestión multicanal: Mercado Libre + Tiendanube + local, stock único, pedidos de todos los canales, **facturación ARCA automática**, rentabilidad por canal | $49.999 (incluye hasta 3 usuarios); 21 días de prueba sin tarjeta | **Multicanal, facturación ARCA, varios usuarios por cuenta**, multi-depósito | Ganancia real por venta y publicación con cargos reales; Flex por zona; cuotas por publicación |
| **Real Trends** (2014, AR/MX/BR) | Métricas, multicuenta, sincronización de stock y precios, tiendas online, app móvil, **IA y plantillas para preguntas**, mensajes automáticos, publicador masivo, posicionamiento con consejos, competencia | No publicado | **Plantillas de respuestas**, mensajes automáticos, **publicación/edición masiva**, app nativa | Conciliación de la plata; costos reales; Monotributo |
| **Nubimetrics** | Inteligencia de mercado: demanda, competencia, oportunidades | No publicado | Datos de mercado de terceros (ventas, visitas) | Todo lo de «tu negocio» con plata real |
| **UpSeller** (ERP certificado) | Multi-marketplace, rentabilidad por pedido y producto, **plantillas de preguntas (hasta 50)** | No publicado | Multi-marketplace, ERP | Foco y simplicidad para Mercado Libre Argentina |
| **YoFacturo / Tributo Simple / Contabilium** | Facturación ARCA de cada venta de Mercado Libre con CAE | Varía (Tributo Simple, app gratuita para monotributistas) | **Facturación** | — (no competimos: conviene integrarse o enlazarlos) |
| **Mercado Libre (gratis)** | Panel de ventas, Mercado Ads, central de promociones, tendencias, FULL | Gratis | Es la fuente | Cruzar todo en un solo lugar y con la plata real |

**Lo que nos diferencia** (hay que cuidarlo y mostrarlo): (1) la **ganancia neta real conciliada con lo que Mercado Pago depositó** (ninguna dice conciliar contra el depósito); (2) **costos reales por publicación**: envío que paga el vendedor, cuotas cobradas por publicación, cargos mensuales de la factura, Flex por zona; (3) **«Lo que tenés que hacer hoy»** y Día a día; (4) el **asistente** que consulta los datos de la cuenta; (5) lo argentino: Monotributo y condición fiscal. **Precio:** $40.000 está entre Jaguar ($25.000) y Spom ($49.999); el Elite a $99.000 por 2 cuentas queda caro contra los $51.700 multicuenta de Jaguar (se decide antes de cobrar, no para la beta).

**Lo que la competencia ya da por sentado** y a nosotros nos falta: plantillas de respuestas para preguntas (N12), varios usuarios por cuenta (N13), facturación ARCA o un puente a quien factura (N14), edición masiva de precios (UX200#87/#89). Solo el primero conviene para la beta.

Fuentes: [Jaguar Sheet: herramientas para vendedores](https://jaguarsheet.com/es/blog/herramientas-vendedores-mercado-libre), [SpomBridge: gestión multicanal](https://app.spomsolutions.com/soluciones/gestion-multicanal), [Real Trends (StartupBlink)](https://coronavirus.startupblink.com/innovations/buenos-aires+argentina/real-trends), [Real Trends en App Store](https://apps.apple.com/us/app/real-trends/id1164234424), [UpSeller: plantillas de preguntas](https://www.upseller.com/es/doc-article/438), [YoFacturo: facturación para Mercado Libre](https://yo-facturo.com/facturacion-mercado-libre/), [Tributo Simple](https://tributosimple.com/argentina/facturacion/), [base.com: facturas en Mercado Libre y ARCA](https://base.com/es-AR/blog/?p=18427).

---

## 3. Lo nuevo de hoy (N)

| # | Qué pasa (verificado) | Qué hacer | Prioridad |
|---|---|---|---|
| **N1** | **La página pública de Planes muestra la barra interna de la app a quien no inició sesión**: buscador de publicaciones, «Actualizar», campana, modo privacidad, chat y un avatar «M» (capturado en `corelux.app/planes` sin sesión). `planes.html` extiende `base.html` (la carcasa de la app). | Para visitantes sin sesión, Planes con la cabecera y el pie de la landing | **P0** |
| **N2** | **Producción tiene `MP_ACCESS_TOKEN` (credenciales de PRUEBA) → `PAGOS_HABILITADOS` es verdadero:** a los 14 días un vendedor de la beta queda frenado en Planes y solo podría «pagar» en el entorno de pruebas de Mercado Pago. Además Planes y la landing hablan de cobro, no de beta. Hoy hay 1 solo usuario (vos, Elite), así que todavía no afectó a nadie. | Un `MODO_BETA` explícito: sin bloqueo por prueba vencida, Planes y landing dicen «Beta gratuita», y la prueba de cobro del dueño (`MP_PRECIO_DE_PRUEBA`) sigue andando | **P0** |
| **N3** | **«Referidos» aparece en el menú** (se muestra cuando hay pagos habilitados, ver N2) y no tiene premio definido (PM#205). | Sacarlo del menú hasta que haya premio | **P0** |
| **N4** | **Pantalla huérfana:** `/comparador_logistica` («Logística propia vs FULL») se abre por dirección pero no está en el menú; su cálculo ya se usa dentro de Ganancia Real. | Quitar la ruta (o volver a mostrarla dentro de Ganancia Real) | P1 |
| **N5** | **Tendencias muestra apodo, reputación, medalla y ventas históricas de los 5 vendedores con más publicaciones** de una búsqueda: es «información de un usuario específico» (cláusula 5.4.5 de los Términos de la API) y no tenemos la autorización. | Para la beta, mostrar solo el agregado (cuántos vendedores, concentración) sin identificar a nadie; se reabre si Mercado Libre autoriza | **P0** |
| **N6** | **Dos pantallas para lo mismo:** la de Tendencias se titula «Tendencias y Mercado» y existe otra «Mercado». | Una sola «Mercado» (búsquedas en alza + explorar + tu catálogo) y la otra se retira | P1 |
| **N7** | **El botón de Elite en Planes es dorado**; la regla de la casa dice que el dorado nunca es un botón (solo logo, insignias y momentos de ganancia). | Botón violeta como el resto; el dorado queda en la insignia «RECOMENDADO» | P1 (decide el dueño) |
| **N8** | **Cualquiera puede registrarse** con «Probar gratis»: no hay invitación ni lista de espera. Con un pooler de 15 conexiones y soporte de una persona, una beta abierta se puede desbordar. | Beta cerrada: código de invitación o lista de cuentas permitidas; quien no está, deja su mail en una lista de espera | **P0** |
| **N9** | **Para un Responsable Inscripto la ganancia incluye el IVA**: no hay ningún cálculo de IVA (`metricas.py`, `dashboard.py`, `reporte_fiscal.py`); la condición fiscal solo decide si se ve Monotributo. Un RI ve la ganancia inflada por el IVA neto (PM#229). | **P0:** un aviso claro cuando la cuenta declaró RI. **P1:** la ganancia neta de IVA (débito − crédito de los cargos de Mercado Libre) con su prueba | **P0** / P1 |
| **N10** | «Sincronizando: solo tarda unos minutos» aunque la primera importación trae **365 días de órdenes**: en una cuenta grande puede tardar mucho más (sin medir en real). | Mostrar el avance real («1.240 ventas importadas de ~3.000») y una estimación; medirlo con una cuenta grande | P1 |
| **N11** | El Dashboard dispara **14 pedidos** al cargar (T34); localmente 8 tardan más de 2,5 s (el ticker 4,2 s). En Fly es mucho menos, pero son 14 conexiones del pooler por visita. | Un pedido para las tarjetas de arriba; el ticker cada 5 min (T33) | P1 |
| **N12** | **Plantillas de respuestas** en Preguntas: Real Trends y UpSeller las tienen; es tarea diaria. Hoy hay sugerencia con IA y responder desde CoreLux. | Respuestas guardadas con variables y contador de 350 caracteres (UX200#51) | P1 |
| **N13** | **Varios usuarios por cuenta** (un empleado que despacha): Spom incluye 3. | Invitar a alguien con permisos de solo Día a día | P2 |
| **N14** | **Facturación ARCA:** la ofrecen Spom y apps especializadas. | No construirla: enlazar o integrar con quien ya factura | P3 |
| **N15** | **Precio frente a la competencia** (ver sección 2). | Revisar Base y Elite antes de cobrar | P2 (dueño) |
| **N16** | Jaguar Sheet ofrece «top 20 más vendidos por categoría» (el `/highlights` que a nosotros nos da 403 con el permiso activo). | Va en el ticket a Mercado Libre (`docs/TICKETS_MERCADO_LIBRE_BORRADOR.md`) | P2 (dueño) |
| **N17** | Avisos al celular **gratis** con notificaciones de la app instalada (web push) para venta, pregunta o reclamo: cubren parte de lo que se esperaba de WhatsApp sin pagar nada. Necesitan el «service worker» (D53). | Hacerlo después de la beta si las personas lo piden | P2 |
| **N18** | **0 comentarios recibidos** en la bandeja de «Enviar un comentario». Sin un canal visible, la beta no va a devolver nada. | «¿Te sirvió?» por pantalla (UX200#177) y un recordatorio de beta con el botón de comentario | P1 |
| **N19** | Términos y Privacidad tienen su propia paleta (D47) y la política no menciona **código postal ni coordenadas** del destino, ni plazos de conservación, ni el país del proveedor de IA. | Texto actualizado para la beta (con abogado antes de cobrar) y el mismo estilo que la landing | **P0** (texto) |
| **N20** | La landing invita a «Probar 14 días gratis» y Planes a «Suscribirme»: en una beta gratis el mensaje correcto es «Sumate a la beta». | Va con N2 | **P0** |
| **N21** | No hay ayuda dentro de la app (preguntas frecuentes, qué es cada término). | Una página de ayuda corta y las definiciones al tocar (D94) | P1 |
| **N22** | No hay **cuenta demo**: para mostrar CoreLux hoy hay que mostrar tus números. | Una cuenta de solo lectura con datos de ejemplo de otro rubro | P1 |
| **N23** | Sin forma de avisar a los beta testers de un problema o una novedad. | Un aviso en la app («Novedades», UX200#175) | P2 |
| **N24** | La capacidad con N cuentas no está medida en Fly (`PLAN_BETA.md` D quedó pendiente): 15 conexiones para todo el proyecto. | `python medir_sync.py` en Fly y calcular cuántas cuentas aguanta antes de invitar | P1 |
| **N25** | Nunca se probó **restaurar** un respaldo (T46); el respaldo semanal depende de la PC del dueño. | Ensayo de restauración y respaldo automático | P1 |

**Descartado al verificar (no está en la lista):** (1) «las ventas viejas de una cuenta nueva quedan sin costos reales hasta que se completan de a 40»: falso, la primera importación trae el envío y el pago de cada orden en paralelo (`ventas_sync.py`, páginas de órdenes); los «completar de a 40» son solo para filas viejas sin dato. (2) Un espacio en blanco arriba del Dashboard en celular: era la animación de entrada detenida porque la pestaña de prueba estaba en segundo plano (el navegador no anima pestañas ocultas). (3) «No hay Sentry»: producción ya tiene `SENTRY_DSN` cargado.

---

## 4. Lo que conviene QUITAR, ocultar o fusionar para la beta

Menos pantallas, mejor terminadas. Nada se borra de la base; solo se saca de la vista o se junta.

| Qué | Por qué | Cómo |
|---|---|---|
| **Referidos** (N3) | Sin premio, en el menú | Ocultar hasta definir el premio |
| **«Logística propia vs FULL»** (N4) | Huérfana; su cálculo ya está en Ganancia Real | Quitar la ruta |
| **Tendencias + Mercado** (N6) | Dos pantallas para lo mismo, y una identifica vendedores (N5) | Una sola «Mercado» |
| **Monotributo + Reporte fiscal** (D68) | Son lo mismo para quien los usa: impuestos | Una pestaña «Impuestos» con las dos partes |
| **Ventas fuera de MeLi** como pestaña (D68) | Es una acción, no una pantalla | Botón «Cargar venta fuera de MeLi» en Ganancia Real |
| **Botón dorado de Elite** (N7) | Rompe la regla de color | Violeta |
| **«Actualizar» violeta en las 25 pantallas** (D32) | Compite con el botón principal | Ícono con «actualizado hace X» |
| **Calidad + Embudo + Opiniones** (UX200#95, PM#224) | Tres pantallas para «cómo está mi publicación» | Después de la beta: una tabla de salud por publicación (ahora no: es grande) |
| **Monitor en vivo** | Muy completo, pero se pisa con el Dashboard | Dejarlo; decidir con los datos de uso de la beta |

---

## 5. Backlog completo, por área y prioridad

**Prioridades:** **P0** antes de invitar a nadie · **P1** durante las primeras semanas de beta · **P2** antes de cobrar o publicitar · **P3** más adelante o ideas. Entre paréntesis, el origen (D/T/UX200/PM/N). Todo lo que no figura acá sigue en su documento de origen.

### A. Puerta de entrada y beta (lo que vive alguien nuevo)
- **P0** Modo beta gratis sin bloqueo a los 14 días, y textos de beta en landing y Planes (N2, N20).
- **P0** Planes pública con cabecera de landing para visitantes (N1).
- **P0** Beta cerrada: invitación o lista permitida + lista de espera (N8).
- **P0** `soporte@corelux.app` funcionando (Cloudflare Email Routing, gratis) y visible en la app.
- **P0** Términos y Privacidad actualizados para la beta (N19, retención de datos de compradores).
- **P1** Primer ingreso guiado que termine en la primera tarea real: cargar el costo del modelo más vendido (UX200#171/#172).
- **P1** Pantallas vacías con ejemplo para cuentas nuevas (D96, UX200#149/#178) y cuenta demo (N22).
- **P1** Avance real de la primera sincronización (N10).
- **P1** Ayuda corta y definiciones al tocar (N21, D94); «¿Te sirvió?» y recordatorio de comentarios (N18, UX200#177).
- **P2** Landing: imagen para compartir 1200×630 y título (D80, D85), celular (D52, D55), calculadora pública (UX200#185), testimonios de la beta (UX200#187), preguntas frecuentes sobre seguridad (UX200#188).
- **P2** Planes: tabla comparativa (D82), días de prueba visibles (D83), cancelar con claridad (UX200#181).

### B. Sistema visual (prolijidad) — detalle en `docs/PLAN_PULIDO_WEB.md`
- ✅ Campos visibles (D13, hecho hoy).
- **P0** Letra mínima de 12 px y escala de 6 tamaños (D12, D22), contrastes que quedan (D14, D16, D17, D18, D20), color de las tarjetas solo con estado (D30), «Actualizar» discreto (D32), tarjetas huérfanas (D29).
- **P1** Escalas de z-index, sombras y radios; una sola etiqueta (D37, D38, D42); botón de Elite violeta (N7); páginas de error y legales con el estilo de la app (D47, N19).
- **P2** Sacar los 934 estilos escritos a mano de las plantillas (D39, UX200#120) y unificar los dos sistemas de CSS (PM#234); página `/ui` de componentes (D99).

### C. Pantallas núcleo (las que se usan todos los días)
- **Dashboard — P1:** perfil incompleto fuera del primer lugar (D31), una cifra una sola vez (D5, D6, D11), el hero sin saltos (D72), un pedido en vez de 14 (N11, T34), pestañas Hoy · Este mes · 14 días en celular (D48).
- **Día a día — P1:** plantillas de respuesta (N12), segundo título más chico (D26), ícono correcto en «pendientes» (D27), foto del paquete en celular (D28), «Cargá lo que te cobra tu logística» una sola vez (D35); P2: posponer un pendiente (UX200#52), agrupar paquetes por tipo y corte (UX200#50).
- **Costos — P1:** una herramienta por segmento con su botón (D24), guardar al salir del campo (D56), planilla arriba (D34), ayuda plegada (D33).
- **Ganancia Real — P1:** período que se aplica al elegir (D25); aviso de IVA para RI (N9, P0) y ganancia neta de IVA (N9, P1).
- **Stock — P2:** fecha estimada de quiebre (UX200#58), capital a costo (UX200#59), resumen antes de escribir en Mercado Libre (UX200#61).
- **Precios — P1:** el costo de la VARIANTE también en Precios, Promociones, Stock y el margen del Dashboard (T13); P2: aplicar el recomendado en lote con vista previa (UX200#87).
- **Promociones — P1:** una fila por modelo (D61); P2: margen con el descuento (UX200#100).
- **Mercado — P1:** fusión con Tendencias (N6), sin vendedores identificados (N5, P0), «sin publicación tuya» una sola vez (D8).
- **Publicidad, Opiniones, Monotributo, Calidad, Embudo — P1:** los puntos D10, D20, UX200#101 y D6.
- **Modo privacidad — P1:** también en los gráficos (D7).

### D. Funciones para pulir (las que ya existen)
- **P1** Plantillas de respuestas (N12); IVA para RI (N9); costo por variante en todas las pantallas (T13).
- **P1** «Deshacer» en lo reversible: borrar un gasto, marcar un paquete, ocultar una pregunta (D73, T93).
- **P1** «Actualizado hace X» y «Reintentar» en lo que viene de Mercado Libre (D74, UX200#152).
- **P2** Asistente: botón «esto estuvo mal» (T98); costo de fabricación con fecha de vigencia (PM#202); exportar a Excel con un solo formato (T95).

### E. Funciones para agregar (con criterio: solo si la beta lo pide)
- **P2** Notificaciones al celular gratis con la app instalada (N17) — requiere el service worker (D53).
- **P2** Varios usuarios por cuenta (N13).
- **P2** Edición masiva de precios con vista previa (UX200#87/#89).
- **P3** Facturación ARCA por medio de un tercero (N14); ficha única de publicación (UX200#92, PM#219); pantalla Posventa (PM#220); multicanal (Tiendanube); inteligencia de mercado según `docs/PLAN_INTELIGENCIA_MERCADO.md` (espera la autorización de la cláusula 5.4).

### F. Código y confiabilidad
- **P1 (chicos, de mucho efecto):** `statement_timeout` en los pedidos web (T36), comprobar la conexión antes de usarla (T37), el refresco del token sin retener la conexión de administración (T26), `Cache-Control: no-store` en las pantallas con plata (T52), contenedor sin root (T50), un solo formato de error JSON y mensajes correctos ante 429/500 (T79, T80), tabla explícita de temas de webhook (T31), medir capacidad con N cuentas (N24), ensayo de restauración (N25).
- **P2:** cancelar la suscripción mantiene el acceso hasta el fin del período (T17) y crear la nueva antes de cancelar la vieja (T18); un solo origen para precios y días de prueba (T19, T22); `firma_valida` cerrada sin secreto (T20); política de scripts estricta (T48, del dueño); base de pruebas separada de producción (T74) y CI con base (T75); entorno de ensayo (T66); registro con niveles en vez de 435 `print` (T72).
- **P3:** dividir `app.py` (4.330 líneas, 148 rutas) en módulos (T77); partir las 8 funciones de más de 120 líneas (T76, empezando por `calcular_ganancia_real`, 268); separar `global.js` (95 KB) por pantalla (PM#242); `ruff` con más reglas (T78).

### G. Operación de la beta
- **P0** Monitor externo gratis de `/healthz/db` con aviso por mail (UptimeRobot o Better Stack) — del dueño.
- **P0** Confirmar que Sentry recibe los errores (el `SENTRY_DSN` ya está cargado) — del dueño, mirar el panel una vez.
- **P1** Medir el uso: qué pantallas se abren y dónde se abandona, sin datos personales (UX200#197); prueba de 5 segundos con 5 personas (UX200#198).
- **P1** Un canal de soporte y un horario dicho a los testers (mail de soporte; WhatsApp después).
- **P2** Avisos dentro de la app para novedades e incidentes (N23).

### H. Legal y datos
- **P0** Texto de Términos y Privacidad para la beta (N19).
- **P1** Plazo de conservación de los datos de compradores (`docs/PROPUESTA_RETENCION_DATOS_COMPRADORES.md`, T39, T40).
- **P2** Revisión con abogado; autorización de Mercado Libre por la cláusula 5.4 (`docs/TICKETS_MERCADO_LIBRE_BORRADOR.md`).

---

## 6. Plan por olas hasta la beta

| Ola | Qué | Tamaño aproximado | Lo despliega el dueño |
|---|---|---|---|
| **0 · Bloqueantes** | N1, N2/N20, N3, N5, N8, aviso de IVA (N9), textos legales (N19). **Del dueño, en paralelo:** `soporte@` con Cloudflare, monitor de caída, mirar Sentry | 1 a 2 sesiones | Sí, al terminar |
| **1 · Sistema visual** | B-P0 (letra, contrastes, color con significado, «Actualizar», tarjetas huérfanas) | 2 sesiones | Sí |
| **2 · Primera impresión** | Primer ingreso guiado, vacíos con ejemplo, avance de la sincronización, ayuda y «¿te sirvió?», cuenta demo | 2 a 3 sesiones | Sí |
| **3 · Pantallas núcleo** | Dashboard, Día a día (plantillas), Costos, Ganancia Real, Precios (costo por variante), Promociones, Mercado (fusión) | 3 a 4 sesiones | Sí |
| **4 · Confianza** | F-P1 (timeouts, conexiones, caché de seguridad, root, errores), «Deshacer», «actualizado hace X», medición de capacidad y restauración | 2 sesiones | Sí |
| **→ Beta cerrada** | Invitar a 5–10 vendedores de rubros distintos; seguimiento semanal de uso y comentarios | 2 a 4 semanas | — |
| **5 · Lo que diga la beta** | Arreglar lo que salga; después, P2 rumbo a cobrar (Mercado Pago real, mails, abogado, precio, autorización 5.4) | — | Sí |

Las olas 1 a 4 pueden empezar a invitar a los primeros 2 o 3 vendedores conocidos apenas termine la Ola 0 y la 1, para aprender antes.

## 7. Decisiones del dueño (cortas)

1. **Beta gratis** con el bloqueo de prueba apagado (N2). Recomendado: sí.
2. **Beta cerrada** con invitación y lista de espera (N8). Recomendado: sí.
3. **Tendencias sin vendedores identificados** hasta tener la autorización (N5). Recomendado: sí.
4. **Botón de Elite violeta** en vez de dorado (N7). Recomendado: sí (es la regla de color de la casa).
5. **Quitar Referidos y la pantalla huérfana** (N3, N4). Recomendado: sí.
6. Lo de siempre que es tuyo: `soporte@`, monitor de caída, mirar Sentry, abogado y precio antes de cobrar.
