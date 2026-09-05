// 🔴 TIEMPO REAL (Socket.IO) — pedido por Tomás: antes la campanita y el Chat Interno solo se
// enteraban de algo nuevo al sondear cada pocos segundos (o había que refrescar/salir y volver
// a entrar para verlo). Este archivo abre UNA conexión de Socket.IO por pestaña (compartida por
// la campanita y el chat) y, apenas el servidor avisa algo nuevo, llama a las mismas funciones
// de siempre — cargarNotificaciones() de notificaciones.js, cargarMensajesChat()/
// cargarContactosChat() de chat.js — en vez de esperar el próximo sondeo. El sondeo periódico
// de esos archivos SIGUE existiendo tal cual estaba: es el respaldo si el socket se cae o
// tarda en reconectar (por ejemplo con mala conexión), así que nunca depende solo de esto.
//
// Quién une a quién a qué "sala" lo decide el servidor al conectarse (ver _socketio_conectar
// en app.py): cada quien a la suya propia (sus notificaciones/directos) y, si es admin/agente,
// también a la del Canal General. Este archivo no necesita saber el usuario ni el rol.

(function () {
    if (typeof io === 'undefined') return; // el script de socket.io no cargó (CDN caído/bloqueado): se sigue con el sondeo normal nada más

    var wrapperNotif = document.getElementById('wrapper-notificaciones');
    if (!wrapperNotif) return; // página sin campanita: no hay nada que conectar aquí

    var socket = io({ transports: ['websocket', 'polling'] });

    socket.on('notificacion_nueva', function (datos) {
        // Cubre TODO lo que ya pasa por crear_notificacion() en el servidor: tickets,
        // comunicados, chat directo, etc. — no solo el chat.
        if (typeof cargarNotificaciones === 'function') cargarNotificaciones();
        _mostrarToastTiempoReal(datos);
    });

    socket.on('chat_canal_mensaje', function () {
        // El Canal General nunca manda notificación de campanita (para no saturar con un
        // canal de equipo activo — ver crear_notificacion en chat_directo_enviar), pero sí
        // debe verse al toque si alguien tiene el chat abierto justo en el Canal General, y
        // su contador de no leídos (parte de chat_no_leidos) igual vive en /notificaciones/resumen.
        if (typeof cargarNotificaciones === 'function') cargarNotificaciones();
        if (typeof _chatActual !== 'undefined' && _chatActual.tipo === 'canal' && typeof cargarMensajesChat === 'function') {
            cargarMensajesChat(false);
        }
        if (typeof cargarContactosChat === 'function') cargarContactosChat();
        // 🪟 Mismo aviso, para quien tenga abierto el widget flotante (chat_widget.js) en vez de
        // (o además de) la página /chat completa — ver ese archivo para el detalle.
        if (typeof _widgetRefrescarCanal === 'function') _widgetRefrescarCanal();
    });

    socket.on('chat_directo_mensaje', function (datos) {
        if (typeof cargarNotificaciones === 'function') cargarNotificaciones();
        if (typeof _chatActual !== 'undefined' && _chatActual.tipo === 'directo' &&
            (_chatActual.usuario === datos.remitente || _chatActual.usuario === datos.destinatario) &&
            typeof cargarMensajesChat === 'function') {
            cargarMensajesChat(false);
        }
        if (typeof cargarContactosChat === 'function') cargarContactosChat();
        if (typeof _widgetRefrescarDirecto === 'function') _widgetRefrescarDirecto(datos);
    });

    // 🍞 Pop-up (toast) simple y apilable, esquina inferior IZQUIERDA — la derecha ya tiene el
    // botón de cambiar tema y la burbuja de Chat Interno. Se autodestruye a los 6s o al clic.
    function _contenedorToastsTiempoReal() {
        var cont = document.getElementById('contenedor-toasts-tiempo-real');
        if (!cont) {
            cont = document.createElement('div');
            cont.id = 'contenedor-toasts-tiempo-real';
            cont.style.cssText = 'position:fixed;bottom:20px;left:20px;z-index:9999;display:flex;flex-direction:column-reverse;gap:8px;max-width:320px;';
            document.body.appendChild(cont);
        }
        return cont;
    }

    function _escapeHtmlToastTiempoReal(texto) {
        var div = document.createElement('div');
        div.textContent = texto || '';
        return div.innerHTML;
    }

    function _mostrarToastTiempoReal(datos) {
        var cont = _contenedorToastsTiempoReal();
        var toast = document.createElement('div');
        toast.style.cssText = 'background:#1e293b;border:1px solid #334155;color:#f1f5f9;border-radius:14px;padding:12px 14px;font-size:12.5px;line-height:1.5;box-shadow:0 10px 25px rgba(0,0,0,.35);cursor:pointer;animation:tiemporeal-toast-in .2s ease-out;font-family:inherit;';
        toast.innerHTML = '<div style="display:flex;align-items:flex-start;gap:8px;">' +
            '<i class="fa-solid fa-bell" style="color:#38bdf8;margin-top:2px;flex-shrink:0;"></i>' +
            '<div style="flex:1;min-width:0;word-wrap:break-word;">' + _escapeHtmlToastTiempoReal(datos.mensaje) + '</div>' +
            '<button type="button" aria-label="Cerrar" style="background:none;border:none;color:#64748b;cursor:pointer;font-size:12px;padding:0 0 0 4px;flex-shrink:0;">✕</button>' +
            '</div>';
        var botonCerrar = toast.querySelector('button');
        var quitar = function () { if (toast.parentNode) toast.parentNode.removeChild(toast); };
        botonCerrar.addEventListener('click', function (e) { e.stopPropagation(); quitar(); });
        toast.addEventListener('click', function () {
            if (datos.url) window.location.href = datos.url;
        });
        cont.appendChild(toast);
        setTimeout(quitar, 6000);
    }

    if (!document.getElementById('tiemporeal-toast-style')) {
        var estilo = document.createElement('style');
        estilo.id = 'tiemporeal-toast-style';
        estilo.textContent = '@keyframes tiemporeal-toast-in { from { opacity:0; transform:translateY(8px);} to {opacity:1; transform:translateY(0);} }';
        document.head.appendChild(estilo);
    }
})();
