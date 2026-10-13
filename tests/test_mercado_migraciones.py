"""
Migraciones 0045 (mercado global) y 0046 (variantes por atributos y costo en dólares) del pivot multi-rubro (docs/PIVOT_SAAS.md).

Dos tipos de prueba:
  · estáticas: leen los .sql (aditivas, idempotentes, sin tocar lo que ya existe, tablas globales de solo lectura para la app);
  · contra la base real, SIEMPRE dentro de una transacción que se revierte: aplican las dos migraciones (dos veces, para comprobar que son idempotentes) y miran el resultado.
    Funcionan igual si las migraciones todavía no se aplicaron o si ya se aplicaron, así que no ponen en rojo a `predeploy.py`.

Cuando una migración posterior elimine `talle` y `color` de productos_variantes, la prueba del relleno tiene que dejar de insertarlos (ver el aviso en su docstring).
"""
import os
import re

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CON_BASE = pytest.mark.skipif(not os.getenv("DATABASE_URL"), reason="Sin DATABASE_URL")

TABLAS_GLOBALES = ("mercado_categorias", "mercado_categoria_diaria", "mercado_keywords", "mercado_tendencias_diaria", "mercado_keyword_estado", "mercado_relevamientos", "cotizaciones_dolar")


def _leer(nombre):
    return open(os.path.join(RAIZ, "migrations", nombre), encoding="utf-8").read()


def _sin_comentarios(sql):
    return "\n".join(re.sub(r"--.*$", "", linea) for linea in sql.splitlines())


MERCADO = _sin_comentarios(_leer("0045_mercado_global.sql"))
VARIANTES = _sin_comentarios(_leer("0046_variantes_atributos_y_costo.sql"))


# ── Estáticas ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_las_migraciones_son_aditivas_e_idempotentes():
    for sql in (MERCADO, VARIANTES):
        assert not re.search(r"\bDROP\s+(TABLE|COLUMN)\b", sql, re.I), "una migración aditiva no borra tablas ni columnas"
        assert not re.search(r"CREATE\s+TABLE\s+(?!IF NOT EXISTS)", sql, re.I)
        assert not re.search(r"ADD\s+COLUMN\s+(?!IF NOT EXISTS)", sql, re.I)
        assert not re.search(r"CREATE\s+(UNIQUE\s+)?INDEX\s+(?!IF NOT EXISTS)", sql, re.I)
    assert "talle" not in re.findall(r"DROP\s+COLUMN\s+(\w+)", VARIANTES, re.I)


def test_las_tablas_de_mercado_son_globales_y_la_app_solo_las_lee():
    assert "cuenta_id" not in MERCADO and "cuenta_id" not in re.search(r"CREATE TABLE IF NOT EXISTS cotizaciones_dolar.*?\);", VARIANTES, re.S).group(0)
    for tabla in TABLAS_GLOBALES:
        origen = MERCADO if tabla != "cotizaciones_dolar" else VARIANTES
        assert re.search(rf"CREATE TABLE IF NOT EXISTS {tabla}\b", origen), tabla
        assert re.search(rf"ALTER TABLE {tabla}\s+ENABLE ROW LEVEL SECURITY", origen), f"{tabla} sin RLS"
        assert re.search(rf"CREATE POLICY \w+ ON {tabla} FOR SELECT TO app_backend USING \(true\)", origen), f"{tabla} sin política de lectura"
    permisos = re.findall(r"GRANT\s+([A-Z, ]+?)\s+ON\s+([\w, ]+?)\s+TO\s+app_backend", MERCADO + VARIANTES)
    for privilegios, tablas in permisos:
        if any(t.strip() in TABLAS_GLOBALES for t in tablas.split(",")):
            assert privilegios.strip() == "SELECT", f"la app no escribe en {tablas}: {privilegios}"


def test_la_migracion_de_variantes_pide_el_candado_con_tope_de_espera():
    assert "SET LOCAL lock_timeout" in VARIANTES.split("ALTER TABLE")[0]


def test_las_versiones_de_las_migraciones_no_se_repiten():
    versiones = [n[:4] for n in os.listdir(os.path.join(RAIZ, "migrations")) if n.endswith(".sql")]
    assert len(versiones) == len(set(versiones))


