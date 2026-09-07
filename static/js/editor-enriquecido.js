// Editor de texto enriquecido (Quill) reutilizado en Solicitudes TI (descripción del ticket,
// comentarios/respuestas) y en Comunicados (Novedades): negrilla, cursiva, subrayado,
// resaltado de color y listas — nivel "básico", nada más, a propósito.
//
// crearEditorEnriquecido crea el editor sobre #idContenedor y mantiene sincronizado su HTML
// con el <input type="hidden"> #idInputOculto en cada cambio, para que el formulario de
// siempre (method="POST", sin nada especial) siga funcionando tal cual.
function crearEditorEnriquecido(idContenedor, idInputOculto, placeholder) {
    // Si por lo que sea el editor no carga (p. ej. el CDN de Quill no respondió), no se debe
    // romper el resto de los scripts de la página (abrir/cerrar modales, etc.) — se deja el
    // <textarea> oculto visible como respaldo para que el usuario pueda seguir escribiendo.
    try {
        const quill = new Quill('#' + idContenedor, {
            theme: 'snow',
            placeholder: placeholder || '',
            modules: {
                toolbar: [
                    ['bold', 'italic', 'underline'],
                    [{ background: [] }],
                    [{ list: 'ordered' }, { list: 'bullet' }]
                ]
            }
        });

        // 🖼️ Pedido de Tomás (07/09/2026): "al adjuntar una imagen en el seguimiento del
        // ticket, sale error". La barra de herramientas no tiene botón de imagen a propósito
        // (este editor es "nivel básico, nada más" — ver el comentario de arriba), pero Quill
        // igual acepta una imagen PEGADA (Ctrl+V, p. ej. una captura de pantalla) y la mete en
        // el propio HTML del campo como una sola línea de texto codificada en base64 — eso puede
        // pesar varios MB. Como este campo llega al servidor como un campo de formulario normal
        // (no un archivo), Werkzeug lo rechaza con un 413 "Request Entity Too Large" en cuanto
        // supera ~500 KB (MAX_FORM_MEMORY_SIZE), muy por debajo de lo que pesa una captura. Se
        // bloquea la imagen pegada (se descarta, sin romper el resto de lo pegado) y se avisa
        // que hay que usar el campo de adjuntar archivo del formulario, que sube a Cloudinary
        // sin este límite — ver el input type="file" junto a este editor.
        try {
            const Delta = Quill.import('delta');
            quill.clipboard.addMatcher('IMG', function () {
                _avisarImagenNoPermitidaEnEditor(idContenedor);
                return new Delta();
            });
        } catch (err) {
            console.warn('No se pudo bloquear el pegado de imágenes en el editor:', err);
        }

        const sincronizar = function () {
            // Quill deja "<p><br></p>" cuando está vacío; se guarda tal cual — el propio
            // servidor (_html_esta_vacio, en app.py) decide si eso cuenta como "sin contenido".
            document.getElementById(idInputOculto).value = quill.root.innerHTML;
        };
        quill.on('text-change', sincronizar);
        sincronizar();
        return quill;
    } catch (err) {
        console.warn('No se pudo cargar el editor de texto enriquecido, se usa el campo de texto simple como respaldo:', err);
        const input = document.getElementById(idInputOculto);
        if (input) input.classList.remove('hidden');
        return null;
    }
}

// Aviso breve (se autodesvanece) de que una imagen pegada en el editor no se guardó — ver el
// matcher 'IMG' en crearEditorEnriquecido más arriba.
function _avisarImagenNoPermitidaEnEditor(idContenedor) {
    const contenedor = document.getElementById(idContenedor);
    if (!contenedor) return;
    const idAviso = idContenedor + '-aviso-imagen';
    let aviso = document.getElementById(idAviso);
    if (aviso) return; // ya se está mostrando; no duplicar
    aviso = document.createElement('p');
    aviso.id = idAviso;
    aviso.className = 'text-amber-400 text-[11px] mt-1.5';
    aviso.innerHTML = '<i class="fa-solid fa-triangle-exclamation mr-1"></i> Las imágenes no se pueden pegar directamente aquí. Si el formulario tiene un campo para adjuntar archivos, úsalo para incluir imágenes.';
    contenedor.insertAdjacentElement('afterend', aviso);
    setTimeout(function () { aviso.remove(); }, 7000);
}

// Para los formularios de EDITAR (ya traen contenido existente): reemplaza el HTML del
// editor y sincroniza de una vez el input oculto, sin esperar a que el usuario escriba algo.
function cargarContenidoEnEditor(quill, idInputOculto, htmlExistente) {
    const input = document.getElementById(idInputOculto);
    if (!quill) {
        // Editor no disponible (ver crearEditorEnriquecido): se deja el HTML tal cual en el
        // campo de texto simple de respaldo.
        if (input) input.value = htmlExistente || '';
        return;
    }
    quill.root.innerHTML = htmlExistente || '';
    if (input) input.value = quill.root.innerHTML;
}
