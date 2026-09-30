/**
 * UX v3 — helpers para armar los componentes de foco (ux.css) desde JS.
 * Las pantallas que se arman con fetch (Dashboard, etc.) usan esto en vez
 * de repetir HTML a mano, así un banner/KPI/acción se ve igual en toda la app.
 *
 * REGLA: todo texto que venga de afuera (MeLi, base de datos, el usuario)
 * entra por `esc()`; los parámetros que terminan en `Html` son los únicos
 * que aceptan HTML y tienen que armarse con `esc()` adentro (ej. <b>).
 */
const UX = (() => {
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

    // "$1.234.567" — entero, punto de miles, signo antes del $
    const plata = (n, decimales = 0) => {
        if (n === null || n === undefined || isNaN(n)) return '—';
        const signo = n < 0 ? '-' : '';
        return signo + '$' + Math.abs(n).toLocaleString('es-AR', { minimumFractionDigits: decimales, maximumFractionDigits: decimales });
    };
    const pct = (n, decimales = 1) => (n === null || n === undefined || isNaN(n)) ? '—' : n.toLocaleString('es-AR', { minimumFractionDigits: 0, maximumFractionDigits: decimales }) + '%';
    const num = n => (n === null || n === undefined || isNaN(n)) ? '—' : Math.round(n).toLocaleString('es-AR');

    const icono = (nombre, estilo = '') => `<svg class="icon" ${estilo ? `style="${estilo}"` : ''} aria-hidden="true"><use href="#icon-${esc(nombre)}"/></svg>`;

    // Pastilla ▲ / ▼. `mejorSiSube` define el color (en costos, que suba es malo).
    const delta = (valor, { mejorSiSube = true, sufijo = '%' } = {}) => {
        if (valor === null || valor === undefined || isNaN(valor)) return '';
        const sube = valor >= 0;
        const bueno = sube === mejorSiSube;
        const tono = valor === 0 ? 'ux-neutral' : (bueno ? 'ux-ok' : 'ux-danger');
        return `<span class="ux-delta ${tono}">${sube ? '▲' : '▼'} ${esc(Math.abs(valor).toLocaleString('es-AR', { maximumFractionDigits: 1 }))}${esc(sufijo)}</span>`;
    };

    // tono: ok | danger | warn | info | accion | gold
    const banner = ({ tono = 'info', icono: ic = 'info', tituloHtml = '', detalle = '', cta = null }) => `
        <div class="ux-banner ux-${esc(tono)}" role="status">
            <div class="ux-banner-icono">${icono(ic)}</div>
            <div class="ux-banner-cuerpo">
                <div class="ux-banner-titulo">${tituloHtml}</div>
                ${detalle ? `<div class="ux-banner-detalle">${esc(detalle)}</div>` : ''}
            </div>
            ${cta ? `<a class="btn ${esc(cta.clase || 'btn-primary')}" href="${esc(cta.href)}">${esc(cta.texto)}</a>` : ''}
        </div>`;

    const kpi = ({ tono = 'accion', icono: ic = 'chart', etiqueta = '', valor = '—', subHtml = '', href = null, id = '' }) => {
        const tag = href ? 'a' : 'div';
        return `<${tag} ${href ? `href="${esc(href)}"` : ''} ${id ? `id="${esc(id)}"` : ''} class="ux-kpi ux-${esc(tono)}">
            <div class="ux-kpi-etiqueta">${icono(ic)}${esc(etiqueta)}</div>
            <div class="ux-kpi-valor">${esc(valor)}</div>
            <div class="ux-kpi-sub">${subHtml}</div>
        </${tag}>`;
    };

    // Ícono por categoría de misión/acción (las categorías vienen de logros.py)
    const ICONO_CATEGORIA = { stock: 'box', reclamos: 'alert', atencion: 'chat', seo: 'edit', financiero: 'coin', tendencias: 'trend' };
    const TONO_PRIORIDAD = { urgente: 'danger', importante: 'warn', opcional: 'accion' };
    const CLASE_BOTON_PRIORIDAD = { urgente: 'btn-urgente', importante: 'btn-alerta', opcional: 'btn-primary' };

    const accion = ({ prioridad = 'opcional', categoria = '', titulo = '', detalle = '', link = null, linkTexto = 'Ver' }) => `
        <div class="ux-item-accion ux-${TONO_PRIORIDAD[prioridad] || 'accion'}">
            <div class="ux-item-accion-icono">${icono(ICONO_CATEGORIA[categoria] || 'bolt')}</div>
            <div class="ux-item-accion-cuerpo">
                <div class="ux-item-accion-titulo">${esc(titulo)}</div>
                ${detalle ? `<div class="ux-item-accion-detalle">${esc(detalle)}</div>` : ''}
            </div>
            ${link ? `<a class="btn ${CLASE_BOTON_PRIORIDAD[prioridad] || 'btn-primary'}" href="${esc(link)}">${esc(linkTexto || 'Ver')}</a>` : ''}
        </div>`;

    return { esc, plata, pct, num, icono, delta, banner, kpi, accion };
})();
