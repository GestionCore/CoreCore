# Borrador de tickets para el soporte de desarrolladores de Mercado Libre — NO ENVIADOS

Preparado el 2026-10-21 y **ajustado el 2026-10-22 con las respuestas de la IA de Mercado Libre** (la IA confirmó que la autorización de la 5.4 se pide por el portal de soporte y que, leída al pie de la letra, casi todo uso de estadísticas de mercado la necesita; no puede concederla). **Nada de esto se envió.** Son tres tickets porque el formulario de Mercado Libre admite hasta **5.000 caracteres** por descripción (los de abajo tienen entre 1.100 y 2.800). Dónde se crean: `developers.mercadolibre.com.ar` → «Soporte para integradores» → **Crear un ticket** (categoría *Productos*; tipo *Consulta* para el 1 y el 3, tipo *Problema* para el 2). Si el formulario no deja entrar por no ser Partner, usar el bot de soporte (atiende 24 h) y pedir que escale el caso a una persona.

**Antes de enviar, completá o verificá** (todo lo que está entre corchetes):
- `[ID de la aplicación]`: el que figura en el DevCenter (el ID de la aplicación se puede compartir; **nunca** el secreto ni tokens).
- `[N]`: cuántos vendedores usan hoy la app (cuentas de Mercado Libre conectadas y activas; el número real, no uno redondeado hacia arriba).
- `[nombre y email de contacto]`.
- Lo que dice cada ticket sobre cómo funciona CoreLux está verificado contra el código al 2026-10-21; si cambia algo antes de enviar, corregirlo.

Después de enviar, guardar el número de caso y pegarlo en `PENDIENTES.md` (sección 0g). Las respuestas se anotan en `docs/PLAN_INTELIGENCIA_MERCADO.md` §3.5.

---

## Ticket 1 — Consulta: autorización de la cláusula 5.4

**Asunto:** Solicitud de autorización de la cláusula 5.4 (información derivada) — aplicación CoreLux [ID de la aplicación]

**Descripción:**

Hola. Somos CoreLux ([ID de la aplicación]), una aplicación web de gestión para vendedores de Mercado Libre Argentina. A cada vendedor le mostramos su ganancia real, costos, stock, reputación, publicidad y reclamos, con los datos de su propia cuenta conectada por OAuth. Hoy la usan [N] vendedores. Enviamos el access token siempre por header, no hacemos scraping y cada vendedor ve solo sus propios datos (aislamiento por cuenta).

Leímos los Términos del Programa (cláusula 5.4, información derivada) y preferimos pedir la autorización expresa antes de seguir ampliando la aplicación. La pedimos para tres usos, todos dentro de la aplicación y solo para vendedores usuarios de Mercado Libre:

a) Métricas PROPIAS de cada vendedor (ventas, conversión, publicidad, reputación), calculadas con su token (5.4.1, 5.4.3 y 5.4.6).
b) Estadísticas públicas de mercado por categoría: cantidad de publicaciones (total_items_in_this_category), búsquedas en alza (/trends) y precios de las ofertas de productos de catálogo (/products/{id}/items), con la fecha y la frecuencia de actualización visibles en pantalla (5.4.1 y 5.4.4). También el cruce de esas búsquedas en alza con los títulos de las propias publicaciones del vendedor y una serie diaria de esos números para mostrar si suben o bajan (5.4.1). Hoy: cantidad de publicaciones y búsquedas 1 vez por día; muestra de precios 1 vez por semana.
c) Seguimiento, a pedido del vendedor, de productos de catálogo: cantidad de ofertas y de vendedores y precio mínimo, mediano y máximo, sin identificar a los vendedores.
d) Una situación que existió y queremos transparentar: la pantalla «Tendencias» mostraba, para una búsqueda, los 5 vendedores con más publicaciones en la muestra de catálogo: apodo, nivel de reputación, medalla y total histórico de ventas (de /users/{id}). Es información de un usuario específico (5.4.5): **ya lo retiramos de la versión que usan los vendedores** y solo lo reactivaríamos con autorización expresa.

Consultas:
1. ¿Esta solicitud alcanza o necesitan más información (descripción del producto, capturas, política de privacidad)? ¿Cuál es el alcance de la autorización (por uso, por categoría) y su plazo?
2. ¿Podemos empezar solo con el uso (a) mientras se evalúan el (b) y el (c)?
3. Las cláusulas 5.2 y 2.2.1.3 piden eliminar el contenido que deja de estar público. Queremos conservar solo NÚMEROS AGREGADOS diarios (cantidad de publicaciones por categoría, posición de una búsqueda en alza), no contenido de publicaciones, para mostrar su evolución. ¿Está permitido y con qué plazo máximo de conservación?
4. La cláusula 5.3 pide actualizar cada 24 horas (6 horas para listados). ¿Aplica a datos agregados, como la mediana de precios de una muestra de catálogo, o a /trends, que se actualiza una vez por semana? ¿Cómo debemos explicitar la frecuencia?

Por ahora no pedimos estimaciones de ventas de terceros ni datos de vendedores específicos. Gracias. Contacto: [nombre y email de contacto].

---

