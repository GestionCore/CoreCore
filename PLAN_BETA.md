# CoreLux — plan para llegar a la beta y a vender (2026-10-02)

Acordado con el dueño: **se deja de agregar funciones y se pule**. El dueño ve y opina; lo técnico y la experiencia de uso los decide y ejecuta Claude,
explicando el motivo de cada cosa. Se registra acá lo hecho para que cualquier sesión retome sin perder el hilo.

## Puntaje de partida y objetivo

| Dimensión | Hoy | Objetivo beta | Objetivo vender |
|---|---|---|---|
| Exactitud del cálculo de plata | 85 | 90 | 95 |
| Experiencia de uso y primeros minutos | 55 | 80 | 90 |
| Confiabilidad en producción | 45 | 85 | 95 |
| Que le sirva a otros vendedores | 45 | 75 | 90 |
| Capacidad para crecer | 45 | 60 | 85 |
| Listo para cobrar | 25 | 40 | 90 |
| Seguridad | 75 | 85 | 92 |

## Orden de trabajo

### A. Que no se caiga y que nos enteremos si se cae (confiabilidad)
1. Versión visible: `/healthz` informa qué commit corre; `postdeploy.py` espera a que producción esté en la versión esperada, prueba las rutas clave y
   dice cómo volver atrás si falla. Motivo: hoy hubo dos caídas por desplegar mal y recién nos enteramos mirando logs.
2. `predeploy.py` verifica además que se esté en la carpeta correcta, en `main`, sin cambios sin commitear y todo subido a GitHub.
3. Configuración validada al arrancar (formato del DSN, URLs, claves) con mensajes claros, sin tumbar la app.
4. Errores: Sentry activo, y una página de error que le sirva al usuario.
5. (Del dueño) monitor externo de `/healthz/db` y alerta por mail.

### B. Los primeros 5 minutos (experiencia de uso)
1. Primer ingreso guiado: costos primero (planilla), con el motivo explicado y la ganancia "provisoria" bien marcada hasta que estén.
2. Menú corto para cuentas nuevas (lo esencial) y "Más" para el resto.
3. Estados vacíos y de error revisados en todas las pantallas con una cuenta vacía.
4. Móvil (375 px) revisado pantalla por pantalla.
5. Ayuda mínima dentro de la app y un canal de feedback.

### C. Que le sirva a otros vendedores (generalidad)
1. Cuenta de prueba sintética de otro perfil (sin FULL, sin Flex, sin publicidad, sin catálogo, con pocas ventas) recorriendo todo.
2. Textos y cálculos sin supuestos de indumentaria ni de AMBA donde se pueda.
3. Con las primeras cuentas reales ajenas: bug bash.

### D. Capacidad
1. Medir cuánto cuesta sincronizar una cuenta (llamadas a Mercado Libre, conexiones, tiempo) y calcular cuántas aguanta Fly hoy.
2. Sync por prioridad: cuentas activas primero, inactivas menos seguido.
3. Pool de conexiones y máquinas dimensionados con ese número.

### E. Listo para cobrar (después de la beta cerrada)
Mercado Pago de punta a punta, planes con límites reales, factura propia, soporte, avisos por mail, textos legales revisados, precio validado.

## Registro
- 2026-10-02: plan creado.