# ── Contra la base real (siempre revertidas) ─────────────────────────────────────────────────────────────────────────────────────────────
class _Revertir(Exception):
    pass


def _aplicar_dos_veces(cur):
    cur.execute("SET LOCAL lock_timeout = '5s'")
    for _ in range(2):
        cur.execute(_leer("0045_mercado_global.sql"))
        cur.execute(_leer("0046_variantes_atributos_y_costo.sql"))


def _rechaza(cur, sql, params=None):
    cur.execute("SAVEPOINT r")
    try:
        cur.execute(sql, params)
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT r")
        return True
    cur.execute("RELEASE SAVEPOINT r")
    return False


@CON_BASE
def test_las_migraciones_corren_dos_veces_y_rellenan_la_etiqueta_de_las_variantes_existentes():
    """Ojo: inserta con las columnas viejas `talle` y `color`; si una migración futura las elimina, este caso hay que reescribirlo."""
    import db
    resultado = {}
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            cur.execute("SET LOCAL lock_timeout = '5s'")
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            fila = cur.fetchone()
            if not fila:
                pytest.skip("Hace falta al menos una cuenta en la base")
            cuenta = fila[0]
            cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo) VALUES (%s, 'MLA_PRUEBA_0046', 'x') RETURNING id", (cuenta,))
            padre = cur.fetchone()[0]
            for sufijo, talle, color in (("1", "M", "Negro"), ("2", "Único", "Único"), ("3", "Único", "Azul"), ("4", "XL", "Único"), ("5", None, None)):
                cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre, talle, color) VALUES (%s, %s, %s, %s, %s)", (cuenta, "PRUEBA_0046_" + sufijo, padre, talle, color))
            _aplicar_dos_veces(cur)
            cur.execute("SELECT id_variante, etiqueta, atributos FROM productos_variantes WHERE id_variante LIKE 'PRUEBA_0046_%' ORDER BY 1")
            resultado["variantes"] = {f[0][-1]: (f[1], f[2]) for f in cur.fetchall()}
            cur.execute("SELECT DISTINCT moneda_costo FROM productos_padre")
            resultado["monedas"] = {f[0] for f in cur.fetchall()}
            cur.execute("SELECT nombre FROM mercado_categorias WHERE category_id = 'MLA'")
            resultado["sitio"] = cur.fetchone()
            raise _Revertir()
    except _Revertir:
        pass
    v = resultado["variantes"]
    assert v["1"][0] == "M / Negro" and [a["id"] for a in v["1"][1]] == ["SIZE", "COLOR"]
    assert v["2"] == ("Única", []) and v["5"] == ("Única", [])                     # «Único» y vacío no son un atributo
    assert v["3"][0] == "Azul" and v["4"][0] == "XL"
    assert all(a["origen"] == "legado" for _, atributos in v.values() for a in atributos)
    assert resultado["monedas"] == {"ARS"}                                           # lo que ya existe sigue en pesos
    assert resultado["sitio"] == ("Todo Mercado Libre",)


