// 🔔 Campanita de notificaciones — compartida por todas las páginas autenticadas de Arkiv.
// Consulta /notificaciones/resumen cada 30s y al cargar la página; pinta el contador de no
// leídas sobre el ícono de campana y la lista desplegable. Cada notificación enlaza a
// /notificaciones/<id>/ir, que la marca como leída y redirige al destino real (el ticket,
// el comunicado, etc.) en un solo clic.
//
// 🗑️ Papelera: la campanita tiene dos vistas ('activas' y 'papelera'), controladas por
// `_vistaNotificaciones`. Archivar es reversible (icono de caneca en cada notificación activa);
// eliminar definitivamente solo se puede hacer DESDE la papelera, nunca desde la lista
// principal — así nadie borra algo sin verlo primero ahí.

var _vistaNotificaciones = 'activas';

function toggleNotificaciones() {
    var dd = document.getElementById('dropdown-notificaciones');
    if (!dd) return;
    var abierta = !dd.classList.contains('hidden');
    if (abierta) {
        _cerrarDropdownNotificaciones();
    } else {
        dd.classList.remove('hidden');
        cargarNotificaciones();
    }
}

function _cerrarDropdownNotificaciones() {
    var dd = document.getElementById('dropdown-notificaciones');
    if (dd) dd.classList.add('hidden');
    // Siempre vuelve a abrir en "Notificaciones" (no en la papelera) la próxima vez.
    if (_vistaNotificaciones === 'papelera') {
        _vistaNotificaciones = 'activas';
        var titulo = document.getElementById('titulo-notificaciones');
        var btnMarcarLeidas = document.getElementById('btn-marcar-leidas');
        var btnVaciar = document.getElementById('btn-vaciar-papelera');
        var btnVer = document.getElementById('btn-ver-papelera');
        if (titulo) titulo.textContent = 'Notificaciones';
        if (btnMarcarLeidas) btnMarcarLeidas.classList.remove('hidden');
        if (btnVaciar) btnVaciar.classList.add('hidden');
        if (btnVer) {
            btnVer.title = 'Ver papelera de notificaciones';
            btnVer.innerHTML = '<i class="fa-solid fa-trash-can text-xs"></i>';
        }
    }
}

function toggleVistaPapelera(evento) {
    // 🐛 Corrección de bug: este botón reemplaza su propio ícono (innerHTML) para cambiar
    // de 🗑️ a ← según la vista. Si el clic ocurrió justo sobre el <i> del ícono, ese <i>
    // queda "desconectado" del DOM en cuanto se reemplaza el innerHTML — y el listener
    // global de "clic afuera" (en notificaciones.js, más abajo) usa wrapper.contains(evento.target)
    // para decidir si cierra el desplegable. Un nodo ya desconectado del DOM nunca está
    // "contenido" en nada, así que ese listener creía que el clic fue AFUERA de la campanita
    // y cerraba el desplegable inmediatamente después de abrir la papelera (nunca se llegaba
    // a ver). stopPropagation() evita que el clic siquiera llegue a ese listener del document.
    if (evento) { evento.stopPropagation(); }
    _vistaNotificaciones = (_vistaNotificaciones === 'papelera') ? 'activas' : 'papelera';
    var titulo = document.getElementById('titulo-notificaciones');
    var btnMarcarLeidas = document.getElementById('btn-marcar-leidas');
    var btnVaciar = document.getElementById('btn-vaciar-papelera');
    var btnVer = document.getElementById('btn-ver-papelera');
    var enPapelera = _vistaNotificaciones === 'papelera';
    if (titulo) titulo.textContent = enPapelera ? 'Papelera' : 'Notificaciones';
    if (btnMarcarLeidas) btnMarcarLeidas.classList.toggle('hidden', enPapelera);
    if (btnVaciar) btnVaciar.classList.toggle('hidden', !enPapelera);
    if (btnVer) {
        btnVer.title = enPapelera ? 'Volver a notificaciones' : 'Ver papelera de notificaciones';
        btnVer.innerHTML = enPapelera ? '<i class="fa-solid fa-arrow-left text-xs"></i>' : '<i class="fa-solid fa-trash-can text-xs"></i>';
    }
    cargarNotificaciones();
}

function _csrfTokenNotif() {
    var wrapper = document.getElementById('wrapper-notificaciones');
    return wrapper ? (wrapper.getAttribute('data-csrf-token') || '') : '';
}

function _escapeHtmlNotif(texto) {
    var div = document.createElement('div');
    div.textContent = texto || '';
    return div.innerHTML;
}

