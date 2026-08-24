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
