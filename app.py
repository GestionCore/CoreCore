"""
CoreLux — esqueleto inicial con el flujo completo de OAuth 2.0 contra
Mercado Libre, multi-tenant, con Postgres/Supabase + Row Level Security.
"""
import io
import sys
import os

# La consola de Windows arranca en cp1252 por default, que no puede
# imprimir los emojis (✅ ⚠️ etc.) que usan los prints de todo el proyecto
# — sin esto, el primer log con un emoji tira UnicodeEncodeError y tumba
# el proceso entero. reconfigure() está desde Python 3.7.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from flask import Flask, request, session, redirect, url_for, render_template, g, jsonify, send_file
import config
from auth import oauth_meli, registro, token_manager
from auth.middleware import login_requerido, admin_requerido, iniciar_sesion, cerrar_sesion, cambiar_cuenta_activa
from auditoria import auditar
import catalogo
import metricas as metricas_mod
import facturacion
import historial_precios as historial_precios_mod
import costos as costos_mod
import calculadora_costos
import meli_http
import logistica
import despacho as despacho_mod
import stock_masivo as stock_masivo_mod
import promociones as promociones_mod
import tendencias as tendencias_mod
import logros as logros_mod
import embudo_conversion as embudo_mod
import reputacion as reputacion_mod
import espia_competencia
import comparador_logistica as comparador_logistica_mod
import publicidad as publicidad_mod
import dashboard as dashboard_mod
import sincronizador
import analisis_stock
import onboarding
import monotributo
import costos_chat
import calidad as calidad_mod
import precios as precios_mod
import publicacion_edicion
import stock_meli
import catalogo_ganar
import mensajes as mensajes_mod
import opiniones as opiniones_mod
import cobros as cobros_mod
import tiempo_respuesta as tiempo_respuesta_mod
import full_stock
import reactivar
import flex
import chat_ia
import db
import nav_config
import timeline_publicacion
import exportador_redes
import scheduler
import ventas_manuales
import pagos
import admin_usuarios
import mis_datos
import preferencias
import meli_errores
import utils
from utils import formatear_moneda, formatear_moneda_entera, SQL_RECLAMO_AFECTA, hoy_argentina, ARGENTINA, sql_momento_argentina
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY
app.config["SECRET_KEY_FALLBACKS"] = [k.strip() for k in config.FLASK_SECRET_KEY_ANTERIOR.split(",") if k.strip()]

# Validación al arrancar: en producción, si falta una variable obligatoria no se arranca (mejor caer al desplegar que fallar a medias).
_faltan, _recomendadas = config.validar()
if _faltan:
    _mensaje = "[Config] ❌ Faltan variables obligatorias: " + ", ".join(_faltan)
    if os.getenv("FLY_APP_NAME"):
        raise RuntimeError(_mensaje)
    print(_mensaje + " (en desarrollo se sigue, pero parte de la app no va a funcionar)")
for _var, _motivo in _recomendadas.items():
    print(f"[Config] ⚠️ {_var} no está configurada: {_motivo}.")

# ── Sentry: monitoreo de errores en producción ──────────────────────────────
# Solo se activa si SENTRY_DSN está configurado en .env. En desarrollo local
# sin la variable, Sentry simplemente no se inicializa — sin efecto.
_dsn_sentry = (config.SENTRY_DSN or "").strip().strip("\"'")
if _dsn_sentry:
    # El monitoreo es un extra: un DSN mal pegado (sin https://, con comillas o con espacios) NO puede impedir que la app arranque.
    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(
            dsn=_dsn_sentry,
            integrations=[FlaskIntegration()],
            traces_sample_rate=0.1,  # 10% de requests trazados para performance
            profiles_sample_rate=0.1,
            send_default_pii=False,  # No enviar cookies ni IP por defecto
        )
        # Añadir contexto de usuario a cada evento para poder filtrar errores
        # por usuario específico en el dashboard de Sentry.
        from flask import g as _g
        import sentry_sdk as _sdk

        @app.before_request
        def _sentry_set_user():
            if getattr(_g, "usuario_id", None):
                _sdk.set_user({"id": str(_g.usuario_id)})
    except Exception as _e:
        print(f"[Sentry] ❌ SENTRY_DSN no es válida ({_e}): la app arranca igual, pero sin monitoreo de errores. Debe tener la forma https://<clave>@<algo>.ingest.sentry.io/<número>.")

# ── Flask-Caching ─────────────────────────────────────────────────────────
from cache import cache, construir_key, leer as cache_leer, guardar as cache_guardar, redis_disponible

_cache_config = {
    "CACHE_TYPE": config.CACHE_TYPE,
    "CACHE_DEFAULT_TIMEOUT": config.CACHE_DEFAULT_TIMEOUT,
    "CACHE_KEY_PREFIX": config.CACHE_KEY_PREFIX,
}
if config.CACHE_TYPE == "RedisCache":
    # Redis no se conecta al iniciar: sin esta comprobación, con Redis inalcanzable (Fly no tiene) cada cache.get() lanzaba ConnectionError
    if redis_disponible(config.REDIS_URL):
        _cache_config["CACHE_REDIS_URL"] = config.REDIS_URL
    else:
        print("[Cache] ℹ️  Redis no disponible: se usa una caché en memoria por proceso.")
        _cache_config = {"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": config.CACHE_DEFAULT_TIMEOUT, "CACHE_KEY_PREFIX": config.CACHE_KEY_PREFIX}

try:
    cache.init_app(app, config=_cache_config)
except Exception as _e:
    # Redis no disponible: degradar a SimpleCache silenciosamente
    import warnings
    warnings.warn(f"[Cache] Redis no disponible, usando SimpleCache: {_e}")
    cache.init_app(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 300})


# Filtros de formato para plantillas: {{ valor|plata }}, {{ valor|pct }}, {{ valor|numero }}
app.add_template_filter(utils.plata, "plata")
app.add_template_filter(utils.porcentaje, "pct")
app.add_template_filter(utils.numero, "numero")
app.add_template_filter(utils.fecha_corta, "fecha")
app.add_template_filter(utils.cuando_corto, "cuando")
app.add_template_filter(utils.plural, "plural")
app.add_template_global(utils.rango_fechas, "rango_fechas")
app.add_template_global(utils.ver_mas, "ver_mas")
app.add_template_filter(utils.html_seguro, "ux_seguro")


@app.context_processor
def _inyectar_version_estaticos():
    def v(nombre_archivo):
        ruta = os.path.join(app.static_folder, nombre_archivo)
        try:
            return str(int(os.path.getmtime(ruta)))
        except OSError:
            return "1"
    return {"static_v": v}


@app.context_processor
def _inyectar_pagos():
    """¿Se puede pagar? Sin Mercado Pago configurado CoreLux es una beta gratuita (ver config.PAGOS_HABILITADOS). Va aparte: lo necesitan también las páginas de error."""
    return {"pagos_habilitados": config.PAGOS_HABILITADOS}


@app.context_processor
def _inyectar_cuentas_usuario():
    """
    Plan Elite multi-cuenta: obtener_cuentas_de_usuario ya existía en
    registro.py, pero no había ninguna pantalla que la usara — la app
    asumía una sola cuenta activa en sesión siempre. Esto la deja
    disponible en cualquier template sin que cada vista tenga que
    acordarse de pasarla; el navbar solo la muestra si hay más de una.
    """
    if getattr(g, "mostrando_error", False):
        # Una página de error NUNCA puede consultar la base: el error suele ser justamente que la base no responde o no hay conexiones libres
        return {"capacidades": {}, "cuentas_disponibles": [], "cuenta_actual": None, "vocab": utils.vocabulario(True), "margen_minimo": preferencias.MARGEN_MINIMO_DEFECTO}
    if not getattr(g, "usuario_id", None):
        # Rutas públicas (/planes, /suscripcion/retorno...): base.html igual arma el menú si hay sesión y llama capacidades.get(...)
        return {"capacidades": {}, "cuentas_disponibles": [], "cuenta_actual": None, "vocab": utils.vocabulario(True), "margen_minimo": preferencias.MARGEN_MINIMO_DEFECTO}
    # Se pedía a la base en CADA página; cambia muy poco (al vincular una cuenta o refrescar capacidades): 60 s de caché, con el usuario en la clave
    clave_cuentas = construir_key("cuentas_usuario", g.usuario_id)
    cuentas = cache_leer(clave_cuentas)
    if cuentas is None:
        try:
            cuentas = registro.obtener_cuentas_de_usuario(g.usuario_id)
        except Exception as e:                      # la base no responde: la página se arma igual, sin selector de cuentas
            print(f"[Contexto] ⚠️ No se pudo leer la lista de cuentas: {e}")
            return {"capacidades": {}, "cuentas_disponibles": [], "cuenta_actual": None, "vocab": utils.vocabulario(True), "margen_minimo": preferencias.MARGEN_MINIMO_DEFECTO}
        cache_guardar(clave_cuentas, cuentas, timeout=60)
    cuenta_actual = next((c for c in cuentas if c["id"] == g.cuenta_id), None)
    # Qué usa esta cuenta (ads, flex, full, catalogo): las pantallas esconden solo lo que se confirmó que no aplica (ver capacidades.py)
    return {"cuentas_disponibles": cuentas, "cuenta_actual": cuenta_actual, "capacidades": (cuenta_actual or {}).get("capacidades") or {},
            "vocab": _vocabulario_de_la_cuenta(g.usuario_id, g.cuenta_id), "margen_minimo": _margen_minimo_de_la_cuenta(g.usuario_id, g.cuenta_id)}


def _margen_minimo_de_la_cuenta(usuario_id, cuenta_id):
    """El piso de margen de esta cuenta (Mi cuenta): lo que deja menos que eso se marca "al límite". 1 minuto en caché por usuario."""
    clave = construir_key("margenes_usuario", usuario_id)
    margenes = cache_leer(clave)
    if margenes is None:
        margenes = {str(k): v for k, v in preferencias.margenes_de_usuario(usuario_id).items()}
        cache_guardar(clave, margenes, timeout=60)
    return margenes.get(str(cuenta_id), preferencias.MARGEN_MINIMO_DEFECTO)


def _vocabulario_de_la_cuenta(usuario_id, cuenta_id):
    """"talle" si la cuenta tiene talles reales, "variante" si no (ver utils.vocabulario). 10 minutos en caché por cuenta."""
    clave = construir_key("usa_talles", cuenta_id)
    usa = cache_leer(clave)
    if usa is None:
        try:
            with db.conexion_usuario(usuario_id, cuenta_id) as conexion:
                usa = utils.cuenta_usa_talles(conexion.cursor())
        except Exception:
            usa = True                      # ante la duda, el vocabulario de siempre
        cache_guardar(clave, usa, timeout=600)
    return utils.vocabulario(usa)


@app.context_processor
def _inyectar_nav_grupos():
    return {"nav_grupos": nav_config.GRUPOS_NAV, "nav_seccion_de": nav_config.SECCION_DE_NAV}


@app.context_processor
def _inyectar_anio_actual():
    return {"anio_actual": hoy_argentina().year}


@app.after_request
def _trackear_navegacion(response):
    """
    Suma una visita a navegacion_visitas cada vez que se entra a una
    página del menú (no APIs) — es lo que alimenta el badge "MÁS USADO".
    Va en after_request (no en login_requerido) para cubrir también
    landing(), que no pasa por ese decorador.
    """
    try:
        usuario_id = getattr(g, "usuario_id", None)
        if usuario_id and request.method == "GET" and response.status_code == 200 and request.endpoint in nav_config.ENDPOINT_A_NAV:
            _, nav_key = nav_config.ENDPOINT_A_NAV[request.endpoint]
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute(
                    """
                    INSERT INTO navegacion_visitas (usuario_id, nav_key, contador, ultima_visita)
                    VALUES (%s, %s, 1, now())
                    ON CONFLICT (usuario_id, nav_key)
                    DO UPDATE SET contador = navegacion_visitas.contador + 1, ultima_visita = now()
                    """,
                    (usuario_id, nav_key),
                )
    except Exception as e:
        print(f"[NavTracking] ⚠️ Error registrando visita: {e}")
    return response


from flask_compress import Compress
Compress(app)

import seguridad
seguridad.iniciar(app)

import legal
app.register_blueprint(legal.bp)
import auditoria
app.register_blueprint(auditoria.bp)
import feedback
app.register_blueprint(feedback.bp)
import salud_sistema
app.register_blueprint(salud_sistema.bp)

import costos_importar
app.register_blueprint(costos_importar.bp)


def _con_aviso(ruta, mensaje, tipo="success"):
    """La ruta con ?msg=…&tipo=… : la pantalla destino lo muestra como aviso emergente (revisarMensajeEnURL en global.js)."""
    return f"{ruta}?{urlencode({'msg': mensaje, 'tipo': tipo})}"


def _detalle_error(e):
    """Mensaje para el usuario cuando algo falla: genérico; el detalle técnico va al log (y a Sentry), no a la pantalla."""
    print(f"[Error] {type(e).__name__}: {e}")
    return "No se pudo completar la acción. Probá de nuevo en un momento."


def _render_stock():
    """La pantalla de Stock (la comparten "/" y "/stock")."""
    productos, stats = catalogo.obtener_productos_y_estadisticas(g.usuario_id, g.cuenta_id)
    full_no_disponible = {"total": 0, "items": []}
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            full_no_disponible = full_stock.unidades_no_disponibles(conexion.cursor(), g.cuenta_id)
    except Exception as e:
        print(f"[Stock] ⚠️ No se pudo leer el stock no disponible de FULL: {e}")
    reactivables = []
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            reactivables = reactivar.listar(conexion.cursor())
    except Exception as e:
        print(f"[Stock] ⚠️ No se pudieron listar las pausadas con stock: {e}")
    return render_template("index.html", productos=productos, stats=stats, full_no_disponible=full_no_disponible, reactivables=reactivables, active_nav="stock")


@app.route("/api/reactivar/aplicar", methods=["POST"])
@login_requerido
@auditar("publicaciones_reactivar")
def api_reactivar_aplicar():
    """Reactiva las publicaciones pausadas que la persona confirmó (se revalidan acá: ver reactivar.py)."""
    ids = (request.get_json(silent=True) or {}).get("ids")
    if not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "detalle": "Elegí al menos una publicación."}), 400
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "Tu cuenta de Mercado Libre se desconectó. Volvé a conectarla."}), 401
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        resultados = reactivar.reactivar(conexion.cursor(), g.cuenta_id, access_token, ids)
    reactivadas = sum(1 for r in resultados if r["ok"])
    return jsonify({"ok": reactivadas > 0, "reactivadas": reactivadas, "fallidas": len(resultados) - reactivadas, "resultados": resultados})


@app.route("/")
def landing():
    if not session.get("usuario_id"):
        return render_template("landing.html")
    g.usuario_id = session["usuario_id"]
    g.cuenta_id = session["cuenta_id"]

    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT onboarding_completo FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila_onb = cursor.fetchone()
    if fila_onb and not fila_onb[0]:
        return redirect(url_for("onboarding_vista"))

    try:
        token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT sincronizacion_inicial_completa FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila_sync = cursor.fetchone()
    if fila_sync and not fila_sync[0]:
        return render_template("sincronizando.html")

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT pantalla_preferida FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila_pref = cursor.fetchone()
    # Reenviamos los query params (ej. ?msg=...&tipo=... de un toast) en
    # este redirect interno — si no, un mensaje armado para "/" se perdía
    # en el salto automático a la pantalla preferida (dashboard/métricas),
    # que nunca llegaba a leerlo.
    if fila_pref and fila_pref[0] == "dashboard":
        return redirect(url_for("dashboard_personalizable", **request.args))
    if fila_pref and fila_pref[0] == "metricas":
        return redirect(url_for("metricas_vista", **request.args))

    return _render_stock()


@app.route("/stock")
@login_requerido
def stock_vista():
    """
    Página fija de Stock — separada de "/" a propósito. "/" ("landing")
    hace un redirect "inteligente" según `pantalla_preferida` (puede
    mandar a Dashboard o a Métricas en vez de mostrar Stock), así que el
    link "Stock" del nav no puede apuntar ahí: si el usuario eligió
    Dashboard como pantalla preferida en el onboarding, cada click en
    "Stock" terminaba devolviéndolo al Dashboard en vez de mostrar el
    catálogo. Esta ruta siempre muestra Stock, sin importar la preferencia.
    """
    try:
        token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    return _render_stock()


