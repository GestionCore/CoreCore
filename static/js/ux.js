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
    const CLASE_BOTON_PRIORIDAD = { urgente: 'btn-urgente', importante: 'btn-alerta', opcional: 'btn-secondary' };

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

/**
 * Eventos sin `onclick=` en el HTML (paso previo a sacar 'unsafe-inline' del script-src de la CSP: un manejador escrito en el atributo es código inline).
 *
 *   <button data-click="funcion" data-click-args='["$el", 7]'>   →   window.funcion(<el botón>, 7)
 *
 * Eventos: data-click | data-change | data-input | data-keyup | data-keydown | data-submit (los argumentos van en data-<evento>-args, un arreglo JSON; en Jinja: `{{ [a, b]|tojson }}` entre comillas simples).
 * En un data-submit, si la función devuelve `false` se cancela el envío (lo que hacía `onsubmit="return f(this)"`) y "$form" es el propio formulario.
 * data-keydown se usa con data-keydown-tecla="Enter" (o varias separadas por coma): solo corre con esas teclas.
 * data-<evento>-propio: solo corre si el evento fue en el propio elemento y no en uno de adentro (el «clic en el fondo» de un modal: antes `if(event.target===this)`).
 * data-prevenir: cancela la acción por defecto del navegador antes de llamar (un enlace que no tiene que navegar: antes `return false`).
 * "funcion" puede ser una ruta (`RangoFechas.toggle`, `window.print`): se llama con su objeto como `this`.
 * Argumentos especiales: "$el" (el elemento), "$ev" (el evento), "$valor" (su value), "$checked" (si está tildado), "$form" (su formulario), "$closest:.selector" (el ancestro más cercano).
 * data-aislar en un elemento frena el click ahí (hace lo que antes `event.stopPropagation()`): un click adentro no activa el data-click de los de afuera.
 * Un elemento con role="button" (que no es un <button>) también se activa con Enter y espacio.
 */
(() => {
    const resolverRuta = (ruta) => {
        let dueno = window, valor = window;
        for (const parte of String(ruta).split('.')) { dueno = valor; valor = valor == null ? undefined : valor[parte]; }
        return typeof valor === 'function' ? [valor, dueno] : [null, null];
    };
    const argumento = (a, el, ev) => {
        if (a === '$el') return el;
        if (a === '$ev') return ev;
        if (a === '$valor') return el.value;
        if (a === '$checked') return !!el.checked;
        if (a === '$form') return el.form || (el.tagName === 'FORM' ? el : el.closest('form'));
        if (typeof a === 'string' && a.startsWith('$closest:')) return el.closest(a.slice(9));
        return a;
    };
    const atender = (ev) => {
        const atributo = 'data-' + ev.type;
        for (let el = ev.target; el && el.nodeType === 1; el = el.parentElement) {
            if (ev.type === 'click' && el.hasAttribute('data-aislar')) return;
            if (!el.hasAttribute(atributo)) continue;
            if (el.hasAttribute(atributo + '-propio') && ev.target !== el) return;
            if (ev.type === 'keydown') {
                const teclas = el.getAttribute('data-keydown-tecla');
                if (teclas && !teclas.split(',').includes(ev.key)) return;
            }
            if (el.hasAttribute('data-prevenir')) ev.preventDefault();
            const [funcion, dueno] = resolverRuta(el.getAttribute(atributo));
            if (!funcion) { console.error('[ux] ' + atributo + ': no existe la función "' + el.getAttribute(atributo) + '"'); return; }
            let args = [];
            try { args = JSON.parse(el.getAttribute(atributo + '-args') || '[]'); } catch (e) { console.error('[ux] ' + atributo + '-args no es un JSON válido', e); return; }
            const resultado = funcion.apply(dueno, args.map(a => argumento(a, el, ev)));
            if (resultado === false && ev.type === 'submit') ev.preventDefault();         // antes un onsubmit="return f(this)" impedía enviar el formulario; solo en submit, para no alterar a los click ya migrados
            return;
        }
    };
    ['click', 'change', 'input', 'keyup', 'keydown', 'submit'].forEach(tipo => document.addEventListener(tipo, atender));
    document.addEventListener('keydown', (ev) => {
        if (ev.key !== 'Enter' && ev.key !== ' ') return;
        const el = ev.target;
        if (el && el.nodeType === 1 && el.getAttribute('role') === 'button' && el.hasAttribute('data-click') && el.tagName !== 'BUTTON') { ev.preventDefault(); el.click(); }
    });
})();

