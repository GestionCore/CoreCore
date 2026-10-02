// ---------- Toasts ----------
// ---------- Sonido: solo para momentos que importan, nunca por cada click ----------
// Sin toggle de silenciar — son sonidos muy sutiles, no hace falta poder
// apagarlos.
let _contextoAudio = null;

function reproducirTono(notas, volumen = 0.06) {
    try {
        if (!_contextoAudio) _contextoAudio = new (window.AudioContext || window.webkitAudioContext)();
        const ctx = _contextoAudio;
        notas.forEach(nota => {
            const osc = ctx.createOscillator();
            const gain = ctx.createGain();
            osc.type = 'sine';
            osc.frequency.value = nota.freq;
            const inicio = ctx.currentTime + nota.t;
            gain.gain.setValueAtTime(0, inicio);
            gain.gain.linearRampToValueAtTime(volumen, inicio + 0.015);
            gain.gain.exponentialRampToValueAtTime(0.001, inicio + nota.dur);
            osc.connect(gain);
            gain.connect(ctx.destination);
            osc.start(inicio);
            osc.stop(inicio + nota.dur + 0.02);
        });
    } catch (e) { /* Web Audio no disponible — seguimos sin sonido, no rompe nada */ }
}

function sonidoExito() { reproducirTono([{freq: 523, t: 0, dur: 0.10}, {freq: 784, t: 0.07, dur: 0.16}]); }
function sonidoError() { reproducirTono([{freq: 220, t: 0, dur: 0.16}], 0.05); }
function sonidoUrgente() { reproducirTono([{freq: 587, t: 0, dur: 0.09}, {freq: 587, t: 0.14, dur: 0.12}], 0.055); }

