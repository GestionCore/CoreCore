-- Conectar una SEGUNDA cuenta de MeLi (plan Elite) tiene un problema real
-- que no depende de CoreLux: si el navegador ya tiene una sesión activa
-- en mercadolibre.com, la pantalla de autorización de MeLi no ofrece
-- elegir cuenta — autoriza de nuevo la misma de siempre. La única forma
-- de autorizar una cuenta DISTINTA es abrir esa autorización en un
-- contexto de MeLi sin sesión (ventana de incógnito, otro navegador,
-- otro dispositivo).
--
-- El problema: el flujo viejo identificaba "a qué usuario de CoreLux hay
-- que vincular esta cuenta nueva" mirando la cookie de sesión de CoreLux
-- en ese mismo navegador — así que abrir el link en una ventana de
-- incógnito (que no tiene ESA cookie tampoco) rompía la vinculación por
-- completo, aunque sí resolvía el problema de MeLi.
--
-- Esta tabla saca esa dependencia de la cookie: el `state` (ya es un
-- token aleatorio de un solo uso, generado con secrets.token_urlsafe)
-- viaja pegado a la URL de autorización de MeLi y vuelve intacto en el
-- callback pase lo que pase con la sesión del navegador — así que sirve
-- como el "documento" que dice a qué usuario vincular, sin importar en
-- qué navegador/ventana/dispositivo se complete el login de MeLi.
CREATE TABLE IF NOT EXISTS oauth_vinculaciones_pendientes (
    state           TEXT PRIMARY KEY,
    usuario_id      BIGINT NOT NULL REFERENCES usuarios(id) ON DELETE CASCADE,
    creado_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, DELETE ON oauth_vinculaciones_pendientes TO app_backend;

-- RLS habilitado CON una política siempre-permisiva, en vez de dejarlo
-- sin RLS: en el momento en que /callback necesita leer esta tabla puede
-- no haber NINGUNA sesión activa (ventana de incógnito) — no hay
-- app.usuario_actual contra el cual filtrar, así que una política que
-- compare contra eso no sirve acá. La seguridad real la da el state en
-- sí (aleatorio, de un solo uso, de vida corta de 15 min), no RLS.
--
-- Por qué CON política y no simplemente sin RLS (como se hizo primero):
-- encontramos en producción que Supabase (probablemente su propio
-- panel/advisor de seguridad, que marca cualquier tabla sin RLS) la
-- terminó activando solo, sin ninguna política — eso bloquea TODO
-- acceso de app_backend con "new row violates row-level security
-- policy", el mismo bug de siempre (ver el comentario del bug #8 en
-- schema/01_schema_multitenant.sql) pero esta vez activándose después
-- de crear la tabla, no en la migración. Con una política explícita
-- que siempre permite, da lo mismo si Supabase prende RLS de nuevo.
ALTER TABLE oauth_vinculaciones_pendientes ENABLE ROW LEVEL SECURITY;
CREATE POLICY oauth_vinculaciones_pendientes_acceso_backend ON oauth_vinculaciones_pendientes
    USING (true) WITH CHECK (true);