@app.route("/exportar_planilla_stock")
@login_requerido
def exportar_planilla_stock():
    """
    "Exportar CSV" en Stock — nunca había tenido backend (404 directo).
    Un renglón por publicación/talle, con el mismo dato que ya se ve en
    pantalla — sin pegarle a MeLi, sale directo de la base local.
    """
    import csv
    from io import BytesIO, StringIO

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT p.id_meli, p.titulo, COALESCE(v.talle, 'Único') AS talle, v.color, p.precio, p.estado,
                   COALESCE(v.stock_propio, 0), COALESCE(v.stock_full, 0)
            FROM productos_padre p
            LEFT JOIN productos_variantes v ON v.id_padre = p.id
            ORDER BY p.titulo, talle
        """)
        filas = cursor.fetchall()

    buffer_texto = StringIO()
    # ; como separador (no ,) porque Excel en configuración regional
    # es-AR usa la coma como separador decimal — con "," como
    # delimitador, un precio "1234,50" en una celda rompe las columnas.
    writer = csv.writer(buffer_texto, delimiter=';')
    writer.writerow(["ID MeLi", "Título", _vocabulario_de_la_cuenta(g.usuario_id, g.cuenta_id)["V1"], "Color", "Precio", "Estado", "Stock Propio", "Stock FULL"])
    for id_meli, titulo, talle, color, precio, estado, stock_propio, stock_full in filas:
        writer.writerow([id_meli, titulo, talle, color or "", precio, estado, stock_propio, stock_full])

    # utf-8-sig (con BOM): sin esto Excel interpreta los acentos/ñ como
    # caracteres sueltos en vez de UTF-8 al abrir el archivo.
    buffer_bytes = BytesIO(buffer_texto.getvalue().encode("utf-8-sig"))
    return send_file(
        buffer_bytes, mimetype="text/csv", as_attachment=True,
        download_name=f"stock_{hoy_argentina().strftime('%Y-%m-%d')}.csv"
    )


@app.route("/conectar")
def conectar():
    """Arranca el flujo — manda al usuario a la pantalla de autorización de MeLi."""
    state = oauth_meli.generar_state()
    session["oauth_state"] = state
    return redirect(oauth_meli.construir_url_autorizacion(state))


@app.route("/conectar_otra_cuenta")
@login_requerido
def conectar_otra_cuenta():
    """
    Arranca el mismo flujo de OAuth que /conectar, pero marcado para que
    /callback sepa que hay que VINCULAR la cuenta de MeLi que autorice al
    usuario ya logueado (registro.vincular_cuenta_adicional), en vez de
    tratarlo como un login nuevo — así es como un usuario Elite conecta
    su segunda (o tercera...) cuenta sin desloguearse.

    Solo plan Elite: el límite "Base = 1 cuenta" no tenía enforcement
    real en el backend antes de esto — lo agregamos acá mismo, en el
    único punto de entrada que puede sumar una cuenta.

    El link de autorización que se muestra abajo funciona en CUALQUIER
    navegador/ventana/dispositivo, no solo en este — ver la nota larga
    en migrations/0013 sobre por qué hacía falta sacar esto de la cookie
    de sesión. Mercado Libre no te deja elegir cuenta en su propio login
    si ya hay una sesión de MeLi activa en el navegador; por eso se
    ofrece copiar el link para abrirlo en otro lado en vez de mandar
    directo.
    """
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT plan FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()
    if not fila or fila[0] != "elite":
        from urllib.parse import urlencode
        return redirect(f"/planes?{urlencode({'msg': 'Conectar más de una cuenta es una función del Plan Elite.', 'tipo': 'info'})}")

    state = oauth_meli.generar_state()
    session["oauth_state"] = state
    session["vinculando_cuenta_extra"] = True
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        # Purga oportunista de intentos viejos abandonados (>15 min) —
        # no hace falta un cron aparte para una tabla tan chica.
        cursor.execute("DELETE FROM oauth_vinculaciones_pendientes WHERE creado_en < now() - interval '15 minutes'")
        cursor.execute("INSERT INTO oauth_vinculaciones_pendientes (state, usuario_id) VALUES (%s, %s)", (state, g.usuario_id))

    url_autorizacion = oauth_meli.construir_url_autorizacion(state)
    return render_template("conectar_otra_cuenta.html", url_autorizacion=url_autorizacion)


MOTIVO_USUARIO_CANCELO = "usuario_cancelo"
MOTIVO_INTENTO_VENCIDO = "intento_vencido"
MOTIVO_GENERICO = "generico"
MOTIVO_CUENTA_YA_VINCULADA = "cuenta_ya_vinculada"


@app.route("/callback")
def callback():
    """MeLi redirige acá después de que el usuario aprueba (o rechaza) el permiso.

    El detalle técnico de cada falla (código HTTP, cuerpo de la respuesta,
    nombres de parámetros OAuth) se loguea server-side para debug, pero
    nunca se le muestra al usuario — error_conexion.html solo recibe una
    categoría, y decide ella misma qué mensaje mostrar.
    """
    error = request.args.get("error")
    if error:
        app.logger.warning("Callback OAuth: MeLi devolvió error=%s", error)
        return render_template("error_conexion.html", motivo=MOTIVO_USUARIO_CANCELO)

    code = request.args.get("code")
    state_recibido = request.args.get("state")
    state_esperado = session.pop("oauth_state", None)

    if not code:
        app.logger.warning("Callback OAuth: no llegó 'code' en la URL de vuelta.")
        return render_template("error_conexion.html", motivo=MOTIVO_GENERICO)

    # El state puede validarse de DOS formas: contra la cookie de sesión
    # de ESTE navegador (login normal, o "agregar cuenta" completado en
    # el mismo navegador) — o contra una vinculación pendiente guardada
    # en la base por /conectar_otra_cuenta, que es justamente lo que
    # permite completar el login de MeLi en OTRO navegador/ventana/
    # dispositivo sin cookie de sesión de CoreLux (ver migrations/0013).
    # El propio state (aleatorio, de un solo uso) es la prueba en ambos
    # casos — no se necesita la cookie si el state matchea esa tabla.
    usuario_id_vinculacion_pendiente = None
    if state_recibido and state_recibido != state_esperado:
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            cursor.execute(
                "DELETE FROM oauth_vinculaciones_pendientes WHERE state = %s AND creado_en > now() - interval '15 minutes' RETURNING usuario_id",
                (state_recibido,)
            )
            fila = cursor.fetchone()
        if fila:
            usuario_id_vinculacion_pendiente = fila[0]

    state_valido = (state_esperado and state_recibido == state_esperado) or usuario_id_vinculacion_pendiente is not None
    if not state_valido:
        app.logger.warning("Callback OAuth: state no coincide (esperado=%s, recibido=%s).", bool(state_esperado), bool(state_recibido))
        return render_template("error_conexion.html", motivo=MOTIVO_INTENTO_VENCIDO)

    ok, resultado = oauth_meli.intercambiar_codigo_por_token(code)
    if not ok:
        app.logger.warning("Callback OAuth: falló el intercambio de código — %s", resultado)
        return render_template("error_conexion.html", motivo=MOTIVO_GENERICO)

    ok_datos, datos_meli = oauth_meli.obtener_datos_usuario_meli(resultado["access_token"])
    if not ok_datos:
        app.logger.warning("Callback OAuth: falló la consulta de datos del usuario — %s", datos_meli)
        return render_template("error_conexion.html", motivo=MOTIVO_GENERICO)

    # Si venimos de "Agregar otra cuenta" (/conectar_otra_cuenta), esta
    # autorización se vincula al usuario_id ya logueado en vez de crear
    # un usuario nuevo — así es como funciona el multi-cuenta de Plan
    # Elite. El usuario_id sale de la vinculación pendiente en la base
    # cuando existe (funciona sin importar en qué navegador se completó
    # el login de MeLi); si no, cae al flag de sesión de siempre (mismo
    # navegador).
    if usuario_id_vinculacion_pendiente is not None:
        vinculando = True
        usuario_id_actual = usuario_id_vinculacion_pendiente
    else:
        vinculando = session.pop("vinculando_cuenta_extra", False)
        usuario_id_actual = session.get("usuario_id")

    if vinculando and usuario_id_actual:
        from urllib.parse import urlencode
        cuenta_id, resultado_vinculo = registro.vincular_cuenta_adicional(usuario_id_actual, datos_meli)
        if resultado_vinculo == "ya_de_otro_usuario":
            app.logger.warning("Callback OAuth: intento de vincular meli_user_id=%s, ya pertenece a otro usuario.", datos_meli.get("meli_user_id"))
            return render_template("error_conexion.html", motivo=MOTIVO_CUENTA_YA_VINCULADA)

        token_manager.guardar_tokens(
            cuenta_id, resultado["access_token"], resultado["refresh_token"], resultado["expires_in"]
        )
        # Activa la cuenta recién vinculada — si ya tenía datos de una
        # sincronización previa (reconexión), login_requerido la deja pasar
        # directo; si es nueva, va a mostrarle sincronizando.html sola.
        iniciar_sesion(usuario_id_actual, cuenta_id)

        if resultado_vinculo == "reconectada":
            # El navegador ya tenía una sesión activa en mercadolibre.com
            # con la MISMA cuenta que ya estaba conectada acá — MeLi no
            # muestra selector de cuenta si ya hay una sesión, así que el
            # OAuth "autoriza" la misma de siempre en vez de una distinta.
            # Antes esto redirigía en silencio al Dashboard sin avisar
            # nada — se sentía como que el botón no hacía nada. Este
            # mensaje explica lo que pasó y cómo conectar una cuenta
            # REALMENTE distinta.
            msg = "Esa cuenta de Mercado Libre ya estaba conectada a tu usuario — no se agregó ninguna nueva. Para sumar una cuenta distinta, primero cerrá sesión en mercadolibre.com (o usá una ventana privada) y volvé a intentar."
            return redirect(f"{url_for('landing')}?{urlencode({'msg': msg, 'tipo': 'info'})}")

        _en_segundo_plano(sincronizador.sincronizar_todo, usuario_id_actual, cuenta_id)
        msg = f"¡Cuenta {datos_meli.get('nickname') or ''} conectada! Ya podés cambiar entre tus cuentas desde el selector del menú.".replace("  ", " ")
        return redirect(f"{url_for('landing')}?{urlencode({'msg': msg, 'tipo': 'success'})}")

    usuario_id, cuenta_id, es_nuevo = registro.crear_o_actualizar_login(datos_meli)

    token_manager.guardar_tokens(
        cuenta_id, resultado["access_token"], resultado["refresh_token"], resultado["expires_in"]
    )

    if es_nuevo:
        ref_code = request.cookies.get("ref_code")
        if ref_code:
            try:
                with db.conexion_admin() as _conn:
                    _cur = _conn.cursor()
                    _cur.execute("SELECT id FROM usuarios WHERE referral_code = %s", (ref_code,))
                    ref_row = _cur.fetchone()
                    if ref_row and ref_row[0] != usuario_id:
                        _cur.execute(
                            "INSERT INTO referrals (referrer_id, referred_id, codigo, convertido_en) VALUES (%s, %s, %s, now()) ON CONFLICT (referred_id) DO NOTHING",
                            (ref_row[0], usuario_id, ref_code)
                        )
            except Exception as e:
                print(f"[Referidos] ⚠️ No se pudo registrar el referido: {e}")

    iniciar_sesion(usuario_id, cuenta_id)

    # Sync inicial en background: si Celery está disponible lo encola
    # (persistente, con reintentos). Si no, cae a un thread de Python
    # como antes — la app funciona igual, solo sin garantía ante reinicios.
    _en_segundo_plano(sincronizador.sincronizar_todo, usuario_id, cuenta_id)

    return redirect(url_for("landing"))


def _en_segundo_plano(funcion, *args):
    """
    Corre `funcion(*args)` en un hilo, sin bloquear el pedido. Mercado Libre espera que el webhook responda casi al instante (si tarda seguido deja
    de mandar notificaciones), así que lo pesado nunca se hace dentro del pedido.
    """
    import threading
    threading.Thread(target=funcion, args=args, daemon=True).start()


@app.route("/notificaciones_meli", methods=["POST"])
@app.route("/webhook", methods=["POST"])
def notificaciones_meli():
    """
    Webhook de Mercado Libre — la URL ya estaba configurada del lado de
    MeLi (se veía en los logs pegando acá y recibiendo 404 porque la
    ruta todavía no existía). MeLi espera una respuesta 200 casi
    inmediata: nunca hacer el trabajo real en el request, todo se
    delega a un hilo de fondo (mismo patrón que /callback) y se
    responde ya. Sin login de por medio a propósito — es MeLi
    pegándole directo, no un usuario con sesión.

    Dos rutas para el mismo handler a propósito: los logs mostraron
    pedidos entrando tanto a /notificaciones_meli como a /webhook (no
    tengo forma de ver cuál está configurada de verdad en MeLi
    Developers desde acá), así que ambas quedan cubiertas en vez de
    apostar a una sola.
    """
    datos = request.get_json(silent=True) or {}
    topic = datos.get("topic")
    resource = datos.get("resource")
    meli_user_id = datos.get("user_id")

    # Las notificaciones de otra aplicación (o una inventada) no disparan nada: el contenido tampoco se toma como dato,
    # solo avisa QUÉ volver a pedirle a Mercado Libre para esa cuenta.
    application_id = datos.get("application_id")
    if application_id is not None and config.MELI_CLIENT_ID and str(application_id) != str(config.MELI_CLIENT_ID):
        return "", 200

    if topic and meli_user_id:
        _en_segundo_plano(sincronizador.procesar_notificacion_webhook, topic, resource, meli_user_id)

    return "", 200


@app.route("/reconectar")
@login_requerido
def reconectar():
    """
    Cuando token_manager detecta invalid_grant, mandamos al usuario acá
    en vez de a /conectar directo — así puede ver un mensaje claro de
    por qué antes de volver a pasar por MeLi.
    """
    return render_template("reconectar.html")


@app.route("/logout")
def logout():
    cerrar_sesion()
    return redirect(url_for("landing"))


@app.route("/cambiar_cuenta/<int:cuenta_id>", methods=["POST"])
@login_requerido
def cambiar_cuenta(cuenta_id):
    """Plan Elite: cambiar cuál cuenta de MeLi conectada está viendo el usuario."""
    cambiar_cuenta_activa(cuenta_id)
    return redirect(url_for("dashboard_personalizable"))


@app.route("/api/hoy")
@login_requerido
def api_hoy():
    return jsonify(dashboard_mod.obtener_ventas_hoy(g.usuario_id, g.cuenta_id))


@app.route("/api/ticker")
@login_requerido
def api_ticker():
    # Este ticker vive en el nav de TODAS las páginas — si esto tira sin
    # capturar, el pill de arriba queda con el efecto skeleton (el
    # "círculo"/franja que se supone brilla mientras carga) trabado para
    # siempre, porque el JS de global.js no tenía manejo de error: solo
    # logueaba en consola y dejaba el elemento tal cual estaba.
    try:
        return jsonify(dashboard_mod.obtener_ticker(g.usuario_id, g.cuenta_id))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error armando el ticker: {e}")
        return jsonify(None), 502


@app.route("/api/quiebre_stock")
@login_requerido
def api_quiebre_stock():
    return jsonify(dashboard_mod.obtener_quiebre_stock(g.usuario_id, g.cuenta_id))


@app.route("/api/resumen_diario")
@login_requerido
def api_resumen_diario():
    try:
        return jsonify(dashboard_mod.obtener_resumen_diario(g.usuario_id, g.cuenta_id))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error en resumen diario: {e}")
        return jsonify(None)


@app.route("/api/metricas/heatmap_horario")
@login_requerido
def api_metricas_heatmap_horario():
    """Ventas agrupadas por hora del día (0-23) y día de la semana (0=Lun … 6=Dom).
    Devuelve una matriz 7×24 con la cantidad de ventas en cada celda."""
    import db
    try:
        dias_str = request.args.get("dias", "90")
        dias = min(max(int(dias_str), 7), 365)
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    EXTRACT(DOW FROM {momento})::int AS dow,
                    EXTRACT(HOUR FROM {momento})::int AS hora,
                    SUM(cantidad)::int AS unidades
                FROM ventas
                WHERE fecha_venta >= CURRENT_DATE - (%s || ' days')::interval
                  AND hora_venta IS NOT NULL
                GROUP BY dow, hora
            """.format(momento=sql_momento_argentina(por_defecto="12:00")), (dias,))
            filas = cur.fetchall()
        # dow: 0=Dom,1=Lun…6=Sab en Postgres EXTRACT(DOW) — reordenamos a Lun-Dom
        matriz = [[0] * 24 for _ in range(7)]
        maximo = 0
        for dow, hora, unidades in filas:
            lun_base = (dow - 1) % 7  # 0=Lun…6=Dom
            matriz[lun_base][hora] = unidades
            if unidades > maximo:
                maximo = unidades
        dias_labels = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
        return jsonify({"matriz": matriz, "maximo": maximo, "dias": dias_labels, "horas": list(range(24))})
    except Exception as e:
        print(f"[Metricas] heatmap_horario error: {e}")
        return jsonify({"matriz": [[0]*24 for _ in range(7)], "maximo": 0, "dias": ["Lun","Mar","Mié","Jue","Vie","Sáb","Dom"], "horas": list(range(24))})


@app.route("/api/metricas/correlacion_precio_ventas")
@login_requerido
def api_correlacion_precio_ventas():
    """Scatter: precio unitario vs unidades vendidas por modelo, para ver si precio alto = menos ventas."""
    import db
    try:
        dias_str = request.args.get("dias", "90")
        dias = min(max(int(dias_str), 7), 365)
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT
                    COALESCE(p.titulo, v.id_meli) AS titulo,
                    AVG(v.precio_venta)::numeric(12,2) AS precio_prom,
                    SUM(v.cantidad)::int AS unidades
                FROM ventas v
                LEFT JOIN productos_padre p ON p.id_meli = v.id_meli
                WHERE v.fecha_venta >= CURRENT_DATE - (%s || ' days')::interval
                GROUP BY p.titulo, v.id_meli
                HAVING SUM(v.cantidad) > 0
                ORDER BY unidades DESC
                LIMIT 60
            """, (dias,))
            filas = cur.fetchall()
        puntos = [{"titulo": f[0][:40], "precio": float(f[1]), "unidades": f[2]} for f in filas]
        return jsonify({"puntos": puntos})
    except Exception as e:
        print(f"[Metricas] correlacion error: {e}")
        return jsonify({"puntos": []})


@app.route("/api/dashboard/cobertura_costos")
@login_requerido
def api_dashboard_cobertura_costos():
    """Qué parte de lo facturado en los últimos 14 días no tiene costo de fabricación cargado (la ganancia del Dashboard cubre esos 14 días)."""
    hasta = hoy_argentina()
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            return jsonify(costos_mod.cobertura_de_costos(conexion.cursor(), hasta - timedelta(days=13), hasta))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error midiendo la cobertura de costos: {e}")
        return jsonify({"avisar": False})


@app.route("/api/dashboard/tendencia_ventas")
@login_requerido
def api_dashboard_tendencia_ventas():
    try:
        return jsonify(dashboard_mod.obtener_tendencia_ventas(g.usuario_id, g.cuenta_id))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error en tendencia de ventas: {e}")
        return jsonify({"serie": [], "total_formateado": "0,00", "promedio_diario_formateado": "0,00"})


@app.route("/api/dashboard/tendencia_ventas.png")
@login_requerido
def api_dashboard_tendencia_ventas_png():
    """Descarga del gráfico de tendencia como imagen — botón de exportar del widget."""
    import graficos_export
    datos = dashboard_mod.obtener_tendencia_ventas(g.usuario_id, g.cuenta_id)
    serie = [{"etiqueta": p["fecha"], "valor": p["facturado"]} for p in datos["serie"]]
    buffer = graficos_export.generar_barras_png(
        serie, titulo=f"Tendencia de Ventas — últimos {len(serie)} días",
        subtitulo=f"Total del período: ${datos['total_formateado']}"
    )
    return send_file(buffer, mimetype="image/png", as_attachment=True, download_name="tendencia_ventas.png")


@app.route("/api/dashboard/reclamos_resumen")
@login_requerido
def api_dashboard_reclamos_resumen():
    return jsonify(dashboard_mod.obtener_reclamos_resumen(g.usuario_id, g.cuenta_id))


@app.route("/api/dashboard/costos_resumen")
@login_requerido
def api_dashboard_costos_resumen():
    return jsonify(dashboard_mod.obtener_costos_resumen(g.usuario_id, g.cuenta_id))


@app.route("/api/dashboard/logro_top")
@login_requerido
def api_dashboard_logro_top():
    import db
    headers = None
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
    except token_manager.CuentaDesconectada:
        pass
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        resultado = logros_mod.obtener_logros(cursor, g.cuenta_id, headers)
    if resultado["misiones"]:
        m = resultado["misiones"][0]
        return jsonify({"hay_mision": True, "titulo": m["titulo"], "descripcion": m["descripcion"], "prioridad": m["prioridad"], "link": m["link"]})
    return jsonify({"hay_mision": False})


@app.route("/api/dashboard/acciones_hoy")
@login_requerido
def api_dashboard_acciones_hoy():
    """
    "Lo que tenés que hacer hoy": las misiones de Logros más prioritarias,
    listas para mostrar como tarjetas con botón. Las opcionales solo se
    incluyen si hay poco más importante, para que la lista no se llene de
    cosas que pueden esperar.
    """
    import db
    headers = None
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
    except token_manager.CuentaDesconectada:
        pass
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        resultado = logros_mod.obtener_logros(cursor, g.cuenta_id, headers)
    misiones = resultado["misiones"]
    importantes = [m for m in misiones if m["prioridad"] != "opcional"]
    elegidas = importantes[:4] if len(importantes) >= 3 else (importantes + [m for m in misiones if m["prioridad"] == "opcional"])[:3]
    return jsonify({
        "total": len(misiones),
        "urgentes": sum(1 for m in misiones if m["prioridad"] == "urgente"),
        "acciones": [
            {"id": m["id"], "prioridad": m["prioridad"], "categoria": m["categoria"], "titulo": m["titulo"],
             "detalle": m["descripcion"], "link": m.get("link"), "link_texto": m.get("link_texto")}
            for m in elegidas
        ],
    })


@app.route("/api/dashboard/ganancia_dia_vs_promedio")
@login_requerido
def api_dashboard_ganancia_dia_vs_promedio():
    """
    Alimenta el hero del Dashboard (Ganancia Neta Real de hoy vs. el
    promedio diario de los últimos 14 días) y el panel de P&L (B1 + B2)
    con UNA sola llamada a calcular_ganancia_real — reutiliza el mismo
    período de 14 días para ambas cosas en vez de pedirlo dos veces
    (cada llamada le pega en vivo a la API de Ads de MeLi, así que
    duplicarla sería plata y tiempo tirados).

    Reemplaza al viejo /api/dashboard/ganancia_hoy, que calculaba una
    "ganancia" simplificada (sin publicidad ni costo de fabricación) —
    eso violaba la fórmula de Ganancia Neta Real que CLAUDE.md marca
    como innegociable. Este endpoint usa la fórmula completa.
    """
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    hoy = datetime.now(ARGENTINA)
    hoy_str = hoy.strftime("%Y-%m-%d")
    desde_str = (hoy - timedelta(days=13)).strftime("%Y-%m-%d")  # 14 días incluyendo hoy

    datos = metricas_mod.calcular_ganancia_real(g.usuario_id, g.cuenta_id, access_token, desde_str, hoy_str)
    r = datos["resumen"]["raw"]

    ganancia_hoy = sum(v["raw"]["ganancia_neta"] for v in datos["ventas"] if v["fecha"] == hoy_str)
    facturado_hoy = sum(v["raw"]["precio_venta"] for v in datos["ventas"] if v["fecha"] == hoy_str)
    ganancia_promedio_diario = r["ganancia_neta"] / 14

    variacion_pct = None
    if ganancia_promedio_diario:
        variacion_pct = round(((ganancia_hoy - ganancia_promedio_diario) / abs(ganancia_promedio_diario)) * 100, 1)

    def _f(n):
        return f"${formatear_moneda_entera(n)}"

    # Ganancia día por día de los últimos 14 (mismas ventas, misma fórmula: no pide nada más a MeLi)
    por_dia = {}
    for v in datos["ventas"]:
        d = por_dia.setdefault(v["fecha"], {"ganancia": 0.0, "facturado": 0.0, "ventas": 0})
        d["ganancia"] += v["raw"]["ganancia_neta"]
        d["facturado"] += v["raw"]["precio_venta"]
        d["ventas"] += 1
    serie_14d = []
    for i in range(14):
        dia = hoy - timedelta(days=13 - i)
        d = por_dia.get(dia.strftime("%Y-%m-%d"), {"ganancia": 0.0, "facturado": 0.0, "ventas": 0})
        serie_14d.append({"fecha": dia.strftime("%Y-%m-%d"), "etiqueta": dia.strftime("%d/%m"), "ganancia": round(d["ganancia"], 2),
                          "facturado": round(d["facturado"], 2), "ventas": d["ventas"]})
    mejor = max(serie_14d, key=lambda s: s["ganancia"])
    mejor_dia = {"etiqueta": mejor["etiqueta"], "ganancia": mejor["ganancia"], "ganancia_f": _f(mejor["ganancia"])} if mejor["ventas"] else None

    ganancia_ayer, ventas_ayer = dashboard_mod.ganancia_de_ayer_hasta_la_hora(datos["ventas"], hoy)
    return jsonify({
        "serie_14d": serie_14d, "mejor_dia": mejor_dia, "ventas_14d": sum(s["ventas"] for s in serie_14d),
        "ayer_misma_hora": {"ganancia": ganancia_ayer, "ganancia_f": _f(ganancia_ayer), "ventas": ventas_ayer},
        "hoy": {
            "ganancia": round(ganancia_hoy, 2), "ganancia_f": _f(ganancia_hoy),
            "facturado": round(facturado_hoy, 2), "facturado_f": _f(facturado_hoy),
        },
        "promedio_diario_14d": {
            "ganancia": round(ganancia_promedio_diario, 2), "ganancia_f": _f(ganancia_promedio_diario),
        },
        "variacion_pct": variacion_pct,
        "por_encima_promedio": ganancia_hoy >= ganancia_promedio_diario,
        "periodo_14d": {
            "facturado": round(r["facturado"], 2), "facturado_f": _f(r["facturado"]),
            "comision": round(r["comision"], 2), "comision_f": _f(r["comision"]),
            "envios": round(r["envios"], 2), "envios_f": _f(r["envios"]),
            "costo_ads": round(r["costo_ads"], 2), "costo_ads_f": _f(r["costo_ads"]),
            "costo_fabricacion": round(r["costo_fabricacion"], 2), "costo_fabricacion_f": _f(r["costo_fabricacion"]),
            "costos_totales": round(r["comision"] + r["envios"] + r["costo_ads"] + r["costo_fabricacion"], 2),
            "costos_totales_f": _f(r["comision"] + r["envios"] + r["costo_ads"] + r["costo_fabricacion"]),
            "margen": round(r["ganancia_neta"], 2), "margen_f": _f(r["ganancia_neta"]),
            "margen_negativo": r["ganancia_neta"] < 0,
        },
    })


@app.route("/api/dashboard/top_productos")
@login_requerido
def api_dashboard_top_productos():
    """Los 5 modelos que más facturaron en 30 días. Consolidado POR MODELO (todos los talles/variantes juntos), no por publicación: la misma campera en
    cuatro talles ocupaba cuatro puestos del ranking."""
    desde = (hoy_argentina() - timedelta(days=30)).isoformat()
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT COALESCE(v.titulo, ''), v.id_meli, SUM(v.cantidad), SUM(v.precio_venta * v.cantidad), MAX(p.thumbnail), BOOL_OR(p.id_meli IS NOT NULL)
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.cuenta_id = %s AND DATE(v.fecha_venta) >= %s AND v.eliminado_en IS NULL
            GROUP BY v.titulo, v.id_meli
        """, (g.cuenta_id, desde))
        filas = cursor.fetchall()
    return jsonify([{
        "nombre": m["nombre"], "unidades": m["unidades"], "facturado": m["facturado"], "facturado_f": utils.plata(m["facturado"]), "pct": m["pct"],
        "publicaciones": m["publicaciones"], "id_meli": m["id_meli"], "miniatura": m["miniatura"],
    } for m in dashboard_mod.top_modelos(filas)])


