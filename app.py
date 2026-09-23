"""
CoreLux — esqueleto inicial con el flujo completo de OAuth 2.0 contra
Mercado Libre, multi-tenant, con Postgres/Supabase + Row Level Security.
"""
import os
import requests
from flask import Flask, request, session, redirect, url_for, render_template, g, jsonify, send_file
import config
from auth import oauth_meli, registro, token_manager
from auth.middleware import login_requerido, iniciar_sesion, cerrar_sesion, cambiar_cuenta_activa
import catalogo
import metricas as metricas_mod
import facturacion
import historial_precios as historial_precios_mod
import costos as costos_mod
import calculadora_costos
import simulador_costos
import logistica
import despacho as despacho_mod
import stock_masivo as stock_masivo_mod
import motor_combos
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
import timeline_publicacion
import exportador_redes
import scheduler
import ventas_manuales
from utils import formatear_moneda
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY


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
def _inyectar_cuentas_usuario():
    """
    Plan Elite multi-cuenta: obtener_cuentas_de_usuario ya existía en
    registro.py, pero no había ninguna pantalla que la usara — la app
    asumía una sola cuenta activa en sesión siempre. Esto la deja
    disponible en cualquier template sin que cada vista tenga que
    acordarse de pasarla; el navbar solo la muestra si hay más de una.
    """
    if not getattr(g, "usuario_id", None):
        return {}
    cuentas = registro.obtener_cuentas_de_usuario(g.usuario_id)
    cuenta_actual = next((c for c in cuentas if c["id"] == g.cuenta_id), None)
    return {"cuentas_disponibles": cuentas, "cuenta_actual": cuenta_actual}


from flask_compress import Compress
Compress(app)


@app.route("/")
def landing():
    if not session.get("usuario_id"):
        return render_template("landing.html")
    g.usuario_id = session["usuario_id"]
    g.cuenta_id = session["cuenta_id"]

    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT onboarding_completo FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila_onb = cursor.fetchone()
    if fila_onb and not fila_onb[0]:
        return redirect(url_for("onboarding_vista"))

    try:
        token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT sincronizacion_inicial_completa FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila_sync = cursor.fetchone()
    if fila_sync and not fila_sync[0]:
        return render_template("sincronizando.html")

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT pantalla_preferida FROM usuarios WHERE id = %s", (g.usuario_id,))
        fila_pref = cursor.fetchone()
    if fila_pref and fila_pref[0] == "dashboard":
        return redirect(url_for("dashboard_personalizable"))
    if fila_pref and fila_pref[0] == "metricas":
        return redirect(url_for("metricas_vista"))

    productos, stats = catalogo.obtener_productos_y_estadisticas(g.usuario_id)
    return render_template("index.html", productos=productos, stats=stats, active_nav="stock")


@app.route("/conectar")
def conectar():
    """Arranca el flujo — manda al usuario a la pantalla de autorización de MeLi."""
    state = oauth_meli.generar_state()
    session["oauth_state"] = state
    return redirect(oauth_meli.construir_url_autorizacion(state))


@app.route("/callback")
def callback():
    """MeLi redirige acá después de que el usuario aprueba (o rechaza) el permiso."""
    error = request.args.get("error")
    if error:
        return render_template("error_conexion.html", motivo=f"Mercado Libre informó un error: {error}")

    code = request.args.get("code")
    state_recibido = request.args.get("state")
    state_esperado = session.pop("oauth_state", None)

    if not code:
        return render_template("error_conexion.html", motivo="No llegó el código de autorización.")
    if not state_esperado or state_recibido != state_esperado:
        return render_template("error_conexion.html", motivo="El parámetro de seguridad (state) no coincide — por las dudas, volvé a intentar conectar.")

    ok, resultado = oauth_meli.intercambiar_codigo_por_token(code)
    if not ok:
        return render_template("error_conexion.html", motivo=resultado)

    ok_datos, datos_meli = oauth_meli.obtener_datos_usuario_meli(resultado["access_token"])
    if not ok_datos:
        return render_template("error_conexion.html", motivo=datos_meli)

    usuario_id, cuenta_id, es_nuevo = registro.crear_o_actualizar_login(datos_meli)

    token_manager.guardar_tokens(
        cuenta_id, resultado["access_token"], resultado["refresh_token"], resultado["expires_in"]
    )

    iniciar_sesion(usuario_id, cuenta_id)

    # Disparamos la sincronización en segundo plano acá mismo, apenas
    # conecta — así no espera al primer clic en "Sincronizar Todo".
    # No bloqueamos la respuesta (podría tardar minutos con un catálogo
    # grande): redirigimos ya, y login_requerido muestra la pantalla de
    # espera hasta que sincronizacion_inicial_completa quede en true.
    import threading
    threading.Thread(target=sincronizador.sincronizar_todo, args=(usuario_id, cuenta_id), daemon=True).start()

    return redirect(url_for("landing"))


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

    if topic and meli_user_id:
        import threading
        threading.Thread(
            target=sincronizador.procesar_notificacion_webhook,
            args=(topic, resource, meli_user_id), daemon=True
        ).start()

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