@CON_BASE
def test_las_restricciones_de_las_tablas_nuevas_rechazan_lo_invalido():
    import db
    rechazos = {}
    aceptados = {}
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            _aplicar_dos_veces(cur)
            cur.execute("SELECT id FROM cuentas_meli ORDER BY id LIMIT 1")
            fila = cur.fetchone()
            cuenta = fila[0] if fila else None
            if cuenta:
                cur.execute("INSERT INTO productos_padre (cuenta_id, id_meli, titulo) VALUES (%s, 'MLA_PRUEBA_0046B', 'x') RETURNING id", (cuenta,))
                padre = cur.fetchone()[0]
                cur.execute("INSERT INTO productos_variantes (cuenta_id, id_variante, id_padre) VALUES (%s, 'PRUEBA_0046_B', %s)", (cuenta, padre))
                rechazos["moneda_padre"] = _rechaza(cur, "UPDATE productos_padre SET moneda_costo = 'EUR' WHERE id = %s", (padre,))
                rechazos["moneda_variante"] = _rechaza(cur, "UPDATE productos_variantes SET moneda_costo = 'EUR' WHERE id_variante = 'PRUEBA_0046_B'")
                rechazos["costo_negativo"] = _rechaza(cur, "UPDATE productos_variantes SET precio_costo = -1 WHERE id_variante = 'PRUEBA_0046_B'")
                aceptados["costo_usd"] = not _rechaza(cur, "UPDATE productos_variantes SET precio_costo = 150, moneda_costo = 'USD' WHERE id_variante = 'PRUEBA_0046_B'")
            rechazos["palabra_con_mayusculas"] = _rechaza(cur, "INSERT INTO mercado_keywords (texto) VALUES ('iPhone 15')")
            rechazos["palabra_vacia"] = _rechaza(cur, "INSERT INTO mercado_keywords (texto) VALUES ('')")
            aceptados["palabra"] = not _rechaza(cur, "INSERT INTO mercado_keywords (texto) VALUES ('iphone 15')")
            rechazos["dolar_cero"] = _rechaza(cur, "INSERT INTO cotizaciones_dolar (fecha, casa, venta, fuente) VALUES (current_date, 'blue', 0, 'x')")
            rechazos["dolar_casa_invalida"] = _rechaza(cur, "INSERT INTO cotizaciones_dolar (fecha, casa, venta, fuente) VALUES (current_date, 'paralelo', 1500, 'x')")
            aceptados["dolar"] = not _rechaza(cur, "INSERT INTO cotizaciones_dolar (fecha, casa, venta, fuente) VALUES (current_date, 'bolsa', 1538.4, 'prueba')")
            rechazos["categoria_inexistente"] = _rechaza(cur, "INSERT INTO mercado_tendencias_diaria (category_id, fecha, keywords) VALUES ('MLA_NO_EXISTE', current_date, ARRAY[1])")
            rechazos["demasiadas_palabras"] = _rechaza(cur, "INSERT INTO mercado_tendencias_diaria (category_id, fecha, keywords) SELECT 'MLA', current_date, array_agg(g) FROM generate_series(1, 101) g")
            aceptados["tendencias"] = not _rechaza(cur, "INSERT INTO mercado_tendencias_diaria (category_id, fecha, keywords) VALUES ('MLA', current_date, ARRAY[1, 2, 3])")
            rechazos["tipo_relevamiento"] = _rechaza(cur, "INSERT INTO mercado_relevamientos (tipo, fecha) VALUES ('otro', current_date)")
            raise _Revertir()
    except _Revertir:
        pass
    assert all(rechazos.values()), {k: v for k, v in rechazos.items() if not v}
    assert all(aceptados.values()), {k: v for k, v in aceptados.items() if not v}


@CON_BASE
def test_la_app_solo_puede_leer_las_tablas_globales_y_cada_clave_foranea_tiene_su_indice():
    import db
    permisos = {}
    sin_indice = []
    try:
        with db.conexion_admin() as con:
            cur = con.cursor()
            _aplicar_dos_veces(cur)
            for tabla in TABLAS_GLOBALES:
                cur.execute("""
                    SELECT has_table_privilege('app_backend', %(t)s, 'SELECT'), has_table_privilege('app_backend', %(t)s, 'INSERT'),
                           has_table_privilege('app_backend', %(t)s, 'UPDATE'), has_table_privilege('app_backend', %(t)s, 'DELETE'),
                           (SELECT relrowsecurity FROM pg_class WHERE relname = %(t)s AND relnamespace = 'public'::regnamespace),
                           (SELECT count(*) FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %(t)s AND column_name = 'cuenta_id')
                """, {"t": tabla})
                permisos[tabla] = cur.fetchone()
            cur.execute("""
                SELECT c.conrelid::regclass::text, c.conname FROM pg_constraint c
                WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace
                  AND c.conrelid::regclass::text = ANY(%s)
                  AND NOT EXISTS (SELECT 1 FROM pg_index i WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])
            """, (list(TABLAS_GLOBALES),))
            sin_indice = cur.fetchall()
            raise _Revertir()
    except _Revertir:
        pass
    for tabla, (leer, insertar, actualizar, borrar, rls, columnas_cuenta) in permisos.items():
        assert leer and not (insertar or actualizar or borrar), tabla
        assert rls and columnas_cuenta == 0, tabla
    assert not sin_indice, f"Claves foráneas sin índice: {sin_indice}"