@app.route("/api/dashboard/ultimas_ventas")
@login_requerido
def api_dashboard_ultimas_ventas():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        # fecha_venta es solo el DÍA: ordenar por ella dejaba las ventas de un mismo día en cualquier orden y mostraba todas a las 00:00
        cursor.execute(f"""
            SELECT
                COALESCE(v.titulo, 'Sin nombre') AS nombre,
                v.cantidad,
                v.precio_venta,
                {utils.sql_momento_argentina("v")} AS momento,
                v.hora_venta IS NOT NULL AS con_hora,
                p.id_meli
            FROM ventas v
            LEFT JOIN productos_padre p ON p.id_meli = v.id_meli AND p.cuenta_id = v.cuenta_id
            WHERE v.cuenta_id = %s
              AND v.eliminado_en IS NULL
            ORDER BY momento DESC
            LIMIT 8
        """, (g.cuenta_id,))
        filas = cursor.fetchall()
    return jsonify([{
        "nombre": utils.limpiar_titulo_modelo(f[0]) or f[0],
        "talle": (lambda talle: None if talle == "Único" else talle)(utils.extraer_talle(f[0])),       # lo que distingue una fila de otra; nada si no tiene talle
        "cantidad": int(f[1]),
        "precio_f": utils.plata(f[2]),
        "fecha": utils.cuando_corto(f[3], con_hora=f[4]),
        "id_meli": f[5],
    } for f in filas])


@app.route("/dashboard")
@login_requerido
def dashboard_personalizable():
    try:
        token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    mono = monotributo.evaluar_categoria(g.usuario_id, g.cuenta_id)
    ventas_por_provincia = None
    try:
        ventas_por_provincia = dashboard_mod.obtener_ventas_por_provincia(g.usuario_id, g.cuenta_id)
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error calculando ventas por provincia: {e}")
    cuando_compran = None
    try:
        cuando_compran = dashboard_mod.obtener_cuando_compran(g.usuario_id, g.cuenta_id)
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error calculando cuándo te compran: {e}")
    proyeccion = None
    try:
        proyeccion = dashboard_mod.obtener_proyeccion_mes(g.usuario_id, g.cuenta_id)
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error calculando la proyección del mes: {e}")
    return render_template(
        "dashboard_personalizable.html", active_nav="dashboard", mono=mono,
        ventas_por_provincia=ventas_por_provincia, cuando_compran=cuando_compran, proyeccion=proyeccion,
    )


