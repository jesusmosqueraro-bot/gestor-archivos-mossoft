// Captura de firma digital: dibujar a mano sobre un <canvas> o subir una imagen ya existente
// (foto de una hoja firmada, por ejemplo) — las dos opciones que pidió Tomás. Se usa tanto en el
// alta de usuario (Gestión de Usuarios y el alta rápida desde el modal de asignación de
// Inventario) como, más adelante, en cualquier otro punto que necesite capturar una firma.
//
// El resultado SIEMPRE se deja como un data URL (data:image/png;base64,... o
// data:image/jpeg;base64,... si se subió un archivo) en un <input type="hidden"> — así el
// formulario de siempre (method="POST", sin multipart) lo manda al servidor tal cual, donde
// _subir_firma_desde_dataurl (app.py) lo sube a Cloudinary igual que cualquier otra imagen.
//
// inicializarFirmaDigital(prefijo) espera en el HTML, con ese mismo prefijo:
//   #{prefijo}-canvas          <canvas> donde se dibuja
//   #{prefijo}-input           <input type="hidden"> con el data URL resultante
//   #{prefijo}-archivo         <input type="file" accept="image/*"> para la opción "Subir imagen"
//   #{prefijo}-tab-dibujar / #{prefijo}-tab-subir       botones para alternar de modo
//   #{prefijo}-panel-dibujar / #{prefijo}-panel-subir   contenedores de cada modo
//   #{prefijo}-borrar          botón "Borrar" (solo modo dibujar)
//   #{prefijo}-preview         <img> de vista previa (solo modo subir)
function inicializarFirmaDigital(prefijo) {
    const canvas = document.getElementById(prefijo + '-canvas');
    const input = document.getElementById(prefijo + '-input');
    if (!canvas || !input) return null;
    const ctx = canvas.getContext('2d');
    let dibujando = false;
    let trazoAlguno = false;

    function lienzoEnBlanco() {
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.strokeStyle = '#1e293b';
        ctx.lineWidth = 2.2;
        ctx.lineCap = 'round';
        ctx.lineJoin = 'round';
    }
    lienzoEnBlanco();

    function posicion(evento) {
        const rect = canvas.getBoundingClientRect();
        const punto = evento.touches && evento.touches.length ? evento.touches[0] : evento;
        return {
            x: (punto.clientX - rect.left) * (canvas.width / rect.width),
            y: (punto.clientY - rect.top) * (canvas.height / rect.height)
        };
    }
    function empezarTrazo(evento) {
        evento.preventDefault();
        dibujando = true;
        const p = posicion(evento);
        ctx.beginPath();
        ctx.moveTo(p.x, p.y);
    }
    function seguirTrazo(evento) {
        if (!dibujando) return;
        evento.preventDefault();
        const p = posicion(evento);
        ctx.lineTo(p.x, p.y);
        ctx.stroke();
        trazoAlguno = true;
    }
    function terminarTrazo() {
        if (!dibujando) return;
        dibujando = false;
        if (trazoAlguno) input.value = canvas.toDataURL('image/png');
    }
    canvas.addEventListener('mousedown', empezarTrazo);
    canvas.addEventListener('mousemove', seguirTrazo);
    window.addEventListener('mouseup', terminarTrazo);
    canvas.addEventListener('touchstart', empezarTrazo, { passive: false });
    canvas.addEventListener('touchmove', seguirTrazo, { passive: false });
    canvas.addEventListener('touchend', terminarTrazo);

    const btnBorrar = document.getElementById(prefijo + '-borrar');
    if (btnBorrar) {
        btnBorrar.addEventListener('click', function () {
            lienzoEnBlanco();
            trazoAlguno = false;
            input.value = '';
        });
    }

    const archivo = document.getElementById(prefijo + '-archivo');
    const preview = document.getElementById(prefijo + '-preview');
    if (archivo) {
        archivo.addEventListener('change', function () {
            const file = archivo.files[0];
            if (!file) return;
            const lector = new FileReader();
            lector.onload = function (e) {
                input.value = e.target.result;
                if (preview) {
                    preview.src = e.target.result;
                    preview.classList.remove('hidden');
                }
            };
            lector.readAsDataURL(file);
        });
    }

    const tabDibujar = document.getElementById(prefijo + '-tab-dibujar');
    const tabSubir = document.getElementById(prefijo + '-tab-subir');
    const panelDibujar = document.getElementById(prefijo + '-panel-dibujar');
    const panelSubir = document.getElementById(prefijo + '-panel-subir');
    function activarModo(modo) {
        const esDibujar = modo === 'dibujar';
        if (panelDibujar) panelDibujar.classList.toggle('hidden', !esDibujar);
        if (panelSubir) panelSubir.classList.toggle('hidden', esDibujar);
        if (tabDibujar) tabDibujar.classList.toggle('bg-orange-600', esDibujar);
        if (tabDibujar) tabDibujar.classList.toggle('text-white', esDibujar);
        if (tabSubir) tabSubir.classList.toggle('bg-orange-600', !esDibujar);
        if (tabSubir) tabSubir.classList.toggle('text-white', !esDibujar);
        // Al cambiar de modo se limpia lo que había en el otro, para no mandar una firma
        // "fantasma" de un modo que la persona decidió no usar al final.
        if (esDibujar) {
            if (archivo) archivo.value = '';
            if (preview) preview.classList.add('hidden');
            input.value = trazoAlguno ? canvas.toDataURL('image/png') : '';
        } else {
            lienzoEnBlanco();
            trazoAlguno = false;
            input.value = '';
        }
    }
    if (tabDibujar) tabDibujar.addEventListener('click', function () { activarModo('dibujar'); });
    if (tabSubir) tabSubir.addEventListener('click', function () { activarModo('subir'); });

    return {
        reiniciar: function () {
            lienzoEnBlanco();
            trazoAlguno = false;
            input.value = '';
            if (archivo) archivo.value = '';
            if (preview) preview.classList.add('hidden');
            if (tabDibujar) activarModo('dibujar');
        }
    };
}
