"""
Fase 0 del pivot multi-rubro (docs/PIVOT_SAAS.md): sondeo de los endpoints de Mercado Libre marcados «sin verificar».

SOLO LECTURA. Hace pedidos GET a Mercado Libre (y uno POST que pide un token de aplicación, que no cambia ningún dato) y a dos servicios públicos externos (cotización del dólar,
inflación). No escribe en la base de CoreLux, no modifica publicaciones y no imprime tokens, claves ni datos personales: de lo que contesta MeLi se muestra la FORMA
(claves y tipos) y unas pocas muestras de datos públicos.

    fly ssh console -a corecore --machine <id> -C "python sondeo_meli.py <cuenta_id>"

Se corre en Fly y no en la PC porque las credenciales locales de MeLi dan `invalid_client`. Usa el token de esa cuenta tal como lo entrega `token_manager` (el mismo camino que el resto de la app).
Qué contesta (ver los títulos «== T… ==» de la salida):
  T0  qué credenciales anda: token de usuario, token de aplicación (client_credentials) o ninguna
  T1  los mismos endpoints públicos con las tres credenciales (decide el token del relevador global)
  T2  por rubro (celulares, herramientas, pintura, ropa, discos, repuestos): categoría, atributos de variación, tendencias, productos de catálogo y sus ofertas
  T3  lo que MeLi cerró (búsqueda general, más vendidos, publicaciones ajenas), vuelto a probar
  T4  una publicación propia con todos sus atributos y user-products
  T5  rutas candidatas de dominios y fichas técnicas
  T6  cotización del dólar e inflación (fuentes externas)
  T7  variantes reales (selectores de los productos de catálogo), atributos que MeLi extrae de una búsqueda, multiget ajeno, publicaciones propias en lote, fichas de dominio
      (`python sondeo_meli.py <cuenta_id> T7` corre solo esta)
"""
import json
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

import requests  # noqa: E402

import config  # noqa: E402
import meli_http  # noqa: E402
from auth import token_manager  # noqa: E402

BASE = "https://api.mercadolibre.com"
PAUSA = 0.12                                    # segundos entre pedidos: es un sondeo, no una carrera
DATOS_PERSONALES = re.compile(r"token|secret|email|phone|password|address|identification|nombre_completo|first_name|last_name", re.I)

RUBROS = (
    ("celulares", "iphone 15 128 gb"),
    ("herramientas", "taladro percutor bosch"),
    ("pintura", "pintura latex interior blanco 4 litros"),
    ("ropa", "campera de jean hombre"),
    ("discos", "disco solido ssd 1tb"),
    ("repuestos", "pastillas de freno fiat palio"),
)


def forma(valor, nivel=2):
    """Claves y tipos de una respuesta, sin los datos: {id:str, price:float, shipping:{…4 claves}}."""
    if isinstance(valor, dict):
        if nivel <= 0:
            return "{…%d claves}" % len(valor)
        partes = [f"{k}:{forma(v, nivel - 1)}" for k, v in list(valor.items())[:45]]
        return "{" + ", ".join(partes) + ("…" if len(valor) > 45 else "") + "}"
    if isinstance(valor, list):
        return "[]" if not valor else f"[{len(valor)}×{forma(valor[0], nivel - 1)}]"
    return "null" if valor is None else type(valor).__name__


def limpio(valor):
    """Copia de una respuesta sin nada que parezca dato personal o credencial."""
    if isinstance(valor, dict):
        return {k: ("[oculto]" if DATOS_PERSONALES.search(str(k)) else limpio(v)) for k, v in valor.items()}
    if isinstance(valor, list):
        return [limpio(v) for v in valor]
    return valor


def corto(valor, largo=700):
    texto = json.dumps(limpio(valor), ensure_ascii=False, default=str)
    return texto if len(texto) <= largo else texto[:largo] + f"…(+{len(texto) - largo})"