@app.route("/metricas")
@login_requerido
def metricas_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    fecha_hasta = request.args.get("fecha_hasta") or hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (hoy_argentina() - timedelta(days=30)).strftime("%Y-%m-%d")

    datos = metricas_mod.calcular_ganancia_real(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)

    cobertura_costos = None
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cobertura_costos = costos_mod.cobertura_de_costos(conexion.cursor(), fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error midiendo la cobertura de costos: {e}")

    # Punto de equilibrio (B7): costos fijos del mismo período vs. el
    # margen de contribución real que ya salió del cálculo de arriba.
    # Ninguno de estos bloques nuevos puede tumbar la página entera si
    # falla — mismo criterio que ya se usa con Ads más arriba.
    punto_equilibrio = None
    try:
        _, stats_gastos, _ = costos_mod.obtener_datos_costos(g.usuario_id, fecha_desde, fecha_hasta, g.cuenta_id)
        costos_fijos = stats_gastos["fijos_raw"]
        facturado_raw = datos["resumen"]["raw"]["facturado"]
        margen_contribucion_pct = (datos["resumen"]["raw"]["ganancia_neta"] / facturado_raw) if facturado_raw > 0 else 0
        if costos_fijos > 0 and margen_contribucion_pct > 0:
            ventas_minimas = costos_fijos / margen_contribucion_pct
            punto_equilibrio = {
                "costos_fijos_f": formatear_moneda(costos_fijos),
                "ventas_minimas_f": formatear_moneda(ventas_minimas),
                "margen_contribucion_pct": round(margen_contribucion_pct * 100, 1),
                "veces_superado": round(facturado_raw / ventas_minimas, 1) if ventas_minimas > 0 else None,
                "superado": facturado_raw >= ventas_minimas,
            }
    except Exception as e:
        print(f"[Métricas] ⚠️ Error calculando punto de equilibrio: {e}")

    # Margen por canal de envío (B6) — Full / Flex / Envíos clásicos.
    # Reemplaza a la página aparte "Propia vs FULL" (retirada del menú).
    canales_envio = None
    try:
        canales_envio, _ = comparador_logistica_mod.calcular_comparacion(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error calculando margen por canal: {e}")

    # Factura MeLi del período de facturación en curso (B3).
    factura_meli = None
    try:
        factura_meli = facturacion.resumen_condensado_periodo_actual(access_token, g.cuenta_id)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error trayendo la factura MeLi: {e}")

    # Evolución mensual, últimos 6 meses (B4).
    evolucion_mensual = []
    try:
        evolucion_mensual = metricas_mod.obtener_evolucion_mensual(g.usuario_id, g.cuenta_id, access_token, meses=6)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error calculando evolución mensual: {e}")

    # Envíos Flex del período: los que siguen sin zona no tienen su costo de entrega en la ganancia.
    flex_resumen = None
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            flex_resumen = flex.resumen_periodo(conexion.cursor(), g.cuenta_id, fecha_desde, fecha_hasta)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error resumiendo envíos Flex: {e}")

    # Lo que más vende y cómo se reparten los márgenes: salen de los modelos consolidados (promedios ponderados reales)
    top_facturacion, top_unidades, distribucion_margenes, modelos_pierden = [], [], [], 0
    try:
        cons = datos["consolidados"]

        # `consolidados` ya viene por MODELO (los talles sumados, metricas.consolidar_por_modelo): lo que importa es qué producto vende, no qué talle
        modelos = [{"titulo": c["titulo"], "thumbnail": c.get("thumbnail"), "facturado": c["raw"]["total_facturado"], "unidades": c["unidades"]} for c in cons]

        def _top(clave, formato):
            ordenados = sorted(modelos, key=lambda c: -clave(c))[:6]
            maximo = clave(ordenados[0]) if ordenados else 0
            return [{"titulo": c["titulo"], "thumbnail": c["thumbnail"], "valor_f": formato(clave(c)),
                     "pct_barra": max(round(clave(c) / maximo * 100), 4) if maximo > 0 else 0} for c in ordenados if clave(c) > 0]

        top_facturacion = _top(lambda c: c["facturado"], lambda x: formatear_moneda(x).split(",")[0])
        top_unidades = _top(lambda c: c["unidades"], lambda x: f"{int(x)} u.")

        tramos = [("Pierden plata", None, 0, "danger"), ("0 a 10%", 0, 10, "warn"), ("10 a 20%", 10, 20, "info"), ("20 a 30%", 20, 30, "ok"),
                  ("30 a 40%", 30, 40, "ok"), ("40 a 50%", 40, 50, "ok"), ("Más de 50%", 50, None, "ok")]
        margenes = [(c["raw"]["neto_total"] / c["raw"]["total_facturado"] * 100) if c["raw"]["total_facturado"] else 0 for c in cons]
        for etiqueta, desde, hasta, tono in tramos:
            cantidad = sum(1 for m in margenes if (desde is None or m >= desde) and (hasta is None or m < hasta))
            distribucion_margenes.append({"etiqueta": etiqueta, "cantidad": cantidad, "tono": tono,
                                          "pct": round(cantidad / len(margenes) * 100) if margenes else 0})
        modelos_pierden = sum(1 for m in margenes if m < 0)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error armando top de productos y distribución de márgenes: {e}")

    # Ganancia por unidad (B8).
    total_unidades_periodo = sum(v["cantidad"] for v in datos["ventas"])
    ganancia_por_unidad = formatear_moneda(datos["resumen"]["raw"]["ganancia_neta"] / total_unidades_periodo) if total_unidades_periodo > 0 else None

    # Clientes: retención y forma de pago del período (C1-C4).
    analitica_clientes = None
    try:
        analitica_clientes = metricas_mod.obtener_analitica_clientes(g.usuario_id, fecha_desde, fecha_hasta, g.cuenta_id)
    except Exception as e:
        print(f"[Métricas] ⚠️ Error calculando analítica de clientes: {e}")

    # Concentración de la ganancia (E2) — Pareto: solo entre los
    # modelos que SÍ dejan plata (los que pierden son un problema de
    # catálogo aparte, mezclarlos distorsiona la curva acumulada).
    pareto_ganancia = None
    try:
        ganadores = sorted(
            [c for c in datos["consolidados"] if c["raw"]["neto_total"] > 0],
            key=lambda c: -c["raw"]["neto_total"]
        )
        ganancia_total_positiva = sum(c["raw"]["neto_total"] for c in ganadores)
        if ganadores and ganancia_total_positiva > 0:
            acumulado = 0.0
            productos_80 = 0
            serie_pareto = []
            for i, c in enumerate(ganadores):
                acumulado += c["raw"]["neto_total"]
                pct_acumulado = round(acumulado / ganancia_total_positiva * 100, 1)
                serie_pareto.append({"titulo": c["titulo"], "ganancia": round(c["raw"]["neto_total"], 2), "pct_acumulado": pct_acumulado})
                if productos_80 == 0 and pct_acumulado >= 80:
                    productos_80 = i + 1
            pareto_ganancia = {
                "productos_80": productos_80 or len(ganadores), "total_productos": len(ganadores),
                "serie": serie_pareto[:15],
            }
    except Exception as e:
        print(f"[Métricas] ⚠️ Error calculando concentración de ganancia: {e}")

    return render_template(
        "metricas.html", cobertura_costos=cobertura_costos, ventas=datos["ventas"], consolidados=datos["consolidados"],
        resumen=datos["resumen"], ads_disponible=datos["ads_disponible"],
        gasto_ads_total_periodo=datos["gasto_ads_total_periodo"], posventa=datos["posventa"],
        comparacion_anterior=datos["comparacion_anterior"],
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        punto_equilibrio=punto_equilibrio, canales_envio=canales_envio,
        factura_meli=factura_meli, evolucion_mensual=evolucion_mensual,
        total_unidades_periodo=total_unidades_periodo, ganancia_por_unidad=ganancia_por_unidad,
        analitica_clientes=analitica_clientes, pareto_ganancia=pareto_ganancia, flex_resumen=flex_resumen, flex_reintegro=flex.REINTEGRO_MELI,
        top_facturacion=top_facturacion, top_unidades=top_unidades, distribucion_margenes=distribucion_margenes, modelos_pierden=modelos_pierden,
        active_nav="metricas"
    )


@app.route("/metricas/exportar_excel")
@login_requerido
def metricas_exportar_excel():
    """Balance de rentabilidad del período como .xlsx — item pendiente #3."""
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    fecha_hasta = request.args.get("fecha_hasta") or hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (hoy_argentina() - timedelta(days=30)).strftime("%Y-%m-%d")
    datos = metricas_mod.calcular_ganancia_real(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)
    buffer = metricas_mod.generar_excel_balance(datos, fecha_desde, fecha_hasta)

    return send_file(
        buffer, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True, download_name=f"balance_ganancia_real_{fecha_desde}_a_{fecha_hasta}.xlsx"
    )


@app.route("/promociones")
@login_requerido
def promociones_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    seller_id = fila[0] if fila else None

    campanias = promociones_mod.obtener_promociones_usuario(access_token, seller_id) if seller_id else []
    campanias_activas = [c for c in campanias if c.get("status") in ("started", "active")]
    campanias_vista = promociones_mod.formatear_campanias_para_vista(campanias_activas)
    hay_cofinanciamiento = any(c["meli_percent"] is not None for c in campanias_vista)

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_meli, titulo, precio, precio_original, thumbnail FROM productos_padre
            WHERE estado = 'active' AND precio_original IS NOT NULL AND precio_original > precio
        """)
        con_descuento = [
            {"id": r[0], "titulo": r[1], "thumbnail": r[4], "precio_formateado": formatear_moneda(r[2]),
             "precio_original_formateado": formatear_moneda(r[3]), "descuento_pct": round((1 - float(r[2]) / float(r[3])) * 100)}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT id_meli, titulo, precio, precio_costo FROM productos_padre WHERE estado = 'active' ORDER BY titulo")
        catalogo_promo = [{"id": r[0], "titulo": r[1], "precio": r[2], "precio_costo": r[3]} for r in cursor.fetchall()]

        impacto_promociones = promociones_mod.obtener_impacto_promociones(cursor)
        sugerencias_promocion = promociones_mod.sugerir_candidatos_promocion(cursor)
        promociones_por_vencer = promociones_mod.obtener_promociones_por_vencer(cursor)
        cupones = promociones_mod.obtener_cupones(cursor, g.cuenta_id)

    return render_template(
        "promociones.html", campanias=campanias_vista, hay_cofinanciamiento=hay_cofinanciamiento, con_descuento=con_descuento,
        catalogo=catalogo_promo, ofertas_relampago=[],
        impacto_promociones=impacto_promociones, sugerencias_promocion=sugerencias_promocion,
        promociones_por_vencer=promociones_por_vencer, cupones=cupones, active_nav="promociones"
    )


@app.route("/promociones/crear_descuento", methods=["POST"])
@login_requerido
@auditar("descuento_crear")
def crear_descuento():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    id_meli = request.form.get("id_meli")
    try:
        deal_price = float(request.form.get("deal_price"))
    except (TypeError, ValueError):
        return redirect(_con_aviso("/promociones", "Escribí el precio del descuento antes de crearlo.", "error"))
    fecha_desde = request.form.get("fecha_desde")
    fecha_hasta = request.form.get("fecha_hasta")

    ok, detalle = promociones_mod.crear_descuento_individual(access_token, id_meli, deal_price, fecha_desde, fecha_hasta)
    if not ok:
        # Antes se ignoraba el rechazo y se volvía a Promociones como si el descuento se hubiera creado
        return redirect(_con_aviso("/promociones", detalle, "error"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT titulo, precio FROM productos_padre WHERE id_meli = %s", (id_meli,))
        fila_producto = cursor.fetchone()
        if fila_producto:
            promociones_mod.registrar_inicio_promocion(cursor, g.cuenta_id, id_meli, fila_producto[0], fila_producto[1], deal_price, fecha_hasta)
    return redirect(_con_aviso("/promociones", "Listo: el descuento quedó creado en Mercado Libre.", "success"))


@app.route("/promociones/eliminar_descuento/<id_meli>", methods=["POST"])
@login_requerido
@auditar("descuento_eliminar")
def eliminar_descuento(id_meli):
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    ok, detalle = promociones_mod.eliminar_promocion_item(access_token, id_meli, "PRICE_DISCOUNT")
    if not ok:
        # Si Mercado Libre no lo eliminó, el descuento sigue activo allá: no se lo da por cerrado acá
        return redirect(_con_aviso("/promociones", detalle, "error"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        promociones_mod.cerrar_promocion_activa(cursor, id_meli)
    return redirect(_con_aviso("/promociones", "Listo: el descuento se eliminó en Mercado Libre.", "success"))


@app.route("/tendencias")
@login_requerido
def tendencias_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            # Las tendencias son las de las categorías específicas donde vende la cuenta; sin categorías todavía, las del rubro raíz.
            del_catalogo = tendencias_mod.obtener_tendencias_del_catalogo(access_token, cursor, g.cuenta_id)
            if del_catalogo:
                category_id, categoria_nombre = None, None
                lista, categorias_tendencia = del_catalogo["lista"], del_catalogo["categorias"]
            else:
                category_id, categoria_nombre = tendencias_mod.obtener_categoria_principal(access_token, g.cuenta_id, cursor)
                lista = tendencias_mod.obtener_tendencias(access_token, category_id=category_id, palabras_del_rubro=None if category_id else tendencias_mod.palabras_del_catalogo(cursor))
                categorias_tendencia = []
            relevantes = [t for t in lista if t.get("relevante")]
            resto = [] if (category_id or del_catalogo) else [t for t in lista if not t.get("relevante")]

            oportunidades = tendencias_mod.cruzar_tendencias_con_catalogo(relevantes, cursor)
            terminos_oportunidad = {o["termino"]: o for o in oportunidades}

            canibalismo = tendencias_mod.detectar_canibalismo(cursor)

            keywords_de_hoy = [t.get("keyword") for t in lista if t.get("keyword")]
            emergentes = tendencias_mod.registrar_y_detectar_emergentes(cursor, g.cuenta_id, keywords_de_hoy)

            seo_scores = tendencias_mod.calcular_seo_scores_catalogo(cursor, relevantes)
            coincide_con_competencia = tendencias_mod.cruzar_tendencias_con_competencia(relevantes, cursor)
            calendario_estacional = tendencias_mod.obtener_calendario_estacional()

            # Aseguramos que la categoría principal quede en seguimiento
            # automático — así el resumen de arriba y la alerta de Logros
            # tienen algo para comparar apenas empiecen a acumularse
            # snapshots (el primer día no hay historial todavía, es honesto).
            categoria_foco_id, categoria_foco_nombre = tendencias_mod.obtener_categoria_especifica(access_token, g.cuenta_id, cursor)
            categoria_foco_id = categoria_foco_id or category_id
            categoria_foco_nombre = categoria_foco_nombre or categoria_nombre
            tendencias_mod.asegurar_seguimiento_categoria_principal(cursor, g.cuenta_id, categoria_foco_id, categoria_foco_nombre)
            seguimientos = tendencias_mod.listar_seguimientos_con_historial(cursor, g.cuenta_id)

    except Exception as e:
        # Esta ruta encadena ~10 pasos (categoría, tendencias de MeLi,
        # cruces con catálogo/competencia, seguimiento histórico) — con
        # todo eso sin red de contención, cualquier tropiezo puntual (un
        # dato inesperado, un hipo de la API de MeLi) tumbaba la página
        # entera con un 500 crudo. Mejor avisar y dejar reintentar.
        print(f"[Tendencias] ❌ Error armando la página: {e}")
        return "No pudimos armar la página de Tendencias ahora mismo. Probá recargar en un rato — si sigue pasando, avisanos.", 502

    # Fuera del `with`: son llamadas a MeLi (lentas) y no tocan la base — no hay
    # por qué mantener una conexión del pool ocupada mientras se resuelven.
    resumen_categoria_principal = tendencias_mod.resumen_categoria(access_token, categoria_foco_id) if categoria_foco_id else None

    for t in relevantes:
        opo = terminos_oportunidad.get(t.get("keyword"))
        t["es_oportunidad"] = opo is not None
        if opo:
            t["id_meli_sugerido"] = opo["id_meli_sugerido"]
            t["titulo_sugerido"] = opo["titulo_sugerido"]
        t["es_emergente"] = t.get("keyword") in emergentes

    return render_template(
        "tendencias.html", relevantes=relevantes, resto=resto, canibalismo=canibalismo,
        seo_scores=seo_scores, coincide_con_competencia=coincide_con_competencia,
        calendario_estacional=calendario_estacional, categoria_nombre=categoria_nombre, categorias_tendencia=categorias_tendencia,
        category_id_principal=category_id, categoria_foco_nombre=categoria_foco_nombre, seguimientos=seguimientos,
        resumen_categoria_principal=resumen_categoria_principal, active_nav="tendencias"
    )


@app.route("/api/tendencias/explorar_demanda")
@login_requerido
def api_tendencias_explorar_demanda():
    termino = request.args.get("q", "").strip()
    category_id = request.args.get("category_id", "").strip() or None
    if not termino and not category_id:
        return jsonify({"error": "Escribí un término o elegí una categoría para buscar."})
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Tu cuenta de Mercado Libre está desconectada — reconectala para usar el explorador."})
    resultado = tendencias_mod.explorar_mercado(access_token, termino=termino, category_id=category_id)
    return jsonify(resultado)


@app.route("/api/tendencias/categorias_raiz")
@login_requerido
def api_tendencias_categorias_raiz():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify([])
    return jsonify(tendencias_mod.obtener_categorias_raiz(access_token))


@app.route("/api/tendencias/subcategorias")
@login_requerido
def api_tendencias_subcategorias():
    category_id = request.args.get("category_id", "").strip()
    if not category_id:
        return jsonify({"error": "Falta la categoría."}), 400
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None
    rama = tendencias_mod.obtener_rama_categoria(category_id, access_token)
    if not rama:
        return jsonify({"error": "No se pudo consultar esa categoría."}), 502
    return jsonify(rama)


@app.route("/api/tendencias/seguir", methods=["POST"])
@login_requerido
def api_tendencias_seguir():
    datos = request.get_json(silent=True) or {}
    tipo = datos.get("tipo")
    valor = (datos.get("valor") or "").strip()
    etiqueta = (datos.get("etiqueta") or valor).strip()
    if tipo not in ("termino", "categoria") or not valor:
        return jsonify({"ok": False, "detalle": "Datos inválidos."}), 400
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        seguimiento_id = tendencias_mod.agregar_seguimiento(cursor, g.cuenta_id, tipo, valor, etiqueta)
    return jsonify({"ok": True, "id": seguimiento_id})


@app.route("/api/tendencias/dejar_de_seguir/<int:seguimiento_id>", methods=["POST"])
@login_requerido
def api_tendencias_dejar_de_seguir(seguimiento_id):
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        eliminado = tendencias_mod.eliminar_seguimiento(cursor, g.cuenta_id, seguimiento_id)
    return jsonify({"ok": eliminado})


@app.route("/api/tendencias/estimar_margen")
@login_requerido
def api_tendencias_estimar_margen():
    category_id = request.args.get("category_id", "").strip()
    try:
        precio = float(request.args.get("precio", ""))
    except (ValueError, TypeError):
        return jsonify({"error": "Precio inválido."}), 400
    try:
        costo_fabricacion = float(request.args.get("costo", "")) if request.args.get("costo") else None
    except (ValueError, TypeError):
        costo_fabricacion = None
    if not category_id or precio <= 0:
        return jsonify({"error": "Faltan datos (categoría y precio)."}), 400
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Tu cuenta de MeLi está desconectada."}), 401
    resultado = tendencias_mod.estimar_margen_categoria(access_token, category_id, precio, costo_fabricacion)
    if not resultado:
        return jsonify({"error": "No se pudo estimar el margen para esta categoría."}), 502
    return jsonify(resultado)


@app.route("/logros")
@login_requerido
def logros_vista():
    import db
    headers = None
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
    except token_manager.CuentaDesconectada:
        pass

    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            resultado = logros_mod.obtener_logros(cursor, g.cuenta_id, headers)
    except Exception as e:
        print(f"[Logros] ❌ Error armando la página: {e}")
        return "No pudimos armar la página de Logros ahora mismo. Probá recargar en un rato — si sigue pasando, avisanos.", 502

    conteo_por_prioridad = {"urgente": 0, "importante": 0, "opcional": 0}
    for m in resultado["misiones"]:
        conteo_por_prioridad[m["prioridad"]] = conteo_por_prioridad.get(m["prioridad"], 0) + 1

    return render_template(
        "logros.html", misiones=resultado["misiones"], mensaje_todo_bien=resultado["mensaje_todo_bien"],
        mensaje_coach=resultado.get("mensaje_coach"), coach_pendiente=resultado.get("coach_pendiente", False),
        conteo_por_prioridad=conteo_por_prioridad,
        logros_resueltos=resultado.get("logros_resueltos", []), recien_resueltas=resultado.get("recien_resueltas", 0),
        active_nav="logros"
    )


@app.route("/api/logros/coach")
@login_requerido
def api_logros_coach():
    """Mensaje del coach de IA, pedido aparte para que Logros cargue al instante (la IA tarda segundos)."""
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        misiones_base = logros_mod._detectar_misiones_base(cursor, g.cuenta_id)
    # La llamada a la IA va DESPUÉS de soltar la conexión del pool
    return jsonify({"mensaje": logros_mod.generar_y_cachear_mensaje_coach(g.usuario_id, g.cuenta_id, misiones_base)})


@app.route("/embudo_conversion")
@login_requerido
def embudo_conversion_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    headers = {"Authorization": f"Bearer {access_token}"}

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        embudo = embudo_mod.calcular_embudo_conversion(headers, g.cuenta_id, cursor)
        zombies = embudo_mod.detectar_publicaciones_zombie(headers, g.cuenta_id, cursor)

    return render_template("embudo_conversion.html", embudo=embudo, zombies=zombies, active_nav="embudo_conversion")


@app.route("/reputacion")
@login_requerido
def reputacion_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    if not fila:
        return "No se encontró tu cuenta.", 401

    datos = reputacion_mod.obtener_reputacion(access_token, fila[0])

    # MeLi solo expone un número agregado de "canceladas" en su reputación
    # oficial (agrupa cancelaciones, devoluciones y ventas no completadas
    # en un solo bucket — no lo separan ni en su propia API). Acá SÍ
    # tenemos el desglose real, porque incidencias_posventa lo trackea
    # por tipo desde que arrancamos a sincronizarlo (devoluciones_sync.py)
    # — se muestra como un panel aparte, no mezclado con el número
    # oficial de MeLi, porque cubren ventanas de tiempo distintas.
    incidencias_por_tipo = {"devoluciones": 0, "reclamos": 0, "reclamos_sin_impacto": 0, "cancelaciones": 0}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        # Los reclamos se separan según Mercado Libre: los que afectan la reputación y los que no (p. ej. un "no lo quiero" en mediación)
        cursor.execute(f"""
            SELECT tipo, COUNT(*), COUNT(*) FILTER (WHERE NOT {SQL_RECLAMO_AFECTA})
            FROM incidencias_posventa GROUP BY tipo
        """)
        conteo_tipo = {tipo: (total, sin_impacto) for tipo, total, sin_impacto in cursor.fetchall()}
    incidencias_por_tipo["devoluciones"] = conteo_tipo.get("return", (0, 0))[0]
    reclamos_total, reclamos_sin = conteo_tipo.get("claim", (0, 0))
    incidencias_por_tipo["reclamos"] = reclamos_total - reclamos_sin
    incidencias_por_tipo["reclamos_sin_impacto"] = reclamos_sin
    incidencias_por_tipo["cancelaciones"] = conteo_tipo.get("cancelacion", (0, 0))[0]

    return render_template("reputacion.html", rep=datos, incidencias_por_tipo=incidencias_por_tipo, active_nav="reputacion")


@app.route("/competencia")
@login_requerido
def competencia_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        productos = espia_competencia.obtener_panorama_competencia(cursor, g.cuenta_id)
        ids_propios = espia_competencia.ids_publicaciones_propias(cursor)
        mis_catalogo = catalogo_ganar.obtener(cursor, g.cuenta_id)
    sugerencias = espia_competencia.sugerir_productos_propios(access_token, ids_propios, {p["id_producto"] for p in productos})
    return render_template("competencia.html", productos=productos, sugerencias=sugerencias, mis_catalogo=mis_catalogo, active_nav="competencia")


@app.route("/api/competencia/agregar", methods=["POST"])
@login_requerido
def api_competencia_agregar():
    import db
    datos = request.get_json(silent=True) or {}
    texto = (datos.get("producto") or "").strip()
    alias = (datos.get("alias") or "").strip()[:80]
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "mensaje": "Tu cuenta de Mercado Libre está desconectada — reconectala para seguir productos."}), 401
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        ok, mensaje = espia_competencia.agregar_competidor(cursor, access_token, g.cuenta_id, texto, alias)
    return jsonify({"ok": ok, "mensaje": mensaje}), (200 if ok else 400)


@app.route("/competencia/eliminar/<id_producto>", methods=["POST"])
@login_requerido
def competencia_eliminar(id_producto):
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        espia_competencia.eliminar_competidor(cursor, g.cuenta_id, id_producto)
    return redirect("/competencia")


@app.route("/comparador_logistica")
@login_requerido
def comparador_logistica_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    fecha_hasta = request.args.get("fecha_hasta") or hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (hoy_argentina() - timedelta(days=30)).strftime("%Y-%m-%d")

    resultado, cantidad_cargos_almacenamiento = comparador_logistica_mod.calcular_comparacion(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)

    return render_template(
        "comparador_logistica.html", resultado=resultado, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        cantidad_cargos_almacenamiento=cantidad_cargos_almacenamiento, active_nav="comparador_logistica"
    )


@app.route("/publicidad")
@login_requerido
def publicidad_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    fecha_hasta = request.args.get("fecha_hasta") or hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (hoy_argentina() - timedelta(days=13)).strftime("%Y-%m-%d")

    datos = publicidad_mod.calcular_datos_publicidad(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)
    if datos is None:
        return render_template("publicidad.html", ads_disponible=False, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, active_nav="publicidad")

    return render_template(
        "publicidad.html", ads_disponible=True, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        active_nav="publicidad", **datos
    )


@app.route("/sincronizar_todo", methods=["POST"])
@login_requerido
def sincronizar_manual():
    """Arranca la sincronización en segundo plano y responde enseguida; el front consulta /api/estado_sincronizacion hasta que termina."""
    if sincronizador.sincronizacion_en_curso(g.cuenta_id):
        return jsonify({"status": "ya_en_curso"})
    _en_segundo_plano(sincronizador.sincronizar_todo, g.usuario_id, g.cuenta_id)
    return jsonify({"status": "iniciado"})


@app.route("/api/curva_talles")
@login_requerido
def api_curva_talles():
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        resultado = analisis_stock.evaluar_curva_talles(cursor)
    return jsonify(resultado)


@app.route("/api/buscar")
@login_requerido
def api_buscar():
    """
    Búsqueda de publicaciones para el comando rápido (Ctrl+K) — el
    frontend ya la llamaba desde antes, pero nunca había tenido
    backend: escribir un nombre de producto no devolvía nada, sin
    ningún error visible (el catch de la búsqueda solo loguea a
    consola).
    """
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_meli, titulo FROM productos_padre
            WHERE titulo ILIKE %s OR id_meli ILIKE %s
            ORDER BY CASE WHEN estado = 'active' THEN 0 ELSE 1 END, titulo
            LIMIT 8
        """, (f"%{q}%", f"%{q}%"))
        filas = cursor.fetchall()
    return jsonify([{"id": f[0], "titulo": f[1]} for f in filas])


@app.route("/api/oportunidades_seo")
@login_requerido
def api_oportunidades_seo():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify([])

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        del_catalogo = tendencias_mod.obtener_tendencias_del_catalogo(access_token, cursor, g.cuenta_id)
        if del_catalogo:
            lista = del_catalogo["lista"]
        else:
            category_id, _ = tendencias_mod.obtener_categoria_principal(access_token, g.cuenta_id, cursor)
            lista = tendencias_mod.obtener_tendencias(access_token, category_id=category_id, palabras_del_rubro=None if category_id else tendencias_mod.palabras_del_catalogo(cursor))
        relevantes = [t for t in lista if t.get("relevante")]
        oportunidades = tendencias_mod.cruzar_tendencias_con_catalogo(relevantes, cursor)
    return jsonify(oportunidades)


@app.route("/onboarding")
@login_requerido
def onboarding_vista():
    return render_template(
        "onboarding.html", opciones_prioridad=onboarding.OPCIONES_PRIORIDAD,
        opciones_experiencia=onboarding.OPCIONES_EXPERIENCIA, opciones_pantalla=onboarding.OPCIONES_PANTALLA
    )


@app.route("/onboarding/guardar", methods=["POST"])
@login_requerido
def onboarding_guardar():
    prioridades = request.form.getlist("prioridad_principal")
    experiencia = request.form.get("experiencia_meli")
    pantalla = request.form.get("pantalla_preferida")
    ok = onboarding.guardar_respuestas(g.usuario_id, prioridades, experiencia, pantalla)
    if not ok:
        return render_template(
            "onboarding.html", opciones_prioridad=onboarding.OPCIONES_PRIORIDAD,
            opciones_experiencia=onboarding.OPCIONES_EXPERIENCIA, opciones_pantalla=onboarding.OPCIONES_PANTALLA,
            error="Elegí una opción en cada pregunta antes de continuar."
        )
    session["mostrar_tutorial"] = True
    return redirect(url_for("landing"))


@app.route("/onboarding/tutorial_visto", methods=["POST"])
@login_requerido
def onboarding_tutorial_visto():
    session.pop("mostrar_tutorial", None)
    return jsonify({"ok": True})


@app.route("/api/onboarding/checklist")
@login_requerido
def api_onboarding_checklist():
    try:
        return jsonify(onboarding.obtener_checklist_progreso(g.usuario_id, g.cuenta_id))
    except Exception as e:
        print(f"[Onboarding] ⚠️ Error en checklist: {e}")
        return jsonify({"pasos": [], "completos": 0, "total": 0, "porcentaje": 100})


@app.route("/api/estado_sincronizacion")
@login_requerido
def api_estado_sincronizacion():
    en_curso = sincronizador.sincronizacion_en_curso(g.cuenta_id)
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT sincronizacion_inicial_completa, EXTRACT(EPOCH FROM (now() - conectada_en)) / 60 FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
        if fila and fila[0]:
            return jsonify({"lista": True, "en_curso": en_curso})
        minutos = float(fila[1] or 0) if fila else 0.0
        cursor.execute("SELECT COUNT(*) FROM productos_padre WHERE cuenta_id = %s", (g.cuenta_id,))
        n_productos = cursor.fetchone()[0] or 0
        cursor.execute("SELECT COUNT(*) FROM ventas WHERE cuenta_id = %s", (g.cuenta_id,))
        n_ventas = cursor.fetchone()[0] or 0
    if n_productos == 0:
        etapa = "productos"
    elif n_ventas == 0:
        etapa = "ventas"
    else:
        etapa = "calculando"
    # Solo si ya pasó un rato se comprueba el permiso (renueva el token: no se hace en cada consulta de la espera normal)
    desconectada = False
    if minutos >= sincronizador.MINUTOS_SYNC_ATASCADA:
        try:
            token_manager.asegurar_token_valido(g.cuenta_id)
        except token_manager.CuentaDesconectada:
            desconectada = True
    diagnostico = sincronizador.diagnostico_sync_inicial(minutos, en_curso, desconectada)
    return jsonify({"lista": False, "en_curso": en_curso, "productos": n_productos, "ventas": n_ventas, "etapa": etapa, "diagnostico": diagnostico})


@app.route("/publicacion/<id_meli>/timeline")
@login_requerido
def timeline_publicacion_vista(id_meli):
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT titulo, thumbnail FROM productos_padre WHERE id_meli = %s", (id_meli,))
        fila = cursor.fetchone()
        titulo = fila[0] if fila else id_meli
        thumbnail = fila[1] if fila else None
        eventos = timeline_publicacion.obtener_timeline(cursor, id_meli, access_token)

    return render_template(
        "timeline_publicacion.html", id_meli=id_meli, titulo=titulo, thumbnail=thumbnail,
        eventos=eventos, active_nav="stock"
    )


@app.route("/publicacion/<id_meli>/exportar_red")
@login_requerido
def exportar_publicacion_red(id_meli):
    import os
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT titulo, precio, thumbnail FROM productos_padre WHERE id_meli = %s", (id_meli,))
        fila = cursor.fetchone()

    if not fila:
        return "Publicación no encontrada.", 404

    titulo, precio, thumbnail = fila
    url_foto = thumbnail

    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
        resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, timeout=8)
        if resp.status_code == 200:
            fotos = resp.json().get("pictures", [])
            if fotos:
                url_foto = fotos[0].get("url", url_foto)
    except Exception as e:
        print(f"[Exportador] ⚠️ No se pudo traer la foto de la publicación: {e}")

    if not url_foto:
        return "Esta publicación no tiene foto disponible para exportar.", 400

    nombre_archivo = f"post_{id_meli}.png"
    os.makedirs("exports", exist_ok=True)
    ruta_salida = os.path.join("exports", nombre_archivo)
    resultado = exportador_redes.generar_imagen_publicacion(url_foto, titulo, formatear_moneda(precio), ruta_salida=ruta_salida)

    if not resultado:
        return "No se pudo generar la imagen — puede que la foto no se haya podido descargar.", 502

    return send_file(resultado, mimetype="image/png", as_attachment=True, download_name=nombre_archivo)


@app.route("/monotributo")
@login_requerido
def monotributo_vista():
    resultado = monotributo.evaluar_categoria(g.usuario_id, g.cuenta_id)
    return render_template("monotributo.html", **resultado, active_nav="monotributo")


@app.route("/monotributo/declarar", methods=["POST"])
@login_requerido
@auditar("monotributo_declarar")
def monotributo_declarar():
    categoria = request.form.get("categoria_monotributo") or None
    monotributo.guardar_categoria_declarada(g.usuario_id, g.cuenta_id, categoria)
    # Monotributo ahora vive como sección inline del Dashboard (ya no
    # está en el menú) — volver ahí después de guardar, no a la página
    # standalone.
    return redirect(url_for("dashboard_personalizable"))


