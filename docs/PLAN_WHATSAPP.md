# CoreLux por WhatsApp — plan (extra del plan Elite)

Escrito el 2026-10-19. Es una propuesta para decidir, no algo construido. Las cifras de Meta están marcadas con su fuente y con lo que **no pude confirmar**.

## 1. La idea en una frase

Que el vendedor **reciba por WhatsApp lo que no puede esperar** (un reclamo, un paquete por despachar, una campaña sin presupuesto, un producto que se queda sin stock) y que pueda **preguntarle a la misma IA de CoreLux** —la de las 29 herramientas, con el mismo límite de temas— sin abrir la página.

Por qué tiene sentido: el vendedor de Mercado Libre vive en el celular y en WhatsApp. Hoy CoreLux tiene la campana y los mails (que están apagados), pero ninguno le llega a la persona mientras está atendiendo el local o en la calle.

## 2. Qué ve y qué puede hacer la persona

### Activarlo (2 minutos)
Mi cuenta → **WhatsApp**: pone su número, le llega un código al WhatsApp, lo escribe y queda vinculado. Elige qué avisos quiere, en qué horario no molestar y a qué hora quiere el resumen del día. Se desvincula con un toque o escribiendo **BAJA**.

### Avisos (lo que CoreLux le manda)
| Aviso | Por qué vale | Por defecto |
|---|---|---|
| **Reclamo que afecta tu reputación** | Hay un plazo para responder | Sí |
| **Paquetes por despachar hoy** y el horario límite | Es lo que más reputación cuida | Sí (a la mañana) |
| **Cuenta de Mercado Libre desconectada** | Si se desconecta, deja de sincronizar | Sí |
| **Se agotó una variante clave** (la que aporta > 30 % de las ventas de su modelo) | Plata que se pierde cada hora | Sí |
| **Pregunta sin responder más de 1 hora** | Responder rápido vende | Sí |
| **Campaña de publicidad** sin presupuesto o con retorno bajo el equilibrio | Se gasta plata sin ganar | Sí |
| **Acreditación de plata** («mañana te llegan $X») | Ordena la caja | No |
| **Resumen del día** (21:00): ventas, ganancia neta real, margen, lo que hay que mirar mañana | Cierra la jornada | Sí |
| **Resumen de la semana** (lunes) | Lo mismo, en grande | No |
| **Ventas nuevas**, agrupadas cada 15 min (no una por una) | Para quien le gusta ver la caja sonar | No |
| **Publicación que empezó a perder plata** (precio bajo el mínimo) | Evita vender a pérdida | No |
| **Monotributo cerca del tope** | Aviso temprano, siempre «confirmalo con tu contador» | No |

Reglas para que no sea molesto: horario de silencio, agrupar avisos parecidos, un tope diario por persona y **cada aviso se reserva antes de mandarse** (el mismo hecho nunca sale dos veces; es lo que ya hace `correos.py`).

### Preguntarle a la IA (lo que la persona le manda)
Lo mismo que el chat de la página, en formato corto de WhatsApp:
- «¿Cuánto gané hoy?», «¿qué producto me deja más margen?», «¿mi publicidad me deja plata?», «compará este mes con el anterior», «¿cómo viene la campera negra?», «¿cuánta plata tengo retenida?»
- Atajos: **resumen**, **hoy**, **stock**, **pendientes**, **pausar avisos 2h**, **cuenta 2** (Elite con varias cuentas de Mercado Libre).
- Cuando conviene ver algo en pantalla, la respuesta trae el **link de CoreLux** que arma el servidor (nunca uno escrito por el modelo).

### Más adelante (con confirmación explícita, nunca solo)
- **Responder preguntas de compradores desde WhatsApp**: la IA propone la respuesta y la persona contesta «1» para enviarla. Escribe en Mercado Libre, así que va auditado y con confirmación.
- **Audios**: hablarle a la IA y que transcriba.
- **Equipo**: que el encargado reciba los avisos de despacho.

## 3. Cómo se arma por dentro (encaja con lo que ya existe)

```
Mercado Libre ──webhook──▶ CoreLux (ya recibe items, ventas, preguntas, reclamos)
                              │
                 detectores de avisos (armar_avisos + nuevos)
                              │  reserva única por persona+tipo+hecho
                              ▼
                       cola de WhatsApp ──▶ Meta Cloud API ──▶ celular
celular ──▶ Meta ──webhook firmado──▶ /webhook/whatsapp ──▶ filtro de alcance ──▶ asistente.responder() ──▶ respuesta
```