## Ticket 2 — Problema: 403 en /highlights con el permiso «Métricas del negocio» activo

**Asunto:** 403 PA_UNAUTHORIZED_RESULT_FROM_POLICIES en GET /highlights con el permiso «Métricas del negocio» activo — aplicación [ID de la aplicación]

**Vendedores o usuarios afectados:** probado con una cuenta de vendedor conectada ([ID de usuario]) y con token de aplicación: ambos reciben el mismo 403.
**Método:** GET
**Recurso:** /highlights/MLA/category/{category_id} y /highlights/MLA/item/{item_id}

**Request:**
- GET https://api.mercadolibre.com/highlights/MLA/category/MLA47769 (categoría hoja, sin subcategorías), header Authorization: Bearer <token de usuario de un vendedor conectado>
- La misma llamada con token de aplicación (client_credentials)
- GET https://api.mercadolibre.com/highlights/MLA/item/MLA1516094749 (publicación propia), con cada uno de los dos tokens
- Control: GET https://api.mercadolibre.com/trends/MLA con cada uno de los dos tokens

**Respuesta:** las cuatro llamadas a /highlights devuelven HTTP 403 con el cuerpo `{"blocked_by":"PolicyAgent","message":"At least one policy returned UNAUTHORIZED.","code":"PA_UNAUTHORIZED_RESULT_FROM_POLICIES","status":403}`. La de control, /trends/MLA, devuelve HTTP 200 con los dos tokens.

**Descripción:**

Según la documentación «Más vendidos en Mercado Libre» (actualizada el 22/06/2026), /highlights pertenece al permiso funcional «Métricas del negocio». Nuestra aplicación [ID de la aplicación] tiene ese permiso activo en «Lectura» (DevCenter → Permisos). Con ese mismo permiso, /trends funciona (200), pero /highlights da 403 siempre: con token de usuario, con token de aplicación, con una categoría hoja y con una publicación propia. La primera vez que lo probamos fue el 13/10/2026 y se repitió el 21/10/2026 con el mismo resultado. El 22/10/2026 quitamos el acceso de la aplicación desde la cuenta del vendedor y la volvimos a autorizar: la pantalla de permisos de Mercado Libre listó los siete permisos, incluido «Métricas del negocio», y el 403 persistió con el token nuevo.

Revisamos las causas que lista la página «Error 403»: con los mismos tokens funcionan otros recursos de lectura y de escritura, así que la aplicación no está bloqueada y los tokens son válidos; no configuramos restricción de IP.

Consultas:
1. ¿Qué condición falta para acceder a /highlights: un programa (por ejemplo, el Developer Partner Program), una aprobación, otro permiso funcional? ¿Cómo se solicita?
2. Si el acceso depende de ser Partner, ¿hay un camino para aplicaciones que todavía no cumplen el GMV mínimo?
3. ¿La documentación de /highlights debería aclarar esa condición?

Gracias. Contacto: [nombre y email de contacto].

---

## Ticket 3 — Consulta: datos de compradores, proveedores y marca

**Asunto:** Consultas sobre retención de datos, proveedores externos y uso de la marca — aplicación CoreLux [ID de la aplicación]

**Descripción:**

Hola. Somos CoreLux ([ID de la aplicación]), aplicación de gestión para vendedores de Mercado Libre Argentina. Queremos cumplir bien los Términos y la guía de Seguridad de aplicaciones, y necesitamos su criterio en estos puntos:

1. Datos cuando un vendedor deja de usar la aplicación (cláusulas 2.2.4 y 14): ¿qué datos debemos eliminar y en qué plazo? ¿Podemos conservar su historial de ventas e importes si él lo pide o por obligación fiscal? ¿Incluye las copias de seguridad?
2. De cada venta guardamos nombre y apodo del comprador, localidad, código postal y coordenadas del destino (para el despacho y los envíos Flex). La guía de Seguridad de aplicaciones trata la dirección de envío como dato personal y pide retención limitada: ¿recomiendan un plazo o anonimizar pasado cierto tiempo desde la entrega?
3. Usamos un proveedor externo de inteligencia artificial al que enviamos cifras agregadas de la cuenta del vendedor (ventas, ganancia, nombres de productos, stock) para responder sus preguntas. Alojamos los datos en São Paulo (hosting y base de datos) y usamos monitoreo de errores en EE. UU. ¿Qué condiciones aplican (cláusulas 2.1.f, 6 y 10)? ¿Hay que informarles la lista de proveedores?
4. La Evaluación de Seguridad del Programa de Partners (65 %): ¿se puede completar antes de postularse? ¿Dónde se pide?
5. Marca (cláusula 2.2.4): una sección del menú se llama «Mercado» y los textos usan «Mercado Libre», «envíos» y «pagos» de forma descriptiva. ¿Alcanza con que el nombre y el logo de la aplicación no las incluyan o hay que cambiar esos textos? ¿Podemos escribir «conectá tu cuenta de Mercado Libre»?
6. ¿Cobrar una suscripción mensual por una aplicación construida sobre la API tiene alguna restricción (cláusula 7.1)? ¿Hay tope de cuentas por aplicación o costo por volumen de llamadas?

Gracias. Contacto: [nombre y email de contacto].