/**
 * Pestañas: <div data-tabs> con hijos .ux-tab-panel (id, data-tab-titulo, data-tab-badge opcional, data-tab-defecto opcional). Arma la barra de pestañas, deja visible UNA y esconde el resto.
 *  · Sin JS todos los paneles quedan a la vista, uno debajo del otro (y al imprimir, también: el CSS los muestra todos).
 *  · Teclado: flechas, Inicio y Fin (patrón WAI-ARIA de pestañas); un enlace #id-de-un-panel (o de algo dentro de uno) abre esa pestaña y baja hasta ahí.
 *  · Al mostrarse un panel dispara `ux:tab-visible` en él (los gráficos se arman recién ahí, cuando ya tienen tamaño).
 */
(() => {
    const iniciar = (cont) => {
        const paneles = [...cont.querySelectorAll(':scope > .ux-tab-panel')];
        if (paneles.length < 2) return;
        const barra = document.createElement('div');
        barra.className = 'ux-tabs-barra';
        barra.setAttribute('role', 'tablist');
        const pestanas = paneles.map((panel, i) => {
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'ux-tab';
            b.id = 'tab-' + (panel.id || (cont.id + '-' + i));
            b.setAttribute('role', 'tab');
            b.setAttribute('aria-controls', panel.id);
            b.textContent = panel.dataset.tabTitulo || ('Detalle ' + (i + 1));
            if (panel.dataset.tabBadge) {
                const n = document.createElement('span');
                n.className = 'ux-tab-badge';
                n.textContent = panel.dataset.tabBadge;
                b.appendChild(n);
            }
            panel.setAttribute('role', 'tabpanel');
            panel.setAttribute('aria-labelledby', b.id);
            barra.appendChild(b);
            return b;
        });
        cont.insertBefore(barra, paneles[0]);
        cont.classList.add('ux-tabs-activas');

        const mostrar = (i, { enfocar = false } = {}) => {
            pestanas.forEach((b, j) => {
                const activa = i === j;
                b.setAttribute('aria-selected', activa ? 'true' : 'false');
                b.tabIndex = activa ? 0 : -1;
                paneles[j].hidden = !activa;
            });
            if (enfocar) pestanas[i].focus();
            pestanas[i].scrollIntoView({ block: 'nearest', inline: 'nearest' });
            paneles[i].dispatchEvent(new CustomEvent('ux:tab-visible', { bubbles: false }));
        };
        const indiceDe = (elemento) => paneles.findIndex(p => p === elemento || p.contains(elemento));

        pestanas.forEach((b, i) => b.addEventListener('click', () => mostrar(i)));
        barra.addEventListener('keydown', (ev) => {
            const actual = pestanas.indexOf(document.activeElement);
            if (actual < 0) return;
            const destino = { ArrowRight: (actual + 1) % pestanas.length, ArrowLeft: (actual - 1 + pestanas.length) % pestanas.length, Home: 0, End: pestanas.length - 1 }[ev.key];
            if (destino === undefined) return;
            ev.preventDefault();
            mostrar(destino, { enfocar: true });
        });

        const irAlHash = () => {
            const id = decodeURIComponent((location.hash || '').slice(1));
            const objetivo = id ? document.getElementById(id) : null;
            const i = objetivo ? indiceDe(objetivo) : -1;
            if (i < 0) return false;
            mostrar(i);
            requestAnimationFrame(() => objetivo.scrollIntoView({ block: 'start', behavior: 'smooth' }));
            return true;
        };
        window.addEventListener('hashchange', irAlHash);
        if (!irAlHash()) {
            const defecto = paneles.findIndex(p => p.hasAttribute('data-tab-defecto'));
            mostrar(defecto >= 0 ? defecto : 0);
        }
        UX.bordesDeslizables(barra);
    };
    window.addEventListener('DOMContentLoaded', () => document.querySelectorAll('[data-tabs]').forEach(iniciar));
})();

/**
 * Un contenedor que se desliza de costado (la barra de pestañas, el menú de secciones) avisa con una sombra en el borde donde todavía hay más: `data-sombra="izq der"` según
 * lo que falte ver (ux.css la dibuja). Se recalcula al deslizar y al cambiar el tamaño.
 */
UX.bordesDeslizables = (el) => {
    if (!el) return;
    const actualizar = () => {
        const max = el.scrollWidth - el.clientWidth;
        const lados = [];
        if (el.scrollLeft > 2) lados.push('izq');
        if (max > 2 && el.scrollLeft < max - 2) lados.push('der');
        el.dataset.sombra = lados.join(' ');
    };
    el.addEventListener('scroll', actualizar, { passive: true });
    window.addEventListener('resize', actualizar);
    if (window.ResizeObserver) new ResizeObserver(actualizar).observe(el);
    actualizar();
};
window.addEventListener('DOMContentLoaded', () => document.querySelectorAll('.subnav-tabs-inner').forEach(UX.bordesDeslizables));

