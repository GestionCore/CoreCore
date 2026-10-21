/*
 * Modo privacidad: tapa (desenfoca) TODO texto que tenga un monto en pesos, no solo los que alguien acordó marcar.
 *
 * Antes el CSS desenfocaba una lista fija de clases (los KPI, el hero, las celdas de tabla…) y en el Dashboard quedaban a la vista 48 de los 57 montos:
 * la píldora de la barra superior («Hoy: 1 venta · $53.349»), las tres tarjetas de «Facturado − Costos = Te queda», el texto del hero, el detalle de cada misión…
 * Ahora, con el modo prendido, se recorre el texto de la página y a cada elemento que contiene «$ 1.234» (o «US$ 12») se le pone la clase `monto-oculto`
 * (ux.css la desenfoca; al pasar el mouse se ve, como siempre). Un observador vuelve a marcar lo que la página arma después (ticker, listas, avisos).
 * Los gráficos (canvas) no son texto: sus ejes y su detalle no se tapan.
 */
(function () {
    'use strict';

    const MONTO = /(?:US)?\$\s?\d/;
    const EXCLUIDOS = 'script,style,textarea,input,select,option,canvas,noscript';
    const MS_ENTRE_REVISIONES = 150;

    function tieneMonto(texto) {
        return MONTO.test(String(texto == null ? '' : texto));
    }

    // Marca con `monto-oculto` cada elemento de `raiz` que tiene un texto con un monto. Devuelve cuántos marcó (los ya marcados no se cuentan).
    function marcar(raiz, documento) {
        const doc = documento || (typeof document !== 'undefined' ? document : null);
        if (!doc || !raiz) return 0;
        let marcados = 0;
        const recorrido = doc.createTreeWalker(raiz, 4 /* NodeFilter.SHOW_TEXT */);
        while (recorrido.nextNode()) {
            const texto = recorrido.currentNode;
            const elemento = texto.parentElement;
            if (!elemento || !tieneMonto(texto.nodeValue) || elemento.closest(EXCLUIDOS)) continue;
            if (!elemento.classList.contains('monto-oculto')) {
                elemento.classList.add('monto-oculto');
                marcados++;
            }
        }
        return marcados;
    }

    let observador = null;
    let revision = null;

    function activar() {
        if (typeof document === 'undefined') return;
        marcar(document.body);
        if (observador || typeof MutationObserver === 'undefined') return;
        observador = new MutationObserver(() => {
            clearTimeout(revision);
            revision = setTimeout(() => marcar(document.body), MS_ENTRE_REVISIONES);
        });
        observador.observe(document.body, { childList: true, subtree: true, characterData: true });
    }

    function desactivar() {
        clearTimeout(revision);
        if (observador) { observador.disconnect(); observador = null; }
    }

    // Alterna el modo (lo que hacía global.js a mano) y arranca o frena el observador según quede.
    function alternar() {
        const encendido = document.documentElement.classList.toggle('modo-privacidad');
        try { localStorage.setItem('modo_privacidad', encendido ? '1' : '0'); } catch (e) { /* sin almacenamiento: el modo vale hasta recargar */ }
        if (encendido) activar(); else desactivar();
        return encendido;
    }

    const api = { tieneMonto, marcar, activar, desactivar, alternar };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;       // para probarlo con node
    if (typeof window !== 'undefined') {
        window.Privacidad = api;
        const iniciar = () => { if (document.documentElement.classList.contains('modo-privacidad')) activar(); };
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
        else iniciar();
    }
})();