@app.route("/api/costos_chat", methods=["POST"])
@login_requerido
def api_costos_chat():
    datos = request.get_json(silent=True) or {}
    historial = datos.get("historial", [])
    if not historial or not isinstance(historial, list):
        return jsonify({"accion": "error", "mensaje": "Faltó el mensaje."}), 400
    resultado = costos_chat.procesar_mensaje(historial, g.usuario_id, g.cuenta_id)
    return jsonify(resultado)


@app.route("/api/costos_chat/confirmar", methods=["POST"])
@login_requerido
@auditar("costos_chat")
def api_costos_chat_confirmar():
    datos = request.get_json(silent=True) or {}
    propuestas = datos.get("propuestas")
    costos_productos = datos.get("costos_productos")
    if not propuestas and not costos_productos:
        return jsonify({"ok": False, "error": "Falta la propuesta."}), 400
    ok, resultado = costos_chat.confirmar_y_guardar(g.usuario_id, g.cuenta_id, propuestas, costos_productos)
    if not ok:
        return jsonify({"ok": False, "error": resultado})
    return jsonify({"ok": True, "error": None, "gastos": resultado["gastos"], "publicaciones": resultado["publicaciones"]})


@app.route("/api/chat_ia", methods=["POST"])
@login_requerido
def api_chat_ia():
    """
    El Asistente de Operaciones (botón flotante) — existía en el
    frontend desde antes pero nunca había tenido backend; el fetch
    siempre daba 404 y el usuario veía "Error de comunicación.".
    """
    datos = request.get_json(silent=True) or {}
    pregunta = datos.get("pregunta") or ""
    try:
        respuesta = chat_ia.responder_pregunta(g.usuario_id, pregunta, g.cuenta_id)
    except Exception as e:
        print(f"[ChatIA] ⚠️ Error respondiendo: {e}")
        respuesta = "Tuve un problema respondiendo eso — probá de nuevo en un rato."
    return jsonify({"respuesta": respuesta})


@app.route("/facturacion")
@login_requerido
def facturacion_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    try:
        periodos = facturacion.obtener_periodos(access_token, g.cuenta_id)
    except Exception as e:
        print(f"[Facturación] ❌ {type(e).__name__}: {e}")
        return "No se pudo traer tus períodos de facturación de Mercado Libre ahora mismo. Probá de nuevo en un rato.", 502

    key_seleccionada = request.args.get("key") or (periodos[0].get("key") if periodos else None)
    periodo_actual = next((p for p in periodos if p.get("key") == key_seleccionada), None)

    resumen = None
    if key_seleccionada:
        try:
            resumen = facturacion.obtener_resumen_periodo(access_token, g.cuenta_id, key_seleccionada)
        except Exception as e:
            print(f"[Facturación] ⚠️ Error trayendo el resumen del período: {e}")

    cargos_dict = {}
    total_cargos = 0.0
    pagos_cobrados = 0.0
    percepciones_total = 0.0
    bill_includes = {}

    if resumen and isinstance(resumen, dict):
        bill_includes = resumen.get("bill_includes", {})
        for c in bill_includes.get("charges", []):
            categoria = (c.get("group_description") or "Otros cargos").strip()
            monto = c.get("amount") or 0.0
            cargos_dict[categoria] = cargos_dict.get(categoria, 0.0) + monto
            total_cargos += monto
        for b in bill_includes.get("bonuses", []):
            categoria = (b.get("group_description") or "Bonificaciones y anulaciones").strip()
            monto = b.get("amount") or 0.0
            cargos_dict[categoria] = cargos_dict.get(categoria, 0.0) + monto
            total_cargos += monto
        percepciones_total = bill_includes.get("total_perception", 0.0) or 0.0
        pago_info = resumen.get("payment_collected", {})
        pagos_cobrados = pago_info.get("operation_discount", 0.0) or 0.0

    cargos = sorted(
        [{"label": k, "monto": v, "monto_formateado": formatear_moneda(v)} for k, v in cargos_dict.items()],
        key=lambda x: -abs(x["monto"])
    )

    pendiente = periodo_actual.get("unpaid_amount", 0.0) if periodo_actual else 0.0
    total_adeudado = round(pendiente + percepciones_total, 2)

    facturado_bruto = 0.0
    ganancia_bruta_real = 0.0
    ganancia_neta_final = 0.0
    gastos_periodo = 0.0
    barra_segmentos = None
    waterfall_facturacion = None

    if periodo_actual:
        fecha_desde_periodo = periodo_actual.get("period", {}).get("date_from")
        fecha_hasta_periodo = periodo_actual.get("period", {}).get("date_to")

        if fecha_desde_periodo and fecha_hasta_periodo:
            import db
            with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("SELECT COALESCE(SUM(precio_venta*cantidad),0) FROM ventas WHERE fecha_venta BETWEEN %s AND %s", (fecha_desde_periodo, fecha_hasta_periodo))
                facturado_bruto = float(cursor.fetchone()[0] or 0.0)
                cursor.execute("SELECT COALESCE(SUM(monto),0) FROM gastos_operativos WHERE fecha BETWEEN %s AND %s", (fecha_desde_periodo, fecha_hasta_periodo))
                gastos_periodo = float(cursor.fetchone()[0] or 0.0)

            ganancia_bruta_real = round(facturado_bruto - total_cargos, 2)
            ganancia_neta_final = round(ganancia_bruta_real - gastos_periodo, 2)

            if facturado_bruto > 0:
                pct_comision = pct_envios = pct_publicidad = 0.0
                for c in bill_includes.get("charges", []):
                    categoria = (c.get("group_description") or "").lower()
                    monto = c.get("amount") or 0.0
                    if "venta" in categoria: pct_comision += monto
                    elif "env" in categoria: pct_envios += monto
                    elif "public" in categoria: pct_publicidad += monto
                # MeLi no siempre manda group_description usable (para varias
                # cuentas viene vacío y todo cae en "Otros cargos"/"Bonificaciones"
                # del desglose de abajo) — lo que no matcheó ninguna palabra clave
                # NO se descarta ni se cuenta como ganancia: se muestra aparte,
                # para que el total del waterfall siga sumando lo mismo que
                # total_cargos (el número real que ya usa Ganancia Neta Real).
                pct_otros = max(total_cargos - pct_comision - pct_envios - pct_publicidad, 0.0)
                pct_neto = max(facturado_bruto - total_cargos, 0)
                barra_segmentos = {
                    "comision": round((pct_comision / facturado_bruto) * 100, 1),
                    "envios": round((pct_envios / facturado_bruto) * 100, 1),
                    "publicidad": round((pct_publicidad / facturado_bruto) * 100, 1),
                    "otros": round((pct_otros / facturado_bruto) * 100, 1),
                    "neto": round((pct_neto / facturado_bruto) * 100, 1)
                }
                # Mismos montos de arriba, pero en $ y en formato de "cascada"
                # fila por fila (label + barra + monto) — más fácil de leer
                # de un vistazo que el % dentro de una barra apilada sola.
                _max_waterfall = max(facturado_bruto, 1)
                waterfall_facturacion = [
                    {"label": "Facturado bruto", "monto_formateado": "$" + formatear_moneda(facturado_bruto), "pct_ancho": 100, "es_total_inicial": True},
                    {"label": "Comisión MeLi", "monto_formateado": "-$" + formatear_moneda(pct_comision), "pct_ancho": round(pct_comision / _max_waterfall * 100, 1)},
                    {"label": "Envíos", "monto_formateado": "-$" + formatear_moneda(pct_envios), "pct_ancho": round(pct_envios / _max_waterfall * 100, 1)},
                    {"label": "Publicidad", "monto_formateado": "-$" + formatear_moneda(pct_publicidad), "pct_ancho": round(pct_publicidad / _max_waterfall * 100, 1)},
                ]
                if pct_otros > 0.01:
                    waterfall_facturacion.append(
                        {"label": "Otros cargos de MeLi (sin categorizar)", "monto_formateado": "-$" + formatear_moneda(pct_otros), "pct_ancho": round(pct_otros / _max_waterfall * 100, 1)}
                    )
                waterfall_facturacion.append(
                    {"label": "Gastos operativos", "monto_formateado": "-$" + formatear_moneda(gastos_periodo), "pct_ancho": round(gastos_periodo / _max_waterfall * 100, 1)}
                )
                waterfall_facturacion.append(
                    {"label": "Ganancia neta final", "monto_formateado": ("-$" if ganancia_neta_final < 0 else "$") + formatear_moneda(abs(ganancia_neta_final)), "pct_ancho": round(abs(ganancia_neta_final) / _max_waterfall * 100, 1), "es_total_final": True, "es_negativo": ganancia_neta_final < 0}
                )

    periodos_vista = [
        {"key": p.get("key"), "date_from": p.get("period", {}).get("date_from"),
         "date_to": p.get("period", {}).get("date_to"), "en_curso": p.get("period_status") == "OPEN"}
        for p in periodos
    ]

    fuera_de_ganancia, total_fuera_de_ganancia = facturacion.cargos_fuera_de_la_ganancia(resumen)
    return render_template(
        "facturacion.html", periodos=periodos_vista, key_seleccionada=key_seleccionada, cargos=cargos,
        fuera_de_ganancia=fuera_de_ganancia, total_fuera_de_ganancia=total_fuera_de_ganancia,
        total_cargos_formateado=formatear_moneda(total_cargos), pagos_cobrados_formateado=formatear_moneda(pagos_cobrados),
        pendiente_formateado=formatear_moneda(pendiente), percepciones_formateado=formatear_moneda(percepciones_total),
        total_adeudado_formateado=formatear_moneda(total_adeudado),
        facturado_bruto_formateado=formatear_moneda(facturado_bruto),
        ganancia_bruta_formateada=formatear_moneda(ganancia_bruta_real),
        ganancia_neta_formateada=formatear_moneda(ganancia_neta_final),
        ganancia_neta_negativa=ganancia_neta_final < 0,
        rs={"facturado": facturado_bruto, "cargos": total_cargos, "gastos": gastos_periodo, "ganancia_bruta": ganancia_bruta_real,
            "ganancia_neta": ganancia_neta_final, "pendiente": pendiente, "percepciones": percepciones_total,
            "pagos_cobrados": pagos_cobrados, "adeudado": total_adeudado},
        barra_segmentos=barra_segmentos, waterfall_facturacion=waterfall_facturacion, active_nav="facturacion"
    )


@app.route("/historial_precios")
@login_requerido
def historial_precios_vista():
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cambios = historial_precios_mod.obtener_historial_con_impacto(cursor)
    return render_template("historial_precios.html", cambios=cambios, active_nav="historial_precios")


@app.route("/costos")
@login_requerido
def costos_vista():
    fecha_hasta = request.args.get("fecha_hasta") or hoy_argentina().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or hoy_argentina().replace(day=1).strftime("%Y-%m-%d")
    gastos, stats, productos = costos_mod.obtener_datos_costos(g.usuario_id, fecha_desde, fecha_hasta, g.cuenta_id)
    # Los talles de un mismo modelo se cargan juntos. Primero los modelos activos con talles sin costo (lo urgente), después el resto.
    grupos = {}
    for p in productos:
        grupos.setdefault(p["modelo"], []).append(p)
    modelos = sorted(
        ({"modelo": m, "talles": it, "activo": any(x["estado"] == "active" for x in it),
          "sin_costo": sum(1 for x in it if x["estado"] == "active" and not x["precio_costo"])} for m, it in grupos.items()),
        key=lambda gr: (not gr["activo"], -gr["sin_costo"], gr["modelo"])
    )
    flex_config, flex_vista_previa, hay_flex, flex_pendientes_n = {"umbrales": [], "info": None}, {"umbrales": [], "ordenes": 0, "costo_total": 0, "sin_precio": 0}, False, 0
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT COUNT(*) FROM ventas WHERE cuenta_id = %s AND origen = 'meli' AND tipo_logistica = 'self_service'", (g.cuenta_id,))
            hay_flex = (cursor.fetchone()[0] or 0) > 0
            flex_config = flex.obtener_config(cursor, g.cuenta_id)
            # Con Flex y sin zonas sincronizadas todavía: se traen solas de Mercado Libre (la primera vez que se abre esto)
            if hay_flex and flex_config["info"] is None:
                try:
                    access_token = token_manager.asegurar_token_valido(g.cuenta_id)
                    cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
                    flex.sincronizar_con_meli(cursor, g.cuenta_id, access_token, cursor.fetchone()[0])
                    flex_config = flex.obtener_config(cursor, g.cuenta_id)
                except token_manager.CuentaDesconectada:
                    pass
            flex_vista_previa = flex.vista_previa(cursor, g.cuenta_id)
            flex_pendientes_n = flex.contar_pendientes(cursor, g.cuenta_id)
    except Exception as e:
        print(f"[Costos] ⚠️ Error armando el panel de Flex: {e}")
    flex_data = {"umbrales": flex.umbrales_para_vista(flex_config), "zonas": (flex_config["info"] or {}).get("zonas", []),
                 "origen": (flex_config["info"] or {}).get("origen"), "reintegro_pct": int(round(flex.REINTEGRO_MELI * 100)),
                 "vista_previa": flex_vista_previa}
    return render_template("costos.html", gastos=gastos, stats=stats, productos=productos, modelos=modelos, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
                           flex_data=flex_data, flex_pendientes_n=flex_pendientes_n, hay_flex=hay_flex, active_nav="costos")


def _config_flex_json(cursor):
    config = flex.obtener_config(cursor, g.cuenta_id)
    return {"umbrales": flex.umbrales_para_vista(config), "zonas": (config["info"] or {}).get("zonas", []), "origen": (config["info"] or {}).get("origen")}


@app.route("/api/flex/sincronizar", methods=["POST"])
@login_requerido
def api_flex_sincronizar():
    """Trae de Mercado Libre las zonas de cobertura Flex del vendedor y su domicilio de salida."""
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "error": "Tu cuenta de Mercado Libre está desconectada. Reconectala para seguir."}), 401
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        ok, error = flex.sincronizar_con_meli(cursor, g.cuenta_id, access_token, cursor.fetchone()[0])
        if not ok:
            return jsonify({"ok": False, "error": error}), 400
        return jsonify({"ok": True, **_config_flex_json(cursor), "vista_previa": flex.vista_previa(cursor, g.cuenta_id)})


@app.route("/api/flex/umbrales", methods=["POST"])
@login_requerido
@auditar("flex_umbrales")
def api_flex_umbrales():
    """Guarda los umbrales (precio + zonas que cubre cada uno). No toca ninguna venta: devuelve la vista previa de lo que aplicaría."""
    datos = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        ok, error = flex.guardar_umbrales(cursor, g.cuenta_id, datos.get("umbrales"))
        if not ok:
            return jsonify({"ok": False, "error": error}), 400
        return jsonify({"ok": True, **_config_flex_json(cursor), "vista_previa": flex.vista_previa(cursor, g.cuenta_id, bool(datos.get("incluir_valuadas")))})


@app.route("/api/flex/vista_previa")
@login_requerido
def api_flex_vista_previa():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        return jsonify(flex.vista_previa(conexion.cursor(), g.cuenta_id, request.args.get("incluir_valuadas") == "1"))


@app.route("/api/flex/aplicar", methods=["POST"])
@login_requerido
@auditar("flex_aplicar")
def api_flex_aplicar():
    """Aplica los umbrales a los envíos Flex (los sin costo cargado y, si el usuario lo pide, también los ya valuados). Lo confirma el usuario tras ver la vista previa."""
    datos = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        aplicadas = flex.aplicar_automatico(conexion.cursor(), g.cuenta_id, bool(datos.get("incluir_valuadas")))
    return jsonify({"ok": True, "aplicadas": aplicadas})


@app.route("/api/flex/zona", methods=["POST"])
@login_requerido
@auditar("flex_zona")
def api_flex_zona():
    """Elige a mano el umbral de UNA orden Flex (0 = sin costo). Mueve el costo de entrega de esa venta."""
    datos = request.get_json(silent=True) or {}
    try:
        umbral = int(datos.get("umbral"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Umbral inválido."}), 400
    id_orden = str(datos.get("id_orden") or "").strip()
    if not id_orden:
        return jsonify({"ok": False, "error": "Falta la orden."}), 400
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        ok, error = flex.asignar_manual(conexion.cursor(), g.cuenta_id, id_orden, umbral)
    return jsonify({"ok": ok, "error": error}), (200 if ok else 400)


@app.route("/ventas_manuales")
@login_requerido
def ventas_manuales_vista():
    """Registrar ventas por fuera de MeLi (mostrador, canal directo) — entran a Ganancia Real igual que las reales."""
    catalogo = ventas_manuales.obtener_catalogo_para_selector(g.usuario_id, g.cuenta_id)
    recientes = ventas_manuales.obtener_ventas_manuales_recientes(g.usuario_id, g.cuenta_id)
    return render_template(
        "ventas_manuales.html", catalogo=catalogo, ventas=recientes,
        hoy=hoy_argentina().strftime("%Y-%m-%d"), active_nav="ventas_manuales", aviso=session.pop("aviso_ventas_manuales", "")
    )


@app.route("/ventas_manuales/agregar", methods=["POST"])
@login_requerido
@auditar("venta_manual_agregar")
def ventas_manuales_agregar():
    ok, error, aviso = ventas_manuales.registrar_venta_manual(
        g.usuario_id, g.cuenta_id,
        request.form.get("id_variante"), request.form.get("cantidad"),
        request.form.get("precio_venta"), request.form.get("fecha_venta"),
        request.form.get("comprador_nombre", "").strip(),
        descontar_en_meli=request.form.get("descontar_en_meli") == "1",
    )
    if not ok:
        return render_template(
            "ventas_manuales.html",
            catalogo=ventas_manuales.obtener_catalogo_para_selector(g.usuario_id, g.cuenta_id),
            ventas=ventas_manuales.obtener_ventas_manuales_recientes(g.usuario_id, g.cuenta_id),
            hoy=hoy_argentina().strftime("%Y-%m-%d"), active_nav="ventas_manuales", error=error
        ), 400
    session["aviso_ventas_manuales"] = aviso or ""
    return redirect(url_for("ventas_manuales_vista"))


@app.route("/ventas_manuales/eliminar/<int:id_venta>", methods=["POST"])
@login_requerido
@auditar("venta_manual_eliminar")
def ventas_manuales_eliminar(id_venta):
    _, aviso = ventas_manuales.eliminar_venta_manual(g.usuario_id, g.cuenta_id, id_venta)
    session["aviso_ventas_manuales"] = aviso or ""
    return redirect(url_for("ventas_manuales_vista"))


@app.route("/agregar_gasto", methods=["POST"])
@login_requerido
@auditar("gasto_agregar")
def agregar_gasto():
    import db
    concepto = request.form.get("concepto", "").strip()
    categoria = request.form.get("categoria")
    monto = float(request.form.get("monto", 0.0))
    fecha = request.form.get("fecha") or hoy_argentina().strftime("%Y-%m-%d")
    if concepto and monto > 0:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha) VALUES (%s, %s, %s, %s, %s)", (g.cuenta_id, concepto, categoria, monto, fecha))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/guardar_costo_producto/<id_meli>", methods=["POST"])
@login_requerido
@auditar("costo_producto")
def guardar_costo_producto(id_meli):
    import db
    nuevo_costo = float(request.form.get("precio_costo", 0.0))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE id_meli = %s", (nuevo_costo, id_meli))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/guardar_costos_masivo", methods=["POST"])
@login_requerido
@auditar("costos_masivo")
def guardar_costos_masivo():
    import db
    data = request.get_json(silent=True) or {}
    costos_dict = data.get("costos", {})
    if not costos_dict:
        return jsonify({"ok": False, "error": "Nada para guardar"}), 400
    actualizados = 0
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        for id_meli, nuevo_costo in costos_dict.items():
            try:
                costo = float(nuevo_costo)
            except (ValueError, TypeError):
                continue
            # Un costo negativo o "nan"/"inf" no tiene sentido y ensuciaría todos los márgenes
            if not (0 <= costo < 1e12):
                continue
            cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE id_meli = %s", (costo, id_meli))
            actualizados += cursor.rowcount
    return jsonify({"ok": True, "actualizados": actualizados})