class Sondeo:
    def __init__(self, token_usuario):
        self.token_usuario = token_usuario
        self.token_app = None
        self.mi_id = None
        self.pedidos = 0
        self.cabeceras_de_limite = set()

    # ── pedidos ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def pedir(self, ruta, token=None, params=None, metodo="get", data=None):
        url = ruta if ruta.startswith("http") else BASE + ruta
        cab = {"Authorization": f"Bearer {token}"} if token else {}
        t0 = time.time()
        try:
            r = getattr(meli_http, metodo)(url, headers=cab, params=params, data=data, timeout=20)
        except Exception as e:                                         # un tropiezo de red no corta el sondeo
            return {"estado": None, "error": f"{type(e).__name__}: {e}", "json": None, "ms": round((time.time() - t0) * 1000)}
        self.pedidos += 1
        for nombre in r.headers:
            if re.search(r"rate|limit|retry|quota|remaining", nombre, re.I):
                self.cabeceras_de_limite.add(f"{nombre}={r.headers[nombre]}"[:80])
        try:
            cuerpo = r.json()
        except ValueError:
            cuerpo = None
        time.sleep(PAUSA)
        return {"estado": r.status_code, "json": cuerpo, "ms": round((time.time() - t0) * 1000), "texto": (r.text or "")[:160] if cuerpo is None else ""}

    def con_usuario(self, ruta, **kw):
        return self.pedir(ruta, token=self.token_usuario, **kw)

    # ── T0 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t0_credenciales(self):
        print("\n== T0 · credenciales ==")
        yo = self.con_usuario("/users/me")
        j = yo["json"] or {}
        print(f"  /users/me con token de usuario → {yo['estado']}  (id={j.get('id')}, site={j.get('site_id')}, nickname={j.get('nickname')})")
        self.mi_id = j.get("id")
        respuesta = self.pedir(
            "/oauth/token", metodo="post",
            data={"grant_type": "client_credentials", "client_id": config.MELI_CLIENT_ID, "client_secret": config.MELI_CLIENT_SECRET},
        )
        cuerpo = respuesta["json"] or {}
        print(f"  POST /oauth/token (client_credentials) → {respuesta['estado']}  claves={sorted(cuerpo.keys())}  expires_in={cuerpo.get('expires_in')}  scope={cuerpo.get('scope')!r}  token_type={cuerpo.get('token_type')}")
        if respuesta["estado"] != 200:
            print(f"    cuerpo: {corto({k: v for k, v in cuerpo.items() if k != 'access_token'})}")
        self.token_app = cuerpo.get("access_token") if respuesta["estado"] == 200 else None

    # ── T1 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t1_comparar_credenciales(self, categoria_ejemplo):
        print("\n== T1 · mismos endpoints con las tres credenciales (usuario / aplicación / ninguna) ==")
        pruebas = (
            ("/trends/MLA", None),
            (f"/trends/MLA/{categoria_ejemplo}", None),
            ("/sites/MLA/categories", None),
            (f"/categories/{categoria_ejemplo}", None),
            (f"/categories/{categoria_ejemplo}/attributes", None),
            ("/sites/MLA/domain_discovery/search", {"q": "iphone 15", "limit": 2}),
            ("/products/search", {"site_id": "MLA", "q": "iphone 15", "status": "active", "limit": 2}),
            ("/sites/MLA/listing_prices", {"price": 100000, "category_id": categoria_ejemplo}),
            ("/sites/MLA/search", {"category": categoria_ejemplo, "limit": 1}),
            (f"/highlights/MLA/category/{categoria_ejemplo}", None),
        )
        print(f"  {'endpoint':56}{'usuario':>9}{'app':>7}{'ninguna':>9}")
        for ruta, params in pruebas:
            estados = []
            for modo, token in (("usuario", self.token_usuario), ("app", self.token_app), ("ninguna", None)):
                if modo == "app" and token is None:
                    estados.append("—")                             # no se pudo obtener el token de aplicación
                else:
                    estados.append(self.pedir(ruta, token=token, params=params)["estado"])
            print(f"  {(ruta + (' ' + str(params) if params else ''))[:55]:56}{estados[0]!s:>9}{estados[1]!s:>7}{estados[2]!s:>9}")

    # ── T2 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def descubrir(self, consulta):
        r = self.con_usuario("/sites/MLA/domain_discovery/search", params={"q": consulta, "limit": 3})
        lista = r["json"] if isinstance(r["json"], list) else []
        return lista[0] if lista else {}, r

    def t2_rubro(self, nombre, consulta):
        print(f"\n== T2 · rubro «{nombre}» (búsqueda: {consulta!r}) ==")
        hallazgo, r = self.descubrir(consulta)
        print(f"  domain_discovery → {r['estado']}  forma={forma(r['json'], 3) if r['json'] else r.get('texto')}")
        categoria_id, dominio = hallazgo.get("category_id"), hallazgo.get("domain_id")
        print(f"  categoría={categoria_id} ({hallazgo.get('category_name')})  dominio={dominio} ({hallazgo.get('domain_name')})")
        resultado = {"rubro": nombre, "categoria_id": categoria_id, "dominio": dominio}
        if not categoria_id:
            return resultado

        c = self.con_usuario(f"/categories/{categoria_id}")
        j = c["json"] or {}
        print(f"  /categories/{{id}} → {c['estado']}  total_items={j.get('total_items_in_this_category')}  hijos={len(j.get('children_categories') or [])}  camino={[p.get('name') for p in j.get('path_from_root') or []]}")
        print(f"    settings={corto(j.get('settings'), 500)}")
        resultado["total_items"] = j.get("total_items_in_this_category")

        a = self.con_usuario(f"/categories/{categoria_id}/attributes")
        atributos = a["json"] if isinstance(a["json"], list) else []
        etiquetas = {}
        for at in atributos:
            for etiqueta in (at.get("tags") or {}):
                etiquetas[etiqueta] = etiquetas.get(etiqueta, 0) + 1
        print(f"  /categories/{{id}}/attributes → {a['estado']}  atributos={len(atributos)}  etiquetas={dict(sorted(etiquetas.items(), key=lambda kv: -kv[1]))}")
        if atributos:
            print(f"    forma de un atributo: {forma(atributos[0], 2)}")
        de_variacion = [at for at in atributos if any("variation" in etiqueta for etiqueta in (at.get("tags") or {}))]
        for at in de_variacion[:14]:
            unidades = at.get("allowed_units")
            print(f"    · variación: {at.get('id')} «{at.get('name')}» tipo={at.get('value_type')} valores={len(at.get('values') or [])} unidades={[u.get('id') for u in unidades] if unidades else None} etiquetas={sorted((at.get('tags') or {}).keys())}")
        sospechosos = [at.get("id") for at in atributos if re.search(r"compat|vehic|brand_model|year|ano", f"{at.get('id')} {at.get('name')}", re.I)]
        if sospechosos:
            print(f"    atributos que suenan a compatibilidad/vehículo: {sospechosos[:12]}")
        resultado["atributos"] = len(atributos)
        resultado["atributos_de_variacion"] = [at.get("id") for at in de_variacion]

        t = self.con_usuario(f"/trends/MLA/{categoria_id}")
        lista = t["json"] if isinstance(t["json"], list) else []
        print(f"  /trends/MLA/{{categoría}} → {t['estado']}  items={len(lista)}  forma={forma(lista[0], 2) if lista else t.get('texto')}")
        print(f"    primeras: {[x.get('keyword') for x in lista[:8]]}")
        resultado["tendencias"] = len(lista)

        p = self.con_usuario("/products/search", params={"site_id": "MLA", "q": consulta, "status": "active", "limit": 10})
        j = p["json"] or {}
        productos = j.get("results") or []
        print(f"  /products/search → {p['estado']}  paging={j.get('paging')}  resultados={len(productos)}")
        if productos:
            print(f"    forma de un producto: {forma(productos[0], 2)}")
            print(f"    nombres: {[x.get('name') for x in productos[:4]]}")
        resultado["catalogo_total"] = (j.get("paging") or {}).get("total")
        resultado["productos"] = [x.get("id") for x in productos]

        con_ofertas = 0
        ofertas_de_ejemplo = None
        for x in productos[:6]:
            o = self.con_usuario(f"/products/{x['id']}/items", params={"limit": 50})
            filas = (o["json"] or {}).get("results") or []
            if o["estado"] == 200 and filas:
                con_ofertas += 1
                if ofertas_de_ejemplo is None:
                    ofertas_de_ejemplo = (x["id"], o, filas)
        resultado["productos_con_ofertas_de_6"] = con_ofertas
        print(f"  /products/{{id}}/items → de los primeros 6 productos, con ofertas: {con_ofertas}")
        if ofertas_de_ejemplo:
            pid, o, filas = ofertas_de_ejemplo
            presencia = {}
            for fila in filas:
                for clave, valor in fila.items():
                    if valor not in (None, "", [], {}):
                        presencia[clave] = presencia.get(clave, 0) + 1
            print(f"    producto {pid}: paging={(o['json'] or {}).get('paging')}  ofertas={len(filas)}")
            print(f"    forma de una oferta: {forma(filas[0], 2)}")
            print(f"    campos con dato (de {len(filas)} ofertas): {dict(sorted(presencia.items(), key=lambda kv: -kv[1]))}")
            print(f"    ¿sold_quantity? {'SÍ' if presencia.get('sold_quantity') else 'no'} · ¿available_quantity? {'SÍ' if presencia.get('available_quantity') else 'no'}")
            resultado["oferta_id"] = filas[0].get("item_id") or filas[0].get("id")
            resultado["vendedor_id"] = filas[0].get("seller_id")
            resultado["tiene_sold_quantity"] = bool(presencia.get("sold_quantity"))
            resultado["producto_con_ofertas"] = pid

            d = self.con_usuario(f"/products/{pid}")
            dj = d["json"] or {}
            print(f"  /products/{{id}} → {d['estado']}  claves={sorted(dj.keys())}")
            print(f"    buy_box_winner={corto(dj.get('buy_box_winner'), 400)}")
            print(f"    pickers={forma(dj.get('pickers'), 2)}  children_ids={len(dj.get('children_ids') or [])}  family_name={dj.get('family_name')!r}  domain_id={dj.get('domain_id')}")
            print(f"    atributos del producto: {[(x.get('id'), x.get('value_name')) for x in (dj.get('attributes') or [])[:14]]}")
            print(f"    main_features={corto(dj.get('main_features'), 300)}")
            r2 = self.con_usuario(f"/reviews/item/{pid}")
            print(f"  /reviews/item/{{catalog_product_id}} → {r2['estado']}  forma={forma(r2['json'], 2) if r2['json'] else r2.get('texto')}")
        return resultado

    # ── T3 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t3_cerrados(self, resultados):
        print("\n== T3 · lo que MeLi cerró, vuelto a probar ==")
        ejemplo = next((r for r in resultados if r.get("oferta_id")), None)
        categoria = next((r["categoria_id"] for r in resultados if r.get("categoria_id")), None)
        pruebas = []
        if ejemplo:
            item = ejemplo["oferta_id"]
            pruebas += [
                (f"/items/{item}", None, "publicación AJENA, completa"),
                (f"/items/{item}", {"attributes": "id,sold_quantity,available_quantity,price"}, "publicación AJENA, solo ventas y stock"),
                ("/items", {"ids": f"{item}", "attributes": "id,sold_quantity"}, "multiget con una publicación ajena"),
                (f"/items/{item}/visits/time_window", {"last": 7, "unit": "day"}, "visitas de una publicación ajena"),
                (f"/users/{ejemplo['vendedor_id']}/items/search", {"limit": 1}, "publicaciones de otro vendedor"),
                ("/sites/MLA/search", {"seller_id": ejemplo["vendedor_id"], "limit": 1}, "búsqueda por vendedor"),
            ]
        if categoria:
            pruebas += [
                ("/sites/MLA/search", {"category": categoria, "sort": "sold_quantity_desc", "limit": 3}, "búsqueda por categoría ordenada por ventas"),
                ("/sites/MLA/search", {"q": "iphone", "limit": 3}, "búsqueda libre"),
                (f"/highlights/MLA/category/{categoria}", None, "más vendidos de la categoría"),
            ]
        for ruta, params, descripcion in pruebas:
            for etiqueta, token in (("usuario", self.token_usuario), ("app", self.token_app)):
                if token is None:
                    continue
                r = self.pedir(ruta, token=token, params=params)
                extra = ""
                if r["estado"] != 200:
                    extra = f"  {r.get('texto') or corto((r['json'] or {}).get('message') or (r['json'] or {}).get('error'), 120)}"
                print(f"  [{etiqueta:7}] {r['estado']}  {descripcion}  ({ruta}){extra}")

    # ── T4 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t4_propia(self):
        print("\n== T4 · una publicación PROPIA, con todos sus atributos ==")
        if not self.mi_id:
            print("  sin id de usuario: se omite")
            return
        r = self.con_usuario(f"/users/{self.mi_id}/items/search", params={"limit": 12})
        ids = (r["json"] or {}).get("results") or []
        print(f"  /users/{{yo}}/items/search → {r['estado']}  ids={len(ids)}")
        vistos_sin, vistos_con, primero_up = 0, 0, None
        for item_id in ids:
            if vistos_sin >= 1 and vistos_con >= 1:
                break
            d = self.con_usuario(f"/items/{item_id}", params={"include_attributes": "all"})
            j = d["json"] or {}
            tiene_variaciones = bool(j.get("variations"))
            if (tiene_variaciones and vistos_con >= 1) or (not tiene_variaciones and vistos_sin >= 1):
                continue
            vistos_con += 1 if tiene_variaciones else 0
            vistos_sin += 0 if tiene_variaciones else 1
            print(f"  /items/{{id}}?include_attributes=all → {d['estado']}  ({'con' if tiene_variaciones else 'sin'} variaciones)")
            print(f"    claves={sorted(j.keys())}")
            print(f"    domain_id={j.get('domain_id')}  category_id={j.get('category_id')}  catalog_product_id={j.get('catalog_product_id')}  user_product_id={j.get('user_product_id')}  family_id={j.get('family_id')}  family_name={j.get('family_name')!r}")
            print(f"    atributos ({len(j.get('attributes') or [])}): {[(a.get('id'), a.get('value_name')) for a in (j.get('attributes') or [])[:16]]}")
            if tiene_variaciones:
                v = j["variations"][0]
                print(f"    variaciones={len(j['variations'])}  forma de una variación: {forma(v, 3)}")
                print(f"    attribute_combinations (muestra): {corto(v.get('attribute_combinations'), 500)}")
            if j.get("user_product_id") and primero_up is None:
                primero_up = j["user_product_id"]
        if primero_up:
            u = self.con_usuario(f"/user-products/{primero_up}")
            uj = u["json"] or {}
            print(f"  /user-products/{{id}} → {u['estado']}  claves={sorted(uj.keys())}")
            print(f"    atributos: {[(a.get('id'), a.get('value_name')) for a in (uj.get('attributes') or [])[:14]]}  domain_id={uj.get('domain_id')}  family_id={uj.get('family_id')}")

    # ── T5 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t5_rutas_candidatas(self, resultados):
        print("\n== T5 · rutas candidatas de dominios y fichas técnicas ==")
        base = next((r for r in resultados if r.get("dominio")), None)
        if not base:
            print("  sin dominio descubierto: se omite")
            return
        dominio, categoria = base["dominio"], base["categoria_id"]
        for ruta in (
            f"/catalog_domains/{dominio}", f"/domains/{dominio}", f"/domains/{dominio}/technical_specs",
            f"/categories/{categoria}/technical_specs/input", f"/categories/{categoria}/technical_specs/output",
            f"/sites/MLA/categories/{categoria}/attributes",
        ):
            r = self.con_usuario(ruta)
            detalle = forma(r["json"], 2)[:260] if r["json"] is not None else (r.get("texto") or r.get("error") or "")
            print(f"  {r['estado']}  {ruta}   {detalle}")

    # ── T7 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t7_detalle(self):
        print("\n== T7 · variantes reales, atributos extraídos de una búsqueda, multiget ajeno, propias en lote, dominios ==")
        ajeno = None
        for nombre, consulta in RUBROS:
            hallazgo, _ = self.descubrir(consulta)
            atributos = hallazgo.get("attributes") or []
            print(f"\n  [{nombre}] domain_discovery → atributos que MeLi extrae de la búsqueda: {corto(atributos, 400)}")
            categoria = self.con_usuario(f"/categories/{hallazgo.get('category_id')}")["json"] or {}
            ajustes = categoria.get("settings") or {}
            print(f"    ajustes de la categoría: {corto({k: ajustes.get(k) for k in ('max_title_length', 'max_variations_allowed', 'item_conditions', 'minimum_price', 'stock', 'price', 'vip_subdomain') if k in ajustes}, 400)}")
            lista = ((self.con_usuario("/products/search", params={"site_id": "MLA", "q": consulta, "status": "active", "limit": 3})["json"]) or {}).get("results") or []
            for producto in lista[:3]:
                d = (self.con_usuario(f"/products/{producto['id']}")["json"]) or {}
                pickers = [
                    {"picker": p.get("picker_id"), "nombre": p.get("picker_name"), "atributos": [a.get("id") for a in p.get("attributes") or []], "productos": len(p.get("products") or [])}
                    for p in d.get("pickers") or []
                ]
                print(f"    producto {producto['id']} «{d.get('name')}»  parent_id={d.get('parent_id')}  grouper_id={d.get('grouper_id')}  family_name={d.get('family_name')!r}")
                print(f"      pickers={corto(pickers, 500)}")
                if ajeno is None:
                    ofertas = (self.con_usuario(f"/products/{producto['id']}/items", params={"limit": 3})["json"] or {}).get("results") or []
                    if ofertas:
                        ajeno = ofertas[0].get("item_id")
        if ajeno:
            r = self.con_usuario("/items", params={"ids": ajeno, "attributes": "id,sold_quantity,available_quantity,price"})
            print(f"\n  multiget /items?ids=<ajena> → {r['estado']}  cuerpo={corto(r['json'], 500)}")

        print("\n  Mis publicaciones, en lote:")
        ids = (self.con_usuario(f"/users/{self.mi_id}/items/search", params={"limit": 20})["json"] or {}).get("results") or []
        lote = self.con_usuario("/items", params={"ids": ",".join(ids[:20]), "include_attributes": "all"})
        cuerpos = [x.get("body") or {} for x in (lote["json"] if isinstance(lote["json"], list) else [])]
        con_talle = con_color = con_variaciones = con_familia = 0
        for it in cuerpos:
            atributos = {a.get("id"): a.get("value_name") for a in it.get("attributes") or []}
            con_talle += 1 if atributos.get("SIZE") else 0
            con_color += 1 if atributos.get("COLOR") else 0
            con_variaciones += 1 if it.get("variations") else 0
            con_familia += 1 if it.get("family_id") else 0
        print(f"    lote → {lote['estado']}  publicaciones={len(cuerpos)}  con SIZE={con_talle}  con COLOR={con_color}  con variaciones clásicas={con_variaciones}  con family_id={con_familia}")
        for it in cuerpos[:3]:
            atributos = {a.get("id"): a.get("value_name") for a in it.get("attributes") or []}
            print(f"    · {it.get('id')}  título={str(it.get('title'))[:60]!r}  SIZE={atributos.get('SIZE')!r}  COLOR={atributos.get('COLOR')!r}  FILTRABLE_SIZE={atributos.get('FILTRABLE_SIZE')!r}  family_name={str(it.get('family_name'))[:50]!r}")

        print("\n  Ficha del dominio de celulares:")
        d = self.con_usuario("/catalog_domains/MLA-CELLPHONES")
        print(f"    /catalog_domains/MLA-CELLPHONES → {d['estado']}  claves={sorted((d['json'] or {}).keys())}")
        e = self.con_usuario("/domains/MLA-CELLPHONES/technical_specs")
        grupos = ((e["json"] or {}).get("input") or {}).get("groups") or []
        print(f"    /domains/MLA-CELLPHONES/technical_specs → {e['estado']}  grupos de entrada={len(grupos)}  forma de un grupo={forma(grupos[0], 3) if grupos else None}")

    # ── T6 ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
    def t6_externas(self):
        print("\n== T6 · fuentes externas (cotización del dólar, inflación) ==")
        for nombre, url in (
            ("dolarapi.com (todas las cotizaciones)", "https://dolarapi.com/v1/dolares"),
            ("dolarapi.com (blue)", "https://dolarapi.com/v1/dolares/blue"),
            ("dolarapi.com (MEP/bolsa)", "https://dolarapi.com/v1/dolares/bolsa"),
            ("bluelytics", "https://api.bluelytics.com.ar/v2/latest"),
            ("IPC nacional (datos.gob.ar)", "https://apis.datos.gob.ar/series/api/series?ids=148.3_INIVELNAL_DICI_M_26&limit=3&sort=desc"),
        ):
            t0 = time.time()
            try:
                r = requests.get(url, timeout=12)
                try:
                    cuerpo = r.json()
                except ValueError:
                    cuerpo = None
                print(f"  {r.status_code}  {nombre}  {round((time.time() - t0) * 1000)} ms  muestra={corto(cuerpo, 420) if cuerpo is not None else r.text[:120]}")
            except Exception as e:
                print(f"  ERROR  {nombre}: {type(e).__name__}: {e}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cuenta_id = int(sys.argv[1])
    solo_t7 = sys.argv[2:] == ["T7"]                          # `python sondeo_meli.py <cuenta> T7`: solo el detalle de variantes
    try:
        token = token_manager.asegurar_token_valido(cuenta_id)
    except token_manager.CuentaDesconectada as e:
        print(f"La cuenta {cuenta_id} no está conectada: {e}")
        sys.exit(2)

    sondeo = Sondeo(token)
    sondeo.t0_credenciales()
    if solo_t7:
        sondeo.t7_detalle()
        print(f"\n  pedidos a Mercado Libre: {sondeo.pedidos}")
        return
    resultados = [sondeo.t2_rubro(nombre, consulta) for nombre, consulta in RUBROS]
    categoria_ejemplo = next((r["categoria_id"] for r in resultados if r.get("categoria_id")), "MLA1055")
    sondeo.t1_comparar_credenciales(categoria_ejemplo)
    sondeo.t3_cerrados(resultados)
    sondeo.t4_propia()
    sondeo.t5_rutas_candidatas(resultados)
    sondeo.t6_externas()
    sondeo.t7_detalle()

    print("\n== RESUMEN ==")
    print(f"  pedidos a Mercado Libre: {sondeo.pedidos}")
    print(f"  cabeceras de límite vistas en las respuestas: {sorted(sondeo.cabeceras_de_limite) or 'ninguna'}")
    print(f"  token de aplicación: {'OBTENIDO' if sondeo.token_app else 'NO se pudo obtener'}")
    print(f"  {'rubro':14}{'categoría':14}{'dominio':26}{'publicaciones':>14}{'catálogo':>10}{'tend.':>7}{'con ofertas/6':>15}{'sold_qty':>10}{'atrib.var.':>12}")
    for r in resultados:
        print(f"  {r['rubro']:14}{str(r.get('categoria_id')):14}{str(r.get('dominio')):26}{r.get('total_items')!s:>14}{r.get('catalogo_total')!s:>10}{r.get('tendencias')!s:>7}"
              f"{r.get('productos_con_ofertas_de_6')!s:>15}{('SÍ' if r.get('tiene_sold_quantity') else 'no'):>10}{len(r.get('atributos_de_variacion') or []):>12}")


if __name__ == "__main__":
    main()