function mostrarToast(mensaje, tipo = 'info') {
    const cont = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast-item toast-${tipo}`;
    toast.textContent = mensaje;
    cont.appendChild(toast);
    requestAnimationFrame(() => toast.classList.add('visible'));
    setTimeout(() => { toast.classList.remove('visible'); setTimeout(() => toast.remove(), 300); }, 3200);
    if (tipo === 'success') sonidoExito();
    else if (tipo === 'error') sonidoError();
}

function revisarMensajeEnURL() {
    const params = new URLSearchParams(window.location.search);
    const msg = params.get('msg');
    const tipo = params.get('tipo') || 'success';
    if (msg) {
        mostrarToast(msg, tipo);
        params.delete('msg'); params.delete('tipo');
        const nuevaUrl = window.location.pathname + (params.toString() ? '?' + params.toString() : '');
        window.history.replaceState({}, '', nuevaUrl);
    }
}

// ---------- Modo Privacidad ----------
function alternarModoPrivacidad() {
    document.documentElement.classList.toggle('modo-privacidad');
    localStorage.setItem('modo_privacidad', document.documentElement.classList.contains('modo-privacidad') ? '1' : '0');
}

// ---------- Panel personalizable (mostrar/ocultar paneles opcionales) ----------
const CLAVE_PANELES_HABILITADOS = 'paneles_stock_habilitados';

function _obtenerPreferenciasPaneles() {
    return JSON.parse(localStorage.getItem(CLAVE_PANELES_HABILITADOS) || '{}');
}

function panelHabilitado(clave) {
    const prefs = _obtenerPreferenciasPaneles();
    return prefs[clave] !== false;  // por defecto, todo visible
}

function togglePanelPersonalizar() {
    const panel = document.getElementById('panel-personalizar');
    if (!panel) return;
    const abrir = panel.style.display === 'none';
    if (abrir) { mostrarPanelConAnimacion(panel); } else { panel.style.display = 'none'; }
    if (abrir) {
        const prefs = _obtenerPreferenciasPaneles();
        document.getElementById('chk-mostrar-agotamiento').checked = prefs.agotamiento !== false;
        document.getElementById('chk-mostrar-oportunidades').checked = prefs.oportunidades !== false;
    }
}

function guardarPreferenciaPanel() {
    const prefs = {
        agotamiento: document.getElementById('chk-mostrar-agotamiento').checked,
        oportunidades: document.getElementById('chk-mostrar-oportunidades').checked
    };
    localStorage.setItem(CLAVE_PANELES_HABILITADOS, JSON.stringify(prefs));
    if (typeof cargarRiesgoStock === 'function') cargarRiesgoStock();
    cargarOportunidadesSeo();
}

// ---------- Tema claro/oscuro ----------
// ---------- "Mostrar más" genérico para listas largas ----------
// Uso: envolvé los ítems más allá del N-ésimo con class="oculto-mostrar-mas"
// (además de cualquier otra clase que ya tengan), y un botón con
// onclick="mostrarMasGenerico(this)" justo después de la lista.
// ---------- Animación de entrada para paneles que aparecen por JS ----------
// Los paneles normales se animan solos al cargar la página (vía CSS). Pero
// un panel que arranca con display:none y se muestra recién cuando termina
// un fetch NO siempre retoma esa animación sola — hay que reiniciarla a mano.
// ---------- Ripple en todos los botones — un solo listener, no toca ningún botón existente ----------
// ---------- Transición suave entre páginas (fade breve antes de navegar) ----------
document.addEventListener('click', function (e) {
    const link = e.target.closest('a[href]');
    if (!link) return;
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (link.target === '_blank' || link.hasAttribute('download')) return;
    const href = link.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:') || href.startsWith('http') || link.origin !== window.location.origin) return;

    const cont = document.querySelector('.page-container');
    if (!cont) return;
    e.preventDefault();
    cont.classList.add('saliendo');
    setTimeout(() => { window.location.href = href; }, 160);
    // Red de seguridad: si esto era una descarga (PDF, planilla) y no una
    // navegación real, la página nunca se recarga — sin esto, quedaría
    // desvanecida para siempre. Si seguimos acá pasado un rato, revertimos.
    setTimeout(() => { cont.classList.remove('saliendo'); }, 1400);
});

document.addEventListener('click', function (e) {
    const boton = e.target.closest('.btn');
    if (!boton) return;
    const rect = boton.getBoundingClientRect();
    const tamano = Math.max(rect.width, rect.height);
    const ripple = document.createElement('span');
    ripple.className = 'btn-ripple';
    ripple.style.width = ripple.style.height = tamano + 'px';
    ripple.style.left = (e.clientX - rect.left - tamano / 2) + 'px';
    ripple.style.top = (e.clientY - rect.top - tamano / 2) + 'px';
    boton.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
});

// ---------- Celebración breve (confeti) al completar algo al 100% ----------
function celebrarConfeti() {
    const colores = ['139, 92, 246', '56, 189, 248', '242, 201, 76', '34, 197, 94'];
    const cantidad = 28;
    for (let i = 0; i < cantidad; i++) {
        const p = document.createElement('div');
        const color = colores[Math.floor(Math.random() * colores.length)];
        const angulo = Math.random() * Math.PI * 2;
        const distancia = 80 + Math.random() * 160;
        p.style.cssText = `
            position: fixed; left: 50%; top: 40%; width: 8px; height: 8px; border-radius: 2px;
            background: rgba(${color}, 0.9); box-shadow: 0 0 6px rgba(${color}, 0.8);
            pointer-events: none; z-index: 600;
            transform: translate(-50%, -50%) rotate(${Math.random()*360}deg);
            transition: transform 0.9s cubic-bezier(0.2, 0.8, 0.4, 1), opacity 0.9s ease-out;
        `;
        document.body.appendChild(p);
        requestAnimationFrame(() => {
            p.style.transform = `translate(calc(-50% + ${Math.cos(angulo) * distancia}px), calc(-50% + ${Math.sin(angulo) * distancia}px)) rotate(${Math.random()*720}deg)`;
            p.style.opacity = '0';
        });
        setTimeout(() => p.remove(), 950);
    }
    reproducirTono([{freq: 523, t: 0, dur: 0.08}, {freq: 659, t: 0.06, dur: 0.08}, {freq: 784, t: 0.12, dur: 0.18}], 0.05);
}

// ---------- Badge de alertas en el nav ----------
function _actualizarBadgeNav(n) {
    const badge = document.getElementById('nav-badge-incidencias');
    if (!badge) return;
    if (n > 0) { badge.textContent = n > 9 ? '9+' : n; badge.style.display = 'inline-flex'; }
    else { badge.style.display = 'none'; }
    // también actualizar el badge de Logros en el dropdown (misiones urgentes)
    const badgeLogros = document.getElementById('nav-badge-logros');
    if (badgeLogros) {
        if (n > 0) { badgeLogros.textContent = n > 9 ? '9+' : n; badgeLogros.style.display = 'inline-flex'; }
        else { badgeLogros.style.display = 'none'; }
    }
}

async function cargarAlertasPendientes() {
    try {
        const resp = await fetch('/api/alertas/pendientes');
        const d = await resp.json();
        if (d.total > 0) _actualizarBadgeNav(d.total);
    } catch (e) { /* silencioso */ }
}

// ---------- Sincronizar Todo (botón global en la barra superior) ----------
// La sincronización corre en segundo plano en el servidor: se la pide con POST (responde enseguida) y se consulta
// /api/estado_sincronizacion cada 2 s hasta que `en_curso` es false.
function ejecutarSincronizarTodo(btn, alTerminar) {
    btn = btn || document.getElementById('btn-sincronizar-todo');
    if (!btn || btn.disabled) return;
    const textoOriginal = btn.innerHTML;
    const _spin = '<svg class="icon spin-anim" style="width:14px;height:14px;"><use href="#icon-refresh"/></svg>';
    const liberar = () => { btn.disabled = false; btn.innerHTML = textoOriginal; };
    btn.disabled = true;
    btn.innerHTML = _spin + '<span class="btn-sync-texto">Sincronizando...</span>';
    fetch('/sincronizar_todo', { method: 'POST' })
        .then(r => r.json())
        .then(data => {
            if (data.status === 'ya_en_curso') mostrarToast('Ya hay una sincronización en curso: esperamos a que termine.', 'info');
            let intentos = 0;
            const maxIntentos = 90;   // 3 minutos como máximo
            const poll = setInterval(() => {
                intentos++;
                fetch('/api/estado_sincronizacion')
                    .then(r => r.json())
                    .then(est => {
                        if (!est.en_curso || intentos >= maxIntentos) {
                            clearInterval(poll);
                            liberar();
                            mostrarToast('Sincronización completada.', 'success');
                            if (alTerminar) alTerminar();
                        }
                    })
                    .catch(() => { clearInterval(poll); liberar(); });
            }, 2000);
        })
        .catch(() => { liberar(); mostrarToast('Error al iniciar sincronización.', 'error'); });
}

// "Traer ventas nuevas" (Despacho): sincroniza y recarga la página cuando termina
function sincronizarYRecargar(btn) { ejecutarSincronizarTodo(btn, () => window.location.reload()); }

function mostrarPanelConAnimacion(elemento) {
    if (!elemento) return;
    elemento.style.display = '';
    elemento.classList.remove('anim-entrada-js');
    void elemento.offsetWidth; // fuerza un reflow para que el navegador "olvide" el estado anterior
    elemento.classList.add('anim-entrada-js');
}

function mostrarMasGenerico(boton) {
    const alcance = boton.closest('[data-mostrar-mas-scope]') || document;
    alcance.querySelectorAll('.oculto-mostrar-mas').forEach(el => { el.classList.remove('oculto-mostrar-mas'); });
    boton.remove();
}

/**
 * Atajo de "últimos N días" para cualquier formulario de período. Se
 * engancha por atributos data-* en el propio <form>, así que se puede
 * reusar en Ganancia Real, Publicidad, Comparador Logística, etc. sin
 * repetir la función — data-form-periodo="idDelForm" en el <form> y
 * onclick="aplicarUltimosDias(N, this)" en cada botón alcanza.
 */
function aplicarUltimosDias(dias, boton) {
    const form = boton.closest('form');
    if (!form) return;
    const hoy = new Date();
    const desde = new Date();
    desde.setDate(hoy.getDate() - (dias - 1));
    // Fecha LOCAL: toISOString() es UTC y después de las 21 h de Argentina ya da el día siguiente
    const aISO = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    form.querySelector('input[name="fecha_desde"]').value = aISO(desde);
    form.querySelector('input[name="fecha_hasta"]').value = aISO(hoy);
    // Feedback visual inmediato del botón tocado — el submit de abajo
    // recarga la página enseguida, pero marcarUltimosDiasActivo() (más
    // abajo) es quien deja el estado "presionado" correcto una vez que
    // esa página nueva termina de cargar.
    form.querySelectorAll('button[onclick^="aplicarUltimosDias("]').forEach(b => b.classList.remove('active'));
    boton.classList.add('active');
    form.submit();
}

/**
 * Al volver a cargar la página después de tocar "7/14/30 días" (o de
 * entrar con un período ya guardado), ninguno de esos botones quedaba
 * marcado como activo — parecía que el click no había hecho nada, aunque
 * el período sí había cambiado. Se fija comparando fecha_desde/fecha_hasta
 * (guardadas en el data-desde/data-hasta de .rango-fechas, que sí vienen
 * del server) contra la cantidad de días de cada botón.
 */
function marcarUltimosDiasActivo() {
    document.querySelectorAll('.rango-fechas[data-desde][data-hasta]').forEach(cont => {
        const form = cont.closest('form');
        const desdeStr = cont.dataset.desde, hastaStr = cont.dataset.hasta;
        if (!form || !desdeStr || !hastaStr) return;
        const botones = form.querySelectorAll('button[onclick^="aplicarUltimosDias("]');
        if (!botones.length) return;
        const desde = new Date(desdeStr + 'T00:00:00');
        const hasta = new Date(hastaStr + 'T00:00:00');
        const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
        const terminaHoy = Math.abs(hasta - hoy) < 86400000;
        const dias = Math.round((hasta - desde) / 86400000) + 1;
        // Un día de tolerancia: el período por defecto del servidor ("hoy menos 30 días") abarca 31 días contando hoy, y el botón
        // "30 días" nunca quedaba marcado. Con botones de 7, 14 y 30 no hay forma de confundir uno con otro.
        botones.forEach(b => {
            const m = b.getAttribute('onclick').match(/aplicarUltimosDias\((\d+)/);
            const n = m ? parseInt(m[1], 10) : null;
            b.classList.toggle('active', terminaHoy && n !== null && Math.abs(n - dias) <= 1);
        });
    });
}
document.addEventListener('DOMContentLoaded', marcarUltimosDiasActivo);

/**
 * Selector de rango de fechas unificado (pedido explícito) — reemplaza
 * los pares de <input type="date"> desde/hasta repetidos en Ganancia
 * Real, Costos, Publicidad, Comparador Logística y Promociones: 1er
 * click define el inicio, 2do click define el fin (si el 2do click cae
 * antes del 1ro, se invierten solos — no hace falta acertar el orden).
 *
 * Uso en el HTML: reemplazar los dos field-group de fecha por
 *   <div class="rango-fechas" id="MI_ID" data-desde="{{ fecha_desde }}" data-hasta="{{ fecha_hasta }}">
 *     <button type="button" class="rango-fechas-boton" onclick="RangoFechas.toggle('MI_ID')"></button>
 *     <input type="hidden" name="fecha_desde">
 *     <input type="hidden" name="fecha_hasta">
 *   </div>
 * e inicializar con RangoFechas.inicializar('MI_ID') en DOMContentLoaded.
 * Los inputs hidden se llaman igual que los <input type="date"> de
 * antes, así que aplicarUltimosDias() y el submit del form no cambian.
 */
const RangoFechas = {
    MESES: ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre'],
    DIAS: ['Lu','Ma','Mi','Ju','Vi','Sá','Do'],
    estados: {},

    _aISO(anio, mes, dia) {
        return `${anio}-${String(mes + 1).padStart(2, '0')}-${String(dia).padStart(2, '0')}`;
    },

    // "2 sep" (con el año solo si no es el actual): se lee de un vistazo, a diferencia de "02/09/2026"
    MESES_CORTOS: ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'],
    _formatearCorto(iso) {
        if (!iso) return '';
        const [a, m, d] = iso.split('-').map(Number);
        return `${d} ${this.MESES_CORTOS[m - 1]}` + (a !== new Date().getFullYear() ? ` ${a}` : '');
    },

    inicializar(id) {
        const cont = document.getElementById(id);
        if (!cont) return;
        const desde = cont.dataset.desde || null;
        const hasta = cont.dataset.hasta || null;
        const base = desde ? new Date(desde + 'T00:00:00') : new Date();
        this.estados[id] = { inicio: desde, fin: hasta, anio: base.getFullYear(), mes: base.getMonth(), abierto: false };
        this._actualizarBoton(id);

        document.addEventListener('click', (e) => {
            const est = this.estados[id];
            if (!est || !est.abierto) return;
            const widget = document.getElementById(id);
            // composedPath() en vez de widget.contains(e.target): elegirDia()
            // reemplaza el innerHTML del popup (re-renderiza el calendario) en
            // el mismo click que lo dispara, así que para cuando este listener
            // corre en la fase de bubble, el <span> del día que se clickeó ya
            // fue reemplazado por uno nuevo — contains() con ese nodo
            // desconectado siempre da false y cerraba el popup en cada click a
            // un día. composedPath() es la ruta del evento capturada ANTES de
            // esa mutación, así que sigue siendo correcta.
            const ruta = e.composedPath ? e.composedPath() : [];
            if (widget && !ruta.includes(widget)) this.cerrar(id);
        });
    },

    toggle(id) {
        const est = this.estados[id];
        if (!est) return;
        est.abierto ? this.cerrar(id) : this.abrir(id);
    },

    abrir(id) {
        const est = this.estados[id];
        est.abierto = true;
        this._render(id);
        document.getElementById(id).classList.add('abierto');
    },

    cerrar(id) {
        const est = this.estados[id];
        if (!est) return;
        est.abierto = false;
        const widget = document.getElementById(id);
        if (widget) widget.classList.remove('abierto');
    },

    cambiarMes(id, delta) {
        const est = this.estados[id];
        est.mes += delta;
        if (est.mes < 0) { est.mes = 11; est.anio--; }
        else if (est.mes > 11) { est.mes = 0; est.anio++; }
        this._render(id);
    },

    elegirDia(id, iso) {
        const est = this.estados[id];
        if (!est.inicio || (est.inicio && est.fin)) {
            est.inicio = iso;
            est.fin = null;
        } else if (iso < est.inicio) {
            est.fin = est.inicio;
            est.inicio = iso;
        } else {
            est.fin = iso;
        }
        this._render(id);
        this._actualizarBoton(id);
        if (est.inicio && est.fin) {
            const cont = document.getElementById(id);
            cont.querySelector('input[name="fecha_desde"]').value = est.inicio;
            cont.querySelector('input[name="fecha_hasta"]').value = est.fin;
            this.cerrar(id);
        }
    },

    _actualizarBoton(id) {
        const est = this.estados[id];
        const cont = document.getElementById(id);
        if (!cont) return;
        const boton = cont.querySelector('.rango-fechas-boton');
        const inputDesde = cont.querySelector('input[name="fecha_desde"]');
        const inputHasta = cont.querySelector('input[name="fecha_hasta"]');
        if (inputDesde) inputDesde.value = est.inicio || '';
        if (inputHasta) inputHasta.value = est.fin || '';
        if (boton) {
            boton.textContent = (est.inicio && est.fin)
                ? `${this._formatearCorto(est.inicio)} – ${this._formatearCorto(est.fin)}`
                : (est.inicio ? `${this._formatearCorto(est.inicio)} – elegí el fin` : 'Elegí un rango');
        }
    },

    _render(id) {
        const est = this.estados[id];
        const cont = document.getElementById(id);
        if (!cont || !est) return;
        let popup = cont.querySelector('.rango-fechas-popup');
        if (!popup) {
            popup = document.createElement('div');
            popup.className = 'rango-fechas-popup';
            cont.appendChild(popup);
        }

        const primerDiaSemana = (new Date(est.anio, est.mes, 1).getDay() + 6) % 7; // lunes=0
        const diasEnMes = new Date(est.anio, est.mes + 1, 0).getDate();
        const hoyISO = this._aISO(new Date().getFullYear(), new Date().getMonth(), new Date().getDate());

        let celdas = '';
        for (let i = 0; i < primerDiaSemana; i++) celdas += '<span class="rf-dia rf-vacio"></span>';
        for (let d = 1; d <= diasEnMes; d++) {
            const iso = this._aISO(est.anio, est.mes, d);
            const esInicio = iso === est.inicio;
            const esFin = iso === est.fin;
            const enRango = est.inicio && est.fin && iso > est.inicio && iso < est.fin;
            const clases = ['rf-dia'];
            if (esInicio || esFin) clases.push('rf-limite');
            if (enRango) clases.push('rf-en-rango');
            if (iso === hoyISO) clases.push('rf-hoy');
            celdas += `<span class="${clases.join(' ')}" onclick="RangoFechas.elegirDia('${id}','${iso}')">${d}</span>`;
        }

        popup.innerHTML = `
            <div class="rf-header">
                <button type="button" onclick="RangoFechas.cambiarMes('${id}',-1)">‹</button>
                <strong>${this.MESES[est.mes]} ${est.anio}</strong>
                <button type="button" onclick="RangoFechas.cambiarMes('${id}',1)">›</button>
            </div>
            <div class="rf-grid rf-grid-header">${this.DIAS.map(d => `<span>${d}</span>`).join('')}</div>
            <div class="rf-grid">${celdas}</div>
            <div class="rf-footer">${est.inicio ? this._formatearCorto(est.inicio) : '...'} → ${est.fin ? this._formatearCorto(est.fin) : '...'}</div>
        `;
    }
};

// ---------- Tutorial guiado (primera vez, después de la encuesta) ----------
const PASOS_TUTORIAL = [
    { selector: '.brand', titulo: 'Este es tu punto de partida', texto: 'El logo te trae de vuelta acá desde cualquier pantalla.' },
    { selector: '#tour-buscador', titulo: 'Buscador universal', texto: 'Buscá cualquier publicación o sección de la app — o abrilo en cualquier momento con Ctrl+K.' },
    { selector: '#tour-nav-catalogo', titulo: 'Catálogo', texto: 'Tu stock por modelo, la vista masiva para editar varios a la vez, y el panel de despacho del día.' },
    { selector: '#tour-nav-finanzas', titulo: 'Finanzas', texto: 'Ganancia Real, Facturación, Costos y más — todo lo que tiene que ver con la plata.' },
    { selector: '#tour-nav-crecimiento', titulo: 'Crecimiento', texto: 'Promociones, tendencias, competencia y publicidad — para vender más, no solo para medir lo que ya vendiste.' },
    { selector: '#btn-sincronizar-todo', titulo: 'Sincronizar Todo', texto: 'Trae lo último de Mercado Libre bajo demanda. De fondo, esto ya corre solo cada tanto — no hace falta que lo toques seguido.' },
    { selector: '.ticker-bar', titulo: 'Estado en vivo', texto: 'Ventas de hoy, plata que se libera mañana, reclamos activos y salud de la cuenta, siempre a la vista.' },
];

let _tourPasoActual = 0;
let _tourElementos = null;

function _crearElementosTour() {
    const capa = document.createElement('div');
    capa.id = 'tour-capa';
    capa.innerHTML = `
        <div class="tour-mascara tour-mascara-top"></div>
        <div class="tour-mascara tour-mascara-bottom"></div>
        <div class="tour-mascara tour-mascara-left"></div>
        <div class="tour-mascara tour-mascara-right"></div>
        <div class="tour-anillo"></div>
        <div class="tour-tarjeta">
            <div class="tour-tarjeta-titulo"></div>
            <div class="tour-tarjeta-texto"></div>
            <div class="tour-tarjeta-footer">
                <button type="button" class="tour-btn-saltar" onclick="saltarTutorial()">Saltar tutorial</button>
                <div style="display:flex; align-items:center; gap:12px;">
                    <span class="tour-tarjeta-contador"></span>
                    <button type="button" class="tour-btn-siguiente" onclick="avanzarTutorial()">Siguiente</button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(capa);
    return {
        capa, top: capa.querySelector('.tour-mascara-top'), bottom: capa.querySelector('.tour-mascara-bottom'),
        left: capa.querySelector('.tour-mascara-left'), right: capa.querySelector('.tour-mascara-right'),
        anillo: capa.querySelector('.tour-anillo'), tarjeta: capa.querySelector('.tour-tarjeta'),
        titulo: capa.querySelector('.tour-tarjeta-titulo'), texto: capa.querySelector('.tour-tarjeta-texto'),
        contador: capa.querySelector('.tour-tarjeta-contador'),
        btnSiguiente: capa.querySelector('.tour-btn-siguiente'),
    };
}

