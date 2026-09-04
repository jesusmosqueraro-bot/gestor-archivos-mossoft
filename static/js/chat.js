// 💬 CHAT INTERNO — página /chat, solo admin/agente. Sigue el mismo patrón que
// notificaciones.js: sin WebSockets, la conversación abierta se refresca con fetch() cada
// pocos segundos (POLL_MENSAJES_MS) y la lista de contactos/badges cada un rato más largo
// (POLL_CONTACTOS_MS). El token CSRF viaja como header X-CSRFToken, igual que en la
// campanita, porque estas llamadas no mandan ningún <form>.

var POLL_MENSAJES_MS = 4000;
var POLL_CONTACTOS_MS = 15000;

var _chatActual = { tipo: 'canal', usuario: null, nombre: null };
var _chatUltimoId = 0;

function _wrapperChat() {
    return document.getElementById('wrapper-chat');
}

function _csrfTokenChat() {
    var w = _wrapperChat();
    return w ? (w.getAttribute('data-csrf-token') || '') : '';
}

function _escapeHtmlChat(texto) {
    var div = document.createElement('div');
    div.textContent = texto || '';
    return div.innerHTML;
}

function _urlMensajesActual() {
    if (_chatActual.tipo === 'canal') return '/chat/canal/mensajes';
    return '/chat/directo/' + encodeURIComponent(_chatActual.usuario) + '/mensajes';
}

function _urlEnviarActual() {
    if (_chatActual.tipo === 'canal') return '/chat/canal/enviar';
    return '/chat/directo/' + encodeURIComponent(_chatActual.usuario) + '/enviar';
}

function abrirCanalGeneral() {
    _chatActual = { tipo: 'canal', usuario: null, nombre: null };
    _chatUltimoId = 0;
    document.getElementById('titulo-conversacion-chat').textContent = 'Canal General';
    document.getElementById('subtitulo-conversacion-chat').textContent = 'Todo el equipo con acceso operativo';
    document.getElementById('icono-titulo-chat').innerHTML = '<i class="fa-solid fa-users"></i>';
    _marcarContactoActivoChat(null);
    _limpiarMensajesChat();
    _mostrarPanelMensajesMovilChat();
    cargarMensajesChat(true);
    cargarContactosChat();
}

function abrirDirecto(usuario, nombre) {
    _chatActual = { tipo: 'directo', usuario: usuario, nombre: nombre };
    _chatUltimoId = 0;
    document.getElementById('titulo-conversacion-chat').textContent = nombre;
    document.getElementById('subtitulo-conversacion-chat').textContent = 'Conversación privada';
    document.getElementById('icono-titulo-chat').textContent = (nombre || '?').slice(0, 1).toUpperCase();
    _marcarContactoActivoChat(usuario);
    _limpiarMensajesChat();
    _mostrarPanelMensajesMovilChat();
    cargarMensajesChat(true);
    cargarContactosChat();
}

function _marcarContactoActivoChat(usuario) {
    var itemCanal = document.getElementById('item-canal-general');
    if (itemCanal) itemCanal.classList.toggle('bg-sky-500/10', !usuario);
    document.querySelectorAll('.item-contacto-chat').forEach(function (el) {
        el.classList.toggle('bg-sky-500/10', el.getAttribute('data-usuario') === usuario);
    });
}

function _limpiarMensajesChat() {
    var lista = document.getElementById('lista-mensajes-chat');
    if (!lista) return;
    lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">Cargando...</p>';
    var errorDiv = document.getElementById('error-chat');
    if (errorDiv) errorDiv.classList.add('hidden');
}

function _mostrarPanelMensajesMovilChat() {
    if (window.innerWidth >= 640) return; // en sm: hacia arriba ya se ven ambos paneles a la vez
    var panelLista = document.getElementById('panel-lista-chat');
    var panelMensajes = document.getElementById('panel-mensajes-chat');
    if (panelLista) panelLista.classList.add('hidden');
    if (panelMensajes) {
        panelMensajes.classList.remove('hidden');
        panelMensajes.classList.add('flex');
    }
}

function _volverListaChatMovil() {
    var panelLista = document.getElementById('panel-lista-chat');
    var panelMensajes = document.getElementById('panel-mensajes-chat');
    if (panelLista) panelLista.classList.remove('hidden');
    if (panelMensajes) {
        panelMensajes.classList.add('hidden');
        panelMensajes.classList.remove('flex');
    }
}

function _burbujaMensajeChat(m) {
    // 🐛 w-fit es necesario para que ml-auto funcione: un <div> de bloque normal ocupa todo el
    // ancho disponible (margin-left:auto no tendría "espacio libre" que empujar), así que sin
    // w-fit las burbujas propias se ven pegadas a la izquierda igual que las ajenas.
    var base = 'w-fit max-w-[75%] px-3.5 py-2 rounded-2xl text-sm leading-relaxed whitespace-pre-wrap break-words';
    var clasePropia = 'ml-auto bg-sky-600 text-white rounded-br-sm';
    var claseAjena = 'bg-slate-800 text-slate-100 rounded-bl-sm';
    var nombreLinea = (!m.es_mio && m.remitente_nombre)
        ? '<div class="text-[10px] font-bold text-sky-400 mb-0.5">' + _escapeHtmlChat(m.remitente_nombre) + '</div>'
        : '';
    return '<div class="' + base + ' ' + (m.es_mio ? clasePropia : claseAjena) + '">' +
        nombreLinea + _escapeHtmlChat(m.mensaje) +
        '<div class="text-[9px] mt-1 ' + (m.es_mio ? 'text-sky-100/70' : 'text-slate-500') + ' font-mono">' +
        _escapeHtmlChat(m.fecha) + '</div></div>';
}