@app.route("/cambiar_cuenta/<int:cuenta_id>")
@login_requerido
def cambiar_cuenta(cuenta_id):
    """Plan Elite: cambiar cuál cuenta de MeLi conectada está viendo el usuario."""
    cambiar_cuenta_activa(cuenta_id)
    return redirect(url_for("dashboard_personalizable"))


@app.route("/api/hoy")
@login_requerido
def api_hoy():
    return jsonify(dashboard_mod.obtener_ventas_hoy(g.usuario_id))


@app.route("/api/ticker")
@login_requerido
def api_ticker():
    return jsonify(dashboard_mod.obtener_ticker(g.usuario_id, g.cuenta_id))


@app.route("/api/quiebre_stock")
@login_requerido
def api_quiebre_stock():
    return jsonify(dashboard_mod.obtener_quiebre_stock(g.usuario_id))


@app.route("/api/resumen_diario")
@login_requerido
def api_resumen_diario():
    try:
        return jsonify(dashboard_mod.obtener_resumen_diario(g.usuario_id))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error en resumen diario: {e}")
        return jsonify(None)


@app.route("/api/dashboard/tendencia_ventas")
@login_requerido
def api_dashboard_tendencia_ventas():
    try:
        return jsonify(dashboard_mod.obtener_tendencia_ventas(g.usuario_id))
    except Exception as e:
        print(f"[Dashboard] ⚠️ Error en tendencia de ventas: {e}")
        return jsonify({"serie": [], "total_formateado": "0,00", "promedio_diario_formateado": "0,00"})


@app.route("/api/dashboard/tendencia_ventas.png")
@login_requerido
def api_dashboard_tendencia_ventas_png():
    """Descarga del gráfico de tendencia como imagen — botón de exportar del widget."""
    import graficos_export
    datos = dashboard_mod.obtener_tendencia_ventas(g.usuario_id)
    serie = [{"etiqueta": p["fecha"], "valor": p["facturado"]} for p in datos["serie"]]
    buffer = graficos_export.generar_barras_png(
        serie, titulo=f"Tendencia de Ventas — últimos {len(serie)} días",
        subtitulo=f"Total del período: ${datos['total_formateado']}"
    )
    return send_file(buffer, mimetype="image/png", as_attachment=True, download_name="tendencia_ventas.png")


@app.route("/api/dashboard/reclamos_resumen")
@login_requerido
def api_dashboard_reclamos_resumen():
    return jsonify(dashboard_mod.obtener_reclamos_resumen(g.usuario_id))


@app.route("/api/dashboard/costos_resumen")
@login_requerido
def api_dashboard_costos_resumen():
    return jsonify(dashboard_mod.obtener_costos_resumen(g.usuario_id))


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
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        resultado = logros_mod.obtener_logros(cursor, g.cuenta_id, headers)
    if resultado["misiones"]:
        m = resultado["misiones"][0]
        return jsonify({"hay_mision": True, "titulo": m["titulo"], "descripcion": m["descripcion"], "prioridad": m["prioridad"], "link": m["link"]})
    return jsonify({"hay_mision": False})