function _posicionarPasoTour() {
    const paso = PASOS_TUTORIAL[_tourPasoActual];
    const objetivo = document.querySelector(paso.selector);
    if (!objetivo) { avanzarTutorial(); return; }
    objetivo.scrollIntoView({ block: 'center', behavior: 'instant' });

    const r = objetivo.getBoundingClientRect();
    const margen = 8;
    const vw = window.innerWidth, vh = window.innerHeight;
    const el = _tourElementos;

    Object.assign(el.top.style, { left: '0px', top: '0px', width: vw + 'px', height: Math.max(r.top - margen, 0) + 'px' });
    Object.assign(el.bottom.style, { left: '0px', top: (r.bottom + margen) + 'px', width: vw + 'px', height: Math.max(vh - r.bottom - margen, 0) + 'px' });
    Object.assign(el.left.style, { left: '0px', top: (r.top - margen) + 'px', width: Math.max(r.left - margen, 0) + 'px', height: (r.height + margen * 2) + 'px' });
    Object.assign(el.right.style, { left: (r.right + margen) + 'px', top: (r.top - margen) + 'px', width: Math.max(vw - r.right - margen, 0) + 'px', height: (r.height + margen * 2) + 'px' });
    Object.assign(el.anillo.style, { left: (r.left - margen) + 'px', top: (r.top - margen) + 'px', width: (r.width + margen * 2) + 'px', height: (r.height + margen * 2) + 'px' });

    el.titulo.textContent = paso.titulo;
    el.texto.textContent = paso.texto;
    el.contador.textContent = `${_tourPasoActual + 1} / ${PASOS_TUTORIAL.length}`;
    el.btnSiguiente.textContent = (_tourPasoActual === PASOS_TUTORIAL.length - 1) ? 'Entendido' : 'Siguiente';

    const tarjetaAncho = 320;
    let tarjetaTop = r.bottom + margen + 14;
    let tarjetaLeft = Math.min(Math.max(r.left, 12), vw - tarjetaAncho - 12);
    if (tarjetaTop + 140 > vh) tarjetaTop = Math.max(r.top - 154, 12);
    Object.assign(el.tarjeta.style, { top: tarjetaTop + 'px', left: tarjetaLeft + 'px' });
}

function avanzarTutorial() {
    _tourPasoActual++;
    if (_tourPasoActual >= PASOS_TUTORIAL.length) { finalizarTutorial(); return; }
    _posicionarPasoTour();
}

function saltarTutorial() { finalizarTutorial(); }

function finalizarTutorial() {
    if (_tourElementos) { _tourElementos.capa.remove(); _tourElementos = null; }
    window.removeEventListener('resize', _posicionarPasoTour);
}

function iniciarTutorial() {
    fetch('/onboarding/tutorial_visto', { method: 'POST' }).catch(() => {});
    _tourPasoActual = 0;
    _tourElementos = _crearElementosTour();
    window.addEventListener('resize', _posicionarPasoTour);
    _posicionarPasoTour();
}

// ---------- Entrega Flex ----------
// Umbral de entrega (id del umbral; 0 = sin costo) de una orden Flex. Devuelve {ok, error}; cada pantalla pinta el resultado a su manera.
async function asignarZonaFlex(idOrden, umbral) {
    try {
        const resp = await fetch('/api/flex/zona', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id_orden: String(idOrden), umbral })
        });
        const data = await resp.json();
        return { ok: !!data.ok, error: data.error || 'No se pudo guardar.' };
    } catch (e) {
        return { ok: false, error: 'No pude conectar — revisá la conexión y probá de nuevo.' };
    }
}

// ---------- Costos por chat ----------
let _costosChatHistorial = [];

function _agregarBurbujaCostosChat(texto, esUsuario) {
    const cont = document.getElementById('costos-chat-mensajes');
    const burbuja = document.createElement('div');
    burbuja.style.cssText = `align-self:${esUsuario ? 'flex-end' : 'flex-start'}; max-width:80%; padding:10px 14px; border-radius:12px; font-size:0.88em; line-height:1.4; background:${esUsuario ? 'var(--accent-primary)' : 'rgba(255,255,255,0.05)'}; color:${esUsuario ? '#fff' : 'var(--text-primary)'};`;
    burbuja.textContent = texto;
    cont.appendChild(burbuja);
    cont.scrollTop = cont.scrollHeight;
}

async function enviarMensajeCostosChat(evento) {
    evento.preventDefault();
    const input = document.getElementById('costos-chat-input');
    const mensaje = input.value.trim();
    if (!mensaje) return false;

    _agregarBurbujaCostosChat(mensaje, true);
    _costosChatHistorial.push({ role: 'user', content: mensaje });
    input.value = '';
    input.disabled = true;

    try {
        const resp = await fetch('/api/costos_chat', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ historial: _costosChatHistorial })
        });
        const data = await resp.json();

        if (data.accion === 'preguntar' || data.accion === 'error') {
            const texto = data.pregunta || data.mensaje;
            _agregarBurbujaCostosChat(texto, false);
            _costosChatHistorial.push({ role: 'assistant', content: JSON.stringify(data) });
        } else if (data.accion === 'confirmar') {
            _mostrarPropuestaCostosChat(data.gastos || [], data.costos_productos || []);
        }
    } catch (e) {
        _agregarBurbujaCostosChat('No pude conectar — intentá de nuevo en un momento.', false);
    } finally {
        input.disabled = false;
        input.focus();
    }
    return false;
}

