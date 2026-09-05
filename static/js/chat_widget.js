// 🪟 WIDGET FLOTANTE DE CHAT INTERNO — pedido por Tomás (como el chatbot de copnia.gov.co): que
// el botón flotante de Chat Interno (partials/chat_flotante.html) abra un panel de chat AHÍ
// MISMO, sin salir de la página en la que se esté, en vez de siempre mandar a /chat. Reutiliza
// las mismas rutas que ya usa chat.js (/chat/contactos, /chat/canal/mensajes,
// /chat/directo/<u>/mensajes, .../enviar) y el MISMO socket que ya abre tiempo_real.js — nunca
// abre una segunda conexión: tiempo_real.js llama a _widgetRefrescarCanal()/
// _widgetRefrescarDirecto() (ver ahí) cuando llega algo nuevo y el panel está construido.
// El botón "expandir" del encabezado lleva a /chat de toda la vida, por si hace falta más
// espacio o el historial completo.
//
// El panel se construye UNA sola vez, la primera vez que se hace clic en el botón (no en cada
// carga de página, para no gastar de más en páginas donde nunca se abre). Vive en TODAS las
// páginas que incluyen partials/chat_flotante.html (solo admin/agente), salvo /chat mismo, que
// ya tiene su propia interfaz completa.

(function () {
    var POLL_MENSAJES_WIDGET_MS = 4000;
    var POLL_CONTACTOS_WIDGET_MS = 15000;

    var _widgetConstruido = false;
    var _widgetAbierto = false;
    var _widgetChatActual = { tipo: null, usuario: null, nombre: null }; // null = nunca se abrió nada todavía
    var _widgetUltimoId = 0;
    var _widgetIdsRenderizados = {}; // mismo remedio que chat.js contra mensajes pintados dos veces
    var _widgetIntervaloMensajes = null;
    var _widgetIntervaloContactos = null;
    var _widgetContactos = [];
    var _widgetCanalNoLeidos = 0;
    var _widgetEnviando = false;
    // 📎 Mismo adjunto pendiente que chat.js (ver ese archivo) — un archivo elegido con el clip
    // o pegado desde el portapapeles, listo para viajar junto con el próximo mensaje.
    var _widgetAdjuntoSeleccionado = null;
    var TAMANO_MAXIMO_ADJUNTO_WIDGET_MB = 25;

    function _csrfTokenWidget() {
        var w = document.getElementById('wrapper-notificaciones'); // ya vive en toda página con campanita
        return w ? (w.getAttribute('data-csrf-token') || '') : '';
    }

    function _escapeHtmlWidget(texto) {
        var div = document.createElement('div');
        div.textContent = texto || '';
        return div.innerHTML;
    }

    // 🔒 Para meter texto dinámico dentro de un atributo HTML (data-nombre="...") hace falta
    // ESCAPAR TAMBIÉN las comillas — _escapeHtmlWidget por sí sola escapa &/</> (vía
    // textContent) pero no una comilla doble, que rompería el atributo si el nombre trae una
    // (p. ej. apellidos con comilla o similar). Nunca se arma un onclick con datos del usuario
    // interpolados directamente — todo pasa por data-* + un solo listener delegado más abajo.
    function _escapeAtributoWidget(texto) {
        return _escapeHtmlWidget(texto).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function _normalizarBusquedaWidget(texto) {
        return (texto || '').toString().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
    }

    function _widgetUrlMensajesActual() {
        if (_widgetChatActual.tipo === 'directo') return '/chat/directo/' + encodeURIComponent(_widgetChatActual.usuario) + '/mensajes';
        return '/chat/canal/mensajes';
    }

    function _widgetUrlEnviarActual() {
        if (_widgetChatActual.tipo === 'directo') return '/chat/directo/' + encodeURIComponent(_widgetChatActual.usuario) + '/enviar';
        return '/chat/canal/enviar';
    }

    // 📎 Mismo patrón que chat.js: miniatura clicable si el adjunto es imagen, tarjeta genérica
    // con el nombre si es cualquier otro archivo permitido.
    function _widgetAdjuntoHtml(m) {
        if (!m.adjunto_url) return '';
        if (m.adjunto_es_imagen) {
            return '<a href="' + _escapeAtributoWidget(m.adjunto_url) + '" target="_blank" rel="noopener" class="block mt-1.5">' +
                '<img src="' + _escapeAtributoWidget(m.adjunto_url) + '" alt="' + _escapeAtributoWidget(m.adjunto_nombre || 'imagen') + '" ' +
                'class="max-w-[160px] max-h-[160px] rounded-lg border border-slate-700/60 object-cover">' +
                '</a>';
        }
        return '<a href="' + _escapeAtributoWidget(m.adjunto_url) + '" target="_blank" rel="noopener" ' +
            'class="flex items-center gap-1.5 mt-1.5 bg-slate-900/40 border border-slate-700/60 rounded-lg px-2 py-1.5 text-[10px]">' +
            '<i class="fa-solid fa-file-lines"></i>' +
            '<span class="max-w-[8rem] truncate">' + _escapeHtmlWidget(m.adjunto_nombre || 'Archivo') + '</span>' +
            '<i class="fa-solid fa-arrow-up-right-from-square text-[8px] opacity-70"></i></a>';
    }

    function _widgetBurbujaMensaje(m) {
        var base = 'w-fit max-w-[80%] px-3 py-1.5 rounded-2xl text-xs leading-relaxed whitespace-pre-wrap break-words';
        var clasePropia = 'ml-auto bg-sky-600 text-white rounded-br-sm';
        var claseAjena = 'bg-slate-800 text-slate-100 rounded-bl-sm';
        var nombreLinea = (!m.es_mio && m.remitente_nombre)
            ? '<div class="text-[9px] font-bold text-sky-400 mb-0.5">' + _escapeHtmlWidget(m.remitente_nombre) + '</div>'
            : '';
        var textoMensaje = m.mensaje ? _escapeHtmlWidget(m.mensaje) : '';
        return '<div class="' + base + ' ' + (m.es_mio ? clasePropia : claseAjena) + '">' +
            nombreLinea + textoMensaje + _widgetAdjuntoHtml(m) +
            '<div class="text-[8px] mt-1 ' + (m.es_mio ? 'text-sky-100/70' : 'text-slate-500') + ' font-mono">' +
            _escapeHtmlWidget(m.fecha) + '</div></div>';
    }

    function _widgetConstruirPanel() {
        if (_widgetConstruido) return;
        _widgetConstruido = true;

        var panel = document.createElement('div');
        panel.id = 'panel-widget-chat-flotante';
        // 🐛 'hidden' y 'flex' NUNCA deben estar los dos presentes a la vez (Tailwind no tiene un
        // orden de especificidad entre utilidades, así que cuál gana es indeterminado desde el
        // markup) — por eso 'flex' se agrega/quita junto con 'hidden' en abrirChatFlotante() y
        // cerrarChatFlotante(), en vez de dejarlo fijo aquí como clase base.
        panel.className = 'hidden fixed bottom-[132px] right-5 z-50 w-[360px] max-w-[92vw] h-[480px] max-h-[70vh] bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl shadow-slate-950/50 flex-col overflow-hidden';
        panel.innerHTML =
            '<div id="widget-vista-lista" class="flex-1 flex flex-col min-h-0">' +
                '<div class="px-4 py-3 border-b border-slate-800 flex items-center justify-between flex-shrink-0">' +
                    '<h2 class="text-sm font-bold text-white flex items-center gap-2"><i class="fa-solid fa-comment-dots text-sky-400"></i>Chat Interno</h2>' +
                    '<div class="flex items-center gap-1">' +
                        '<a href="/chat" title="Abrir en pantalla completa" class="text-slate-500 hover:text-white w-7 h-7 flex items-center justify-center rounded-lg hover:bg-slate-800"><i class="fa-solid fa-up-right-and-down-left-from-center text-xs"></i></a>' +
                        '<button type="button" id="widget-boton-cerrar-lista" class="text-slate-500 hover:text-white w-7 h-7 flex items-center justify-center rounded-lg hover:bg-slate-800"><i class="fa-solid fa-xmark"></i></button>' +
                    '</div>' +
                '</div>' +
                '<div class="px-3 py-2 border-b border-slate-800/70 flex-shrink-0">' +
                    '<div class="relative">' +
                        '<i class="fa-solid fa-magnifying-glass absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 text-xs pointer-events-none"></i>' +
                        '<input type="text" id="widget-buscar-contactos" placeholder="Buscar por nombre o usuario..." autocomplete="off" ' +
                            'class="w-full pl-8 pr-3 py-1.5 bg-slate-800/70 border border-slate-700 rounded-lg text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500">' +
                    '</div>' +
                '</div>' +
                '<div id="widget-lista-conversaciones" class="flex-1 overflow-y-auto divide-y divide-slate-800/50">' +
                    '<p class="text-slate-500 text-center text-[11px] py-6 px-4">Cargando...</p>' +
                '</div>' +
            '</div>' +
            '<div id="widget-vista-conversacion" class="hidden flex-1 flex-col min-h-0">' +
                '<div class="px-2.5 py-2.5 border-b border-slate-800 flex items-center gap-2 flex-shrink-0">' +
                    '<button type="button" id="widget-boton-volver" class="text-slate-400 hover:text-white w-7 h-7 flex items-center justify-center flex-shrink-0"><i class="fa-solid fa-arrow-left"></i></button>' +
                    '<div class="w-8 h-8 rounded-lg bg-sky-500/15 text-sky-400 border border-sky-500/25 flex items-center justify-center text-xs flex-shrink-0" id="widget-icono-titulo"><i class="fa-solid fa-users"></i></div>' +
                    '<div class="min-w-0 flex-1"><div class="text-xs font-bold text-white truncate" id="widget-titulo-conversacion">Canal General</div></div>' +
                    '<a id="widget-abrir-completo" href="/chat" title="Abrir en pantalla completa" class="text-slate-500 hover:text-white w-7 h-7 flex items-center justify-center flex-shrink-0"><i class="fa-solid fa-up-right-and-down-left-from-center text-xs"></i></a>' +
                    '<button type="button" id="widget-boton-cerrar-conversacion" class="text-slate-500 hover:text-white w-7 h-7 flex items-center justify-center flex-shrink-0"><i class="fa-solid fa-xmark"></i></button>' +
                '</div>' +
                '<div id="widget-lista-mensajes" class="flex-1 overflow-y-auto px-3 py-3 space-y-2"></div>' +
                '<div id="widget-error-chat" class="hidden px-3 py-1.5 text-[10px] text-rose-400 bg-rose-500/10 border-t border-rose-500/20"></div>' +
                '<form id="widget-form-enviar" class="border-t border-slate-800 p-2 flex-shrink-0">' +
                    // 📎 Mismo patrón que chat.html: clip + previsualización + pegar imagen (ver
                    // _widgetSeleccionarAdjunto/_widgetPegarEnMensaje más abajo).
                    '<div id="widget-previsualizacion-adjunto" class="hidden mb-1.5 flex items-center gap-1.5 bg-slate-800/70 border border-slate-700 rounded-lg px-2 py-1.5 text-[10px] text-slate-300">' +
                        '<i class="fa-solid fa-paperclip text-sky-400"></i>' +
                        '<span id="widget-nombre-adjunto" class="flex-1 min-w-0 truncate"></span>' +
                        '<button type="button" id="widget-quitar-adjunto" title="Quitar adjunto" class="text-slate-500 hover:text-rose-400 px-1"><i class="fa-solid fa-xmark"></i></button>' +
                    '</div>' +
                    '<div class="flex items-end gap-1.5">' +
                        '<input type="file" id="widget-input-adjunto" class="hidden" ' +
                            'accept=".png,.jpg,.jpeg,.gif,.webp,.pdf,.txt,.docx,.xlsx,.pptx,.mp4,.mov,.webm,.avi,.zip,.rar,.7z,.tar,.gz">' +
                        '<button type="button" id="widget-boton-adjuntar" title="Adjuntar archivo" ' +
                            'class="w-8 h-8 flex-shrink-0 bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-300 rounded-xl flex items-center justify-center"><i class="fa-solid fa-paperclip"></i></button>' +
                        '<textarea id="widget-input-mensaje" rows="1" maxlength="2000" placeholder="Escribe un mensaje..." ' +
                            'class="flex-1 resize-none px-3 py-2 bg-slate-800 border border-slate-700 rounded-xl text-xs text-white placeholder-slate-500 focus:outline-none focus:border-sky-500"></textarea>' +
                        '<button type="submit" class="w-8 h-8 flex-shrink-0 bg-sky-600 hover:bg-sky-500 text-white text-xs rounded-xl flex items-center justify-center"><i class="fa-solid fa-paper-plane"></i></button>' +
                    '</div>' +
                '</form>' +
            '</div>';
        document.body.appendChild(panel);

        // 🖱️ Un solo listener delegado para toda la lista (Canal General + contactos), en vez de
        // onclick individuales con datos interpolados — así nunca hay riesgo de romper el HTML
        // con un nombre que traiga comillas o similar (ver _escapeAtributoWidget arriba).
        document.getElementById('widget-lista-conversaciones').addEventListener('click', function (e) {
            var itemCanal = e.target.closest('#widget-item-canal-general');
            if (itemCanal) { _widgetAbrirCanalGeneral(); return; }
            var itemContacto = e.target.closest('.widget-item-contacto');
            if (itemContacto) {
                _widgetAbrirDirecto(itemContacto.getAttribute('data-usuario'), itemContacto.getAttribute('data-nombre'));
            }
        });

        document.getElementById('widget-buscar-contactos').addEventListener('input', _widgetPintarLista);
        document.getElementById('widget-boton-volver').addEventListener('click', _widgetVolverALista);
        document.getElementById('widget-boton-cerrar-lista').addEventListener('click', cerrarChatFlotante);
        document.getElementById('widget-boton-cerrar-conversacion').addEventListener('click', cerrarChatFlotante);
        document.getElementById('widget-form-enviar').addEventListener('submit', _widgetEnviarMensaje);
        document.getElementById('widget-boton-adjuntar').addEventListener('click', function () {
            document.getElementById('widget-input-adjunto').click();
        });
        document.getElementById('widget-input-adjunto').addEventListener('change', _widgetSeleccionarAdjunto);
        document.getElementById('widget-quitar-adjunto').addEventListener('click', _widgetQuitarAdjunto);

        var input = document.getElementById('widget-input-mensaje');
        input.addEventListener('keydown', _widgetTeclaMensaje);
        input.addEventListener('paste', _widgetPegarEnMensaje);
        input.addEventListener('input', function () {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 100) + 'px';
        });
    }

    function _widgetPintarLista() {
        var cont = document.getElementById('widget-lista-conversaciones');
        if (!cont) return;
        var inputBusqueda = document.getElementById('widget-buscar-contactos');
        var consulta = _normalizarBusquedaWidget(inputBusqueda ? inputBusqueda.value : '').trim();

        var html = '';
        var coincideCanal = !consulta || _normalizarBusquedaWidget('Canal General').indexOf(consulta) !== -1;
        if (coincideCanal) {
            var activoCanal = _widgetChatActual.tipo === 'canal';
            html += '<button type="button" id="widget-item-canal-general" class="w-full text-left px-3 py-2.5 flex items-center gap-2.5 hover:bg-slate-800/60 transition-colors ' + (activoCanal ? 'bg-sky-500/10' : '') + '">' +
                '<div class="w-8 h-8 rounded-lg bg-sky-500/15 text-sky-400 border border-sky-500/25 flex items-center justify-center text-xs flex-shrink-0"><i class="fa-solid fa-users"></i></div>' +
                '<div class="min-w-0 flex-1"><div class="text-xs font-semibold text-white truncate">Canal General</div><div class="text-[10px] text-slate-500 truncate">Todo el equipo</div></div>' +
                (_widgetCanalNoLeidos > 0 && !activoCanal ? '<span class="bg-rose-500 text-white text-[9px] font-bold rounded-full min-w-[16px] h-4 flex items-center justify-center px-1 flex-shrink-0">' + (_widgetCanalNoLeidos > 99 ? '99+' : _widgetCanalNoLeidos) + '</span>' : '') +
                '</button>';
        }

        var algunContacto = false;
        _widgetContactos.forEach(function (c) {
            var usuarioNorm = _normalizarBusquedaWidget(c.usuario);
            var nombreNorm = _normalizarBusquedaWidget(c.nombre);
            if (consulta && usuarioNorm.indexOf(consulta) === -1 && nombreNorm.indexOf(consulta) === -1) return;
            algunContacto = true;
            var activo = _widgetChatActual.tipo === 'directo' && _widgetChatActual.usuario === c.usuario;
            var noLeidos = activo ? 0 : (c.no_leidos || 0);
            var previa = c.ultimo_mensaje ? (c.ultimo_mensaje.length > 34 ? c.ultimo_mensaje.slice(0, 34) + '…' : c.ultimo_mensaje) : 'Sin mensajes todavía';
            html += '<button type="button" class="widget-item-contacto w-full text-left px-3 py-2.5 flex items-center gap-2.5 hover:bg-slate-800/60 transition-colors ' + (activo ? 'bg-sky-500/10' : '') + '" ' +
                'data-usuario="' + _escapeAtributoWidget(c.usuario) + '" data-nombre="' + _escapeAtributoWidget(c.nombre) + '">' +
                '<div class="w-8 h-8 rounded-lg bg-slate-700/60 text-slate-300 border border-slate-700 flex items-center justify-center text-[10px] font-bold flex-shrink-0">' + _escapeHtmlWidget((c.nombre || '?').slice(0, 1).toUpperCase()) + '</div>' +
                '<div class="min-w-0 flex-1"><div class="text-xs font-semibold text-white truncate">' + _escapeHtmlWidget(c.nombre) + '</div><div class="text-[10px] text-slate-500 truncate">' + _escapeHtmlWidget(previa) + '</div></div>' +
                (noLeidos > 0 ? '<span class="bg-rose-500 text-white text-[9px] font-bold rounded-full min-w-[16px] h-4 flex items-center justify-center px-1 flex-shrink-0">' + (noLeidos > 99 ? '99+' : noLeidos) + '</span>' : '') +
                '</button>';
        });

        if (!coincideCanal && !algunContacto) {
            html = '<p class="text-slate-500 text-center text-[11px] py-6 px-4">Sin resultados para tu búsqueda.</p>';
        } else if (!_widgetContactos.length && !consulta) {
            html += '<p class="text-slate-500 text-center text-[11px] py-6 px-4">No hay más admin/agente activos para chatear.</p>';
        }
        cont.innerHTML = html;
    }

    function _widgetCargarContactos() {
        fetch('/chat/contactos')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _widgetContactos = data.contactos || [];
                _widgetCanalNoLeidos = data.canal_no_leidos || 0;
                _widgetPintarLista();
            })
            .catch(function () { /* silencioso: igual que chat.js, un fallo de red no debe interrumpir nada */ });
    }

    function _widgetMostrarVista(vista) {
        var vistaLista = document.getElementById('widget-vista-lista');
        var vistaConversacion = document.getElementById('widget-vista-conversacion');
        if (vista === 'conversacion') {
            vistaLista.classList.add('hidden');
            vistaConversacion.classList.remove('hidden');
            vistaConversacion.classList.add('flex');
        } else {
            vistaConversacion.classList.add('hidden');
            vistaConversacion.classList.remove('flex');
            vistaLista.classList.remove('hidden');
        }
    }

    function _widgetVolverALista() {
        _widgetMostrarVista('lista');
        _widgetPintarLista(); // refresca resaltado/badges por si cambiaron mientras se leía
    }

    function _widgetLimpiarMensajes() {
        var lista = document.getElementById('widget-lista-mensajes');
        if (lista) lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">Cargando...</p>';
        var errorDiv = document.getElementById('widget-error-chat');
        if (errorDiv) errorDiv.classList.add('hidden');
        _widgetIdsRenderizados = {};
        _widgetQuitarAdjunto(); // un adjunto pendiente no debe viajar a la conversación nueva
    }

    function _widgetAbrirCanalGeneral() {
        _widgetChatActual = { tipo: 'canal', usuario: null, nombre: null };
        _widgetUltimoId = 0;
        document.getElementById('widget-titulo-conversacion').textContent = 'Canal General';
        document.getElementById('widget-icono-titulo').innerHTML = '<i class="fa-solid fa-users"></i>';
        document.getElementById('widget-abrir-completo').setAttribute('href', '/chat');
        _widgetLimpiarMensajes();
        _widgetMostrarVista('conversacion');
        _widgetCargarMensajes(true);
        _widgetAsegurarSondeoMensajes();
    }

    function _widgetAbrirDirecto(usuario, nombre) {
        _widgetChatActual = { tipo: 'directo', usuario: usuario, nombre: nombre };
        _widgetUltimoId = 0;
        document.getElementById('widget-titulo-conversacion').textContent = nombre;
        document.getElementById('widget-icono-titulo').textContent = (nombre || '?').slice(0, 1).toUpperCase();
        document.getElementById('widget-abrir-completo').setAttribute('href', '/chat?con=' + encodeURIComponent(usuario));
        _widgetLimpiarMensajes();
        _widgetMostrarVista('conversacion');
        _widgetCargarMensajes(true);
        _widgetAsegurarSondeoMensajes();
    }

    function _widgetCargarMensajes(esCargaInicial) {
        var conversacionAlPedir = _widgetChatActual.tipo + ':' + (_widgetChatActual.usuario || '');
        fetch(_widgetUrlMensajesActual() + '?desde_id=' + (esCargaInicial ? 0 : _widgetUltimoId))
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if ((_widgetChatActual.tipo + ':' + (_widgetChatActual.usuario || '')) !== conversacionAlPedir) return;
                var lista = document.getElementById('widget-lista-mensajes');
                if (!lista) return;
                var mensajes = data.mensajes || [];
                if (esCargaInicial) {
                    lista.innerHTML = '';
                    if (!mensajes.length) {
                        lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">Todavía no hay mensajes. ¡Escribe el primero!</p>';
                    }
                } else if (!mensajes.length) {
                    return;
                } else if (lista.querySelector('p')) {
                    lista.innerHTML = '';
                }
                var estabaAbajo = (lista.scrollHeight - lista.scrollTop - lista.clientHeight) < 80;
                mensajes.forEach(function (m) {
                    _widgetUltimoId = Math.max(_widgetUltimoId, m.id);
                    if (_widgetIdsRenderizados[m.id]) return;
                    _widgetIdsRenderizados[m.id] = true;
                    lista.insertAdjacentHTML('beforeend', _widgetBurbujaMensaje(m));
                });
                if (esCargaInicial || estabaAbajo) lista.scrollTop = lista.scrollHeight;
            })
            .catch(function () { /* silencioso */ });
    }

    function _widgetTeclaMensaje(evento) {
        if (evento.key === 'Enter' && !evento.shiftKey) {
            evento.preventDefault();
            var form = document.getElementById('widget-form-enviar');
            if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', { cancelable: true }));
        }
    }

    function _widgetEnviarMensaje(evento) {
        if (evento) evento.preventDefault();
        if (_widgetEnviando || _widgetChatActual.tipo === null) return false;
        var input = document.getElementById('widget-input-mensaje');
        var mensaje = (input.value || '').trim();
        if (!mensaje && !_widgetAdjuntoSeleccionado) return false;
        _widgetEnviando = true;
        var errorDiv = document.getElementById('widget-error-chat');
        errorDiv.classList.add('hidden');

        var datosFormulario = new FormData();
        datosFormulario.append('mensaje', mensaje);
        if (_widgetAdjuntoSeleccionado) datosFormulario.append('adjunto', _widgetAdjuntoSeleccionado);

        fetch(_widgetUrlEnviarActual(), {
            method: 'POST',
            headers: { 'X-CSRFToken': _csrfTokenWidget() },
            body: datosFormulario
        })
            .then(function (r) { return r.json(); })
            .then(function (data) {
                _widgetEnviando = false;
                if (data && data.success) {
                    input.value = '';
                    input.style.height = 'auto';
                    _widgetQuitarAdjunto();
                    _widgetCargarMensajes(false);
                    _widgetCargarContactos();
                } else {
                    errorDiv.textContent = (data && data.error) || 'No se pudo enviar el mensaje.';
                    errorDiv.classList.remove('hidden');
                }
            })
            .catch(function () {
                _widgetEnviando = false;
                errorDiv.textContent = 'No se pudo enviar el mensaje. Revisa tu conexión.';
                errorDiv.classList.remove('hidden');
            });
        return false;
    }

    // 📎 Elegir un archivo con el clip.
    function _widgetSeleccionarAdjunto(evento) {
        var archivo = evento.target.files && evento.target.files[0];
        if (archivo) _widgetFijarAdjunto(archivo);
    }

    // 📋 Pegar una imagen copiada directo en el cuadro de texto del widget — mismo comportamiento
    // que chat.js (ver _pegarEnMensajeChat ahí para el detalle).
    function _widgetPegarEnMensaje(evento) {
        var items = (evento.clipboardData && evento.clipboardData.items) || [];
        for (var i = 0; i < items.length; i++) {
            if (items[i].type && items[i].type.indexOf('image/') === 0) {
                var archivo = items[i].getAsFile();
                if (archivo) {
                    evento.preventDefault();
                    _widgetFijarAdjunto(archivo);
                }
                return;
            }
        }
    }

    function _widgetFijarAdjunto(archivo) {
        var errorDiv = document.getElementById('widget-error-chat');
        if (archivo.size > TAMANO_MAXIMO_ADJUNTO_WIDGET_MB * 1024 * 1024) {
            if (errorDiv) {
                errorDiv.textContent = 'El archivo no puede superar ' + TAMANO_MAXIMO_ADJUNTO_WIDGET_MB + ' MB.';
                errorDiv.classList.remove('hidden');
            }
            return;
        }
        if (errorDiv) errorDiv.classList.add('hidden');
        _widgetAdjuntoSeleccionado = archivo;
        var previsualizacion = document.getElementById('widget-previsualizacion-adjunto');
        var nombreSpan = document.getElementById('widget-nombre-adjunto');
        if (nombreSpan) nombreSpan.textContent = archivo.name || 'Archivo adjunto';
        if (previsualizacion) previsualizacion.classList.remove('hidden');
    }

    function _widgetQuitarAdjunto() {
        _widgetAdjuntoSeleccionado = null;
        var previsualizacion = document.getElementById('widget-previsualizacion-adjunto');
        if (previsualizacion) previsualizacion.classList.add('hidden');
        var inputArchivo = document.getElementById('widget-input-adjunto');
        if (inputArchivo) inputArchivo.value = '';
    }

    function _widgetAsegurarSondeoMensajes() {
        // El sondeo de mensajes solo arranca cuando de verdad se abrió una conversación (no
        // apenas se abre el panel) — así no se gasta en pedir Canal General de fondo mientras
        // alguien solo está mirando la lista de contactos sin haber entrado a ninguna.
        if (_widgetIntervaloMensajes) return;
        _widgetIntervaloMensajes = setInterval(function () { _widgetCargarMensajes(false); }, POLL_MENSAJES_WIDGET_MS);
    }

    function abrirChatFlotante() {
        _widgetConstruirPanel();
        var panel = document.getElementById('panel-widget-chat-flotante');
        if (!panel) return;
        panel.classList.remove('hidden');
        panel.classList.add('flex');
        _widgetAbierto = true;
        _widgetCargarContactos();
        if (_widgetChatActual.tipo !== null) _widgetCargarMensajes(false); // recupera lo que haya llegado mientras estaba cerrado
        if (!_widgetIntervaloContactos) {
            _widgetIntervaloContactos = setInterval(_widgetCargarContactos, POLL_CONTACTOS_WIDGET_MS);
        }
    }

    function cerrarChatFlotante() {
        var panel = document.getElementById('panel-widget-chat-flotante');
        if (panel) { panel.classList.add('hidden'); panel.classList.remove('flex'); }
        _widgetAbierto = false;
        if (_widgetIntervaloContactos) { clearInterval(_widgetIntervaloContactos); _widgetIntervaloContactos = null; }
        if (_widgetIntervaloMensajes) { clearInterval(_widgetIntervaloMensajes); _widgetIntervaloMensajes = null; }
    }

    // 🌐 Expuestas globalmente: las llama el botón (chat_flotante.html) y tiempo_real.js.
    window.toggleChatFlotante = function () {
        var panel = document.getElementById('panel-widget-chat-flotante');
        var estaAbierto = panel && !panel.classList.contains('hidden');
        if (estaAbierto) cerrarChatFlotante(); else abrirChatFlotante();
    };

    window._widgetRefrescarCanal = function () {
        if (!_widgetAbierto) return;
        if (_widgetChatActual.tipo === 'canal') _widgetCargarMensajes(false);
        _widgetCargarContactos();
    };

    window._widgetRefrescarDirecto = function (datos) {
        if (!_widgetAbierto) return;
        if (_widgetChatActual.tipo === 'directo' &&
            (_widgetChatActual.usuario === datos.remitente || _widgetChatActual.usuario === datos.destinatario)) {
            _widgetCargarMensajes(false);
        }
        _widgetCargarContactos();
    };
})();
