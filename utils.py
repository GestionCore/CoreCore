"""Utilidades compartidas entre páginas — portadas tal cual de Santi Mens."""
import re

ESTADOS_INCIDENCIA_LEGIBLES = {
    "open": "Abierto", "opened": "Abierto",
    "closed": "Cerrado",
    "claim": "Reclamo activo",
    "dispute": "En mediación",
    "mediation": "En mediación",
    "resolved": "Resuelto",
    "none": "Sin etapa",
}


def formatear_estado_incidencia(estado):
    return ESTADOS_INCIDENCIA_LEGIBLES.get((estado or "").lower(), (estado or "Sin dato").capitalize())


def formatear_moneda(valor):
    try:
        val = float(valor or 0.0)
        return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "0,00"


def formatear_moneda_entera(valor):
    """
    Igual que formatear_moneda pero sin centavos — para números "hero"
    en letra grande, donde mostrar ",00" es ruido visual. Misma lógica
    de separador de miles (punto) que el resto de la app, para no
    reinventar el formateo con un f-string suelto en cada lugar nuevo.
    """
    try:
        val = float(valor or 0.0)
        return f"{val:,.0f}".replace(",", ".")
    except (TypeError, ValueError):
        return "0"


def limpiar_titulo_modelo(titulo):
    t = re.sub(r'\b(talle|size)\s*[:#]?\s*(xxxl|xxl|xl|l|m|s|\d+)\b', '', titulo, flags=re.IGNORECASE)
    t = re.sub(r'\b(xxxl|xxl|xl|l|m|s)\b', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+\d+\s*$', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t