function _mostrarPropuestaCostosChat(gastos, costosProductos) {
    const cont = document.getElementById('costos-chat-propuesta');
    const plata = n => '$' + Number(n).toLocaleString('es-AR');
    const pub = n => n === 1 ? 'publicación' : 'publicaciones';
    const estiloFila = 'font-size:0.9em; line-height:1.7; color:var(--text-secondary); padding:6px 0; border-top:1px solid var(--glass-border);';

    const filasGastos = gastos.map(propuesta => {
        const tipoTexto = propuesta.recurrente ? `Recurrente desde ${propuesta.fecha_desde}` : `Único, el ${propuesta.fecha_desde}`;
        return `<div style="${estiloFila}">
            <strong style="color:var(--text-primary);">${escapeHtml(String(propuesta.concepto))}</strong> — ${plata(propuesta.monto)}
            — ${propuesta.categoria === 'fijo' ? 'Fijo' : 'Variable'} — ${escapeHtml(tipoTexto)}
        </div>`;
    }).join('');

    // Costos de fabricación por producto: se muestra CADA modelo que se va a tocar, con su costo de antes
    const antes = m => m.costo_actual_max <= 0 ? 'sin costo cargado' : (m.costo_actual_min === m.costo_actual_max ? `antes ${plata(m.costo_actual_min)}` : `antes ${plata(m.costo_actual_min)} a ${plata(m.costo_actual_max)}`);
    const bloquesCostos = costosProductos.map(cp => {
        if (!cp.total) {
            return `<div style="${estiloFila}"><strong style="color:var(--semantic-warning);">⚠ No encontré publicaciones para «${escapeHtml(cp.grupo)}»</strong> — no se carga nada para ese grupo. Podés corregirlo y mandarlo de nuevo.</div>`;
        }
        const modelos = cp.modelos.map(m => `<div style="padding-left:14px;">· ${escapeHtml(m.modelo)} <span style="color:var(--text-faint);">— ${m.cantidad} ${pub(m.cantidad)} (${antes(m)})</span></div>`).join('');
        return `<div style="${estiloFila}"><strong style="color:var(--text-primary);">Costo de fabricación ${plata(cp.costo)} por unidad</strong> para «${escapeHtml(cp.grupo)}» — <b>${cp.total} ${pub(cp.total)}</b>${modelos}</div>`;
    }).join('');

    const partes = [];
    if (gastos.length) partes.push(gastos.length > 1 ? `${gastos.length} gastos` : '1 gasto');
    const totalPubs = costosProductos.reduce((s, cp) => s + (cp.total || 0), 0);
    if (totalPubs) partes.push(`el costo de ${totalPubs} ${pub(totalPubs)}`);
    const titulo = partes.length ? `Voy a cargar ${partes.join(' y ')}:` : 'No hay nada para cargar todavía:';
    cont.innerHTML = `
        <div class="panel" style="border-color:var(--accent-primary); margin:0 0 14px;">
            <div style="font-weight:600; margin-bottom:4px;">${titulo}</div>
            ${filasGastos}${bloquesCostos}
            <div style="display:flex; gap:10px; margin-top:14px;">
                ${partes.length ? '<button type="button" class="btn btn-primary" onclick="confirmarPropuestaCostosChat()">Confirmar y cargar</button>' : ''}
                <button type="button" class="btn btn-secondary" onclick="corregirPropuestaCostosChat()">Corregir</button>
            </div>
        </div>
    `;
    cont.style.display = 'block';
    cont.dataset.propuesta = JSON.stringify({
        gastos,
        costos_productos: costosProductos.filter(cp => cp.total).map(cp => ({ costo: cp.costo, ids: cp.modelos.flatMap(m => m.ids) })),
    });
}

async function confirmarPropuestaCostosChat() {
    const cont = document.getElementById('costos-chat-propuesta');
    const { gastos, costos_productos } = JSON.parse(cont.dataset.propuesta);
    const pub = n => n === 1 ? 'publicación' : 'publicaciones';
    try {
        const resp = await fetch('/api/costos_chat/confirmar', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ propuestas: gastos, costos_productos })
        });
        const data = await resp.json();
        if (data.ok) {
            const dichos = [];
            if (data.gastos) dichos.push(`${data.gastos} gasto${data.gastos === 1 ? '' : 's'}`);
            if (data.publicaciones) dichos.push(`costo de ${data.publicaciones} ${pub(data.publicaciones)}`);
            const params = new URLSearchParams(window.location.search);
            params.set('msg', `Listo: cargué ${dichos.join(' y ') || 'los datos'}.`); params.set('tipo', 'success');
            window.location.search = params.toString();
            return;
        } else {
            _agregarBurbujaCostosChat('No se pudo guardar: ' + (data.error || 'error desconocido'), false);
        }
    } catch (e) {
        _agregarBurbujaCostosChat('No pude guardar el gasto — intentá de nuevo.', false);
    }
    cont.style.display = 'none';
}

function corregirPropuestaCostosChat() {
    document.getElementById('costos-chat-propuesta').style.display = 'none';
    _agregarBurbujaCostosChat('Contame qué querés cambiar.', false);
    document.getElementById('costos-chat-input').focus();
}

function alternarTema() {
    const esClaro = document.documentElement.dataset.theme === 'light';
    if (esClaro) {
        delete document.documentElement.dataset.theme;
        localStorage.setItem('tema', 'dark');
        _setIconoTema('moon');
    } else {
        document.documentElement.dataset.theme = 'light';
        localStorage.setItem('tema', 'light');
        _setIconoTema('sun');
    }
}

function _setIconoTema(nombre) {
    const use = document.getElementById('icono-tema-use');
    if (use) use.setAttribute('href', '#icon-' + nombre);
}

function _inicializarIconoTema() {
    _setIconoTema(document.documentElement.dataset.theme === 'light' ? 'sun' : 'moon');
}

// ---------- Números que ruedan ----------
function parsearValorMoneda(texto) {
    const match = texto.match(/^([^\d]*)([\d.,]+)(.*)$/);
    if (!match) return null;
    const [, prefijo, numeroStr, sufijo] = match;
    const numero = parseFloat(numeroStr.replace(/\./g, '').replace(',', '.'));
    if (isNaN(numero)) return null;
    return { prefijo, numero, sufijo, tieneDecimales: numeroStr.includes(',') };
}
function formatearNumeroAR(valor, conDecimales) {
    return valor.toLocaleString('es-AR', conDecimales ? { minimumFractionDigits: 2, maximumFractionDigits: 2 } : { maximumFractionDigits: 0 });
}
// Cuenta ascendente genérica para un número que llega por fetch (no estaba
// en el HTML al cargar la página, así que animarContadoresEnPagina() no lo
// puede tomar solo) — from 0 hasta valorFinal, formateado con `formatearFn`.
function animarNumeroHasta(el, valorFinal, formatearFn, duracionMs = 650) {
    const t0 = performance.now();
    function frame(t) {
        const progreso = Math.min((t - t0) / duracionMs, 1);
        const facilitado = 1 - Math.pow(1 - progreso, 3);
        el.textContent = formatearFn(valorFinal * facilitado);
        if (progreso < 1) requestAnimationFrame(frame); else el.textContent = formatearFn(valorFinal);
    }
    requestAnimationFrame(frame);
}
function animarContadoresEnPagina() {
    document.querySelectorAll('.stat-chip-value, .hero-number').forEach(el => {
        if (el.children.length > 0) return; // tiene contenido anidado (ej: variación al lado) — no lo tocamos
        const original = el.textContent.trim();
        const parseado = parsearValorMoneda(original);
        if (!parseado) return;
        const { prefijo, numero, sufijo, tieneDecimales } = parseado;
        const t0 = performance.now();
        const duracion = 550;
        function frame(t) {
            const progreso = Math.min((t - t0) / duracion, 1);
            const facilitado = 1 - Math.pow(1 - progreso, 3);
            el.textContent = prefijo + formatearNumeroAR(numero * facilitado, tieneDecimales) + sufijo;
            if (progreso < 1) requestAnimationFrame(frame); else el.textContent = original;
        }
        requestAnimationFrame(frame);
    });
}

// ---------- Búsqueda flexible multi-token ----------
function coincideBusqueda(textoCompleto, consulta) {
    const tokens = consulta.toLowerCase().split(/\s+/).filter(Boolean);
    const texto = textoCompleto.toLowerCase();
    return tokens.every(t => texto.includes(t));
}

// ---------- IDs copiables ----------
function envolverIdsCopiables(raiz) {
    const regexId = /\bMLA\d{6,}\b/;
    const treeWalker = document.createTreeWalker(raiz, NodeFilter.SHOW_TEXT, {
        acceptNode: (nodo) => {
            const padre = nodo.parentElement;
            if (!padre) return NodeFilter.FILTER_REJECT;
            if (['SCRIPT', 'STYLE', 'INPUT', 'TEXTAREA', 'OPTION'].includes(padre.tagName)) return NodeFilter.FILTER_REJECT;
            if (padre.closest('.id-copiable')) return NodeFilter.FILTER_REJECT;
            return regexId.test(nodo.textContent) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
        }
    });
    const nodos = [];
    let n;
    while ((n = treeWalker.nextNode())) nodos.push(n);
    nodos.forEach(nodo => {
        const partes = nodo.textContent.split(/(\bMLA\d{6,}\b)/g);
        if (partes.length <= 1) return;
        const fragmento = document.createDocumentFragment();
        partes.forEach(parte => {
            if (/^MLA\d{6,}$/.test(parte)) {
                const span = document.createElement('span');
                span.className = 'id-copiable';
                span.title = 'Click para copiar';
                span.textContent = parte;
                fragmento.appendChild(span);
            } else { fragmento.appendChild(document.createTextNode(parte)); }
        });
        nodo.parentNode.replaceChild(fragmento, nodo);
    });
}
document.addEventListener('click', (e) => {
    const el = e.target.closest('.id-copiable');
    if (!el) return;
    navigator.clipboard.writeText(el.textContent).then(() => {
        mostrarToast('Dato copiado al portapapeles', 'success');
        el.classList.remove('destello-copiado');
        void el.offsetWidth;
        el.classList.add('destello-copiado');
    });
});

// ---------- Ctrl+Enter guarda el formulario activo ----------
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const formActivo = document.activeElement ? document.activeElement.closest('form') : null;
        if (formActivo) {
            e.preventDefault();
            formActivo.requestSubmit ? formActivo.requestSubmit() : formActivo.submit();
        }
    }
});

