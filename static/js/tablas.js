/*
 * Tablas que se ordenan al tocar el encabezado de una columna.
 *
 * Uso: <table class="data-table" data-ordenable> y en cada <th> ordenable data-orden="num" (números) o data-orden="texto".
 *   - El valor de una celda es su atributo data-orden si lo tiene (la forma exacta: una fecha ISO, un número sin formato) y si no, su texto.
 *   - Un texto numérico se lee con el formato argentino: "$1.234.567" → 1234567, "12,5%" → 12.5, "-$1.234" → -1234. Sin número ("—", vacío) va siempre al final.
 *   - Una fila con class="ux-subfila" es el detalle de la fila de arriba y viaja con ella.
 *   - Si la lista está recortada con "ver más" (class="oculto-mostrar-mas"), se ordena TODA la tabla y después se vuelve a recortar: se ven las primeras del orden nuevo.
 * Primer toque: números de mayor a menor, textos de A a Z (data-primero="asc" o "desc" en el <th> lo cambia: fechas de la más nueva, "días que alcanza" de la más urgente).
 * Segundo: al revés. Tercero: vuelve al orden original.
 */
(function () {
    'use strict';

    // "$1.234.567" / "-$1.234" / "12,5%" → número; null si el texto no trae ninguno
    function valorNumerico(texto) {
        const limpio = String(texto == null ? '' : texto).replace(/[\s$]/g, '');
        const m = limpio.match(/-?\d[\d.]*(?:,\d+)?/);
        if (!m) return null;
        const n = Number(m[0].replace(/\./g, '').replace(',', '.'));
        return Number.isFinite(n) ? n : null;
    }

    // Compara dos valores del mismo tipo; los vacíos (null / '') van siempre al final, sin importar el sentido
    function comparar(a, b, tipo, sentido) {
        const vacio = (v) => v === null || v === undefined || v === '';
        if (vacio(a) && vacio(b)) return 0;
        if (vacio(a)) return 1;
        if (vacio(b)) return -1;
        const base = tipo === 'num' ? a - b : String(a).localeCompare(String(b), 'es', { sensitivity: 'base', numeric: true });
        return sentido === 'desc' ? -base : base;
    }

    // Primer toque: descendente en números, ascendente en textos (o el `preferido` de la columna); después alterna y al tercero vuelve al orden original (null)
    function siguienteSentido(actual, tipo, preferido) {
        const primero = preferido === 'asc' || preferido === 'desc' ? preferido : (tipo === 'num' ? 'desc' : 'asc');
        const segundo = primero === 'desc' ? 'asc' : 'desc';
        if (!actual) return primero;
        return actual === primero ? segundo : null;
    }

    // Ordena grupos [{valor, original}] (estable) y devuelve el arreglo nuevo; sentido null = orden original
    function ordenarGrupos(grupos, tipo, sentido) {
        const copia = grupos.slice();
        if (!sentido) return copia.sort((x, y) => x.original - y.original);
        return copia.sort((x, y) => comparar(x.valor, y.valor, tipo, sentido) || x.original - y.original);
    }

    function valorDeCelda(celda, tipo) {
        if (!celda) return null;
        const exacto = celda.dataset ? celda.dataset.orden : undefined;
        if (tipo === 'num') return exacto !== undefined ? (exacto === '' ? null : Number(exacto)) : valorNumerico(celda.textContent);
        return exacto !== undefined ? exacto : celda.textContent.trim().toLowerCase();
    }

    function ordenarTabla(tabla, indiceColumna, tipo, sentido) {
        const cuerpo = tabla.tBodies[0];
        if (!cuerpo) return;
        if (!tabla._ordenOriginal) {
            // el orden original se guarda una vez: cada fila lleva su posición
            Array.from(cuerpo.rows).forEach((fila, i) => { fila._posicionOriginal = i; });
            tabla._ordenOriginal = true;
        }
        // grupos: una fila principal y las de detalle que le siguen
        const grupos = [];
        Array.from(cuerpo.rows).forEach(fila => {
            if (fila.classList.contains('ux-subfila') && grupos.length) grupos[grupos.length - 1].filas.push(fila);
            else grupos.push({ filas: [fila], original: fila._posicionOriginal, valor: null });
        });
        const visibles = grupos.filter(g => !g.filas[0].classList.contains('oculto-mostrar-mas')).length;
        const recortada = visibles < grupos.length;
        grupos.forEach(g => { g.valor = valorDeCelda(g.filas[0].cells[indiceColumna], tipo); });

        const ordenados = ordenarGrupos(grupos, tipo, sentido);
        ordenados.forEach((g, posicion) => {
            g.filas.forEach(fila => {
                cuerpo.appendChild(fila);
                if (recortada) fila.classList.toggle('oculto-mostrar-mas', posicion >= visibles);
            });
        });
    }

    // Cómo se llama el orden de una columna en el selector del celular
    function etiquetaDeOrden(tipo, sentido) {
        if (tipo === 'num') return sentido === 'desc' ? 'de mayor a menor' : 'de menor a mayor';
        return sentido === 'asc' ? 'de la A a la Z' : 'de la Z a la A';
    }

    function iniciar(tabla) {
        if (!tabla || tabla._ordenable || !tabla.tHead) return;
        tabla._ordenable = true;
        const encabezados = Array.from(tabla.tHead.rows[0].cells);
        const columnas = [];      // las ordenables: { th, indice, tipo }

        // Ordena y deja marcado (aria-sort) cuál columna manda; sentido null = orden original
        function aplicar(columna, sentido) {
            encabezados.forEach(otro => { if (otro !== columna.th && otro.hasAttribute('aria-sort')) otro.setAttribute('aria-sort', 'none'); });
            columna.th.setAttribute('aria-sort', sentido === 'asc' ? 'ascending' : (sentido === 'desc' ? 'descending' : 'none'));
            ordenarTabla(tabla, columna.indice, columna.tipo, sentido);
            if (tabla._selector) tabla._selector.value = sentido ? `${columnas.indexOf(columna)}:${sentido}` : '';
        }

        encabezados.forEach((th, indice) => {
            const tipo = th.dataset.orden;
            if (tipo !== 'num' && tipo !== 'texto') return;
            const columna = { th, indice, tipo };
            columnas.push(columna);
            // un botón dentro del encabezado: se alcanza con el teclado y el lector de pantalla lo anuncia, sin romper la semántica de la tabla
            const boton = document.createElement('button');
            boton.type = 'button';
            boton.className = 'th-orden';
            boton.title = th.getAttribute('title') || 'Ordenar por esta columna';
            columna.nombre = th.textContent.trim();
            th.removeAttribute('title');
            while (th.firstChild) boton.appendChild(th.firstChild);
            th.appendChild(boton);
            th.setAttribute('aria-sort', 'none');
            boton.addEventListener('click', () => {
                const actual = { ascending: 'asc', descending: 'desc' }[th.getAttribute('aria-sort')] || null;
                aplicar(columna, siguienteSentido(actual, tipo, th.dataset.primero));
            });
        });

        // En el celular una tabla "de tarjetas" no muestra encabezados: se ofrece un selector (solo visible ahí, ver ux.css)
        if (tabla.classList.contains('ux-tabla-cards') && columnas.length) {
            const caja = document.createElement('div');
            caja.className = 'orden-movil';
            const etiqueta = document.createElement('label');
            const selector = document.createElement('select');
            selector.id = `orden-movil-${Math.random().toString(36).slice(2, 8)}`;
            etiqueta.htmlFor = selector.id;
            etiqueta.textContent = 'Ordenar por';
            const original = document.createElement('option');
            original.value = '';
            original.textContent = 'Orden original';
            selector.appendChild(original);
            columnas.forEach((columna, i) => {
                const sentido = siguienteSentido(null, columna.tipo, columna.th.dataset.primero);
                const opcion = document.createElement('option');
                opcion.value = `${i}:${sentido}`;
                opcion.textContent = `${columna.nombre} (${etiquetaDeOrden(columna.tipo, sentido)})`;
                selector.appendChild(opcion);
            });
            selector.addEventListener('change', () => {
                if (!selector.value) { aplicar(columnas[0], null); return; }
                const [i, sentido] = selector.value.split(':');
                aplicar(columnas[Number(i)], sentido);
            });
            caja.append(etiqueta, selector);
            tabla._selector = selector;
            tabla.parentNode.insertBefore(caja, tabla);
        }
    }

    function iniciarTodas() { document.querySelectorAll('table[data-ordenable]').forEach(iniciar); }

    const api = { valorNumerico, comparar, siguienteSentido, ordenarGrupos, etiquetaDeOrden, iniciar, iniciarTodas };
    if (typeof module !== 'undefined' && module.exports) module.exports = api;       // para probarlo con node
    if (typeof window !== 'undefined') {
        window.Tablas = api;
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciarTodas);
        else iniciarTodas();
    }
})();