@app.route("/eliminar_gasto/<int:id_gasto>", methods=["POST"])
@login_requerido
@auditar("gasto_eliminar")
def eliminar_gasto(id_gasto):
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM gastos_operativos WHERE id = %s", (id_gasto,))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/despacho")
@login_requerido
def despacho_vista():
    import db
    fecha = request.args.get("fecha") or hoy_argentina().strftime("%Y-%m-%d")

    hora_corte = 11
    flex_habilitado = False
    access_token = None
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    seller_id = fila[0] if fila else None

    if access_token and seller_id:
        hora_real = logistica.obtener_horario_corte_hoy(access_token, seller_id, "drop_off")
        if hora_real is not None:
            hora_corte = hora_real
        flex_habilitado = logistica.tiene_flex_habilitado(access_token, "MLA", seller_id)

    offset_horas = 24 - hora_corte
    paquetes, total, listos, cantidad_shipments, tiene_flex = despacho_mod.obtener_paquetes_del_dia(g.usuario_id, g.cuenta_id, access_token, fecha, offset_horas)
    # El chequeo de la API de "¿tenés Flex?" puede fallar por un hipo
    # transitorio y quedar cacheado horas (ver logistica.py) — si hoy
    # mismo hay al menos un envío real de Flex en la lista, eso pesa más
    # que la respuesta de esa API: es evidencia directa de que sí lo tiene.
    flex_habilitado = flex_habilitado or tiene_flex

    umbrales_flex = []
    if tiene_flex:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            umbrales_flex = flex.umbrales_para_vista(flex.obtener_config(conexion.cursor(), g.cuenta_id))

    return render_template(
        "despacho.html", paquetes=paquetes, fecha=fecha, total=total, listos=listos,
        cantidad_shipments=cantidad_shipments, hora_corte=hora_corte,
        flex_habilitado=flex_habilitado, umbrales_flex=umbrales_flex, active_nav="despacho"
    )


@app.route("/despacho/etiquetas_pdf")
@login_requerido
def despacho_etiquetas_pdf():
    """
    Descarga en un solo PDF las etiquetas de envío del día — nunca
    había tenido backend. MeLi ya arma el PDF combinado del lado de
    ellos (shipment_labels con varios ids), así que esto solo reúne
    los shipment_id del día y devuelve ese PDF tal cual, sin generar
    nada acá.
    """
    from io import BytesIO
    fecha = request.args.get("fecha") or hoy_argentina().strftime("%Y-%m-%d")
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    seller_id = fila[0] if fila else None

    hora_corte = 11
    if seller_id:
        hora_real = logistica.obtener_horario_corte_hoy(access_token, seller_id, "drop_off")
        if hora_real is not None:
            hora_corte = hora_real
    offset_horas = 24 - hora_corte

    shipment_ids = despacho_mod.obtener_shipment_ids_del_dia(g.usuario_id, fecha, offset_horas, g.cuenta_id)
    if not shipment_ids:
        return "No hay etiquetas para descargar en esta fecha.", 404

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(
            "https://api.mercadolibre.com/shipment_labels",
            headers=headers,
            params={"shipment_ids": ",".join(str(s) for s in shipment_ids), "response_type": "pdf"},
            timeout=30,
        )
        if resp.status_code != 200:
            print(f"[Etiquetas] MeLi respondió {resp.status_code}")
            return "Mercado Libre no pudo generar las etiquetas ahora mismo. Probá de nuevo en un rato.", 502
    except Exception as e:
        print(f"[Calculadora] ❌ {type(e).__name__}: {e}")
        return "No se pudo consultar Mercado Libre ahora mismo. Probá de nuevo en un rato.", 502

    return send_file(BytesIO(resp.content), mimetype="application/pdf", as_attachment=True, download_name=f"etiquetas_{fecha}.pdf")


@app.route("/api/calculadora_categorias")
@login_requerido
def api_calculadora_categorias():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Cuenta desconectada"}), 401
    import db
    # Una llamada a MeLi por publicación (1,7 s): las categorías de un catálogo casi no cambian, se guardan 6 horas por cuenta
    clave = construir_key("categorias_calculadora", g.cuenta_id)
    categorias = cache_leer(clave)
    if categorias is None:
        headers = {"Authorization": f"Bearer {access_token}"}
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            categorias = calculadora_costos.obtener_categorias_del_catalogo(headers, cursor)
        cache_guardar(clave, categorias, timeout=6 * 3600)
    return jsonify(categorias)


@app.route("/api/calculadora_buscar_categoria")
@login_requerido
def api_calculadora_buscar_categoria():
    q = request.args.get("q", "").strip()
    if len(q) < 3:
        return jsonify([])
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
    except token_manager.CuentaDesconectada:
        access_token, headers = None, {}
    try:
        # Búsqueda por dominio/keyword (devuelve las categorías con mejor score semántico)
        # OJO: este endpoint de MeLi rechaza con 400 cualquier "limit" fuera
        # de 1-8 (a diferencia de la mayoría de sus otros endpoints, que
        # toleran hasta 50) — con 10 esta búsqueda fallaba SIEMPRE de forma
        # silenciosa (cae al fallback, que es mucho menos preciso) para
        # cualquier término, no solo los nuevos.
        resp = meli_http.get(
            "https://api.mercadolibre.com/sites/MLA/domain_discovery/search",
            headers=headers,
            params={"q": q, "limit": 8},
        )
        resultados = []
        if resp.status_code == 200:
            data = resp.json()
            seen = set()
            for item in (data if isinstance(data, list) else []):
                cat_id = item.get("category_id")
                if cat_id and cat_id not in seen:
                    seen.add(cat_id)
                    nombre = item.get("category_name") or item.get("domain_name") or cat_id
                    resultados.append({"id": cat_id, "nombre": nombre})
            # Varias categorías comparten nombre ("Medias" está en ropa interior, deportiva, bebés…):
            # se agrega el camino completo para poder distinguirlas.
            caminos = calculadora_costos.caminos_de_categorias([r["id"] for r in resultados], headers)
            for r in resultados:
                r["camino"] = caminos.get(r["id"])
        if not resultados:
            # Último fallback, sin depender de ningún endpoint "inteligente"
            # de MeLi (domain_discovery/search predictor pueden no devolver
            # nada para un término genérico de una sola palabra, tipo
            # "ropa" — no son buscadores de categorías, son predictores de
            # categoría a partir de un título de publicación completo):
            # match por texto contra las ~30 categorías raíz de MeLi, que
            # cubre exactamente ese caso ("ropa" → "Ropa y Accesorios").
            q_lower = q.lower()
            palabras_q = set(q_lower.split())
            for c in tendencias_mod.obtener_categorias_raiz(access_token):
                nombre_lower = c["nombre"].lower()
                if q_lower in nombre_lower or palabras_q & set(nombre_lower.split()):
                    resultados.append({"id": c["id"], "nombre": c["nombre"]})
        return jsonify(resultados[:10])
    except Exception as e:
        print(f"[Calculadora] Error buscando categoría: {e}")
        return jsonify([])


@app.route("/api/calculadora_costos")
@login_requerido
def api_calculadora_costos():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Cuenta desconectada"}), 401
    try:
        precio = float(request.args.get("precio", 0))
    except ValueError:
        return jsonify({"error": "Precio inválido"}), 400
    category_id = request.args.get("category_id")
    listing_type_id = request.args.get("listing_type_id", "gold_special")
    ofrece_cuotas = request.args.get("ofrece_cuotas") == "true"
    if not category_id or precio <= 0:
        return jsonify({"error": "Faltan datos (precio y categoría)"}), 400
    resultado = calculadora_costos.calcular_desglose_real(access_token, precio, category_id, listing_type_id, ofrece_cuotas)
    return jsonify(resultado)


@app.route("/api/simular_costo")
@login_requerido
def api_simular_costo():
    """
    Simulador de impacto en margen al crear un descuento (Promociones)
    — el frontend ya lo llamaba, sin backend detrás (se quedaba
    colgado en "Calculando impacto en margen..." para siempre).
    Reusa calculadora_costos.calcular_desglose_real, la misma fuente
    real de MeLi que ya usa la Calculadora de Comisiones, en vez de
    inventar un % de comisión aparte para este simulador.
    """
    try:
        precio = float(request.args.get("precio", ""))
    except ValueError:
        return jsonify({"error": "Precio inválido."}), 400
    if precio <= 0:
        return jsonify({"error": "Precio inválido."}), 400
    try:
        costo = float(request.args.get("costo", "0") or 0)
    except ValueError:
        costo = 0.0

    id_meli = request.args.get("id_meli")
    if not id_meli:
        return jsonify({"error": "Falta indicar la publicación."}), 400

    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Tu cuenta de MeLi está desconectada."}), 401

    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        resp = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers)
        if resp.status_code != 200:
            return jsonify({"error": "No se pudo consultar la publicación en MeLi."}), 502
        category_id = resp.json().get("category_id")
    except Exception as e:
        return jsonify({"error": f"Error consultando MeLi: {e}"}), 502
    if not category_id:
        return jsonify({"error": "No se pudo determinar la categoría de la publicación."}), 502

    desglose = calculadora_costos.calcular_desglose_real(access_token, precio, category_id, "gold_special", ofrece_cuotas=False)
    if "error" in desglose:
        return jsonify(desglose), 502

    ganancia_neta = round(desglose["recibis"] - costo, 2)
    margen_pct = round((ganancia_neta / precio) * 100, 1)
    return jsonify({
        "ganancia_neta": ganancia_neta, "margen_pct": margen_pct,
        "comision_total": desglose["comision_total"], "costo_envio": desglose["costo_envio"],
    })


@app.route("/stock_masivo")
@login_requerido
def stock_masivo_vista():
    modelos = stock_masivo_mod.obtener_modelos_agrupados(g.usuario_id, g.cuenta_id)
    return render_template("stock_masivo.html", modelos=modelos, active_nav="stock_masivo")


@app.route("/actualizar_stock_multiple", methods=["POST"])
@login_requerido
@auditar("stock_masivo")
def actualizar_stock_multiple():
    """
    "Aplicar cambios a Mercado Libre" en Stock Masivo — nunca había
    tenido backend (el form apuntaba a una URL que no existía).

    Cada input del form es stock_<id_meli> — en este catálogo cada
    "talle" es una PUBLICACIÓN separada (ver stock_masivo.py), no una
    variación de MeLi dentro de un mismo item. Ojo con los pocos
    items que SÍ tienen variaciones reales de MeLi (más de una fila en
    productos_variantes para el mismo id_meli — típicamente colores
    distintos dentro del mismo talle): el input de esta pantalla es UN
    solo número que representa la SUMA de esas variaciones. Repartir
    esa suma entre colores sin que el usuario diga cómo sería inventar
    un número en el stock real — esos casos se saltean a propósito y
    se reportan aparte, nunca se escribe una distribución adivinada.
    """
    from urllib.parse import urlencode
    volver_a = request.form.get("volver_a") or "/stock_masivo"
    campos_stock = {k[len("stock_"):]: v for k, v in request.form.items() if k.startswith("stock_")}
    # Solo se tocan las publicaciones cuyo valor CAMBIÓ respecto del que mostraba la pantalla (orig_<id>).
    # Antes se mandaban TODAS a Mercado Libre: el stock local puede estar unos minutos atrasado (una venta
    # reciente), así que reenviar lo que no se tocó podía pisar el stock real de MeLi con un número viejo.
    originales = {k[len("orig_"):]: v for k, v in request.form.items() if k.startswith("orig_")}
    campos_stock = {k: v for k, v in campos_stock.items() if originales.get(k) != v}
    if not campos_stock:
        return redirect(f"{volver_a}?{urlencode({'msg': 'No había ningún cambio para aplicar.', 'tipo': 'info'})}")

    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    actualizados, saltados, fallidos = 0, 0, 0

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()

        # Un solo roundtrip para las variantes de TODOS los id_meli del
        # lote, en vez de una subquery por ítem dentro del loop (N+1).
        ids_meli = list(campos_stock.keys())
        cursor.execute(
            """
            SELECT p.id_meli, v.id_variante
            FROM productos_padre p
            JOIN productos_variantes v ON v.id_padre = p.id
            WHERE p.id_meli = ANY(%s)
            """,
            (ids_meli,)
        )
        variantes_por_item = {}
        for id_meli_fila, id_variante in cursor.fetchall():
            variantes_por_item.setdefault(id_meli_fila, []).append(id_variante)

        for id_meli, valor in campos_stock.items():
            try:
                nuevo_stock = int(valor)
            except (ValueError, TypeError):
                fallidos += 1
                continue
            if nuevo_stock < 0:
                fallidos += 1
                continue

            variantes_del_item = variantes_por_item.get(id_meli, [])

            if len(variantes_del_item) > 1:
                saltados += 1
                continue

            try:
                # Sin variaciones la variante guardada es «<id>_unica» (id interno): a MeLi va available_quantity de la publicación, no esa variación
                payload = stock_meli.payload_para_stock(variantes_del_item, nuevo_stock)
                r = meli_http.put(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, json=payload)
                if r.status_code not in (200, 201):
                    print(f"[StockMasivo] ⚠️ MeLi rechazó el stock de {id_meli}: {r.status_code} - {r.text[:200]}")
                    fallidos += 1
                    continue
            except Exception as e:
                print(f"[StockMasivo] ⚠️ Error actualizando {id_meli}: {e}")
                fallidos += 1
                continue

            cursor.execute(
                "UPDATE productos_variantes SET stock_propio = %s WHERE id_padre = (SELECT id FROM productos_padre WHERE id_meli = %s)",
                (nuevo_stock, id_meli)
            )
            actualizados += 1

    partes = ["1 actualizada" if actualizados == 1 else f"{actualizados} actualizadas"]
    if saltados:
        partes.append(f"{saltados} con varios colores (revisalas a mano en MeLi)")
    if fallidos:
        partes.append(f"{fallidos} con error")
    mensaje = ", ".join(partes) + "."
    tipo = "success" if (actualizados and not fallidos and not saltados) else ("error" if not actualizados else "info")
    return redirect(f"{volver_a}?{urlencode({'msg': mensaje, 'tipo': tipo})}")


@app.route("/despacho/marcar", methods=["POST"])
@login_requerido
def despacho_marcar():
    import db
    data = request.get_json(silent=True) or {}
    id_orden = data.get("id_orden")
    id_meli = data.get("id_meli")
    id_variante = data.get("id_variante")
    nuevo_estado = bool(data.get("despachado"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE ventas SET despachado = %s WHERE id_orden = %s AND id_meli = %s AND id_variante = %s",
            (nuevo_estado, id_orden, id_meli, id_variante)
        )
    return jsonify({"ok": True})


@app.route("/api/alertas/pendientes")
@login_requerido
def api_alertas_pendientes():
    """
    Devuelve las alertas in-app no leídas del usuario actual.
    Usado por el badge de notificaciones en el nav (Fase 5 — UI todavía no
    construida, pero el endpoint ya está listo para cuando llegue).
    """
    import db
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            from psycopg.rows import dict_row
            cursor = conexion.cursor(row_factory=dict_row)
            cursor.execute(
                """SELECT id, tipo, titulo, mensaje, accion_url, creada_en
                   FROM alertas_usuario
                   WHERE usuario_id = %s AND leida = false
                   ORDER BY creada_en DESC
                   LIMIT 20""",
                (g.usuario_id,),
            )
            alertas = cursor.fetchall()
        return jsonify({
            "total": len(alertas),
            "alertas": [
                {
                    "id": a["id"],
                    "tipo": a["tipo"],
                    "titulo": a["titulo"],
                    "mensaje": a["mensaje"],
                    "accion_url": a["accion_url"],
                    "creada_en": a["creada_en"].isoformat() if a["creada_en"] else None,
                }
                for a in alertas
            ],
        })
    except Exception:
        # La tabla puede no existir todavía si las migraciones están pendientes
        return jsonify({"total": 0, "alertas": []})


@app.route("/api/alertas/<int:id_alerta>/leer", methods=["POST"])
@login_requerido
def api_alerta_marcar_leida(id_alerta):
    """Marca una alerta como leída."""
    import db
    from datetime import datetime, timezone
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute(
                "UPDATE alertas_usuario SET leida = true, leida_en = %s WHERE id = %s AND usuario_id = %s",
                (datetime.now(timezone.utc), id_alerta, g.usuario_id),
            )
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": _detalle_error(e)}), 500


# ─────────────────── Calculadora MeLi ───────────────────

@app.route("/calculadora")
@login_requerido
def calculadora_vista():
    return render_template("calculadora.html", active_nav="calculadora")


# ─────────────────── Reporte Fiscal ───────────────────

@app.route("/reporte_fiscal")
@login_requerido
def reporte_fiscal_vista():
    import reporte_fiscal as rf
    anio_actual = hoy_argentina().year
    anio_seleccionado = request.args.get("anio", anio_actual, type=int)
    if not 2000 <= anio_seleccionado <= anio_actual + 1:
        anio_seleccionado = anio_actual
    # Ofrece los últimos 3 años como opciones
    anios_disponibles = [anio_actual, anio_actual - 1, anio_actual - 2]

    meses = rf.calcular_reporte_anual(g.usuario_id, anio_seleccionado, g.cuenta_id)
    from utils import formatear_moneda
    totales = {
        "facturacion": sum(m["facturacion"] for m in meses),
        "comisiones":  sum(m["comisiones"] for m in meses),
        "envios":      sum(m["envios"] for m in meses),
        "cargos_totales": sum(m["cargos_totales"] for m in meses),
        "gastos":      sum(m["gastos"] for m in meses),
        "costo_fabricacion": sum(m["costo_fabricacion"] for m in meses),
        "ganancia_estimada": sum(m["ganancia_estimada"] for m in meses),
        "retenciones": sum(m["retenciones"] for m in meses),
        "ordenes":  sum(m["ordenes"] for m in meses),
        "unidades": sum(m["unidades"] for m in meses),
    }
    totales["facturacion_f"]     = formatear_moneda(totales["facturacion"])
    totales["comisiones_f"]      = formatear_moneda(totales["comisiones"])
    totales["envios_f"]          = formatear_moneda(totales["envios"])
    totales["cargos_totales_f"]  = formatear_moneda(totales["cargos_totales"])
    totales["gastos_f"]          = formatear_moneda(totales["gastos"])
    totales["costo_fab_f"]       = formatear_moneda(totales["costo_fabricacion"])
    totales["ganancia_f"]        = formatear_moneda(totales["ganancia_estimada"])

    return render_template(
        "reporte_fiscal.html",
        active_nav="reporte_fiscal",
        anio_seleccionado=anio_seleccionado,
        anios_disponibles=anios_disponibles,
        meses=meses,
        totales=totales,
    )


@app.route("/reporte_fiscal/exportar")
@login_requerido
def reporte_fiscal_exportar():
    import reporte_fiscal as rf
    anio = request.args.get("anio", hoy_argentina().year, type=int)
    if not 2000 <= anio <= hoy_argentina().year + 1:
        return jsonify({"ok": False, "detalle": "Año inválido."}), 400
    meses = rf.calcular_reporte_anual(g.usuario_id, anio, g.cuenta_id)
    buf = rf.generar_excel_fiscal(meses, anio)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"reporte_fiscal_{anio}.xlsx",
    )


@app.route("/reporte_fiscal/detalle")
@login_requerido
def reporte_fiscal_detalle():
    """Las ventas de un mes, línea por línea (libro de ventas para el contador)."""
    import reporte_fiscal as rf
    anio = request.args.get("anio", type=int)
    mes = request.args.get("mes", type=int)
    if not anio or not mes or not 2000 <= anio <= hoy_argentina().year + 1 or not 1 <= mes <= 12:
        return jsonify({"ok": False, "detalle": "Año o mes inválido."}), 400
    buf = rf.generar_excel_detalle(rf.detalle_del_mes(g.usuario_id, anio, mes, g.cuenta_id), anio, mes)
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"ventas_{anio}_{mes:02d}.xlsx",
    )


# ─────────────────── Drawer 360° ───────────────────