// ---------- Ticker superior ----------
async function actualizarTicker() {
    try {
        const resp = await fetch('/api/ticker');
        const data = await resp.json();
        const elVentas = document.getElementById('ticker-ventas');
        const elLiberacion = document.getElementById('ticker-liberacion');
        elVentas.classList.remove('skeleton');
        elLiberacion.classList.remove('skeleton');
        elVentas.textContent = `Hoy: ${data.ventas_hoy} ${Number(data.ventas_hoy) === 1 ? 'venta' : 'ventas'} · $${String(data.facturado_hoy).split(',')[0]}`;
        // Lo que MeLi va a acreditar: mañana si hay algo, y si no el próximo depósito (las acreditaciones caen en pocos días sueltos)
        const sinCentavos = (s) => String(s).split(',')[0];
        if (data.hay_liberaciones && data.liberacion_manana && sinCentavos(data.liberacion_manana) !== '0') elLiberacion.textContent = `Mañana te acreditan: $${sinCentavos(data.liberacion_manana)}`;
        else if (data.proxima_liberacion) {
            // "04/10" → "4 oct", igual que el resto de las fechas de la app
            const f = String(data.proxima_liberacion.fecha || '').match(/^(\d{1,2})\/(\d{1,2})/);
            const fecha = f ? `${Number(f[1])} ${RangoFechas.MESES_CORTOS[Number(f[2]) - 1] || ''}`.trim() : data.proxima_liberacion.fecha;
            elLiberacion.textContent = `Próximo depósito: $${sinCentavos(data.proxima_liberacion.monto)} · ${fecha}`;
        }
        else elLiberacion.textContent = `Disponible mañana: $${data.liberacion_manana}`;
        elLiberacion.title = data.hay_liberaciones ? `En total te falta acreditar $${sinCentavos(data.a_liberar_total)}` : '';


        const pillInc = document.getElementById('ticker-incidencias-pill');
        const txtInc = document.getElementById('ticker-incidencias-texto');
        if (pillInc && txtInc) {
            if (data.incidencias_activas > 0) {
                pillInc.style.display = 'inline-flex';
                txtInc.textContent = `${data.incidencias_activas} reclamo${data.incidencias_activas === 1 ? '' : 's'} activo${data.incidencias_activas === 1 ? '' : 's'}`;
            } else {
                pillInc.style.display = 'none';
            }
        }

        const dotSalud = document.getElementById('ticker-salud-dot');
        const txtSalud = document.getElementById('ticker-salud-texto');
        if (dotSalud && txtSalud && data.salud_score !== undefined) {
            txtSalud.textContent = `Salud: ${data.salud_score} (${data.salud_etiqueta})`;
            let color = 'var(--success)';
            if (data.salud_score < 45) color = 'var(--danger)';
            else if (data.salud_score < 65) color = getComputedStyle(document.documentElement).getPropertyValue('--semantic-warning').trim() || '#f0a13b';
            dotSalud.style.background = color;
            dotSalud.style.boxShadow = `0 0 6px ${color}`;
        }

        const pillRacha = document.getElementById('ticker-racha-pill');
        const txtRacha = document.getElementById('ticker-racha-texto');
        if (pillRacha && txtRacha) {
            if (data.racha_dias >= 2) {
                pillRacha.style.display = 'inline-flex';
                txtRacha.textContent = `${data.racha_dias} días seguidos`;
            } else {
                pillRacha.style.display = 'none';
            }
        }

        // Badge en el nav: incidencias operativas del ticker
        _actualizarBadgeNav((data.incidencias_activas || 0) + (data.salud_score !== undefined && data.salud_score < 65 ? 1 : 0));

        window._ultimoTickerData = data;
    } catch (e) {
        console.error('Error actualizando ticker:', e);
        // Sin esto, un error acá (server 502, JSON inválido, etc.) dejaba
        // el pill de arriba con el efecto skeleton (brillo animado) para
        // siempre — parecía "cargando" sin fin en vez de mostrar que no
        // se pudo traer el dato.
        const elVentas = document.getElementById('ticker-ventas');
        const elLiberacion = document.getElementById('ticker-liberacion');
        if (elVentas) { elVentas.classList.remove('skeleton'); elVentas.textContent = 'No se pudo cargar'; }
        if (elLiberacion) { elLiberacion.classList.remove('skeleton'); elLiberacion.textContent = 'No se pudo cargar'; }
    }
}

// ---------- Tooltips ricos de la barra superior ----------
let _tooltipTickerEl = null;

function _crearTooltipTicker() {
    if (_tooltipTickerEl) return _tooltipTickerEl;
    const el = document.createElement('div');
    el.className = 'tooltip-ticker';
    document.body.appendChild(el);
    _tooltipTickerEl = el;
    return el;
}

function _posicionarTooltipTicker(el, ancla) {
    const rect = ancla.getBoundingClientRect();
    el.style.left = Math.max(10, rect.left) + 'px';
    el.style.top = (rect.bottom + 10) + 'px';
}

function mostrarTooltipSalud(ancla) {
    const data = window._ultimoTickerData;
    const el = _crearTooltipTicker();
    if (!data || data.salud_score === undefined) {
        el.innerHTML = '<div class="tooltip-ticker-cuerpo">Cargando...</div>';
        el.style.removeProperty('--tooltip-acento');
    } else {
        const detalle = data.salud_detalle || [];
        const estilo = getComputedStyle(document.documentElement);
        const color = data.salud_score >= 80 ? estilo.getPropertyValue('--success').trim()
            : data.salud_score >= 65 ? estilo.getPropertyValue('--semantic-warning').trim()
            : estilo.getPropertyValue('--danger').trim();
        el.style.setProperty('--tooltip-acento', color);
        el.innerHTML = `
            <div class="tooltip-ticker-acento"></div>
            <div class="tooltip-ticker-cuerpo">
                <div class="tooltip-ticker-titulo">Score de salud: ${data.salud_score}/100 (${data.salud_etiqueta})</div>
                ${detalle.length ? `
                    <div class="tooltip-ticker-sub">En qué se basó:</div>
                    <ul class="tooltip-ticker-lista">${detalle.map(d => `<li>${d}</li>`).join('')}</ul>
                    <div class="tooltip-ticker-sub">Resolviendo estos puntos, el score sube solo.</div>
                ` : `<div class="tooltip-ticker-sub">Sin descuentos activos — todo en orden.</div>`}
            </div>
        `;
    }
    _posicionarTooltipTicker(el, ancla);
    el.classList.add('visible');
}

function mostrarTooltipVentas(ancla) {
    const data = window._ultimoTickerData;
    const el = _crearTooltipTicker();
    el.style.removeProperty('--tooltip-acento');
    if (!data) { el.innerHTML = '<div class="tooltip-ticker-cuerpo">Cargando...</div>'; }
    else {
        const lista = data.ventas_hoy_detalle || [];
        el.innerHTML = `
            <div class="tooltip-ticker-cuerpo">
                <div class="tooltip-ticker-titulo">Ventas de hoy — $${data.facturado_hoy}</div>
                ${lista.length ? `
                    <ul class="tooltip-ticker-lista">
                        ${lista.map(v => `<li>${v.hora} — ${v.cantidad}× ${v.titulo.slice(0, 38)}${v.titulo.length > 38 ? '…' : ''} <strong>$${v.precio_formateado}</strong></li>`).join('')}
                    </ul>
                ` : `<div class="tooltip-ticker-sub">Todavía no hay ventas registradas hoy.</div>`}
            </div>
        `;
    }
    _posicionarTooltipTicker(el, ancla);
    el.classList.add('visible');
}

function ocultarTooltipTicker() {
    if (_tooltipTickerEl) _tooltipTickerEl.classList.remove('visible');
}

async function marcarCurvaRota() {
    try {
        const resp = await fetch('/api/curva_talles');
        const lista = await resp.json();
        if (!lista.length) return;
        const modelos = new Set(lista.map(r => r.modelo));
        document.querySelectorAll('[data-modelo-titulo]').forEach(el => {
            if (modelos.has(el.dataset.modeloTitulo) && !el.querySelector('.badge-curva-rota')) {
                const badge = document.createElement('span');
                badge.className = 'badge badge-curva-rota';
                badge.textContent = 'Curva Rota';
                (el.querySelector('strong') || el).after(badge);
            }
        });
    } catch (e) { console.error(e); }
}