function cargarNotificaciones() {
    fetch('/notificaciones/resumen?vista=' + _vistaNotificaciones)
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var badge = document.getElementById('badge-notificaciones');
            if (badge) {
                if (data.no_leidas > 0) {
                    badge.textContent = data.no_leidas > 99 ? '99+' : data.no_leidas;
                    badge.classList.remove('hidden');
                } else {
                    badge.classList.add('hidden');
                }
            }
            // 💬 Mismo sondeo, mismo dato de siempre: pinta el contador del botón de Chat
            // Interno de la barra (partials/chat_boton.html) y el de la burbuja flotante
            // (partials/chat_flotante.html) si esta página tiene alguno de los dos.
            ['badge-chat-header', 'badge-chat-flotante'].forEach(function (idBadge) {
                var badgeChat = document.getElementById(idBadge);
                if (!badgeChat) return;
                if (data.chat_no_leidos > 0) {
                    badgeChat.textContent = data.chat_no_leidos > 99 ? '99+' : data.chat_no_leidos;
                    badgeChat.classList.remove('hidden');
                } else {
                    badgeChat.classList.add('hidden');
                }
            });
            var lista = document.getElementById('lista-notificaciones');
            if (!lista) return;
            var enPapelera = _vistaNotificaciones === 'papelera';
            if (!data.recientes || !data.recientes.length) {
                lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">' +
                    (enPapelera ? 'La papelera está vacía.' : 'No tienes notificaciones todavía.') + '</p>';
                return;
            }
            lista.innerHTML = data.recientes.map(function (n) {
                var noLeidaClase = (!enPapelera && !n.leida) ? 'bg-sky-500/10' : '';
                var puntoNoLeida = (!enPapelera && !n.leida) ? '<span class="w-1.5 h-1.5 rounded-full bg-sky-400 inline-block mr-1.5"></span>' : '';
                var botonesAccion = enPapelera
                    ? ('<button type="button" onclick="restaurarNotificacion(' + n.id + ', event)" title="Restaurar" class="px-2 text-slate-400 hover:text-sky-400"><i class="fa-solid fa-rotate-left text-[11px]"></i></button>' +
                       '<button type="button" onclick="eliminarNotificacionDefinitiva(' + n.id + ', event)" title="Eliminar definitivamente" class="px-2 text-slate-400 hover:text-rose-400"><i class="fa-solid fa-trash text-[11px]"></i></button>')
                    : ('<button type="button" onclick="archivarNotificacion(' + n.id + ', event)" title="Archivar" class="px-2 text-slate-500 hover:text-rose-400"><i class="fa-solid fa-box-archive text-[11px]"></i></button>');
                return '<div class="flex items-stretch text-[11px] text-slate-300 hover:bg-slate-700/50 transition-colors ' + noLeidaClase + '">' +
                    '<a href="/notificaciones/' + n.id + '/ir" class="flex-1 min-w-0 block px-4 py-2.5">' +
                    puntoNoLeida + _escapeHtmlNotif(n.mensaje) +
                    '<div class="text-slate-500 font-mono text-[10px] mt-0.5">' + _escapeHtmlNotif(n.fecha) + '</div></a>' +
                    '<div class="flex items-center flex-shrink-0">' + botonesAccion + '</div></div>';
            }).join('');
        })
        .catch(function () { /* silencioso: la campanita no debe romper la página si falla */ });
}

function marcarTodasLeidas() {
    // 🛡️ La app valida CSRF real en todo POST (ver CSRFProtect en app.py); esta llamada no
    // manda ningún <form>, así que el token va como header — si no, Flask-WTF la rechaza en
    // silencio (redirige) y el fetch la da por buena sin haber marcado nada como leído.
    fetch('/notificaciones/marcar_todas_leidas', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenNotif() }
    }).then(function () {
        cargarNotificaciones();
    });
}

function archivarNotificacion(id, evento) {
    if (evento) { evento.preventDefault(); evento.stopPropagation(); }
    fetch('/notificaciones/' + id + '/archivar', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenNotif() }
    }).then(function () { cargarNotificaciones(); });
}

function restaurarNotificacion(id, evento) {
    if (evento) { evento.preventDefault(); evento.stopPropagation(); }
    fetch('/notificaciones/' + id + '/restaurar', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenNotif() }
    }).then(function () { cargarNotificaciones(); });
}

function eliminarNotificacionDefinitiva(id, evento) {
    if (evento) { evento.preventDefault(); evento.stopPropagation(); }
    if (!confirm('¿Eliminar esta notificación definitivamente? No se puede deshacer.')) return;
    fetch('/notificaciones/' + id + '/eliminar', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenNotif() }
    }).then(function () { cargarNotificaciones(); });
}

function vaciarPapelera() {
    if (!confirm('¿Vaciar la papelera? Se eliminarán definitivamente todas las notificaciones archivadas y no se puede deshacer.')) return;
    fetch('/notificaciones/papelera/vaciar', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenNotif() }
    }).then(function () { cargarNotificaciones(); });
}

document.addEventListener('DOMContentLoaded', function () {
    cargarNotificaciones();
    setInterval(cargarNotificaciones, 30000);

    // Cierra el desplegable al hacer clic fuera de la campanita.
    document.addEventListener('click', function (evento) {
        var wrapper = document.getElementById('wrapper-notificaciones');
        var dd = document.getElementById('dropdown-notificaciones');
        if (!wrapper || !dd || dd.classList.contains('hidden')) return;
        if (!wrapper.contains(evento.target)) {
            _cerrarDropdownNotificaciones();
        }
    });
});