@app.route("/api/drawer/info/<id_meli>")
@login_requerido
def api_drawer_info(id_meli):
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT titulo, precio, estado, precio_costo FROM productos_padre WHERE id_meli = %s",
            (id_meli,),
        )
        fila = cursor.fetchone()

    if not fila:
        return jsonify({"error": "Publicación no encontrada"}), 404

    titulo, precio, estado, precio_costo = fila
    descripcion = ""
    atributos = []
    editable = estado in publicacion_edicion.ESTADOS_EDITABLES

    if access_token:
        try:
            headers = {"Authorization": f"Bearer {access_token}"}
            r = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}?include_attributes=all", headers=headers)
            if r.status_code == 200:
                data = r.json()
                atributos_raw = data.get("attributes", [])
                atributos = [
                    {"id": a.get("id", ""), "nombre": a.get("name", ""), "valor": a.get("value_name") or a.get("value_id") or ""}
                    for a in atributos_raw if a.get("value_name") or a.get("value_id")
                ]
            r2 = meli_http.get(f"https://api.mercadolibre.com/items/{id_meli}/description", headers=headers)
            if r2.status_code == 200:
                descripcion = r2.json().get("plain_text", "")
        except Exception as e:
            print(f"[Exportador] ⚠️ No se pudo traer la descripción: {e}")

    return jsonify({
        "titulo": titulo, "precio": precio, "estado": estado, "estado_nombre": publicacion_edicion.nombre_estado(estado), "estado_editable": editable,
        "titulo_max": publicacion_edicion.MAX_TITULO, "precio_costo": precio_costo or 0.0,
        "descripcion": descripcion, "atributos": atributos,
    })


@app.route("/api/drawer/guardar/<id_meli>", methods=["POST"])
@login_requerido
@auditar("publicacion_editar")
def api_drawer_guardar(id_meli):
    """
    Guarda lo que se editó en el panel de una publicación. El costo de fabricación es solo de CoreLux. Título, precio y estado se mandan a Mercado
    Libre (solo lo que cambió, ver publicacion_edicion) y recién cuando MeLi los acepta se reflejan acá y se anota el cambio de precio.
    """
    data = request.get_json(silent=True) or {}
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT titulo, precio, estado FROM productos_padre WHERE cuenta_id = %s AND id_meli = %s", (g.cuenta_id, id_meli))
        fila = cursor.fetchone()
    if not fila:
        return jsonify({"ok": False, "detalle": "No encontramos esa publicación."}), 404
    actual = {"titulo": fila[0], "precio": float(fila[1] or 0), "estado": fila[2]}

    payload, errores = publicacion_edicion.armar_cambios(actual, {"titulo": data.get("titulo"), "precio": data.get("precio"), "estado": data.get("estado")})
    precio_costo = None
    if data.get("precio_costo") not in (None, ""):
        try:
            precio_costo = float(data["precio_costo"])
        except (TypeError, ValueError):
            precio_costo = None
        if precio_costo is None or precio_costo < 0 or precio_costo != precio_costo:
            errores.append("El costo de fabricación tiene que ser un número de cero o más.")
    if errores:
        return jsonify({"ok": False, "detalle": errores[0]}), 400

    if precio_costo is not None:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            conexion.cursor().execute("UPDATE productos_padre SET precio_costo = %s WHERE cuenta_id = %s AND id_meli = %s", (precio_costo, g.cuenta_id, id_meli))

    cambios = publicacion_edicion.resumen_cambios(actual, payload)
    if payload:
        try:
            access_token = token_manager.asegurar_token_valido(g.cuenta_id)
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            r = meli_http.put(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, json=payload)
        except token_manager.CuentaDesconectada:
            return jsonify({"ok": False, "detalle": "La cuenta de Mercado Libre está desconectada: reconectala primero."})
        except Exception as e:
            return jsonify({"ok": False, "detalle": _detalle_error(e)})
        if r.status_code not in (200, 201):
            try:
                cuerpo = r.json()
            except ValueError:
                cuerpo = None
            print(f"[Publicación] MeLi rechazó {sorted(payload)} de {id_meli}: {r.status_code} {r.text[:300]}")
            return jsonify({"ok": False, "detalle": publicacion_edicion.explicar_error_meli(r.status_code, cuerpo)})
        # Mercado Libre aceptó: recién ahora CoreLux refleja el cambio (y anota el precio, que la sincronización ya no va a ver como diferencia)
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            sets, params = [], []
            for columna, clave in (("titulo", "title"), ("precio", "price"), ("estado", "status")):
                if clave in payload:
                    sets.append(f"{columna} = %s")
                    params.append(payload[clave])
            cursor.execute(f"UPDATE productos_padre SET {', '.join(sets)} WHERE cuenta_id = %s AND id_meli = %s", (*params, g.cuenta_id, id_meli))
            if "price" in payload:
                cursor.execute(
                    "INSERT INTO historial_precios (cuenta_id, id_meli, precio_anterior, precio_nuevo, fecha_cambio) VALUES (%s, %s, %s, %s, now())",
                    (g.cuenta_id, id_meli, actual["precio"], payload["price"]),
                )
    return jsonify({"ok": True, "cambios": cambios, "costo_guardado": precio_costo is not None, "titulo": payload.get("title", actual["titulo"])})


@app.route("/api/drawer/guardar_descripcion/<id_meli>", methods=["POST"])
@login_requerido
@auditar("publicacion_descripcion")
def api_drawer_guardar_descripcion(id_meli):
    data = request.get_json(silent=True) or {}
    descripcion = (data.get("descripcion") or "").strip()
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        r = meli_http.post(
            f"https://api.mercadolibre.com/items/{id_meli}/description",
            headers=headers, json={"plain_text": descripcion},
        )
        if r.status_code not in (200, 201):
            return jsonify({"ok": False, "detalle": meli_errores.explicar_respuesta(r)})
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "Tu cuenta de Mercado Libre está desconectada. Reconectala para seguir."})
    except Exception as e:
        return jsonify({"ok": False, "detalle": _detalle_error(e)})
    return jsonify({"ok": True})


@app.route("/api/drawer/guardar_atributos/<id_meli>", methods=["POST"])
@login_requerido
@auditar("publicacion_atributos")
def api_drawer_guardar_atributos(id_meli):
    data = request.get_json(silent=True) or {}
    atributos = data.get("atributos") or []
    if not atributos:
        return jsonify({"ok": False, "detalle": "Sin atributos"})
    payload = [{"id": a["id"], "value_name": a.get("value_name", "")} for a in atributos if a.get("id")]
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        r = meli_http.put(
            f"https://api.mercadolibre.com/items/{id_meli}",
            headers=headers, json={"attributes": payload},
        )
        if r.status_code not in (200, 201):
            return jsonify({"ok": False, "detalle": meli_errores.explicar_respuesta(r)})
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "Tu cuenta de Mercado Libre está desconectada. Reconectala para seguir."})
    except Exception as e:
        return jsonify({"ok": False, "detalle": _detalle_error(e)})
    return jsonify({"ok": True})


@app.route("/api/drawer/resenas/<id_meli>")
@login_requerido
def api_drawer_resenas(id_meli):
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}"}
        r = meli_http.get(f"https://api.mercadolibre.com/reviews/item/{id_meli}", headers=headers)
        if r.status_code != 200:
            return jsonify({"rating_average": None, "reviews": []})
        raw = r.json()
        reviews = [
            {
                "titulo": rev.get("title", ""),
                "texto": rev.get("content", ""),
                "rating": rev.get("rating", 0),
                "fecha": rev.get("date_created", "")[:10] if rev.get("date_created") else "",
            }
            for rev in raw.get("reviews", [])[:10]
        ]
        return jsonify({"rating_average": raw.get("rating_average"), "reviews": reviews})
    except token_manager.CuentaDesconectada:
        return jsonify({"rating_average": None, "reviews": []})
    except Exception as e:
        return jsonify({"error": _detalle_error(e)}), 500


@app.route("/api/drawer/preguntas/<id_meli>")
@login_requerido
def api_drawer_preguntas(id_meli):
    import db
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            """SELECT question_id, texto_pregunta, estado, respuesta_sugerida, creado_en
               FROM preguntas_pendientes
               WHERE item_id = %s
               ORDER BY creado_en DESC LIMIT 50""",
            (id_meli,),
        )
        filas = cursor.fetchall()
    preguntas = [
        {
            "id": f[0], "texto": f[1] or "", "estado": f[2],
            "respuesta": f[3] or "",
            "fecha": f[4].strftime("%Y-%m-%d") if f[4] and hasattr(f[4], "strftime") else str(f[4] or ""),
        }
        for f in filas
    ]
    return jsonify(preguntas)


@app.route("/api/drawer/optimizar_titulo/<id_meli>", methods=["POST"])
@login_requerido
def api_drawer_optimizar_titulo(id_meli):
    import ia_asistente
    data = request.get_json(silent=True) or {}
    titulo_actual = (data.get("titulo") or "").strip()
    if not titulo_actual:
        return jsonify({"ok": False, "error": "Falta el título actual"}), 400

    prompt_sistema = (
        "Sos un experto en optimización de títulos para Mercado Libre Argentina. "
        "El título tiene que tener entre 60 y 80 caracteres, incluir el modelo o marca si está implícita, "
        "mencionar atributos clave de búsqueda (material, talle si aplica, uso), "
        "y estar en mayúsculas como es la convención en MeLi. "
        "Respondé SOLO con el título sugerido, sin comillas, sin explicación."
    )
    prompt_usuario = f"Optimizá este título para MeLi:\n{titulo_actual}"
    ok, resultado = ia_asistente.preguntar_ia(prompt_sistema, prompt_usuario, max_tokens=120, temperatura=0.5)
    if not ok:
        return jsonify({"ok": False, "error": resultado})
    titulo_sugerido = resultado.strip().strip('"').strip("'")
    return jsonify({"ok": True, "titulo": titulo_sugerido})


@app.route("/api/drawer/salud/<id_meli>")
@login_requerido
def api_drawer_salud(id_meli):
    """Score de salud por publicación individual (distinto al score global de cuenta)."""
    import db
    from datetime import timedelta

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()

        cursor.execute(
            "SELECT titulo, precio, estado, precio_costo FROM productos_padre WHERE id_meli = %s",
            (id_meli,),
        )
        fila = cursor.fetchone()
        if not fila:
            return jsonify({"error": "Publicación no encontrada"}), 404
        titulo, precio, estado, precio_costo = fila

        score = 100
        recomendaciones = []

        # Sin precio de costo → no podemos calcular ganancia real
        if not precio_costo or precio_costo <= 0:
            score -= 15
            recomendaciones.append("Cargá el costo de fabricación para calcular la ganancia real.")

        # Publicación pausada o cerrada
        if estado == "paused":
            score -= 10
            recomendaciones.append("La publicación está pausada — activala si querés que aparezca en los resultados.")
        elif estado == "closed":
            score -= 25
            recomendaciones.append("La publicación está inactiva (cerrada) — si es intencional, podés ignorar esto.")

        # Preguntas sin responder hace más de 24hs
        cursor.execute(
            """SELECT COUNT(*) FROM preguntas_pendientes
               WHERE item_id = %s AND estado = 'pendiente'
                 AND creado_en < (now() - interval '1 day')""",
            (id_meli,),
        )
        preguntas_viejas = cursor.fetchone()[0] or 0
        if preguntas_viejas > 0:
            score -= min(preguntas_viejas * 8, 20)
            recomendaciones.append(
                f"Tenés {utils.plural(preguntas_viejas, 'pregunta')} sin responder hace más de 24 h — responder rápido mejora el ranking."
            )

        # Sin ventas en los últimos 30 días
        hace_30 = (hoy_argentina() - timedelta(days=30)).strftime("%Y-%m-%d")
        cursor.execute(
            "SELECT COALESCE(SUM(cantidad), 0) FROM ventas WHERE id_meli = %s AND fecha_venta >= %s",
            (id_meli, hace_30),
        )
        ventas_30d = cursor.fetchone()[0] or 0
        if ventas_30d == 0 and estado == "active":
            score -= 20
            recomendaciones.append("No registra ventas en los últimos 30 días — puede que tenga baja visibilidad o sea muy reciente.")

        # Stock bajo o sin stock
        cursor.execute(
            """SELECT COALESCE(SUM(stock_propio),0) + COALESCE(SUM(stock_full),0)
               FROM productos_variantes v
               JOIN productos_padre p ON p.id = v.id_padre
               WHERE p.id_meli = %s""",
            (id_meli,),
        )
        stock_total = cursor.fetchone()[0] or 0
        if stock_total == 0 and estado == "active":
            score -= 25
            recomendaciones.append("Stock en cero — la publicación activa sin stock tiene mala posición en MeLi.")
        elif stock_total <= 3 and estado == "active":
            score -= 8
            recomendaciones.append(f"Stock muy bajo ({utils.plural(stock_total, 'unidad', 'unidades')}) — considerá reponer antes de quedarte sin.")

        score = max(0, min(100, score))

    return jsonify({"porcentaje": score, "recomendaciones": recomendaciones})


# ── Preguntas de compradores ──────────────────────────────────────────────

@app.route("/precios")
@login_requerido
def precios_vista():
    margen, publicidad = precios_mod.parametros(request.args.get("margen"), request.args.get("publicidad"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        datos = precios_mod.obtener_datos(conexion.cursor(), g.cuenta_id, margen, publicidad)
    return render_template("precios.html", active_nav="precios", **datos)


@app.route("/api/precios/aplicar", methods=["POST"])
@login_requerido
@auditar("precios_guiado")
def api_precios_aplicar():
    """Sube a Mercado Libre el precio recomendado de las publicaciones que la persona revisó y confirmó (ver precios.aplicar)."""
    cuerpo = request.get_json(silent=True) or {}
    cambios = cuerpo.get("cambios")
    if not isinstance(cambios, list) or not cambios:
        return jsonify({"ok": False, "detalle": "Elegí al menos una publicación."}), 400
    if not cuerpo.get("confirmado"):
        return jsonify({"ok": False, "detalle": "Falta la confirmación."}), 400
    margen, publicidad = precios_mod.parametros(cuerpo.get("margen"), cuerpo.get("publicidad"))
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "Tu cuenta de Mercado Libre se desconectó. Volvé a conectarla."}), 401
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        datos = precios_mod.obtener_datos(cursor, g.cuenta_id, margen, publicidad)
        resultados = precios_mod.aplicar(cursor, g.cuenta_id, access_token, cambios, datos)
    cambiadas = sum(1 for r in resultados if r["ok"])
    return jsonify({"ok": cambiadas > 0, "cambiadas": cambiadas, "fallidas": len(resultados) - cambiadas, "resultados": resultados})


@app.route("/api/precios/ajuste/vista_previa", methods=["POST"])
@login_requerido
def api_precios_ajuste_vista_previa():
    """Qué pasaría con cada publicación activa si se sube o baja el precio un porcentaje. No cambia nada."""
    cuerpo = request.get_json(silent=True) or {}
    porcentaje = precios_mod.porcentaje_valido(cuerpo.get("porcentaje"))
    if porcentaje is None:
        return jsonify({"ok": False, "detalle": f"Poné un porcentaje entre -{precios_mod.LIMITE_AJUSTE_PCT} y {precios_mod.LIMITE_AJUSTE_PCT} (distinto de cero)."}), 400
    margen, publicidad = precios_mod.parametros(cuerpo.get("margen"), cuerpo.get("publicidad"))
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        datos = precios_mod.obtener_datos(conexion.cursor(), g.cuenta_id, margen, publicidad)
    return jsonify({"ok": True, "porcentaje": porcentaje, "items": precios_mod.calcular_ajuste(datos, porcentaje)})


@app.route("/api/precios/ajuste/aplicar", methods=["POST"])
@login_requerido
@auditar("precios_ajuste")
def api_precios_ajuste_aplicar():
    """Cambia en Mercado Libre el precio de las publicaciones que la persona revisó y confirmó (ver precios.aplicar_ajuste)."""
    cuerpo = request.get_json(silent=True) or {}
    porcentaje = precios_mod.porcentaje_valido(cuerpo.get("porcentaje"))
    ids = cuerpo.get("ids")
    if porcentaje is None or not isinstance(ids, list) or not ids:
        return jsonify({"ok": False, "detalle": "Elegí un porcentaje válido y al menos una publicación."}), 400
    if not cuerpo.get("confirmado"):
        return jsonify({"ok": False, "detalle": "Falta la confirmación."}), 400
    margen, publicidad = precios_mod.parametros(cuerpo.get("margen"), cuerpo.get("publicidad"))
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "Tu cuenta de Mercado Libre se desconectó. Volvé a conectarla."}), 401
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        datos = precios_mod.obtener_datos(cursor, g.cuenta_id, margen, publicidad)
        resultados = precios_mod.aplicar_ajuste(cursor, g.cuenta_id, access_token, porcentaje, ids, datos)
    cambiadas = sum(1 for r in resultados if r["ok"])
    return jsonify({"ok": cambiadas > 0, "cambiadas": cambiadas, "fallidas": len(resultados) - cambiadas, "resultados": resultados})


@app.route("/cobros")
@login_requerido
def cobros_vista():
    periodos = []
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        periodos = facturacion.obtener_periodos(access_token, g.cuenta_id)   # con caché; si Mercado Libre no responde, la pantalla sigue sin el cuadro de la factura
    except Exception as e:
        print(f"[Cobros] ⚠️ No se pudo traer la factura de Mercado Libre: {e}")
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        datos = cobros_mod.obtener_datos(conexion.cursor(), g.cuenta_id, periodos_factura=periodos)
    return render_template("cobros.html", active_nav="cobros", **datos)


@app.route("/opiniones")
@login_requerido
def opiniones_vista():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        datos = opiniones_mod.obtener_datos(conexion.cursor(), g.cuenta_id)
    return render_template("opiniones.html", active_nav="opiniones", **datos)


@app.route("/calidad")
@login_requerido
def calidad_vista():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        datos = calidad_mod.obtener_datos(conexion.cursor(), g.cuenta_id)
    return render_template("calidad.html", active_nav="calidad", **datos)


@app.route("/preguntas")
@login_requerido
def preguntas_vista():
    return render_template("preguntas.html", active_nav="preguntas")


@app.route("/api/mensajes/sin_leer")
@login_requerido
def api_mensajes_sin_leer():
    """Mensajes de compradores sin leer (se consulta a Mercado Libre como mucho 1 vez por minuto por cuenta)."""
    clave = construir_key("mensajes_sin_leer", g.cuenta_id)
    datos = cache_leer(clave)
    if datos is None:
        try:
            access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        except token_manager.CuentaDesconectada:
            return jsonify({"total": 0, "conversaciones": []})
        datos = mensajes_mod.sin_leer(access_token) or {"total": 0, "conversaciones": []}
        cache_guardar(clave, datos, timeout=60)
    return jsonify(datos)


@app.route("/api/preguntas/tiempo_respuesta")
@login_requerido
def api_preguntas_tiempo_respuesta():
    """Cuánto tardás en responder (mediana de las últimas respondidas). Caché de 30 minutos por cuenta."""
    clave = construir_key("tiempo_respuesta", g.cuenta_id)
    datos = cache_leer(clave)
    if datos is None:
        try:
            access_token = token_manager.asegurar_token_valido(g.cuenta_id)
            with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
                fila = cursor.fetchone()
        except token_manager.CuentaDesconectada:
            return jsonify(None)
        datos = (tiempo_respuesta_mod.calcular(access_token, fila[0]) if fila else None) or {}
        cache_guardar(clave, datos, timeout=1800)
    return jsonify(datos or None)


@app.route("/api/preguntas/lista")
@login_requerido
def api_preguntas_lista():
    estado = request.args.get("estado", "pendiente")
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        sql = """
            SELECT p.id, p.question_id, p.item_id, p.texto_pregunta,
                   p.respuesta_sugerida, p.estado, p.creado_en,
                   COALESCE(pp.titulo, p.item_id) AS titulo_item, pp.thumbnail
            FROM preguntas_pendientes p
            LEFT JOIN productos_padre pp ON pp.id_meli = p.item_id
            WHERE p.cuenta_id = %s
        """
        params = [g.cuenta_id]
        if estado != "todos":
            sql += " AND p.estado = %s"
            params.append(estado)
        # Las pendientes, de la más vieja a la más nueva: la que lleva más tiempo esperando es la más urgente
        sql += " ORDER BY p.creado_en " + ("ASC" if estado == "pendiente" else "DESC") + " LIMIT 200"
        cursor.execute(sql, params)
        filas = cursor.fetchall()
    preguntas = []
    for f in filas:
        preguntas.append({
            "id": f[0],
            "question_id": f[1],
            "item_id": f[2] or "",
            "texto": f[3] or "",
            "respuesta_sugerida": f[4] or "",
            "estado": f[5],
            "fecha": f[6].strftime("%Y-%m-%d %H:%M") if f[6] and hasattr(f[6], "strftime") else str(f[6] or ""),
            "creado_en_iso": f[6].isoformat() if f[6] and hasattr(f[6], "isoformat") else None,
            "titulo_item": f[7] or f[2] or "—",
            "thumbnail": f[8],
        })
    return jsonify(preguntas)


