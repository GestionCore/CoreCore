/**
 * Fondo de partículas estilo Tron/vaporwave.
 * - Puntos flotando con profundidad (tamaño/velocidad varían = sensación de distancia)
 * - Gravedad sutil: las partículas cercanas al mouse se sienten atraídas
 * - Estrellas fugaces ocasionales, muy espaciadas
 * - Color según la sección de la app (Catálogo=violeta, Finanzas=dorado/cian, Crecimiento=cian)
 * Nada de esto interfiere con clicks (pointer-events: none) y se apaga
 * solo si el navegador pide "reducir movimiento" (accesibilidad).
 */
(function () {
    const prefiereMenosMovimiento = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const canvas = document.getElementById('fondo-particulas');
    if (!canvas || prefiereMenosMovimiento) return;

    const ctx = canvas.getContext('2d');
    let ancho, alto, particulas = [], fugaces = [];
    const CANTIDAD_BASE = 70;
    const DISTANCIA_LINEA = 130;
    const RADIO_GRAVEDAD = 150;
    const mouse = { x: -9999, y: -9999 };

    const PALETAS = {
        catalogo:    ['176, 107, 255', '46, 230, 255'],   // violeta dominante
        finanzas:    ['255, 217, 61', '176, 107, 255'],   // dorado dominante (plata)
        crecimiento: ['46, 230, 255', '176, 107, 255']    // cian dominante
    };
    const seccion = canvas.dataset.seccion || 'catalogo';
    const paleta = PALETAS[seccion] || PALETAS.catalogo;

    function redimensionar() {
        ancho = canvas.width = window.innerWidth;
        alto = canvas.height = window.innerHeight;
        const cantidad = Math.round(CANTIDAD_BASE * (ancho / 1400));
        particulas = Array.from({ length: cantidad }, crearParticula);
    }

    function crearParticula() {
        // Profundidad: partículas "lejanas" (chicas) se mueven más lento,
        // las "cercanas" (grandes) más rápido — sensación de perspectiva.
        const profundidad = Math.random(); // 0 = lejos, 1 = cerca
        const colorElegido = Math.random() < 0.65 ? paleta[0] : paleta[1];
        return {
            x: Math.random() * ancho,
            y: Math.random() * alto,
            vx: (Math.random() - 0.5) * (0.08 + profundidad * 0.22),
            vy: (Math.random() - 0.5) * (0.08 + profundidad * 0.22),
            radio: 0.5 + profundidad * 1.6,
            color: colorElegido
        };
    }

    function lanzarEstrellaFugaz() {
        const desdeArriba = Math.random() < 0.5;
        fugaces.push({
            x: Math.random() * ancho * 0.6,
            y: desdeArriba ? -20 : Math.random() * alto * 0.3,
            vx: 6 + Math.random() * 4,
            vy: 3 + Math.random() * 2,
            vida: 1
        });
        // La próxima aparece bastante después, para que sea un detalle
        // ocasional y no algo constante/molesto.
        setTimeout(lanzarEstrellaFugaz, 14000 + Math.random() * 18000);
    }

    function paso() {
        ctx.clearRect(0, 0, ancho, alto);

        if (mouse.x > -9000) {
            const halo = ctx.createRadialGradient(mouse.x, mouse.y, 0, mouse.x, mouse.y, 260);
            halo.addColorStop(0, `rgba(${paleta[0]}, 0.10)`);
            halo.addColorStop(1, `rgba(${paleta[0]}, 0)`);
            ctx.fillStyle = halo;
            ctx.fillRect(0, 0, ancho, alto);
        }

        for (let i = 0; i < particulas.length; i++) {
            const p = particulas[i];

            // Gravedad sutil hacia el mouse — nunca las "engancha", solo
            // curva levemente su trayectoria si están cerca.
            const dx = mouse.x - p.x, dy = mouse.y - p.y;
            const distMouse = Math.hypot(dx, dy);
            if (distMouse < RADIO_GRAVEDAD && distMouse > 1) {
                const fuerza = (1 - distMouse / RADIO_GRAVEDAD) * 0.010;
                p.vx += (dx / distMouse) * fuerza;
                p.vy += (dy / distMouse) * fuerza;
            }
            // Fricción leve para que no acumulen velocidad infinita
            p.vx *= 0.995; p.vy *= 0.995;

            p.x += p.vx; p.y += p.vy;
            if (p.x < 0 || p.x > ancho) p.vx *= -1;
            if (p.y < 0 || p.y > alto) p.vy *= -1;

            const brillo = distMouse < 200 ? 1 - distMouse / 200 : 0;

            ctx.beginPath();
            ctx.arc(p.x, p.y, p.radio + brillo * 1.5, 0, Math.PI * 2);
            ctx.fillStyle = `rgba(${p.color}, ${0.3 + brillo * 0.5})`;
            ctx.fill();

            for (let j = i + 1; j < particulas.length; j++) {
                const q = particulas[j];
                const d = Math.hypot(p.x - q.x, p.y - q.y);
                if (d < DISTANCIA_LINEA) {
                    ctx.beginPath();
                    ctx.moveTo(p.x, p.y);
                    ctx.lineTo(q.x, q.y);
                    ctx.strokeStyle = `rgba(${p.color}, ${0.1 * (1 - d / DISTANCIA_LINEA)})`;
                    ctx.lineWidth = 0.6;
                    ctx.stroke();
                }
            }
        }

        // Estrellas fugaces
        for (let i = fugaces.length - 1; i >= 0; i--) {
            const f = fugaces[i];
            f.x += f.vx; f.y += f.vy; f.vida -= 0.012;
            if (f.vida <= 0) { fugaces.splice(i, 1); continue; }
            const grad = ctx.createLinearGradient(f.x, f.y, f.x - f.vx * 8, f.y - f.vy * 8);
            grad.addColorStop(0, `rgba(255,255,255,${f.vida})`);
            grad.addColorStop(1, 'rgba(255,255,255,0)');
            ctx.strokeStyle = grad;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(f.x, f.y);
            ctx.lineTo(f.x - f.vx * 8, f.y - f.vy * 8);
            ctx.stroke();
        }

        requestAnimationFrame(paso);
    }

    window.addEventListener('resize', redimensionar);
    window.addEventListener('mousemove', (e) => { mouse.x = e.clientX; mouse.y = e.clientY; });
    window.addEventListener('mouseleave', () => { mouse.x = -9999; mouse.y = -9999; });

    redimensionar();
    requestAnimationFrame(paso);
    setTimeout(lanzarEstrellaFugaz, 8000 + Math.random() * 10000);
})();