function cargarMensajesChat(esCargaInicial) {
    var conversacionAlPedir = _chatActual.tipo + ':' + (_chatActual.usuario || '');
    fetch(_urlMensajesActual() + '?desde_id=' + (esCargaInicial ? 0 : _chatUltimoId))
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // Si mientras esta respuesta viajaba el usuario abrió otra conversación, se
            // descarta — si no, estos mensajes aparecerían pegados a la conversación nueva.
            if ((_chatActual.tipo + ':' + (_chatActual.usuario || '')) !== conversacionAlPedir) return;
            var lista = document.getElementById('lista-mensajes-chat');
            if (!lista) return;
            var mensajes = data.mensajes || [];
            if (esCargaInicial) {
                lista.innerHTML = '';
                if (!mensajes.length) {
                    lista.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">Todavía no hay mensajes. ¡Escribe el primero!</p>';
                }
            } else if (!mensajes.length) {
                return; // nada nuevo desde el último poll
            } else if (lista.querySelector('p')) {
                lista.innerHTML = ''; // quita el "Todavía no hay mensajes..." / "Cargando..."
            }
            var estabaAbajo = (lista.scrollHeight - lista.scrollTop - lista.clientHeight) < 80;
            mensajes.forEach(function (m) {
                lista.insertAdjacentHTML('beforeend', _burbujaMensajeChat(m));
                _chatUltimoId = Math.max(_chatUltimoId, m.id);
            });
            if (esCargaInicial || estabaAbajo) {
                lista.scrollTop = lista.scrollHeight;
            }
        })
        .catch(function () { /* silencioso: un fallo de red no debe interrumpir el chat */ });
}

function _teclaMensajeChat(evento) {
    if (evento.key === 'Enter' && !evento.shiftKey) {
        evento.preventDefault();
        var form = document.getElementById('form-enviar-chat');
        if (form.requestSubmit) form.requestSubmit(); else form.dispatchEvent(new Event('submit', { cancelable: true }));
        return false;
    }
    return true;
}

var _chatEnviando = false;

function enviarMensajeChat(evento) {
    if (evento) evento.preventDefault();
    if (_chatEnviando) return false;
    var input = document.getElementById('input-mensaje-chat');
    var mensaje = (input.value || '').trim();
    if (!mensaje) return false;
    _chatEnviando = true;
    var errorDiv = document.getElementById('error-chat');
    errorDiv.classList.add('hidden');

    fetch(_urlEnviarActual(), {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenChat(), 'Content-Type': 'application/x-www-form-urlencoded' },
        body: 'mensaje=' + encodeURIComponent(mensaje)
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _chatEnviando = false;
            if (data && data.success) {
                input.value = '';
                input.style.height = 'auto';
                cargarMensajesChat(false);
                cargarContactosChat();
            } else {
                errorDiv.textContent = (data && data.error) || 'No se pudo enviar el mensaje.';
                errorDiv.classList.remove('hidden');
            }
        })
        .catch(function () {
            _chatEnviando = false;
            errorDiv.textContent = 'No se pudo enviar el mensaje. Revisa tu conexión.';
            errorDiv.classList.remove('hidden');
        });
    return false;
}

function cargarContactosChat() {
    fetch('/chat/contactos')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            var badgeCanal = document.getElementById('badge-canal-general');
            if (badgeCanal) {
                var noLeidosCanal = _chatActual.tipo === 'canal' ? 0 : (data.canal_no_leidos || 0);
                if (noLeidosCanal > 0) {
                    badgeCanal.textContent = noLeidosCanal > 99 ? '99+' : noLeidosCanal;
                    badgeCanal.classList.remove('hidden');
                } else {
                    badgeCanal.classList.add('hidden');
                }
            }

            (data.contactos || []).forEach(function (c) {
                var el = document.querySelector('.item-contacto-chat[data-usuario="' + c.usuario + '"]');
                if (!el) return;
                var previsualizacion = el.querySelector('.previsualizacion-contacto-chat');
                if (previsualizacion && c.ultimo_mensaje) {
                    previsualizacion.textContent = c.ultimo_mensaje.length > 40 ? c.ultimo_mensaje.slice(0, 40) + '…' : c.ultimo_mensaje;
                }
                var badge = el.querySelector('.badge-contacto-chat');
                var noLeidos = (_chatActual.tipo === 'directo' && _chatActual.usuario === c.usuario) ? 0 : (c.no_leidos || 0);
                if (badge) {
                    if (noLeidos > 0) {
                        badge.textContent = noLeidos > 99 ? '99+' : noLeidos;
                        badge.classList.remove('hidden');
                    } else {
                        badge.classList.add('hidden');
                    }
                }
            });
        })
        .catch(function () { /* silencioso */ });
}

document.addEventListener('DOMContentLoaded', function () {
    var wrapper = _wrapperChat();
    if (!wrapper) return;

    var conInicial = wrapper.getAttribute('data-con-inicial');
    var abierto = false;
    if (conInicial) {
        var el = document.querySelector('.item-contacto-chat[data-usuario="' + conInicial + '"]');
        if (el) {
            el.click();
            abierto = true;
        }
    }
    if (!abierto) {
        abrirCanalGeneral();
    }

    setInterval(function () { cargarMensajesChat(false); }, POLL_MENSAJES_MS);
    setInterval(cargarContactosChat, POLL_CONTACTOS_MS);

    var input = document.getElementById('input-mensaje-chat');
    if (input) {
        input.addEventListener('input', function () {
            input.style.height = 'auto';
            input.style.height = Math.min(input.scrollHeight, 140) + 'px';
        });
    }
});
