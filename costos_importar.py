"""
Cargar el costo de fabricación de muchas publicaciones de una vez, desde un Excel o un CSV.

Flujo (nada se guarda hasta que el usuario confirma):
  1. /costos/plantilla  → Excel con todas sus publicaciones y el costo actual, para completar.
  2. /api/costos/importar/vista_previa → lee el archivo y devuelve qué cambiaría (antes → después), qué se ignora y qué tiene errores.
  3. /api/costos/importar/aplicar → guarda SOLO los cambios que el usuario vio, bajo RLS (solo publicaciones de su cuenta).
"""
import csv
import io
import re
from flask import Blueprint, request, jsonify, send_file, g
from auth.middleware import login_requerido
from auditoria import auditar
import db

bp = Blueprint("costos_importar", __name__)

COLUMNAS_ID = ("id de publicacion", "id de publicación", "id_meli", "id", "publicacion", "publicación", "mla")
COLUMNAS_COSTO = ("costo de fabricacion ($)", "costo de fabricación ($)", "costo de fabricacion", "costo de fabricación", "costo", "precio_costo")
MAX_FILAS = 5000


def parsear_monto(valor):
    """
    '12.500,50' (es-AR), '12500.5', '$ 12.500', '12.000' (miles) y 12000 → 12500.5 / 12500.0. None si no es un número ≥ 0.
    Un punto seguido de exactamente 3 dígitos y sin coma se toma como separador de miles.
    """
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor >= 0 else None
    s = re.sub(r"[^\d.,-]", "", str(valor))
    if not s or s in ("-", ".", ","):
        return None
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        n = float(s)
    except ValueError:
        return None
    return n if n >= 0 else None


def _normalizar_encabezado(texto):
    return re.sub(r"\s+", " ", str(texto or "").strip().lower())


def _filas_de_tabla(tabla):
    """tabla: lista de filas (listas). Devuelve [(id_meli, valor_crudo)] usando el encabezado para ubicar las columnas."""
    tabla = [f for f in tabla if any(c not in (None, "") for c in f)]
    if not tabla:
        return []
    encabezado = [_normalizar_encabezado(c) for c in tabla[0]]
    try:
        i_id = next(i for i, c in enumerate(encabezado) if c in COLUMNAS_ID)
        i_costo = next(i for i, c in enumerate(encabezado) if c in COLUMNAS_COSTO)
    except StopIteration:
        raise ValueError("No encontramos las columnas 'ID de publicación' y 'Costo de fabricación ($)'. Descargá la plantilla y completala.")
    return [(str(f[i_id]).strip() if i_id < len(f) and f[i_id] is not None else "", f[i_costo] if i_costo < len(f) else None) for f in tabla[1:MAX_FILAS + 1]]


def leer_archivo(nombre, contenido):
    """Lee un .xlsx o un .csv y devuelve [(id_meli, valor_crudo)]."""
    nombre = (nombre or "").lower()
    if nombre.endswith(".xlsx"):
        from openpyxl import load_workbook
        hoja = load_workbook(io.BytesIO(contenido), read_only=True, data_only=True).active
        return _filas_de_tabla([list(f) for f in hoja.iter_rows(values_only=True)])
    if nombre.endswith(".csv") or nombre.endswith(".txt"):
        try:
            texto = contenido.decode("utf-8-sig")
        except UnicodeDecodeError:
            texto = contenido.decode("latin-1")
        muestra = texto[:2000]
        delimitador = ";" if muestra.count(";") >= muestra.count(",") else ","
        return _filas_de_tabla(list(csv.reader(io.StringIO(texto), delimiter=delimitador)))
    raise ValueError("El archivo tiene que ser un Excel (.xlsx) o un CSV (.csv).")


