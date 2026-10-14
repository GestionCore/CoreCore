"""
«¿Sirve para cualquier rubro?»: un vendedor de electrónica no tiene talles. Sus variantes son «128 GB / Azul», «256 GB / Negro»: lo que distingue a cada una sale de los atributos que informa Mercado Libre.
Se arma esa cuenta con datos (publicaciones, variantes, ventas, costos en pesos y en dólares) dentro de una transacción que nunca se confirma, se recorren todas las pantallas y se verifica que:
  · ninguna falla;
  · en ningún texto que lee la persona aparece «talle» ni «talles»;
  · lo que distingue a cada variante («128 GB») sí aparece donde corresponde (Stock, Costos).
"""
import os
import re

import pytest

pytestmark = pytest.mark.db
if not os.getenv("DATABASE_URL"):
    pytest.skip("Sin DATABASE_URL: se omite el recorrido de una cuenta de electrónica", allow_module_level=True)

from tests.test_cuenta_nueva import _Compartida, _rutas_get, cliente_nuevo  # noqa: E402,F401  (cliente_nuevo es el fixture que usa este módulo)

BLOQUES_QUE_NO_LEE_NADIE = re.compile(r"<script\b.*?</script>|<style\b.*?</style>|<!--.*?-->", re.S | re.I)
ETIQUETAS_TAG = re.compile(r"<[^>]+>")
PALABRA_TALLE = re.compile(r"\btalles?\b", re.I)

MODELOS = [("Samsung Galaxy A15", "Celular Samsung Galaxy A15"), ("Motorola Moto G54", "Celular Motorola Moto G54"), ("Xiaomi Redmi 13", "Celular Xiaomi Redmi 13"), ("Apple iPhone 14", "Celular Apple iPhone 14")]
VARIANTES = [("128 GB / Azul", "128 GB", "Azul"), ("256 GB / Negro", "256 GB", "Negro")]


@pytest.fixture
def cliente_electronica(cliente_nuevo):
    cur = _Compartida.conexion.cursor()
    cuenta = _Compartida.cuenta
    cur.execute("SELECT set_config('app.cuenta_actual', %s, true)", (str(cuenta),))
    for i, (modelo, titulo) in enumerate(MODELOS):
        id_meli = f"MLAELEC{i}"
        cur.execute("""
            INSERT INTO productos_padre (cuenta_id, id_meli, titulo, precio, estado, category_id, precio_costo, recibis_estimado, family_id, domain_id)
            VALUES (%s, %s, %s, %s, 'active', 'MLA1055', %s, %s, %s, 'MLA-CELLPHONES') RETURNING id
        """, (cuenta, id_meli, f"{titulo} {VARIANTES[0][1]} Azul", 250000 + i * 40000, 160000 + i * 20000 if i < 3 else None, 200000 + i * 30000, f"FAM{i}"))
        id_padre = cur.fetchone()[0]
        for j, (etiqueta, memoria, color) in enumerate(VARIANTES):
            cur.execute("""
                INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, talle, color, atributos, etiqueta, stock_propio, stock_full)
                VALUES (%s, %s, %s, 'Único', %s, %s::jsonb, %s, %s, 0)
            """, (cuenta, f"{id_meli}-{j}", id_padre, color, f'{{"INTERNAL_MEMORY": "{memoria}", "COLOR": "{color}"}}', etiqueta, 0 if (i == 0 and j == 0) else 5))
            for k in range(6):
                cur.execute("""
                    INSERT INTO ventas (cuenta_id, id_orden, id_meli, id_variante, titulo, cantidad, precio_venta, cargo_venta, costo_envio, fecha_venta, hora_venta, origen, tipo_logistica, neto_recibido, hora_normalizada)
                    VALUES (%s, %s, %s, %s, %s, 1, %s, %s, 3500, current_date - %s, make_time(%s, 15, 0), 'meli', 'drop_off', %s, true)
                """, (cuenta, f"ELEC{i}-{j}-{k}", id_meli, f"{id_meli}-{j}", titulo, 250000 + i * 40000, 40000, (k * 3) % 25, 9 + k, 200000))
    return cliente_nuevo


def _texto_visible(html):
    return ETIQUETAS_TAG.sub(" ", BLOQUES_QUE_NO_LEE_NADIE.sub(" ", html))


def test_una_cuenta_de_electronica_recorre_todas_las_pantallas_sin_hablar_de_talles(cliente_electronica):
    malas, con_talle, total = [], [], 0
    for ruta in _rutas_get():
        total += 1
        try:
            r = cliente_electronica.get(ruta)
        except Exception as e:                                                                   # TESTING = True: una excepción sin atrapar llega hasta acá
            malas.append(f"{ruta} -> {type(e).__name__}: {str(e)[:110]}")
            continue
        if r.status_code == 500:
            malas.append(f"{ruta} -> 500")
            continue
        if r.status_code == 200 and r.mimetype == "text/html":
            coincidencias = PALABRA_TALLE.findall(_texto_visible(r.get_data(as_text=True)))
            if coincidencias:
                con_talle.append(f"{ruta} -> {len(coincidencias)} vez/veces")
    assert total > 40
    assert not malas, "\n".join(malas)
    assert not con_talle, "Pantallas que le hablan de talles a un vendedor de electrónica:\n" + "\n".join(con_talle)


def test_stock_y_costos_muestran_lo_que_distingue_a_cada_variante(cliente_electronica):
    for ruta in ("/stock", "/costos"):
        r = cliente_electronica.get(ruta)
        assert r.status_code == 200
        texto = _texto_visible(r.get_data(as_text=True))
        assert "128 GB" in texto and "256 GB" in texto, f"{ruta} no muestra la memoria que distingue a cada variante"


def test_los_datos_de_la_cuenta_de_electronica_se_arman_por_variante(cliente_electronica):
    r = cliente_electronica.get("/api/dashboard/ultimas_ventas")
    assert r.status_code == 200
    filas = r.get_json()
    assert filas and all(f["variante"] in {e for e, _, _ in VARIANTES} for f in filas), filas
    r = cliente_electronica.get("/api/cobertura_variantes")
    assert r.status_code == 200
