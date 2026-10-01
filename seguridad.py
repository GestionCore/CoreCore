"""
Seguridad y errores de la app web, en un solo lugar (se activa con seguridad.iniciar(app)):

  · Cookie de sesión: HttpOnly, SameSite=Lax y, en producción (Fly), Secure; la sesión vence a los 14 días.
  · Anti-CSRF: todo POST/PUT/PATCH/DELETE de un navegador tiene que venir de este mismo sitio. Se usa Sec-Fetch-Site (todos los navegadores
    actuales) y, si falta, Origin/Referer. Los webhooks de Mercado Libre y Mercado Pago, que no vienen de un navegador, quedan exentos.
  · Cabeceras: X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy y HSTS (solo en producción).
  · Estáticos con caché de un año cuando llevan ?v= (la versión cambia con el archivo).
  · /healthz (liviano, no toca la base: lo usa Fly) y /healthz/db (chequeo completo, para un monitor externo).
  · Páginas de error propias en español; las rutas /api/* responden JSON.
"""
import os
from datetime import timedelta
from urllib.parse import urlparse
from flask import request, jsonify, render_template

METODOS_QUE_ESCRIBEN = {"POST", "PUT", "PATCH", "DELETE"}
RUTAS_EXENTAS = {"/notificaciones_meli", "/webhook", "/webhook/mercadopago"}
EN_PRODUCCION = bool(os.getenv("FLY_APP_NAME"))
HOSTS_EXTRA = {h.strip() for h in os.getenv("HOSTS_PERMITIDOS", "").split(",") if h.strip()}


def _host(valor):
    return (urlparse(valor).netloc or "").split(":")[0].lower()


def _origen_permitido():
    """True si el pedido viene de este mismo sitio (o no viene de un navegador)."""
    sitio = request.headers.get("Sec-Fetch-Site")
    if sitio in ("same-origin", "none"):
        return True
    if sitio in ("cross-site", "same-site"):
        # same-site = otro subdominio: se acepta solo si coincide el Origin
        pass
    origen = request.headers.get("Origin") or request.headers.get("Referer")
    if not origen:
        return sitio is None            # sin ninguna señal de navegador: cliente de API o prueba
    permitidos = {request.host.split(":")[0].lower()} | HOSTS_EXTRA
    return _host(origen) in permitidos


def iniciar(app):
    if EN_PRODUCCION:
        # Detrás del proxy de Fly el pedido llega por http: sin esto, request.url_root/is_secure y los enlaces absolutos saldrían con http://
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=EN_PRODUCCION,
        PERMANENT_SESSION_LIFETIME=timedelta(days=14),
    )

    @app.before_request
    def _verificar_origen():
        if request.method in METODOS_QUE_ESCRIBEN and request.path not in RUTAS_EXENTAS and not _origen_permitido():
            return _error(403, "Pedido bloqueado", "El pedido no vino de CoreLux. Volvé a intentarlo desde la página.")

    @app.after_request
    def _cabeceras(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if EN_PRODUCCION:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
        if request.path.startswith("/static/") and "v" in request.args and resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp

    @app.route("/healthz")
    def healthz():
        return jsonify({"ok": True})

    @app.route("/healthz/db")
    def healthz_db():
        try:
            import db
            with db.conexion_admin() as conexion:
                conexion.cursor().execute("SELECT 1")
            return jsonify({"ok": True, "db": True})
        except Exception:
            return jsonify({"ok": False, "db": False}), 503

    @app.errorhandler(403)
    def _403(e):
        return _error(403, "Sin permiso", "No tenés permiso para ver esta página.")

    @app.errorhandler(404)
    def _404(e):
        return _error(404, "No encontramos esa página", "El enlace puede estar viejo o la página ya no existe.")

    @app.errorhandler(405)
    def _405(e):
        return _error(405, "Acción no disponible", "Esa acción no está permitida desde acá.")

    @app.errorhandler(429)
    def _429(e):
        return _error(429, "Demasiados pedidos", "Esperá un momento y volvé a intentar.")

    @app.errorhandler(500)
    def _500(e):
        return _error(500, "Algo salió mal de nuestro lado", "Ya quedó registrado. Probá de nuevo en un momento; si sigue, avisanos.")


def _error(codigo, titulo, detalle):
    if request.path.startswith("/api/") or request.is_json or "application/json" in (request.headers.get("Accept") or ""):
        return jsonify({"ok": False, "detalle": titulo + ". " + detalle}), codigo
    return render_template("errores.html", codigo=codigo, titulo=titulo, detalle=detalle, logueado=bool(request.cookies.get("session"))), codigo