Piezas nuevas (todas pequeñas, reutilizan lo existente):
- `whatsapp.py`: enviar (Graph API), verificar la firma `X-Hub-Signature-256` del webhook, plantillas.
- Ruta `/webhook/whatsapp` (exenta de CSRF como los otros webhooks, con la firma obligatoria).
- Tablas: `whatsapp_vinculos` (persona, número **cifrado** con la clave que ya usamos para los tokens + hash para buscar, verificado el, preferencias, última vez que escribió), `whatsapp_enviados` (reserva única de avisos, estado, costo) y la conversación de los últimos 10 mensajes (en `cache_db`, como el chat de la web).
- Los detectores corren en el scheduler y, mejor, **al llegar el webhook de Mercado Libre** (un reclamo llega y se avisa en segundos, no en 30 minutos).
- La IA responde con **el mismo `asistente.responder`**: mismo filtro de alcance (solo Mercado Libre, la cuenta y CoreLux), mismas 29 herramientas de solo lectura, mismo tope diario. La cuenta sale del número vinculado, nunca de lo que escriba la persona.
- Solo para `plan = 'elite'` (y con un interruptor para apagarlo todo).

### La regla de Meta que condiciona todo: la ventana de 24 horas
- Cuando **la persona escribe**, se abre una ventana de 24 h donde se le puede mandar texto libre.
- Fuera de esa ventana solo se pueden mandar **plantillas aprobadas por Meta** (y se cobran).
- Diseño: el resumen del día sale como plantilla con un botón («Ver avisos en vivo»); al tocarlo se abre la ventana y los avisos de las siguientes 24 h salen como texto libre. Una persona que le habla a la IA durante el día mantiene la ventana abierta sola.

## 4. Opciones técnicas

| | **API oficial de Meta (Cloud API)** | **No oficial (Baileys / WhatsApp Web)** |
|---|---|---|
| Costo inicial | Verificación del negocio + número dedicado | Casi cero |
| Riesgo de baja del número | Bajo si se respetan las reglas | **Alto**: va contra los términos de WhatsApp; si banean el número, **todos los clientes pierden el servicio** |
| Mensajes proactivos | Plantillas aprobadas fuera de la ventana | Libre (por eso tienta) |
| Estabilidad | Contrato y soporte de Meta | Se rompe cuando WhatsApp cambia algo |
| Apto para cobrar como producto | **Sí** | **No** |

**Recomendación: la API oficial, directa con Meta** (sin intermediario: así no se paga el recargo de un proveedor). El camino no oficial sirve, como mucho, para una prueba personal tuya; no para algo que le vendés a un cliente.