@app.route("/dashboard")
@login_requerido
def dashboard_personalizable():
    try:
        token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    return render_template("dashboard_personalizable.html", active_nav="dashboard")


@app.route("/metricas")
@login_requerido
def metricas_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    fecha_hasta = request.args.get("fecha_hasta") or datetime.now().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    datos = metricas_mod.calcular_ganancia_real(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)

    return render_template(
        "metricas.html", ventas=datos["ventas"], consolidados=datos["consolidados"],
        resumen=datos["resumen"], ads_disponible=datos["ads_disponible"],
        gasto_ads_total_periodo=datos["gasto_ads_total_periodo"], posventa=datos["posventa"],
        comparacion_anterior=datos["comparacion_anterior"],
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
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

    fecha_hasta = request.args.get("fecha_hasta") or datetime.now().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
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

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    seller_id = fila[0] if fila else None

    campanias = promociones_mod.obtener_promociones_usuario(access_token, seller_id) if seller_id else []
    campanias_activas = [c for c in campanias if c.get("status") in ("started", "active")]

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_meli, titulo, precio, precio_original FROM productos_padre
            WHERE estado = 'active' AND precio_original IS NOT NULL AND precio_original > precio
        """)
        con_descuento = [
            {"id": r[0], "titulo": r[1], "precio_formateado": formatear_moneda(r[2]),
             "precio_original_formateado": formatear_moneda(r[3]), "descuento_pct": round((1 - float(r[2]) / float(r[3])) * 100)}
            for r in cursor.fetchall()
        ]

        cursor.execute("SELECT id_meli, titulo, precio, precio_costo FROM productos_padre WHERE estado = 'active' ORDER BY titulo")
        catalogo_promo = [{"id": r[0], "titulo": r[1], "precio": r[2], "precio_costo": r[3]} for r in cursor.fetchall()]

        combos_sugeridos = motor_combos.obtener_combos_sugeridos(cursor)
        impacto_promociones = promociones_mod.obtener_impacto_promociones(cursor)
        sugerencias_promocion = promociones_mod.sugerir_candidatos_promocion(cursor)
        promociones_por_vencer = promociones_mod.obtener_promociones_por_vencer(cursor)

    return render_template(
        "promociones.html", campanias=campanias_activas, con_descuento=con_descuento,
        catalogo=catalogo_promo, ofertas_relampago=[], combos_sugeridos=combos_sugeridos,
        impacto_promociones=impacto_promociones, sugerencias_promocion=sugerencias_promocion,
        promociones_por_vencer=promociones_por_vencer, active_nav="promociones"
    )


@app.route("/promociones/crear_descuento", methods=["POST"])
@login_requerido
def crear_descuento():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    id_meli = request.form.get("id_meli")
    deal_price = float(request.form.get("deal_price"))
    fecha_desde = request.form.get("fecha_desde")
    fecha_hasta = request.form.get("fecha_hasta")

    ok, detalle = promociones_mod.crear_descuento_individual(access_token, id_meli, deal_price, fecha_desde, fecha_hasta)
    if ok:
        with db.conexion_usuario(g.usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("SELECT titulo, precio FROM productos_padre WHERE id_meli = %s", (id_meli,))
            fila_producto = cursor.fetchone()
            if fila_producto:
                promociones_mod.registrar_inicio_promocion(cursor, g.cuenta_id, id_meli, fila_producto[0], fila_producto[1], deal_price, fecha_hasta)
    return redirect("/promociones")


@app.route("/promociones/eliminar_descuento/<id_meli>", methods=["POST"])
@login_requerido
def eliminar_descuento(id_meli):
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    promociones_mod.eliminar_promocion_item(access_token, id_meli, "PRICE_DISCOUNT")
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        promociones_mod.cerrar_promocion_activa(cursor, id_meli)
    return redirect("/promociones")


@app.route("/tendencias")
@login_requerido
def tendencias_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        category_id, categoria_nombre = tendencias_mod.obtener_categoria_principal(access_token, g.cuenta_id, cursor)

        lista = tendencias_mod.obtener_tendencias(access_token, category_id=category_id)
        relevantes = [t for t in lista if t.get("relevante")]
        resto = [] if category_id else [t for t in lista if not t.get("relevante")]

        oportunidades = tendencias_mod.cruzar_tendencias_con_catalogo(relevantes, cursor)
        terminos_oportunidad = {o["termino"]: o for o in oportunidades}

        canibalismo = tendencias_mod.detectar_canibalismo(cursor)

        keywords_de_hoy = [t.get("keyword") for t in lista if t.get("keyword")]
        emergentes = tendencias_mod.registrar_y_detectar_emergentes(cursor, g.cuenta_id, keywords_de_hoy)

        seo_scores = tendencias_mod.calcular_seo_scores_catalogo(cursor, relevantes)
        coincide_con_competencia = tendencias_mod.cruzar_tendencias_con_competencia(relevantes, cursor)
        calendario_estacional = tendencias_mod.obtener_calendario_estacional()

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
        calendario_estacional=calendario_estacional, categoria_nombre=categoria_nombre, active_nav="tendencias"
    )


@app.route("/api/tendencias/explorar_demanda")
@login_requerido
def api_tendencias_explorar_demanda():
    termino = request.args.get("q", "").strip()
    if not termino:
        return jsonify({"error": "Escribí un término para buscar."})
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None  # /sites/{id}/search es publico, no hace falta token
    resultado = tendencias_mod.explorar_demanda(access_token, termino)
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

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        resultado = logros_mod.obtener_logros(cursor, g.cuenta_id, headers)

    conteo_por_prioridad = {"urgente": 0, "importante": 0, "opcional": 0}
    for m in resultado["misiones"]:
        conteo_por_prioridad[m["prioridad"]] = conteo_por_prioridad.get(m["prioridad"], 0) + 1

    return render_template(
        "logros.html", misiones=resultado["misiones"], mensaje_todo_bien=resultado["mensaje_todo_bien"],
        mensaje_coach=resultado.get("mensaje_coach"), conteo_por_prioridad=conteo_por_prioridad,
        logros_resueltos=resultado.get("logros_resueltos", []), recien_resueltas=resultado.get("recien_resueltas", 0),
        active_nav="logros"
    )


@app.route("/embudo_conversion")
@login_requerido
def embudo_conversion_vista():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))
    headers = {"Authorization": f"Bearer {access_token}"}

    with db.conexion_usuario(g.usuario_id) as conexion:
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

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT meli_user_id FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    if not fila:
        return "No se encontró tu cuenta.", 401

    datos = reputacion_mod.obtener_reputacion(access_token, fila[0])
    return render_template("reputacion.html", rep=datos, active_nav="reputacion")


@app.route("/competencia")
@login_requerido
def competencia_vista():
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        rivales = espia_competencia.obtener_panorama_competencia(cursor)
    return render_template("competencia.html", rivales=rivales, active_nav="competencia")


@app.route("/competencia/agregar", methods=["POST"])
@login_requerido
def competencia_agregar():
    import db
    id_meli_rival = request.form.get("id_meli_rival", "").strip()
    alias = request.form.get("alias", "").strip()
    if id_meli_rival:
        with db.conexion_usuario(g.usuario_id) as conexion:
            cursor = conexion.cursor()
            espia_competencia.agregar_competidor(cursor, g.cuenta_id, id_meli_rival, alias)
    return redirect("/competencia")


@app.route("/competencia/eliminar/<id_meli_rival>", methods=["POST"])
@login_requerido
def competencia_eliminar(id_meli_rival):
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        espia_competencia.eliminar_competidor(cursor, id_meli_rival)
    return redirect("/competencia")


@app.route("/comparador_logistica")
@login_requerido
def comparador_logistica_vista():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    fecha_hasta = request.args.get("fecha_hasta") or datetime.now().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

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

    fecha_hasta = request.args.get("fecha_hasta") or datetime.now().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or (datetime.now() - timedelta(days=13)).strftime("%Y-%m-%d")

    datos = publicidad_mod.calcular_datos_publicidad(g.usuario_id, g.cuenta_id, access_token, fecha_desde, fecha_hasta)
    if datos is None:
        return render_template("publicidad.html", ads_disponible=False, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, active_nav="publicidad")

    return render_template(
        "publicidad.html", ads_disponible=True, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
        active_nav="publicidad", **datos
    )


@app.route("/sincronizar_todo", methods=["GET", "POST"])
@login_requerido
def sincronizar_manual():
    sincronizador.sincronizar_todo(g.usuario_id, g.cuenta_id)
    return jsonify({"status": "iniciado"})


@app.route("/api/curva_talles")
@login_requerido
def api_curva_talles():
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        resultado = analisis_stock.evaluar_curva_talles(cursor)
    return jsonify(resultado)


@app.route("/api/oportunidades_seo")
@login_requerido
def api_oportunidades_seo():
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify([])

    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        category_id, _ = tendencias_mod.obtener_categoria_principal(access_token, g.cuenta_id, cursor)
        lista = tendencias_mod.obtener_tendencias(access_token, category_id=category_id)
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
    prioridad = request.form.get("prioridad_principal")
    experiencia = request.form.get("experiencia_meli")
    pantalla = request.form.get("pantalla_preferida")
    ok = onboarding.guardar_respuestas(g.usuario_id, prioridad, experiencia, pantalla)
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
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("SELECT sincronizacion_inicial_completa FROM cuentas_meli WHERE id = %s", (g.cuenta_id,))
        fila = cursor.fetchone()
    return jsonify({"lista": bool(fila and fila[0])})


@app.route("/publicacion/<id_meli>/timeline")
@login_requerido
def timeline_publicacion_vista(id_meli):
    import db
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        access_token = None

    with db.conexion_usuario(g.usuario_id) as conexion:
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
    with db.conexion_usuario(g.usuario_id) as conexion:
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
        resp = requests.get(f"https://api.mercadolibre.com/items/{id_meli}", headers=headers, timeout=8)
        if resp.status_code == 200:
            fotos = resp.json().get("pictures", [])
            if fotos:
                url_foto = fotos[0].get("url", url_foto)
    except Exception:
        pass

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
def monotributo_declarar():
    categoria = request.form.get("categoria_monotributo") or None
    monotributo.guardar_categoria_declarada(g.usuario_id, g.cuenta_id, categoria)
    return redirect(url_for("monotributo_vista"))


@app.route("/api/costos_chat", methods=["POST"])
@login_requerido
def api_costos_chat():
    datos = request.get_json(silent=True) or {}
    historial = datos.get("historial", [])
    if not historial or not isinstance(historial, list):
        return jsonify({"accion": "error", "mensaje": "Faltó el mensaje."}), 400
    resultado = costos_chat.procesar_mensaje(historial)
    return jsonify(resultado)


@app.route("/api/costos_chat/confirmar", methods=["POST"])
@login_requerido
def api_costos_chat_confirmar():
    datos = request.get_json(silent=True) or {}
    propuesta = datos.get("propuesta")
    if not propuesta:
        return jsonify({"ok": False, "error": "Falta la propuesta."}), 400
    ok, mensaje = costos_chat.confirmar_y_guardar(g.usuario_id, g.cuenta_id, propuesta)
    return jsonify({"ok": ok, "error": None if ok else mensaje})


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
        return f"No se pudo traer tus períodos de facturación de MeLi ahora mismo ({e}). Probá de nuevo en un rato.", 502

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
    barra_segmentos = None

    if periodo_actual:
        fecha_desde_periodo = periodo_actual.get("period", {}).get("date_from")
        fecha_hasta_periodo = periodo_actual.get("period", {}).get("date_to")

        if fecha_desde_periodo and fecha_hasta_periodo:
            import db
            with db.conexion_usuario(g.usuario_id) as conexion:
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
                pct_neto = max(facturado_bruto - pct_comision - pct_envios - pct_publicidad, 0)
                barra_segmentos = {
                    "comision": round((pct_comision / facturado_bruto) * 100, 1),
                    "envios": round((pct_envios / facturado_bruto) * 100, 1),
                    "publicidad": round((pct_publicidad / facturado_bruto) * 100, 1),
                    "neto": round((pct_neto / facturado_bruto) * 100, 1)
                }

    periodos_vista = [
        {"key": p.get("key"), "date_from": p.get("period", {}).get("date_from"),
         "date_to": p.get("period", {}).get("date_to"), "en_curso": p.get("period_status") == "OPEN"}
        for p in periodos
    ]

    return render_template(
        "facturacion.html", periodos=periodos_vista, key_seleccionada=key_seleccionada, cargos=cargos,
        total_cargos_formateado=formatear_moneda(total_cargos), pagos_cobrados_formateado=formatear_moneda(pagos_cobrados),
        pendiente_formateado=formatear_moneda(pendiente), percepciones_formateado=formatear_moneda(percepciones_total),
        total_adeudado_formateado=formatear_moneda(total_adeudado),
        facturado_bruto_formateado=formatear_moneda(facturado_bruto),
        ganancia_bruta_formateada=formatear_moneda(ganancia_bruta_real),
        ganancia_neta_formateada=formatear_moneda(ganancia_neta_final),
        ganancia_neta_negativa=ganancia_neta_final < 0,
        barra_segmentos=barra_segmentos, active_nav="facturacion"
    )


@app.route("/historial_precios")
@login_requerido
def historial_precios_vista():
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cambios = historial_precios_mod.obtener_historial_con_impacto(cursor)
    return render_template("historial_precios.html", cambios=cambios, active_nav="historial_precios")


@app.route("/costos")
@login_requerido
def costos_vista():
    fecha_hasta = request.args.get("fecha_hasta") or datetime.now().strftime("%Y-%m-%d")
    fecha_desde = request.args.get("fecha_desde") or datetime.now().replace(day=1).strftime("%Y-%m-%d")
    gastos, stats, productos = costos_mod.obtener_datos_costos(g.usuario_id, fecha_desde, fecha_hasta)
    return render_template("costos.html", gastos=gastos, stats=stats, productos=productos, fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, active_nav="costos")


@app.route("/ventas_manuales")
@login_requerido
def ventas_manuales_vista():
    """Registrar ventas por fuera de MeLi (mostrador, canal directo) — entran a Ganancia Real igual que las reales."""
    catalogo = ventas_manuales.obtener_catalogo_para_selector(g.usuario_id, g.cuenta_id)
    recientes = ventas_manuales.obtener_ventas_manuales_recientes(g.usuario_id, g.cuenta_id)
    return render_template(
        "ventas_manuales.html", catalogo=catalogo, ventas=recientes,
        hoy=datetime.now().strftime("%Y-%m-%d"), active_nav="ventas_manuales"
    )


@app.route("/ventas_manuales/agregar", methods=["POST"])
@login_requerido
def ventas_manuales_agregar():
    ok, error = ventas_manuales.registrar_venta_manual(
        g.usuario_id, g.cuenta_id,
        request.form.get("id_variante"), request.form.get("cantidad"),
        request.form.get("precio_venta"), request.form.get("fecha_venta"),
        request.form.get("comprador_nombre", "").strip(),
    )
    if not ok:
        return render_template(
            "ventas_manuales.html",
            catalogo=ventas_manuales.obtener_catalogo_para_selector(g.usuario_id, g.cuenta_id),
            ventas=ventas_manuales.obtener_ventas_manuales_recientes(g.usuario_id, g.cuenta_id),
            hoy=datetime.now().strftime("%Y-%m-%d"), active_nav="ventas_manuales", error=error
        ), 400
    return redirect(url_for("ventas_manuales_vista"))


@app.route("/ventas_manuales/eliminar/<int:id_venta>", methods=["POST"])
@login_requerido
def ventas_manuales_eliminar(id_venta):
    ventas_manuales.eliminar_venta_manual(g.usuario_id, g.cuenta_id, id_venta)
    return redirect(url_for("ventas_manuales_vista"))


@app.route("/agregar_gasto", methods=["POST"])
@login_requerido
def agregar_gasto():
    import db
    concepto = request.form.get("concepto", "").strip()
    categoria = request.form.get("categoria")
    monto = float(request.form.get("monto", 0.0))
    fecha = request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    if concepto and monto > 0:
        with db.conexion_usuario(g.usuario_id) as conexion:
            cursor = conexion.cursor()
            cursor.execute("INSERT INTO gastos_operativos (cuenta_id, concepto, categoria, monto, fecha) VALUES (%s, %s, %s, %s, %s)", (g.cuenta_id, concepto, categoria, monto, fecha))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/guardar_costo_producto/<id_meli>", methods=["POST"])
@login_requerido
def guardar_costo_producto(id_meli):
    import db
    nuevo_costo = float(request.form.get("precio_costo", 0.0))
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE id_meli = %s", (nuevo_costo, id_meli))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/guardar_costos_masivo", methods=["POST"])
@login_requerido
def guardar_costos_masivo():
    import db
    data = request.get_json(silent=True) or {}
    costos_dict = data.get("costos", {})
    if not costos_dict:
        return jsonify({"ok": False, "error": "Nada para guardar"}), 400
    actualizados = 0
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        for id_meli, nuevo_costo in costos_dict.items():
            try:
                cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE id_meli = %s", (float(nuevo_costo), id_meli))
                actualizados += cursor.rowcount
            except (ValueError, TypeError):
                continue
    return jsonify({"ok": True, "actualizados": actualizados})


@app.route("/eliminar_gasto/<int:id_gasto>", methods=["POST"])
@login_requerido
def eliminar_gasto(id_gasto):
    import db
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("DELETE FROM gastos_operativos WHERE id = %s", (id_gasto,))
    return redirect(f"/costos?fecha_desde={request.form.get('fecha_desde')}&fecha_hasta={request.form.get('fecha_hasta')}")


@app.route("/despacho")
@login_requerido
def despacho_vista():
    import db
    fecha = request.args.get("fecha") or datetime.now().strftime("%Y-%m-%d")

    hora_corte = 11
    flex_habilitado = False
    access_token = None
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return redirect(url_for("reconectar"))

    with db.conexion_usuario(g.usuario_id) as conexion:
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
    paquetes, total, listos, cantidad_shipments = despacho_mod.obtener_paquetes_del_dia(g.usuario_id, g.cuenta_id, access_token, fecha, offset_horas)

    return render_template(
        "despacho.html", paquetes=paquetes, fecha=fecha, total=total, listos=listos,
        cantidad_shipments=cantidad_shipments, hora_corte=hora_corte,
        flex_habilitado=flex_habilitado, active_nav="despacho"
    )


@app.route("/api/calculadora_categorias")
@login_requerido
def api_calculadora_categorias():
    try:
        access_token = token_manager.asegurar_token_valido(g.cuenta_id)
    except token_manager.CuentaDesconectada:
        return jsonify({"error": "Cuenta desconectada"}), 401
    import db
    headers = {"Authorization": f"Bearer {access_token}"}
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        categorias = calculadora_costos.obtener_categorias_del_catalogo(headers, cursor)
    return jsonify(categorias)


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


@app.route("/stock_masivo")
@login_requerido
def stock_masivo_vista():
    modelos = stock_masivo_mod.obtener_modelos_agrupados(g.usuario_id)
    return render_template("stock_masivo.html", modelos=modelos, active_nav="stock_masivo")


@app.route("/despacho/marcar", methods=["POST"])
@login_requerido
def despacho_marcar():
    import db
    data = request.get_json(silent=True) or {}
    id_orden = data.get("id_orden")
    id_meli = data.get("id_meli")
    id_variante = data.get("id_variante")
    nuevo_estado = bool(data.get("despachado"))
    with db.conexion_usuario(g.usuario_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute(
            "UPDATE ventas SET despachado = %s WHERE id_orden = %s AND id_meli = %s AND id_variante = %s",
            (nuevo_estado, id_orden, id_meli, id_variante)
        )
    return jsonify({"ok": True})


if __name__ == "__main__":
    if config.DEBUG:
        print("=" * 70)
        print("⚠️  FLASK_DEBUG=true — NUNCA expongas esta app por ngrok así.")
        print("    Con debug activado, un error muestra una consola de Python")
        print("    interactiva a cualquiera que la vea — es ejecución de código")
        print("    remoto en tu máquina, no un detalle menor.")
        print("=" * 70)
    scheduler.iniciar_scheduler()
    app.run(debug=config.DEBUG, host="0.0.0.0", port=5000, threaded=True)