def armar_vista_previa(cursor, cuenta_id, filas):
    """Compara lo que dice el archivo con lo que hay guardado. No escribe nada."""
    cursor.execute("SELECT id_meli, titulo, precio_costo FROM productos_padre WHERE cuenta_id = %s", (cuenta_id,))
    existentes = {r[0]: (r[1], float(r[2]) if r[2] is not None else 0.0) for r in cursor.fetchall()}
    cambios, sin_cambio, ignoradas, errores = [], 0, [], []
    vistos = set()
    for numero, (id_meli, crudo) in enumerate(filas, start=2):
        if not id_meli:
            continue
        if id_meli not in existentes:
            ignoradas.append({"fila": numero, "id": id_meli})
            continue
        if id_meli in vistos:
            errores.append({"fila": numero, "id": id_meli, "motivo": "Está repetida en el archivo"})
            continue
        vistos.add(id_meli)
        if crudo is None or str(crudo).strip() == "":
            continue        # celda vacía: no se toca el costo que ya había
        nuevo = parsear_monto(crudo)
        titulo, antes = existentes[id_meli]
        if nuevo is None:
            errores.append({"fila": numero, "id": id_meli, "titulo": titulo, "motivo": f"'{crudo}' no es un monto válido"})
        elif abs(nuevo - antes) < 0.005:
            sin_cambio += 1
        else:
            cambios.append({"id_meli": id_meli, "titulo": titulo, "antes": antes, "despues": round(nuevo, 2)})
    return {"cambios": cambios, "sin_cambio": sin_cambio, "ignoradas": ignoradas[:20], "total_ignoradas": len(ignoradas), "errores": errores[:20], "total_errores": len(errores)}


def aplicar(cursor, cuenta_id, cambios):
    """Guarda los cambios. Valida cada monto otra vez y solo toca publicaciones de esta cuenta. Devuelve cuántas actualizó."""
    actualizadas = 0
    for c in cambios[:MAX_FILAS]:
        id_meli, monto = str(c.get("id_meli") or ""), parsear_monto(c.get("despues"))
        if not id_meli or monto is None:
            continue
        cursor.execute("UPDATE productos_padre SET precio_costo = %s WHERE cuenta_id = %s AND id_meli = %s", (round(monto, 2), cuenta_id, id_meli))
        actualizadas += cursor.rowcount
    return actualizadas


@bp.route("/costos/plantilla")
@login_requerido
def plantilla():
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        cursor = conexion.cursor()
        cursor.execute("""
            SELECT id_meli, titulo, estado, COALESCE(precio_costo, 0) FROM productos_padre WHERE cuenta_id = %s
            ORDER BY (COALESCE(precio_costo, 0) = 0) DESC, (estado = 'active') DESC, titulo
        """, (g.cuenta_id,))
        filas = cursor.fetchall()
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Costos"
    hoja.append(["ID de publicación", "Título (no editar)", "Estado (no editar)", "Costo de fabricación ($)"])
    for celda in hoja[1]:
        celda.font = Font(bold=True, color="FFFFFF")
        celda.fill = PatternFill("solid", fgColor="7C3AED")
    for id_meli, titulo, estado, costo in filas:
        hoja.append([id_meli, titulo, {"active": "Activa", "paused": "Pausada"}.get(estado, estado), float(costo) if costo else None])
    hoja.column_dimensions["A"].width = 20
    hoja.column_dimensions["B"].width = 70
    hoja.column_dimensions["C"].width = 14
    hoja.column_dimensions["D"].width = 26
    hoja.freeze_panes = "A2"
    salida = io.BytesIO()
    libro.save(salida)
    salida.seek(0)
    return send_file(salida, as_attachment=True, download_name="costos_corelux.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@bp.route("/api/costos/importar/vista_previa", methods=["POST"])
@login_requerido
def vista_previa():
    archivo = request.files.get("archivo")
    if not archivo or not archivo.filename:
        return jsonify({"ok": False, "detalle": "Elegí un archivo."}), 400
    try:
        filas = leer_archivo(archivo.filename, archivo.read())
    except ValueError as e:
        return jsonify({"ok": False, "detalle": str(e)}), 400
    except Exception:
        return jsonify({"ok": False, "detalle": "No pudimos leer el archivo. Probá con la plantilla que descargás desde acá."}), 400
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        previa = armar_vista_previa(conexion.cursor(), g.cuenta_id, filas)
    return jsonify({"ok": True, **previa})


@bp.route("/api/costos/importar/aplicar", methods=["POST"])
@login_requerido
@auditar("costos_importar")
def aplicar_cambios():
    cambios = (request.get_json(silent=True) or {}).get("cambios") or []
    if not isinstance(cambios, list) or not cambios:
        return jsonify({"ok": False, "detalle": "No hay cambios para guardar."}), 400
    with db.conexion_usuario(g.usuario_id, g.cuenta_id) as conexion:
        actualizadas = aplicar(conexion.cursor(), g.cuenta_id, cambios)
    return jsonify({"ok": True, "actualizadas": actualizadas})
