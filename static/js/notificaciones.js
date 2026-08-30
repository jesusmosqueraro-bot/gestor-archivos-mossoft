// 🔔 Campanita de notificaciones — compartida por todas las páginas autenticadas de Arkiv.
// Consulta /notificaciones/resumen cada 30s y al cargar la página; pinta el contador de no
// leídas sobre el ícono de campana y la lista desplegable. Cada notificación enlaza a
// /notificaciones/<id>/ir, que la marca como leída y redirige al destino real (el ticket,
// el comunicado, etc.) en un solo clic.

function toggleNotificaciones() {
    var dd = document.getElementById('dropdown-notificaciones');
    if (!dd) return;
    var abierta = !dd.classList.contains('hidden');
    if (abierta) {
        dd.classList.add('hidden');
    } else {
        dd.classList.remove('hidden');
        cargarNotificaciones();
    }
}

function _escapeHtmlNotif(texto) {
    var div = document.createElement('div');
    div.textContent = texto || '';
    return div.innerHTML;
}

function cargarNotificaciones() {
    fetch('/notificaciones/resumen')
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
            var lista = document.getElementById('lista-notificaciones');
            if (!lista) return;
            if (!data.recientes || !data.recientes.length) {
                lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">No tienes notificaciones todavía.</p>';
                return;
            }
            lista.innerHTML = data.recientes.map(function (n) {
                var noLeidaClase = n.leida ? '' : 'bg-sky-500/10';
                var puntoNoLeida = n.leida ? '' : '<span class="w-1.5 h-1.5 rounded-full bg-sky-400 inline-block mr-1.5"></span>';
                return '<a href="/notificaciones/' + n.id + '/ir" class="block px-4 py-2.5 text-[11px] text-slate-300 hover:bg-slate-700/50 transition-colors ' + noLeidaClase + '">' +
                    puntoNoLeida + _escapeHtmlNotif(n.mensaje) +
                    '<div class="text-slate-500 font-mono text-[10px] mt-0.5">' + _escapeHtmlNotif(n.fecha) + '</div></a>';
            }).join('');
        })
        .catch(function () { /* silencioso: la campanita no debe romper la página si falla */ });
}

function marcarTodasLeidas() {
    // 🛡️ La app valida CSRF real en todo POST (ver CSRFProtect en app.py); esta llamada no
    // manda ningún <form>, así que el token va como header — si no, Flask-WTF la rechaza en
    // silencio (redirige) y el fetch la da por buena sin haber marcado nada como leído.
    var wrapper = document.getElementById('wrapper-notificaciones');
    var token = wrapper ? wrapper.getAttribute('data-csrf-token') : '';
    fetch('/notificaciones/marcar_todas_leidas', {
        method: 'POST',
        headers: { 'X-CSRFToken': token || '' }
    }).then(function () {
        cargarNotificaciones();
    });
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
            dd.classList.add('hidden');
        }
    });
});