// ---------- Comando Universal (Ctrl+K) ----------
// "De verdad" quiere decir dos cosas que antes faltaban: cubrir TODAS las
// secciones (antes eran 8 de ~19) y navegar con flechas + Enter, no solo
// con el mouse. También suma comandos de ACCIÓN (no solo ir-a-una-página):
// esos llevan `accion` (nombre de función global) en vez de `url`.
const ATAJOS_COMANDO = [
    { alias: ['stk', 'stock'], texto: 'Ir a Stock', url: '/stock' },
    { alias: ['inicio', 'home'], texto: 'Ir a Inicio', url: '/' },
    { alias: ['masivo', 'stockm'], texto: 'Ir a Stock Masivo', url: '/stock_masivo' },
    { alias: ['desp', 'despacho'], texto: 'Ir a Despacho', url: '/despacho' },
    { alias: ['dash', 'dashboard', 'resumen'], texto: 'Ir a Dashboard', url: '/dashboard' },
    { alias: ['gan', 'ganancia', 'metricas'], texto: 'Ir a Ganancia Real', url: '/metricas' },
    { alias: ['fac', 'facturacion'], texto: 'Ir a Facturación', url: '/facturacion' },
    { alias: ['cobros', 'cobrar', 'acreditacion', 'liquidez', 'retenido'], texto: 'Ir a Cobros (cuándo te acreditan)', url: '/cobros' },
    { alias: ['cos', 'costos'], texto: 'Ir a Costos', url: '/costos' },
    { alias: ['full', 'logistica', 'comparador'], texto: 'Ir a Propia vs FULL', url: '/comparador_logistica' },
    { alias: ['hist', 'historial'], texto: 'Ir a Historial de Precios', url: '/historial_precios' },
    { alias: ['precios', 'minimo', 'pmin'], texto: 'Ir a Precios (mínimo por publicación)', url: '/precios' },
    { alias: ['calc', 'calculadora', 'comision'], texto: 'Ir a Calculadora', url: '/calculadora' },
    { alias: ['cal', 'calidad'], texto: 'Ir a Calidad de publicaciones', url: '/calidad' },
    { alias: ['op', 'opiniones', 'resenas', 'reviews', 'estrellas'], texto: 'Ir a Opiniones de compradores', url: '/opiniones' },
    { alias: ['mono', 'monotributo'], texto: 'Ir a Monotributo', url: '/monotributo' },
    { alias: ['manual', 'mostrador', 'directo'], texto: 'Ir a Ventas fuera de MeLi', url: '/ventas_manuales' },
    { alias: ['prom', 'promo', 'promociones'], texto: 'Ir a Promociones', url: '/promociones' },
    { alias: ['tend', 'tendencias'], texto: 'Ir a Tendencias', url: '/tendencias' },
    { alias: ['comp', 'competencia', 'espia'], texto: 'Ir a Competencia', url: '/competencia', requiere: 'catalogo' },
    { alias: ['embudo', 'conversion'], texto: 'Ir a Embudo de Conversión', url: '/embudo_conversion' },
    { alias: ['rep', 'reputacion'], texto: 'Ir a Reputación', url: '/reputacion' },
    { alias: ['ads', 'publicidad'], texto: 'Ir a Publicidad', url: '/publicidad', requiere: 'ads' },
    { alias: ['log', 'logros', 'misiones'], texto: 'Ir a Logros', url: '/logros' },
];
const ACCIONES_COMANDO = [
    { alias: ['sinc', 'sincronizar', 'actualizar'], texto: 'Sincronizar Todo', accion: 'ejecutarSincronizarTodo' },
    { alias: ['tema', 'oscuro', 'claro', 'dark', 'light'], texto: 'Cambiar tema claro/oscuro', accion: 'alternarTema' },
    { alias: ['privacidad', 'ocultar', 'blur'], texto: 'Modo privacidad (ocultar montos)', accion: 'alternarModoPrivacidad' },
];
function abrirComando() {
    document.getElementById('command-overlay').classList.add('open');
    const input = document.getElementById('command-input');
    input.value = ''; input.focus();
    _comandoIndiceActivo = -1;
    renderizarResultadosComando([]);
}
function cerrarComando() { document.getElementById('command-overlay').classList.remove('open'); }
let _comandoItemsActuales = [];
let _comandoIndiceActivo = -1;
function renderizarResultadosComando(items) {
    _comandoItemsActuales = items;
    _comandoIndiceActivo = items.length ? 0 : -1;
    const cont = document.getElementById('command-results');
    if (items.length === 0) { cont.innerHTML = '<div class="command-empty">Escribí para buscar publicaciones, secciones o acciones ("sincronizar", "tema"...)</div>'; return; }
    cont.innerHTML = items.map((item, i) => {
        const claseActiva = i === _comandoIndiceActivo ? ' activo' : '';
        const etiqueta = `<span>${item.texto}</span>${item.tag ? `<span class="badge badge-neutral">${item.tag}</span>` : ''}`;
        // Un resultado de producto (idMeli) abre el drawer de gestión — no
        // navega a una página aparte, mismo comportamiento que el botón
        // "Gestionar" del listado de Stock.
        return (item.accion || item.idMeli)
            ? `<a href="#" class="command-item${claseActiva}" data-idx="${i}" onclick="event.preventDefault(); ejecutarItemComando(${i});">${etiqueta}</a>`
            : `<a href="${item.url}" class="command-item${claseActiva}" data-idx="${i}">${etiqueta}</a>`;
    }).join('');
}
function ejecutarItemComando(i) {
    const item = _comandoItemsActuales[i];
    if (!item) return;
    if (item.accion) {
        cerrarComando();
        const fn = window[item.accion];
        if (typeof fn === 'function') fn();
    } else if (item.idMeli) {
        cerrarComando();
        abrirDrawer(item.idMeli);
    } else if (item.url) {
        window.location.href = item.url;
    }
}
function _moverSeleccionComando(delta) {
    if (!_comandoItemsActuales.length) return;
    _comandoIndiceActivo = (_comandoIndiceActivo + delta + _comandoItemsActuales.length) % _comandoItemsActuales.length;
    document.querySelectorAll('#command-results .command-item').forEach((el, i) => el.classList.toggle('activo', i === _comandoIndiceActivo));
    const activo = document.querySelector('#command-results .command-item.activo');
    if (activo) activo.scrollIntoView({ block: 'nearest' });
}
let comandoDebounce = null;
function inicializarComando() {
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); abrirComando(); return; }
        if (e.key === 'Escape') { cerrarComando(); cerrarDrawer(); }
        if (!document.getElementById('command-overlay').classList.contains('open')) return;
        if (e.key === 'ArrowDown') { e.preventDefault(); _moverSeleccionComando(1); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); _moverSeleccionComando(-1); }
        else if (e.key === 'Enter' && document.activeElement && document.activeElement.id === 'command-input') {
            e.preventDefault();
            if (_comandoIndiceActivo >= 0) ejecutarItemComando(_comandoIndiceActivo);
        }
    });
    document.addEventListener('input', (e) => {
        if (e.target.id !== 'command-input') return;
        const q = e.target.value.trim().toLowerCase();
        clearTimeout(comandoDebounce);
        if (!q) { renderizarResultadosComando([]); return; }
        const secciones = ATAJOS_COMANDO.filter(a => !a.requiere || (window.CAPACIDADES || {})[a.requiere] !== false).filter(a => a.alias.some(al => al.includes(q) || q.includes(al))).map(a => ({ texto: a.texto, url: a.url, tag: 'Sección' }));
        const acciones = ACCIONES_COMANDO.filter(a => a.alias.some(al => al.includes(q) || q.includes(al))).map(a => ({ texto: a.texto, accion: a.accion, tag: 'Acción' }));
        renderizarResultadosComando([...acciones, ...secciones]);
        comandoDebounce = setTimeout(async () => {
            try {
                const resp = await fetch('/api/buscar?q=' + encodeURIComponent(q));
                const productos = await resp.json();
                const itemsProductos = productos.map(p => ({ texto: p.titulo, idMeli: p.id, tag: p.id }));
                renderizarResultadosComando([...acciones, ...secciones, ...itemsProductos]);
            } catch (err) { console.error(err); }
        }, 200);
    });
}

// ---------- Drawer 360° ----------
let drawerIdActual = null;
let drawerTabsCargadas = new Set();
let _tituloSugeridoPendiente = null;

function abrirDrawerConSugerencia(idMeli, tituloSugerido) {
    _tituloSugeridoPendiente = tituloSugerido;
    abrirDrawer(idMeli);
}

async function cargarOportunidadesSeo() {
    try {
        const resp = await fetch('/api/oportunidades_seo');
        const oportunidades = await resp.json();
        const panel = document.getElementById('panel-oportunidades-seo');
        if (!panel) return;
        if (!oportunidades.length || !panelHabilitado('oportunidades')) { panel.style.display = 'none'; return; }
        const cont = document.getElementById('lista-oportunidades-seo');
        mostrarPanelConAnimacion(panel);
        cont.innerHTML = oportunidades.map(o => `
            <button type="button" class="badge badge-success" style="cursor:pointer; font-size:0.88em; padding:8px 14px; border:none;"
                onclick="abrirDrawerConSugerencia('${o.id_meli_sugerido}', '${o.titulo_sugerido.replace(/'/g, "\\'")}')">
                Sumar "${o.termino}" a ${o.titulo_actual.length > 30 ? o.titulo_actual.slice(0,30)+'…' : o.titulo_actual}
            </button>
        `).join('');
    } catch (e) { console.error(e); }
}

function inicializarDropdownsNav() {
    document.querySelectorAll('.nav-dropdown-toggle').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            const dropdown = btn.closest('.nav-dropdown');
            document.querySelectorAll('.nav-dropdown.open').forEach(d => { if (d !== dropdown) d.classList.remove('open'); });
            dropdown.classList.toggle('open');
        });
    });
    document.addEventListener('click', () => document.querySelectorAll('.nav-dropdown.open').forEach(d => d.classList.remove('open')));
}