@app.route("/api/preguntas/responder", methods=["POST"])
@login_requerido
@auditar("pregunta_responder")
def api_preguntas_responder():
    """Responde una pregunta de un comprador (la usan Preguntas y la pestaña Preguntas del panel de una publicación: un solo camino)."""
    data = request.get_json(silent=True) or {}
    question_id = data.get("question_id")
    texto = (data.get("texto") or "").strip()
    if not question_id or not texto:
        return jsonify({"ok": False, "detalle": "Escribí la respuesta antes de enviarla."}), 400
    if len(texto) > 2000:
        return jsonify({"ok": False, "detalle": "La respuesta es muy larga: Mercado Libre acepta hasta 2000 caracteres."}), 400
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        r = meli_http.post("https://api.mercadolibre.com/answers", headers=headers, json={"question_id": question_id, "text": texto})
        if r.status_code not in (200, 201):
            print(f"[Preguntas] MeLi rechazó la respuesta a {question_id}: {r.status_code} {r.text[:200]}")
            if r.status_code in (400, 404, 409):
                return jsonify({"ok": False, "detalle": "Esa pregunta ya no se puede responder: puede que ya esté respondida o que el comprador la haya borrado."})
            return jsonify({"ok": False, "detalle": publicacion_edicion.explicar_error_meli(r.status_code, None)})
    except token_manager.CuentaDesconectada:
        return jsonify({"ok": False, "detalle": "La cuenta de Mercado Libre está desconectada: reconectala primero."})
    except Exception as e:
        return jsonify({"ok": False, "detalle": _detalle_error(e)})
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE preguntas_pendientes SET estado = 'respondida', respuesta_sugerida = %s WHERE question_id = %s AND cuenta_id = %s",
            (texto, str(question_id), g.cuenta_id),
        )
    return jsonify({"ok": True})


@app.route("/api/preguntas/ignorar", methods=["POST"])
@login_requerido
def api_preguntas_ignorar():
    data = request.get_json(silent=True) or {}
    ids = data.get("question_ids", [])
    if not ids:
        return jsonify({"ok": False, "detalle": "Sin preguntas"}), 400
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE preguntas_pendientes SET estado = 'ignorada' WHERE question_id = ANY(%s::text[]) AND cuenta_id = %s",
            (ids, g.cuenta_id),
        )
    return jsonify({"ok": True, "actualizadas": len(ids)})


@app.route("/api/preguntas/sugerir", methods=["POST"])
@login_requerido
def api_preguntas_sugerir():
    import ia_asistente
    data = request.get_json(silent=True) or {}
    texto_pregunta = (data.get("texto") or "").strip()
    titulo_item = (data.get("titulo_item") or "").strip()
    if not texto_pregunta:
        return jsonify({"ok": False, "error": "Falta el texto de la pregunta"}), 400
    prompt = (
        "Sos el vendedor de una tienda en Mercado Libre Argentina. "
        "Respondé la siguiente pregunta de un comprador de forma breve, cordial y profesional. "
        "La respuesta debe ser directa (máximo 2 oraciones). No uses emojis.\n\n"
    )
    if titulo_item:
        prompt += f"Producto: {titulo_item}\n"
    prompt += f"Pregunta: {texto_pregunta}\n\nRespuesta:"
    try:
        respuesta = ia_asistente.preguntar_ia(prompt)
        return jsonify({"ok": True, "respuesta": respuesta.strip()})
    except Exception as e:
        return jsonify({"ok": False, "error": _detalle_error(e)})

# ── /Preguntas ────────────────────────────────────────────────────────────

# ── Sistema de referidos ──────────────────────────────────────────────────

@app.route("/r/<string:code>")
def referral_redirect(code):
    """Guarda el código en una cookie y redirige al landing."""
    resp = redirect(url_for("landing"))
    resp.set_cookie("ref_code", code.upper(), max_age=30 * 24 * 3600, httponly=True, samesite="Lax")
    return resp


@app.route("/referidos")
@login_requerido
def referidos_vista():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT referral_code FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()
        referral_code = fila[0] if fila else None
        cursor.execute(
            """SELECT r.creado_en, r.convertido_en, u.email
               FROM referrals r
               LEFT JOIN usuarios u ON u.id = r.referred_id
               WHERE r.referrer_id = %s
               ORDER BY r.creado_en DESC""",
            (g.usuario_id,)
        )
        referidos = [{"creado_en": row[0], "convertido_en": row[1], "email": row[2]} for row in cursor.fetchall()]
    base_url = request.host_url.rstrip("/")
    referral_link = f"{base_url}/r/{referral_code}" if referral_code else None
    return render_template("referidos.html", active_nav="referidos", referral_code=referral_code, referral_link=referral_link, referidos=referidos)


# ── Panel de administración ───────────────────────────────────────────────

@app.route("/admin")
@login_requerido
@admin_requerido
def admin_panel():
    # Usamos conexion_admin para ver TODOS los usuarios y sus cuentas
    # (cuentas_meli tiene RLS que bloquea la vista cross-usuario normal).
    # Requiere que DATABASE_URL_ADMIN tenga GRANT SELECT en usuarios/cuentas_meli.
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT
                u.id, u.email, COALESCE(u.nombre, '') AS nombre,
                u.plan, u.activo, u.creado_en, u.trial_termina_en,
                u.onboarding_completo,
                COUNT(c.id)                                   AS num_cuentas,
                MAX(c.ultima_sincronizacion_ventas)           AS ultima_sync,
                MAX(c.racha_dias)                             AS racha_dias,
                MAX(c.sincronizacion_inicial_completa::int)   AS sync_completa,
                MAX(c.racha_ultimo_dia)                       AS ultima_visita
            FROM usuarios u
            LEFT JOIN cuentas_meli c ON c.usuario_id = u.id
            GROUP BY u.id, u.email, u.nombre, u.plan, u.activo,
                     u.creado_en, u.trial_termina_en, u.onboarding_completo
            ORDER BY u.creado_en DESC
        """)
        filas = cursor.fetchall()

    usuarios_lista, stats = admin_usuarios.armar_usuarios(filas, hoy_argentina(), datetime.now(timezone.utc))
    return render_template("admin_panel.html", active_nav="admin",
                           usuarios=usuarios_lista, stats=stats)


@app.route("/admin/usuario/<int:uid>/plan", methods=["POST"])
@login_requerido
@admin_requerido
@auditar("plan_cambiar")
def admin_cambiar_plan(uid):
    nuevo_plan = (request.get_json(silent=True) or {}).get("plan", "")
    planes_validos = {"trial", "base", "elite", "cancelado"}
    if nuevo_plan not in planes_validos:
        return jsonify({"ok": False, "detalle": "Plan inválido"}), 400
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE usuarios SET plan = %s, actualizado_en = now() WHERE id = %s",
            (nuevo_plan, uid),
        )
    return jsonify({"ok": True})


@app.route("/admin/usuario/<int:uid>/extender_trial", methods=["POST"])
@login_requerido
@admin_requerido
@auditar("trial_extender")
def admin_extender_trial(uid):
    """Suma días a la prueba de un usuario en trial: desde hoy si ya venció, desde su fecha de fin si todavía no."""
    try:
        dias = int((request.get_json(silent=True) or {}).get("dias", 7))
    except (TypeError, ValueError):
        dias = 0
    if not 1 <= dias <= 60:
        return jsonify({"ok": False, "detalle": "Los días tienen que ser entre 1 y 60."}), 400
    with db.conexion_admin() as conexion:
        fin = admin_usuarios.extender_prueba(conexion.cursor(), uid, dias)
    if not fin:
        return jsonify({"ok": False, "detalle": "Solo se extiende la prueba de quien está en el plan trial."}), 404
    return jsonify({"ok": True, "trial_termina_en": utils.fecha_corta(fin), "dias": dias})


@app.route("/admin/usuario/<int:uid>/toggle_activo", methods=["POST"])
@login_requerido
@admin_requerido
@auditar("usuario_activar")
def admin_toggle_activo(uid):
    with db.conexion_admin() as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE usuarios SET activo = NOT activo, actualizado_en = now() WHERE id = %s RETURNING activo",
            (uid,),
        )
        fila = cursor.fetchone()
    if not fila:
        return jsonify({"ok": False, "detalle": "Usuario no encontrado"}), 404
    return jsonify({"ok": True, "activo": fila[0]})

# ── /Panel de administración ──────────────────────────────────────────────

# ── Suscripciones / Pagos ─────────────────────────────────────────────────

@app.route("/planes")
def planes_vista():
    """Página de precios — accesible sin login."""
    usuario_id = session.get("usuario_id")
    plan_actual = None
    trial_termina_en = None
    if usuario_id:
        try:
            with db.conexion_usuario(usuario_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute("SELECT plan, trial_termina_en FROM usuarios WHERE id = %s", (usuario_id,))
                fila = cursor.fetchone()
            if fila:
                plan_actual, trial_termina_en = fila
        except Exception as e:
            print(f"[Planes] ⚠️ No se pudo leer el plan del usuario: {e}")
    dias_trial = None
    if plan_actual == "trial" and trial_termina_en:
        delta = trial_termina_en - datetime.now(timezone.utc)
        dias_trial = max(0, delta.days)
    # Los errores del alta de suscripción vuelven acá con un código (antes el navegador mostraba un JSON crudo)
    avisos = {
        "sin_pagos": "Los pagos todavía no están habilitados en esta cuenta. Escribinos y te activamos el plan a mano.",
        "plan_invalido": "No reconocimos ese plan — elegí uno de los de abajo.",
        "mp_error": "No pudimos conectar con Mercado Pago ahora. Probá de nuevo en unos minutos.",
    }
    return render_template("planes.html", plan_actual=plan_actual, dias_trial=dias_trial, aviso=avisos.get(request.args.get("aviso")), pagos_habilitados=config.PAGOS_HABILITADOS)


@app.route("/cuenta")
@login_requerido
def cuenta_vista():
    """Preferencias del negocio y datos de la persona: margen mínimo, descargar mis datos, eliminar la cuenta."""
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT plan, trial_termina_en, email FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()
    if not fila:
        return redirect(url_for("planes_vista"))
    plan, trial_termina_en, email = fila
    if (email or "").endswith("@pendiente.corelux.app"):
        email = None                          # email provisorio hasta que se lea el real de Mercado Libre: no se le muestra a la persona
    dias_trial = max(0, (trial_termina_en - datetime.now(timezone.utc)).days) if plan == "trial" and trial_termina_en else None
    nombre_plan = {"trial": "Prueba gratuita", "base": "Plan Base", "elite": "Plan Elite", "cancelado": "Cancelado"}.get(plan, plan)
    return render_template("cuenta.html", active_nav="cuenta", plan=plan, nombre_plan=nombre_plan, email=email, dias_trial=dias_trial,
                           pagos_habilitados=config.PAGOS_HABILITADOS, contacto=legal.CONTACTO_EMAIL)


@app.route("/api/cuenta/margen_minimo", methods=["POST"])
@login_requerido
@auditar("margen_minimo")
def api_cuenta_margen_minimo():
    margen = preferencias.normalizar_margen((request.get_json(silent=True) or {}).get("valor"))
    if margen is None:
        return jsonify({"ok": False, "detalle": "Escribí un porcentaje entre 0 y 60."}), 400
    try:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            preferencias.guardar_margen_minimo(conexion.cursor(), g.cuenta_id, margen)
    except Exception as e:
        return jsonify({"ok": False, "detalle": _detalle_error(e)}), 500
    cache_guardar(construir_key("margenes_usuario", g.usuario_id), {str(k): v for k, v in preferencias.margenes_de_usuario(g.usuario_id).items()}, timeout=60)
    return jsonify({"ok": True, "margen_minimo": margen})


@app.route("/cuenta/descargar_datos", methods=["POST"])
@login_requerido
@auditar("datos_descargar")
def cuenta_descargar_datos():
    """Un zip con los datos de la persona (una carpeta por cuenta de Mercado Libre). Se lee con su propia conexión: la seguridad por cuenta decide qué sale."""
    cuentas = registro.obtener_cuentas_de_usuario(g.usuario_id)
    contenido, _ = mis_datos.armar_zip(g.usuario_id, cuentas)
    return send_file(io.BytesIO(contenido), mimetype="application/zip", as_attachment=True, download_name=f"corelux_mis_datos_{hoy_argentina().strftime('%Y%m%d')}.zip")


@app.route("/suscripcion")
@login_requerido
def suscripcion_vista():
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "SELECT plan, trial_termina_en, mp_suscripcion_id, suscripcion_activada_en, email FROM usuarios WHERE id = %s",
            (g.usuario_id,)
        )
        fila = cursor.fetchone()
    if not fila:
        return redirect(url_for("planes_vista"))
    plan, trial_termina_en, mp_id, activada_en, email = fila
    dias_trial = None
    if plan == "trial" and trial_termina_en:
        delta = trial_termina_en - datetime.now(timezone.utc)
        dias_trial = max(0, delta.days)

    # G4: mostrar el precio también como $/día — el mismo monto mensual
    # se siente más chico así, y ayuda a justificar el gasto de un
    # vistazo sin tener que hacer la cuenta uno mismo.
    precio_mensual = pagos.PRECIOS_PLAN.get(plan)
    precio_por_dia = round(precio_mensual / 30) if precio_mensual else None

    return render_template(
        "suscripcion.html",
        plan=plan, dias_trial=dias_trial,
        mp_suscripcion_id=mp_id, activada_en=activada_en, email=email,
        precio_mensual=precio_mensual, precio_por_dia=precio_por_dia,
        active_nav="suscripcion",
    )


@app.route("/suscripcion/iniciar", methods=["POST"])
@login_requerido
def suscripcion_iniciar():
    """Crea el link de pago en MP y redirige al usuario."""
    if not config.MP_ACCESS_TOKEN:
        return redirect(url_for("planes_vista", aviso="sin_pagos"))

    plan = request.form.get("plan", "")
    if plan not in ("base", "elite"):
        return redirect(url_for("planes_vista", aviso="plan_invalido"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT email FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()
    email = fila[0] if fila else f"usuario{g.usuario_id}@corelux.app"

    back_url = url_for("suscripcion_retorno", _external=True)
    try:
        init_point, preapproval_id = pagos.crear_link_suscripcion(plan, g.usuario_id, email, back_url)
    except Exception as e:
        print(f"[Pagos] ❌ Error creando suscripción para usuario {g.usuario_id}: {e}")
        return redirect(url_for("planes_vista", aviso="mp_error"))

    # Guardamos el preapproval_id antes de redirigir para poder actualizar el estado en el retorno
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE usuarios SET mp_suscripcion_id = %s WHERE id = %s",
            (preapproval_id, g.usuario_id)
        )

    return redirect(init_point)


@app.route("/suscripcion/retorno")
@login_requerido
def suscripcion_retorno():
    """
    MP redirige acá después de que el usuario autoriza (o rechaza) la suscripción.
    Consultamos el estado real de MP para actualizar el plan.
    """
    if not config.MP_ACCESS_TOKEN:
        return redirect(url_for("suscripcion_vista"))

    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT mp_suscripcion_id FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()

    mp_id = fila[0] if fila else None
    if not mp_id:
        return redirect(url_for("suscripcion_vista"))

    info = pagos.obtener_estado_suscripcion(mp_id)
    if info:
        status = info.get("status", "")
        ext_ref = info.get("external_reference", "")
        plan_str = ext_ref.split("|")[0] if "|" in ext_ref else ""
        if status == "authorized" and plan_str in ("base", "elite"):
            with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
                cursor = conexion.cursor()
                cursor.execute(
                    "UPDATE usuarios SET plan = %s, suscripcion_activada_en = now() WHERE id = %s",
                    (plan_str, g.usuario_id)
                )
            print(f"[Pagos] ✅ Usuario {g.usuario_id} activó plan {plan_str} vía retorno MP.")

    return redirect(url_for("suscripcion_vista"))


@app.route("/suscripcion/cancelar", methods=["POST"])
@login_requerido
@auditar("suscripcion_cancelar")
def suscripcion_cancelar():
    """Cancela la suscripción activa en MP y actualiza el plan."""
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT mp_suscripcion_id, plan FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila = cursor.fetchone()

    if not fila or not fila[0]:
        return jsonify({"ok": False, "detalle": "No hay suscripción activa para cancelar."}), 400

    mp_id, plan_actual = fila
    if plan_actual not in ("base", "elite"):
        return jsonify({"ok": False, "detalle": "Solo podés cancelar una suscripción paga."}), 400

    ok = pagos.cancelar_suscripcion(mp_id)
    if ok:
        with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute(
                "UPDATE usuarios SET plan = 'cancelado' WHERE id = %s",
                (g.usuario_id,)
            )
        print(f"[Pagos] ⚠️ Usuario {g.usuario_id} canceló su suscripción {mp_id}.")
        return jsonify({"ok": True})
    else:
        return jsonify({"ok": False, "detalle": "No se pudo cancelar en Mercado Pago. Intentá de nuevo o contactá soporte."}), 502


@app.route("/webhook/mercadopago", methods=["POST"])
def webhook_mercadopago():
    """
    Webhook de MP para actualizar estado de suscripciones automáticamente.
    MP manda esto cuando: cobro mensual exitoso, cobro fallido, cancelación.
    No requiere login — MP lo llama directamente.
    """
    data = request.get_json(silent=True) or {}
    data_id = request.args.get("data.id") or (data.get("data") or {}).get("id") or data.get("id")
    if not pagos.firma_valida(request.headers.get("x-signature"), request.headers.get("x-request-id"), data_id, config.MP_WEBHOOK_SECRET):
        app.logger.warning("Webhook de Mercado Pago con firma inválida (data.id=%s): se ignora.", data_id)
        return "", 401
    resultado = pagos.procesar_webhook(data)
    if not resultado:
        return "", 200  # MP espera 200 aunque ignoremos el evento

    usuario_id, nuevo_plan, preapproval_id = resultado
    try:
        with db.conexion_admin() as conexion:
            cursor = conexion.cursor()
            if nuevo_plan in ("base", "elite"):
                cursor.execute(
                    "UPDATE usuarios SET plan = %s, mp_suscripcion_id = %s, suscripcion_activada_en = COALESCE(suscripcion_activada_en, now()) WHERE id = %s",
                    (nuevo_plan, preapproval_id, usuario_id)
                )
            elif nuevo_plan == "cancelado":
                cursor.execute(
                    "UPDATE usuarios SET plan = 'cancelado' WHERE id = %s",
                    (usuario_id,)
                )
        print(f"[Pagos] 🔔 Webhook MP: usuario {usuario_id} → plan {nuevo_plan} (preapproval {preapproval_id})")
    except Exception as e:
        print(f"[Pagos] ❌ Error procesando webhook para usuario {usuario_id}: {e}")
        return "", 500

    return "", 200

# ─────────────────────────────────────────────────────────

# A nivel de módulo (no solo dentro de "python app.py" directo) —
# gunicorn importa este archivo como módulo y nunca ejecuta el bloque
# de más abajo, así que si esta llamada quedaba ahí adentro, correr la
# app por gunicorn (como en Railway) dejaba el sync automático sin
# arrancar NUNCA, en silencio. scheduler.iniciar_scheduler() ya decide
# cuál proceso corre las tareas (lock de Postgres), así que es seguro
# llamarlo siempre, una vez por proceso.
scheduler.iniciar_scheduler()

if __name__ == "__main__":
    if config.DEBUG:
        print("=" * 70)
        print("⚠️  FLASK_DEBUG=true — NUNCA expongas esta app por ngrok así.")
        print("    Con debug activado, un error muestra una consola de Python")
        print("    interactiva a cualquiera que la vea — es ejecución de código")
        print("    remoto en tu máquina, no un detalle menor.")
        print("=" * 70)

    # Waitress: servidor WSGI de producción para Windows.
    # Para Linux en producción, usar Gunicorn (ver gunicorn.conf.py).
    try:
        from waitress import serve
        print("[CoreLux] Iniciando con Waitress en http://0.0.0.0:5000")
        serve(app, host="0.0.0.0", port=5000, threads=8, channel_timeout=120)
    except ImportError:
        # Fallback a Flask dev server si waitress no está instalado todavía
        print("[CoreLux] Waitress no instalado — usando Flask dev server.")
        print("          Corré: pip install waitress")
        app.run(debug=config.DEBUG, host="0.0.0.0", port=5000, threaded=True)