**Otro punto de Meta que revisé:** desde el 15/01/2026 prohíbe en su API los **bots de IA de propósito general** (ChatGPT, Perplexity y similares), pero permite los que cumplen una función de negocio concreta: soporte, pedidos, avisos, ventas ([fuente](https://respond.io/blog/whatsapp-general-purpose-chatbots-ban), [fuente](https://9to5mac.com/2025/10/20/whatsapp-bans-ai-chatbots-from-using-its-business-api/)). El de CoreLux queda en el lado permitido a propósito: solo habla de la cuenta de Mercado Libre de la persona y rechaza todo lo demás. Aun así Meta decide qué es «función principal» a su criterio, así que conviene que el asistente nunca se parezca a un chat libre.

## 5. Costos

**Lo que cobra Meta** (sin cuota mensual; se paga por mensaje):
- Texto libre dentro de la ventana de 24 h: **gratis hasta 1.000 mensajes por mes por número**; desde el 01/10/2026 se cobra del 1.001 en adelante.
- **Cambio de hace 18 días:** las plantillas de «utilidad» enviadas dentro de la ventana también pasaron a cobrarse desde el 01/10/2026 ([Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing)). Meta avisa además que sin medio de pago cargado antes del 30/09 los mensajes que pasaron a cobrarse pueden dejar de entregarse.
- Argentina es un mercado propio en la tarifa de Meta. Las cifras que encontré son de **terceros y de 2025**: plantilla de utilidad ≈ **US$ 0,026–0,029** y de marketing ≈ **US$ 0,062–0,069** por mensaje ([Gupshup](https://www.gupshup.ai/resources/wp-content/uploads/2025/10/USD_Oct2025.pdf), [SleekFlow](https://help.sleekflow.io/es_/daftar-harga)). **No pude confirmar** la tarifa actual en pesos ni cuánto cuesta un mensaje de servicio pasado el 1.000: hay que mirar la tarifa oficial de Meta antes de fijar precios.
- Hay descuentos por volumen en utilidad y autenticación.

**Lo que cuesta la IA:** cada pregunta usa 2–3 pedidos al modelo; con DeepSeek es del orden de **un par de centavos de dólar o menos** (estimación mía: confirmarla con tu factura real de DeepSeek).

**Lo demás:** el número dedicado (una línea que pueda recibir el código de verificación), nada nuevo en Fly (los pedidos de WhatsApp son livianos) y un medio de pago en Meta.

**Ejemplo con 20 personas en Elite** (estimado; usando US$ 0,03 por plantilla):
| Concepto | Cuenta | Por mes |
|---|---|---|
| Plantillas (resumen diario + ~2 avisos fuera de ventana, por persona y día) | 20 × 3 × 30 = 1.800 | ≈ **US$ 54** |
| Texto libre dentro de la ventana | ≈ 1.500 | gratis los primeros 1.000; el resto, tarifa a confirmar |
| IA (20 preguntas por persona) | 400 | ≈ **US$ 1–2** |
| **Por persona** | | **≈ US$ 3** |

El plan Elite cuesta $99.000 (≈ **US$ 64** al MEP actual): el WhatsApp sería **alrededor del 5 %** del ingreso por persona, y menos si se agrupan los avisos y se usa bien la ventana. Con 100 personas serían ≈ US$ 300 por mes.

**Control de gasto:** tope de mensajes por persona y por mes (con aviso al llegar al 80 %), interruptor general y un contador de costo estimado en `/admin/salud`.

## 6. Riesgos y cómo se cubren
| Riesgo | Qué se hace |
|---|---|
| Un número ajeno recibe datos del negocio (cambio de línea, robo de chip) | Código de verificación, **repetirlo cada 90 días**, «¿sos vos?» ante un cambio, desvincular desde la web o con BAJA |
| Alguien escribe al bot sin estar vinculado | Respuesta fija con el link para vincularse; nunca datos |
| Que el bot se use para otra cosa | El mismo filtro de alcance de la web (servidor) |
| Meta rechaza una plantilla o baja la calidad del número | Plantillas simples y de utilidad, sin marketing; límite de avisos por persona |
| Gasto que se dispara | Topes y contador (arriba) |
| Datos personales | Consentimiento explícito al vincular; actualizar Términos y Privacidad (el número y el contenido pasan por Meta); **que lo revise tu abogado** junto con el resto |
| La IA se equivoca | Ya se midió: 0 de 36 ataques se escaparon y los números salen de las herramientas, no del modelo. Solo lectura al principio |

## 7. Plan por fases
| Fase | Qué incluye | Quién |
|---|---|---|
| **0 · Meta (calendario, no de desarrollo)** | Cuenta de Meta Business, **verificación del negocio** (suele tardar de días a un par de semanas), cuenta de WhatsApp Business, registrar el número dedicado, medio de pago, nombre visible aprobado | **Vos** |
| **1 · Avisos** | Vincular con código, preferencias, webhook firmado, los avisos de la tabla, resumen del día, BAJA y AYUDA, topes de gasto, pruebas | Yo |
| **2 · La IA por WhatsApp** | Responder con `asistente.responder`, historial, formato corto, atajos, link a pantalla, tope por número | Yo |
| **3 · Con confirmación** | Responder preguntas de compradores y otras acciones, todas auditadas | Yo |
| **4 · Monetización** | Incluido en Elite con tope justo; después evaluar un extra para el plan Base | Vos y yo |

**Para no esperar a Meta:** mientras se verifica el negocio, Meta da un **número de prueba gratuito** con hasta 5 destinatarios de prueba. Con eso se puede construir y probar la Fase 1 completa; al llegar la verificación solo se cambia el número y la clave.

## 8. Lo que necesito que decidas
1. **¿API oficial?** (recomendado) o la no oficial solo para pruebas tuyas.
2. **¿Incluido en Elite con tope de uso, o un extra aparte?** Recomiendo incluirlo en Elite como diferencial y ver el consumo real antes de cobrar un extra.
3. **Arrancar hoy la verificación en Meta**, que es lo que más tarda.
4. **Cuáles avisos van activados por defecto** (la tabla de arriba es mi propuesta).