function abrirDrawer(idMeli) {
    drawerIdActual = idMeli;
    drawerTabsCargadas = new Set();
    document.getElementById('drawer-overlay').classList.add('open');
    document.querySelectorAll('.drawer-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'info'));
    document.querySelectorAll('.drawer-tab-content').forEach(c => c.style.display = 'none');
    document.getElementById('tab-info').style.display = 'block';
    cargarTabInfo(idMeli);
}
function cerrarDrawer() { document.getElementById('drawer-overlay').classList.remove('open'); drawerIdActual = null; }
function cambiarTabDrawer(tab) {
    document.querySelectorAll('.drawer-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    document.querySelectorAll('.drawer-tab-content').forEach(c => c.style.display = 'none');
    document.getElementById('tab-' + tab).style.display = 'block';
    if (drawerTabsCargadas.has(tab)) return;
    drawerTabsCargadas.add(tab);
    if (tab === 'ficha') cargarTabFicha(drawerIdActual);
    if (tab === 'resenas') cargarTabResenas(drawerIdActual);
    if (tab === 'preguntas') cargarTabPreguntas(drawerIdActual);
    if (tab === 'salud') cargarTabSalud(drawerIdActual);
}

async function cargarTabInfo(idMeli) {
    const cont = document.getElementById('tab-info');
    cont.innerHTML = '<div class="drawer-loading">Cargando...</div>';
    try {
        const resp = await fetch(`/api/drawer/info/${idMeli}`);
        const d = await resp.json();
        if (d.error) { cont.innerHTML = `<div class="text-danger">${d.error}</div>`; return; }
        document.getElementById('drawer-titulo-header').textContent = d.titulo;
        window._drawerOriginal = { titulo: d.titulo, precio: Number(d.precio) || 0, estado: d.estado, costo: Number(d.precio_costo) || 0, estadoNombre: d.estado_nombre };
        // Solo se puede activar o pausar. Una publicación finalizada o en revisión muestra su estado, bloqueado: "finalizar" no tiene vuelta atrás en Mercado Libre.
        const opcionesEstado = d.estado_editable
            ? `<option value="active" ${d.estado === 'active' ? 'selected' : ''}>Activa</option><option value="paused" ${d.estado === 'paused' ? 'selected' : ''}>Pausada</option>`
            : `<option value="${UX.esc(d.estado)}" selected>${UX.esc(d.estado_nombre)}</option>`;
        cont.innerHTML = `
            <div class="field-group" style="margin-bottom:14px;">
                <label class="field-label">Título <span class="text-muted" id="drawer-titulo-largo" style="font-weight:400;"></span></label>
                <input type="text" id="drawer-titulo" maxlength="${Number(d.titulo_max) || 60}" value="${UX.esc(d.titulo)}" oninput="actualizarLargoTituloDrawer()">
                <button type="button" class="btn btn-secondary" style="margin-top:6px;" onclick="optimizarTitulo()"><svg class="icon" style="margin-right:5px;vertical-align:middle;"><use href="#icon-bolt"/></svg>Optimizar Título con IA</button>
            </div>
            <div class="filter-row" style="margin-bottom:14px;">
                <div class="field-group" style="flex:1;"><label class="field-label">Precio ($)</label><input type="number" step="0.01" min="0" id="drawer-precio" value="${Number(d.precio) || ''}"></div>
                <div class="field-group" style="flex:1;"><label class="field-label">Estado</label>
                    <select id="drawer-estado" ${d.estado_editable ? '' : 'disabled'}>${opcionesEstado}</select>
                </div>
            </div>
            <div class="field-group" style="margin-bottom:14px;"><label class="field-label">Costo de fabricación ($) <span class="text-muted" style="font-weight:400;">solo en CoreLux</span></label><input type="number" step="0.01" min="0" id="drawer-costo" value="${Number(d.precio_costo) || 0}"></div>
            <button type="button" class="btn btn-primary btn-block" onclick="guardarDrawerInfo()">Guardar cambios</button>
            <a href="/publicacion/${idMeli}/timeline" class="btn btn-secondary btn-block" style="margin-top:8px; text-align:center; text-decoration:none;"><svg class="icon" style="margin-right:5px;vertical-align:middle;"><use href="#icon-info"/></svg>Ver línea de tiempo completa</a>
        `;
        actualizarLargoTituloDrawer();
        if (_tituloSugeridoPendiente) {
            document.getElementById('drawer-titulo').value = _tituloSugeridoPendiente;
            mostrarToast('Título sugerido cargado — revisalo y guardá si te convence.', 'info'); actualizarLargoTituloDrawer();
            _tituloSugeridoPendiente = null;
        }
    } catch(e) { cont.innerHTML = '<div class="text-danger">Error al cargar.</div>'; }
}

function actualizarLargoTituloDrawer() {
    const el = document.getElementById('drawer-titulo'), nota = document.getElementById('drawer-titulo-largo');
    if (el && nota) nota.textContent = `· ${el.value.length} caracteres`;
}

async function guardarDrawerInfo() {
    const orig = window._drawerOriginal || {};
    const titulo = document.getElementById('drawer-titulo').value.replace(/\s+/g, ' ').trim();
    const precio = document.getElementById('drawer-precio').value;
    const estado = document.getElementById('drawer-estado').value;
    const costo = document.getElementById('drawer-costo').value;
    // Lo que se va a cambiar en Mercado Libre se muestra antes, con el valor de antes y el de después (el costo es solo de CoreLux y no lo necesita)
    const lineas = [];
    if (titulo !== orig.titulo) lineas.push(`Título: «${orig.titulo}» → «${titulo}»`);
    if (precio !== '' && Math.abs(Number(precio) - orig.precio) > 0.004) lineas.push(`Precio: ${UX.plata(orig.precio)} → ${UX.plata(Number(precio))}`);
    if (estado !== orig.estado) lineas.push(`Estado: ${orig.estadoNombre} → ${estado === 'paused' ? 'Pausada' : 'Activa'}`);
    if (lineas.length && !(await confirmarDecision('¿Cambiar esto en Mercado Libre?', 'Cambiar en Mercado Libre', lineas.join('\n')))) return;
    const body = { titulo, precio, estado, precio_costo: costo };
    try {
        const resp = await fetch(`/api/drawer/guardar/${drawerIdActual}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
        const data = await resp.json();
        if (!data.ok) { mostrarToast(data.detalle || 'No se pudieron guardar los cambios', 'error'); return; }
        window._drawerOriginal = { titulo: data.titulo, precio: Number(precio) || orig.precio, estado, costo: Number(costo) || 0, estadoNombre: estado === 'paused' ? 'Pausada' : 'Activa' };
        document.getElementById('drawer-titulo-header').textContent = data.titulo;
        mostrarToast(data.cambios && data.cambios.length ? 'Listo: Mercado Libre aceptó el cambio.' : 'Costo guardado.', 'success');
    } catch(e) { mostrarToast('No se pudo conectar. Probá de nuevo.', 'error'); }
}

// ---------- Efecto máquina de escribir (rápido) para texto generado por IA ----------
function escribirTextoEnInput(input, texto, velocidadMs = 14) {
    input.value = '';
    let i = 0;
    return new Promise(resolve => {
        (function paso() {
            input.value += texto[i];
            i++;
            if (i < texto.length) setTimeout(paso, velocidadMs);
            else resolve();
        })();
    });
}

async function optimizarTitulo() {
    const tituloActual = document.getElementById('drawer-titulo').value;
    mostrarToast('Optimizando título con IA...', 'info');
    try {
        const resp = await fetch(`/api/drawer/optimizar_titulo/${drawerIdActual}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({titulo: tituloActual}) });
        const data = await resp.json();
        if (data.ok) { await escribirTextoEnInput(document.getElementById('drawer-titulo'), data.titulo); mostrarToast('Título optimizado — revisalo antes de guardar', 'success'); }
        else mostrarToast(data.error || 'No se pudo optimizar', 'error');
    } catch(e) { mostrarToast('Error consultando la IA', 'error'); }
}

async function cargarTabFicha(idMeli) {
    const cont = document.getElementById('tab-ficha');
    cont.innerHTML = '<div class="drawer-loading">Cargando...</div>';
    try {
        const resp = await fetch(`/api/drawer/info/${idMeli}`);
        const d = await resp.json();
        // Atributos editables: solo los que tienen valor no vacío o son relevantes
        const atributosHtml = (d.atributos || []).map((a, i) => `
            <div style="display:flex; align-items:center; gap:10px; padding:8px 0; border-bottom:1px solid var(--glass-border);">
                <span style="color:var(--text-secondary); font-size:0.82em; width:42%; flex-shrink:0;">${a.nombre}</span>
                <input type="text" data-attr-id="${a.id || ''}" value="${(a.valor || '').replace(/"/g,'&quot;')}"
                    style="flex:1; background:rgba(255,255,255,0.04); border:1px solid transparent; border-radius:4px; color:var(--text-primary); padding:4px 8px; font-size:0.85em; transition:border-color 0.15s;"
                    onfocus="this.style.borderColor='var(--accent-brand)'" onblur="this.style.borderColor='transparent'"
                    placeholder="(vacío)">
            </div>`).join('');
        cont.innerHTML = `
            <div class="field-group" style="margin-bottom:16px;">
                <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:6px;">
                    <label class="field-label" style="margin:0;">Descripción</label>
                    <span class="text-muted" style="font-size:0.75em;" id="desc-chars"></span>
                </div>
                <textarea id="drawer-descripcion" rows="7"
                    style="width:100%; background:rgba(255,255,255,0.04); border:1px solid var(--glass-border); border-radius:var(--radius-sm); color:var(--text-primary); padding:10px; font-family:var(--font-ui); font-size:0.88em; line-height:1.5; resize:vertical;"
                    oninput="document.getElementById('desc-chars').textContent = this.value.length + ' caracteres'">${d.descripcion || ''}</textarea>
                <button type="button" class="btn btn-primary" style="margin-top:8px;" onclick="guardarDescripcion()">
                    <svg class="icon" style="margin-right:5px;"><use href="#icon-check"/></svg>Guardar descripción
                </button>
            </div>
            ${atributosHtml ? `
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:8px;">
                <div class="field-label" style="margin:0;">Atributos técnicos</div>
                <button type="button" class="btn btn-secondary" style="padding:4px 10px; font-size:0.8em;" onclick="guardarAtributosFicha()">
                    <svg class="icon" style="width:12px;height:12px;margin-right:4px;"><use href="#icon-check"/></svg>Guardar atributos
                </button>
            </div>
            <div id="ficha-atributos-cont">${atributosHtml}</div>
            <div class="text-muted" style="font-size:0.75em; margin-top:10px; line-height:1.4;">
                Los atributos son visibles en MeLi. Algunos tienen valores fijos que MeLi no permite cambiar libremente (pueden quedar ignorados al guardar).
            </div>` : '<div class="alert-empty">Sin atributos técnicos cargados.</div>'}
        `;
        // inicializar contador de chars
        const ta = document.getElementById('drawer-descripcion');
        if (ta) document.getElementById('desc-chars').textContent = ta.value.length + ' caracteres';
    } catch(e) { cont.innerHTML = '<div class="text-danger">Error al cargar.</div>'; }
}

async function guardarAtributosFicha() {
    const inputs = document.querySelectorAll('#ficha-atributos-cont input[data-attr-id]');
    const atributos = Array.from(inputs).map(inp => ({ id: inp.dataset.attrId, value_name: inp.value })).filter(a => a.id);
    if (!atributos.length) { mostrarToast('Sin atributos para guardar', 'error'); return; }
    try {
        const resp = await fetch(`/api/drawer/guardar_atributos/${drawerIdActual}`, {
            method: 'POST', headers: {'Content-Type':'application/json'},
            body: JSON.stringify({ atributos })
        });
        const data = await resp.json();
        mostrarToast(data.ok ? 'Atributos actualizados en MeLi' : (data.detalle || 'No se pudieron guardar los atributos'), data.ok ? 'success' : 'error');
    } catch(e) { mostrarToast('Error guardando atributos', 'error'); }
}

async function guardarDescripcion() {
    const texto = document.getElementById('drawer-descripcion').value;
    try {
        const resp = await fetch(`/api/drawer/guardar_descripcion/${drawerIdActual}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({descripcion: texto}) });
        const data = await resp.json();
        mostrarToast(data.ok ? 'Descripción actualizada' : 'No se pudo guardar la descripción', data.ok ? 'success' : 'error');
    } catch(e) { mostrarToast('Error guardando la descripción', 'error'); }
}

async function cargarTabResenas(idMeli) {
    const cont = document.getElementById('tab-resenas');
    cont.innerHTML = '<div class="drawer-loading">Cargando...</div>';
    try {
        const resp = await fetch(`/api/drawer/resenas/${idMeli}`);
        const d = await resp.json();
        if (!d.rating_average) { cont.innerHTML = '<div class="alert-empty">Todavía no tiene opiniones.</div>'; return; }
        const reviewsHtml = d.reviews.map(r => `
            <div class="mobile-card"><div class="mobile-card-top"><strong>${'⭐'.repeat(r.rate || 0)}</strong><span class="text-muted" style="font-size:0.78em;">${r.fecha}</span></div>
            <div>${r.titulo ? '<strong>' + r.titulo + '</strong><br>' : ''}${r.contenido || ''}</div></div>
        `).join('');
        cont.innerHTML = `
            <div class="stat-strip" style="margin-bottom:16px;"><div class="stat-chip accent-gold"><div class="stat-chip-label">Promedio</div><div class="stat-chip-value">${d.rating_average} ⭐</div></div></div>
            ${reviewsHtml || '<div class="alert-empty">Sin comentarios de texto todavía.</div>'}
        `;
    } catch(e) { cont.innerHTML = '<div class="text-danger">Error al cargar.</div>'; }
}

async function cargarTabPreguntas(idMeli) {
    const cont = document.getElementById('tab-preguntas');
    cont.innerHTML = '<div class="drawer-loading">Cargando...</div>';
    try {
        const resp = await fetch(`/api/drawer/preguntas/${idMeli}`);
        const preguntas = await resp.json();
        if (preguntas.length === 0) { cont.innerHTML = '<div class="alert-empty">Sin preguntas registradas.</div>'; return; }
        cont.innerHTML = preguntas.map(p => `
            <div class="mobile-card">
                <div class="mobile-card-top"><strong>${p.fecha}</strong>${p.estado === 'UNANSWERED' ? '<span class="badge badge-warning">Sin responder</span>' : '<span class="badge badge-success">Respondida</span>'}</div>
                <div style="margin-bottom:8px;">${p.texto}</div>
                ${p.respuesta ? `<div class="text-muted" style="font-size:0.85em;">Respuesta: ${p.respuesta}</div>` : `
                    <div class="flex-gap"><input type="text" id="respuesta-${p.id}" placeholder="Escribí una respuesta..." style="flex:1;"><button type="button" class="btn btn-secondary" onclick="responderPreguntaDrawer(${p.id})">Enviar</button></div>
                `}
            </div>
        `).join('');
    } catch(e) { cont.innerHTML = '<div class="text-danger">Error al cargar.</div>'; }
}

async function responderPreguntaDrawer(questionId) {
    const texto = document.getElementById('respuesta-' + questionId).value.trim();
    if (!texto) return;
    try {
        const resp = await fetch('/api/drawer/responder_pregunta', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({question_id: questionId, texto}) });
        const data = await resp.json();
        if (data.ok) { mostrarToast('Respuesta publicada en Mercado Libre', 'success'); cargarTabPreguntas(drawerIdActual); }
        else mostrarToast('No se pudo publicar la respuesta', 'error');
    } catch(e) { mostrarToast('Error publicando la respuesta', 'error'); }
}

async function cargarTabSalud(idMeli) {
    const cont = document.getElementById('tab-salud');
    cont.innerHTML = '<div class="drawer-loading">Cargando...</div>';
    try {
        const resp = await fetch(`/api/drawer/salud/${idMeli}`);
        const d = await resp.json();
        const color = d.porcentaje >= 70 ? 'var(--success)' : (d.porcentaje >= 40 ? 'var(--warning)' : 'var(--danger)');
        const recs = d.recomendaciones.map(r => `<li style="margin-bottom:6px;">${r}</li>`).join('');
        cont.innerHTML = `
            <div class="page-subtitle" style="margin-bottom:14px;">Puntaje estimado por CoreLux, no el oficial de MeLi.</div>
            <div style="height:14px; background:rgba(255,255,255,0.06); border-radius:99px; overflow:hidden; margin-bottom:16px;"><div style="height:100%; width:${d.porcentaje}%; background:${color};"></div></div>
            <div class="stat-chip-value" style="margin-bottom:16px;">${d.porcentaje}%</div>
            ${recs ? `<ul style="padding-left:18px;">${recs}</ul>` : '<div class="text-success">¡Sin recomendaciones pendientes!</div>'}
        `;
    } catch(e) { cont.innerHTML = '<div class="text-danger">Error al cargar.</div>'; }
}

// ---------- Chat IA: markdown seguro + typing indicator ----------
function toggleChat() { document.getElementById('chat-window').classList.toggle('open'); }
function escapeHtml(str) { const div = document.createElement('div'); div.textContent = str; return div.innerHTML; }

function formatearMarkdownSeguro(texto) {
    let seguro = escapeHtml(texto);
    seguro = seguro.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    const lineas = seguro.split('\n');
    let html = '';
    let dentroDeLista = false;
    for (const linea of lineas) {
        const esItem = /^\s*[-•]\s+(.*)$/.exec(linea);
        if (esItem) {
            if (!dentroDeLista) { html += '<ul style="margin:6px 0; padding-left:18px;">'; dentroDeLista = true; }
            html += `<li>${esItem[1]}</li>`;
        } else {
            if (dentroDeLista) { html += '</ul>'; dentroDeLista = false; }
            if (linea.trim() !== '') html += linea + '<br>';
        }
    }
    if (dentroDeLista) html += '</ul>';
    return html;
}

async function enviarMensajeIA() {
    const input = document.getElementById('chat-input');
    const texto = input.value.trim();
    if (!texto) return;
    const body = document.getElementById('chat-body');
    body.innerHTML += `<div class="chat-msg-user">${escapeHtml(texto)}</div>`;
    input.value = '';
    const typingId = 'typing-' + Date.now();
    body.innerHTML += `<div class="chat-msg-bot" id="${typingId}"><span class="typing-dots"><span></span><span></span><span></span></span></div>`;
    body.scrollTop = body.scrollHeight;

    try {
        const res = await fetch('/api/chat_ia', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({pregunta: texto}) });
        const data = await res.json();
        document.getElementById(typingId).innerHTML = formatearMarkdownSeguro(data.respuesta);
    } catch(e) {
        document.getElementById(typingId).innerHTML = '<span class="text-danger">Error de comunicación.</span>';
    }
    body.scrollTop = body.scrollHeight;
}

// ---------- Protector de inactividad ----------
// A los 10 minutos sin mouse/teclado/touch, tapa la pantalla con blur —
// NO cierra sesión (eso sería perder lo que se estaba haciendo), solo
// evita que quede información sensible a la vista si alguien se aleja de
// la pantalla en el local. Un click en cualquier lado lo saca.
const MINUTOS_INACTIVIDAD = 10;
let _timerInactividad = null;
function mostrarProtectorInactividad() {
    const overlay = document.getElementById('inactividad-overlay');
    if (overlay) overlay.classList.add('visible');
}
function ocultarProtectorInactividad() {
    const overlay = document.getElementById('inactividad-overlay');
    if (overlay) overlay.classList.remove('visible');
    reiniciarTimerInactividad();
}
function reiniciarTimerInactividad() {
    clearTimeout(_timerInactividad);
    _timerInactividad = setTimeout(mostrarProtectorInactividad, MINUTOS_INACTIVIDAD * 60 * 1000);
}
function inicializarProtectorInactividad() {
    ['mousemove', 'mousedown', 'keydown', 'touchstart', 'scroll'].forEach(evento => {
        document.addEventListener(evento, () => {
            // Si ya está tapado, el propio click de "volver" es el que lo
            // saca (ocultarProtectorInactividad) — un mousemove de fondo
            // no debería destaparlo solo.
            if (!document.getElementById('inactividad-overlay')?.classList.contains('visible')) {
                reiniciarTimerInactividad();
            }
        }, { passive: true });
    });
    reiniciarTimerInactividad();
}

// ---------- Paneles colapsables: accesibles por teclado ----------
// Los .panel-colapsable son <div onclick> (no <button>, porque contienen
// contenido rico y una zona interna que no debe togglear el panel) —
// sin esto, un usuario de teclado no podía abrirlos ni enterarse de que
// son interactivos. Un solo listener delegado cubre los 6 que hay en el
// proyecto (dashboard, index, métricas) en vez de repetir la lógica.
document.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && e.target.matches('.panel-colapsable[role="button"]')) {
        e.preventDefault();
        e.target.click();
    }
});
document.addEventListener('click', (e) => {
    const panel = e.target.closest('.panel-colapsable[role="button"]');
    if (panel) panel.setAttribute('aria-expanded', panel.classList.contains('abierto'));
});

// ---------- Arranque global ----------
document.addEventListener('DOMContentLoaded', () => {
    _inicializarIconoTema();
    animarContadoresEnPagina();
    envolverIdsCopiables(document.body);
    inicializarComando();
    actualizarTicker();
    // El HUD fijo solo pedía sus datos AL ABRIRSE — quedaba en "—" 5-6
    // segundos justo cuando el usuario ya quería verlo. Se precarga acá,
    // en segundo plano, apenas entra a cualquier pantalla, para que al
    // hacer click el panel ya tenga los números listos.
    cargarHud();
    revisarMensajeEnURL();
    marcarCurvaRota();
    cargarOportunidadesSeo();
    inicializarDropdownsNav();
    inicializarProtectorInactividad();
    // El ticker (varias consultas a la base) se actualiza cada 60 s y SOLO con la pestaña a la vista; al volver a mirarla se refresca enseguida.
    setInterval(() => { if (!document.hidden) actualizarTicker(); }, 60000);
    document.addEventListener('visibilitychange', () => { if (!document.hidden) actualizarTicker(); });
    cargarAlertasPendientes();
    setInterval(() => { if (!document.hidden) cargarAlertasPendientes(); }, 300000); // cada 5 minutos, con la pestaña a la vista
    if (document.body.dataset.mostrarTutorial) { setTimeout(iniciarTutorial, 500); }
});