// ── Colores de los gráficos y cambio de tema ─────────────────────────────────────────────────────────────────────────────────
// Chart.js lee los colores UNA vez, al crear el gráfico: al cambiar el tema en vivo (data-theme) un gráfico ya dibujado conservaba los del tema anterior hasta recargar la página.
// Acá se recolorea todo gráfico vivo: se reemplaza cada color que era el de un token del tema viejo por el del mismo token en el nuevo (también las versiones con transparencia,
// rgba(r,g,b,a)). Lo que arma una función (colores calculados al momento de dibujar) se actualiza solo con chart.update().
const _TOKENS_DE_GRAFICOS = ['--text-primary', '--text-secondary', '--text-muted', '--text-faint', '--border', '--border-soft', '--glass-border', '--glass-bg', '--glass-bg-alt',
    '--success', '--danger', '--semantic-warning', '--accent-primary', '--accent-gold', '--accent-cyan', '--accent-texto'];

// "#8b5cf6" / "rgb(1, 2, 3)" / "rgba(1,2,3,.5)" → [r, g, b, a] o null si no es un color que se pueda leer
UX.colorARgba = (texto) => {
    const t = String(texto || '').trim().toLowerCase();
    let m = t.match(/^#([0-9a-f]{3})$/);
    if (m) return [...m[1]].map(c => parseInt(c + c, 16)).concat(1);
    m = t.match(/^#([0-9a-f]{6})([0-9a-f]{2})?$/);
    if (m) return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16), parseInt(m[1].slice(4, 6), 16), m[2] ? parseInt(m[2], 16) / 255 : 1];
    m = t.match(/^rgba?\(\s*(\d+)\s*[, ]\s*(\d+)\s*[, ]\s*(\d+)\s*(?:[,/]\s*([\d.]+%?)\s*)?\)$/);
    if (m) return [+m[1], +m[2], +m[3], m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]))];
    return null;
};
// El color de un token del tema con una transparencia: UX.alfa('--accent-primary', 0.35) → "rgba(139, 92, 246, 0.35)". Evita escribir el violeta a mano en los gráficos.
UX.alfa = (token, alfa, respaldo = '#8b5cf6') => {
    const c = UX.colorARgba(getComputedStyle(document.documentElement).getPropertyValue(token)) || UX.colorARgba(respaldo);
    return `rgba(${c[0]}, ${c[1]}, ${c[2]}, ${alfa})`;
};
UX.tokensDeGraficos = () => {
    const estilo = getComputedStyle(document.documentElement), tokens = {};
    _TOKENS_DE_GRAFICOS.forEach(t => { tokens[t] = estilo.getPropertyValue(t).trim(); });
    return tokens;
};
// Reemplaza en un objeto de configuración de Chart.js (recursivo, sin tocar funciones ni gradientes) los colores de `antes` por los de `despues`. Devuelve cuántos cambió.
UX.recolorear = (nodo, antes, despues, visto = new Set()) => {
    if (!nodo || typeof nodo !== 'object' || visto.has(nodo)) return 0;
    const proto = Object.getPrototypeOf(nodo);
    if (proto !== Object.prototype && proto !== null && !Array.isArray(nodo)) return 0;               // gradientes, patrones, contextos: no se tocan (Chart.js arma varios objetos sin prototipo: esos sí)
    visto.add(nodo);
    let cambios = 0;
    const iguales = (a, b) => a[0] === b[0] && a[1] === b[1] && a[2] === b[2];
    const aTexto = (rgb, alfa) => alfa >= 0.999 ? `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` : `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${+alfa.toFixed(3)})`;
    const convertir = (valor) => {
        const viejo = UX.colorARgba(valor);
        if (!viejo) return valor;
        const pares = Object.keys(antes).map(t => [UX.colorARgba(antes[t]), UX.colorARgba(despues[t])]).filter(([a, d]) => a && d && !(iguales(a, d) && Math.abs(a[3] - d[3]) < 0.005));
        // 1.º el color IDÉNTICO a un token (mismo color y misma transparencia: p. ej. la grilla, que es translúcida por definición del tema)…
        const exacto = pares.find(([a]) => iguales(a, viejo) && Math.abs(a[3] - viejo[3]) < 0.005);
        if (exacto) return aTexto(exacto[1], exacto[1][3]);
        // …y si no, el mismo color con OTRA transparencia (un relleno al 35 % del violeta): se conserva la proporción.
        const parcial = pares.find(([a]) => iguales(a, viejo));
        if (parcial) return aTexto(parcial[1], viejo[3] * parcial[1][3] / (parcial[0][3] || 1));
        return valor;
    };
    for (const clave of Object.keys(nodo)) {
        const valor = nodo[clave];
        if (typeof valor === 'string') {
            const nuevo = convertir(valor);
            if (nuevo !== valor) { nodo[clave] = nuevo; cambios++; }
        } else {
            cambios += UX.recolorear(valor, antes, despues, visto);
        }
    }
    return cambios;
};
let _tokensVistos = null;
UX.recolorearGraficos = () => {
    const ahora = UX.tokensDeGraficos();
    const antes = _tokensVistos || ahora;
    _tokensVistos = ahora;
    if (!window.Chart || !window.Chart.instances) return 0;
    let total = 0;
    Object.values(window.Chart.instances).forEach(grafico => {
        total += UX.recolorear(grafico.config.data, antes, ahora) + UX.recolorear(grafico.config.options, antes, ahora);
        grafico.update('none');               // también los que arman el color con una función: se vuelve a calcular con el tema nuevo
    });
    return total;
};
window.addEventListener('DOMContentLoaded', () => {
    _tokensVistos = UX.tokensDeGraficos();
    if (window.MutationObserver) new MutationObserver(() => UX.recolorearGraficos()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
});

// ── Foco en los paneles que tapan la página (cajón de publicación, menú lateral, comentarios, buscador, confirmaciones) ────────────────────────────
// Un panel modal tiene que: (1) dejar a Tab y Mayús+Tab dando vueltas ADENTRO, (2) devolver el foco a quien lo abrió al cerrarse. Sin eso, quien navega con teclado o lector de pantalla
// sigue tabulando por una página tapada y, al cerrar, queda perdido al principio. UX.atraparFoco(panel) al abrir y UX.soltarFoco(panel) al cerrar (una pila: sirve con paneles encima de otros).
UX.ciclarFoco = (contenedor, e) => {
    const enfocables = [...contenedor.querySelectorAll('input, select, textarea, button, a[href], [tabindex]:not([tabindex="-1"])')].filter(el => !el.disabled && el.offsetParent !== null);
    if (!enfocables.length) { e.preventDefault(); contenedor.focus && contenedor.focus(); return; }
    const primero = enfocables[0], ultimo = enfocables[enfocables.length - 1];
    if (!contenedor.contains(document.activeElement)) { e.preventDefault(); primero.focus(); }
    else if (e.shiftKey && document.activeElement === primero) { e.preventDefault(); ultimo.focus(); }
    else if (!e.shiftKey && document.activeElement === ultimo) { e.preventDefault(); primero.focus(); }
};
const _pilaDeFoco = [];
UX.atraparFoco = (contenedor) => {
    if (!contenedor || _pilaDeFoco.some(x => x.contenedor === contenedor)) return;
    _pilaDeFoco.push({ contenedor, previo: document.activeElement });
    if (!contenedor.hasAttribute('tabindex')) contenedor.setAttribute('tabindex', '-1');
    contenedor.focus({ preventScroll: true });                 // el foco entra al panel: Tab empieza por su primer elemento
};
UX.soltarFoco = (contenedor) => {
    const i = _pilaDeFoco.findIndex(x => x.contenedor === contenedor);
    if (i < 0) return;
    const { previo } = _pilaDeFoco.splice(i, 1)[0];
    if (previo && previo !== document.body && document.contains(previo) && typeof previo.focus === 'function') previo.focus();
};
document.addEventListener('keydown', (e) => { if (e.key === 'Tab' && _pilaDeFoco.length) UX.ciclarFoco(_pilaDeFoco[_pilaDeFoco.length - 1].contenedor, e); });

// Un enlace marcado como deshabilitado (<a class="btn disabled"> o aria-disabled="true") no navega: antes lo frenaba `pointer-events: none`, que además escondía el tooltip con el motivo.
document.addEventListener('click', (e) => {
    const enlace = e.target.closest && e.target.closest('a.btn.disabled, a[aria-disabled="true"]');
    if (enlace) { e.preventDefault(); e.stopImmediatePropagation(); }
}, true);

// Para data-change="enviarFormulario" data-change-args='["$form"]': enviar el formulario apenas cambia un campo (por ejemplo, la fecha de Despacho).
function enviarFormulario(formulario) { if (formulario) formulario.submit(); }
// Para data-click="seleccionarTodo" data-click-args='["$el"]': seleccionar el texto de un campo al hacer clic (un link que se copia).
function seleccionarTodo(campo) { if (campo && campo.select) campo.select(); }

// Al imprimir / exportar a PDF se abren todas las secciones plegables (cerradas no se imprimen) y después se restauran.
window.addEventListener('beforeprint', () => document.querySelectorAll('details.ux-detalle').forEach(d => { d.dataset.estabaAbierto = d.open ? '1' : '0'; d.open = true; }));
window.addEventListener('afterprint', () => document.querySelectorAll('details.ux-detalle').forEach(d => { d.open = d.dataset.estabaAbierto === '1'; }));
