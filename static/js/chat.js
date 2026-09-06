// 💬 CHAT INTERNO — página /chat, solo admin/agente. Sigue el mismo patrón que
// notificaciones.js: sin WebSockets, la conversación abierta se refresca con fetch() cada
// pocos segundos (POLL_MENSAJES_MS) y la lista de contactos/badges cada un rato más largo
// (POLL_CONTACTOS_MS). El token CSRF viaja como header X-CSRFToken, igual que en la
// campanita, porque estas llamadas no mandan ningún <form>.

var POLL_MENSAJES_MS = 4000;
var POLL_CONTACTOS_MS = 15000;

var _chatActual = { tipo: 'canal', usuario: null, nombre: null };
var _chatUltimoId = 0;

// 🐛 Bug reportado por Tomás: al enviar un mensaje al Canal General, el propio remitente lo veía
// duplicado. Causa: al enviar, el propio enviarMensajeChat() pide los mensajes nuevos (desde_id)
// Y, casi al mismo tiempo, tiempo_real.js recibe el 'empujón' del socket (el remitente también
// está en la sala del canal) y pide los mismos mensajes nuevos otra vez — dos fetch() en
// paralelo pueden llegar los dos con el mismo mensaje antes de que _chatUltimoId se actualice.
// Este set recuerda qué ids YA se pintaron en la conversación abierta, sin importar por cuál de
// los dos caminos llegaron, para nunca pintar el mismo mensaje dos veces.
var _idsMensajesRenderizadosChat = {};

// 📎 Adjunto multimedia (pedido por Tomás): imagen o archivo elegido con el clip, o pegado
// directo desde el portapapeles (Ctrl+V de una captura de pantalla, por ejemplo). Un solo
// adjunto pendiente a la vez, igual que WhatsApp/Slack — se manda junto con el mensaje (o
// solo, si no se escribió texto) y se limpia apenas se envía o se cambia de conversación.
var _adjuntoChatSeleccionado = null;
var TAMANO_MAXIMO_ADJUNTO_CHAT_MB = 25;

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

// 🛡️ _escapeHtmlChat no basta para meter texto dinámico DENTRO de un atributo entre comillas
// dobles (no escapa " ni ') — hace falta para el nombre del adjunto en alt="..." (el nombre
// original del archivo lo elige quien lo sube, no es texto de confianza).
function _escapeAtributoChat(texto) {
    return _escapeHtmlChat(texto).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
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

function abrirDirecto(usuario, nombre, foto) {
    _chatActual = { tipo: 'directo', usuario: usuario, nombre: nombre };
    _chatUltimoId = 0;
    document.getElementById('titulo-conversacion-chat').textContent = nombre;
    document.getElementById('subtitulo-conversacion-chat').textContent = 'Conversación privada';
    // 🖼️ Foto de perfil (pedido por Tomás): si la persona subió una desde /perfil, se usa esa
    // en vez de la inicial — mismo criterio que el avatar de la lista de contactos.
    var iconoTitulo = document.getElementById('icono-titulo-chat');
    if (foto) {
        iconoTitulo.innerHTML = '<img src="' + _escapeAtributoChat(foto) + '" alt="" class="w-full h-full object-cover">';
    } else {
        iconoTitulo.textContent = (nombre || '?').slice(0, 1).toUpperCase();
    }
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
    _idsMensajesRenderizadosChat = {}; // nueva conversación: ningún mensaje pintado todavía
    _quitarAdjuntoChat(); // un adjunto pendiente no debe viajar a la conversación nueva
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

// 📎 Pinta el adjunto de un mensaje (si trae uno): miniatura clicable si es imagen, o una
// tarjeta genérica con el nombre del archivo — mismo patrón que ya usan los adjuntos de
// tickets (ver templates/ticket_detalle.html).
function _adjuntoHtmlChat(m) {
    if (!m.adjunto_url) return '';
    if (m.adjunto_es_imagen) {
        return '<a href="' + _escapeAtributoChat(m.adjunto_url) + '" target="_blank" rel="noopener" class="block mt-1.5">' +
            '<img src="' + _escapeAtributoChat(m.adjunto_url) + '" alt="' + _escapeAtributoChat(m.adjunto_nombre || 'imagen') + '" ' +
            'class="max-w-[220px] max-h-[220px] rounded-xl border border-slate-700/60 object-cover">' +
            '</a>';
    }
    return '<a href="' + _escapeAtributoChat(m.adjunto_url) + '" target="_blank" rel="noopener" ' +
        'class="flex items-center gap-2 mt-1.5 bg-slate-900/40 border border-slate-700/60 rounded-xl px-3 py-2 text-[11px]">' +
        '<i class="fa-solid fa-file-lines"></i>' +
        '<span class="max-w-[10rem] truncate">' + _escapeHtmlChat(m.adjunto_nombre || 'Archivo') + '</span>' +
        '<i class="fa-solid fa-arrow-up-right-from-square text-[9px] opacity-70"></i></a>';
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
    // Un mensaje puede traer solo adjunto (sin texto) — nunca los dos vacíos, el servidor no lo permite.
    var textoMensaje = m.mensaje ? _escapeHtmlChat(m.mensaje) : '';
    return '<div class="' + base + ' ' + (m.es_mio ? clasePropia : claseAjena) + '">' +
        nombreLinea + textoMensaje + _adjuntoHtmlChat(m) +
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
                _chatUltimoId = Math.max(_chatUltimoId, m.id);
                if (_idsMensajesRenderizadosChat[m.id]) return; // ya pintado (ver comentario arriba)
                _idsMensajesRenderizadosChat[m.id] = true;
                lista.insertAdjacentHTML('beforeend', _burbujaMensajeChat(m));
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
    if (!mensaje && !_adjuntoChatSeleccionado) return false; // ni texto ni adjunto: nada que mandar
    _chatEnviando = true;
    var errorDiv = document.getElementById('error-chat');
    errorDiv.classList.add('hidden');

    // FormData (no urlencoded) desde que se puede mandar un archivo — el navegador arma el
    // 'Content-Type: multipart/form-data' con su boundary solo, no hay que ponerlo a mano.
    var datosFormulario = new FormData();
    datosFormulario.append('mensaje', mensaje);
    if (_adjuntoChatSeleccionado) datosFormulario.append('adjunto', _adjuntoChatSeleccionado);

    fetch(_urlEnviarActual(), {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenChat() },
        body: datosFormulario
    })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            _chatEnviando = false;
            if (data && data.success) {
                input.value = '';
                input.style.height = 'auto';
                _quitarAdjuntoChat();
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

// 📎 Elegir un archivo con el clip (input[type=file] oculto, ver chat.html).
function _seleccionarAdjuntoChat(evento) {
    var archivo = evento.target.files && evento.target.files[0];
    if (archivo) _fijarAdjuntoChat(archivo);
}

// 📋 Pegar una imagen copiada (captura de pantalla, "Copiar imagen" de otra página, etc.)
// directo en el cuadro de texto — pedido por Tomás. Si el portapapeles trae una imagen se
// adjunta igual que con el clip; si lo que se pega es texto normal, se deja que el navegador
// lo pegue como siempre (no se cancela el evento en ese caso).
function _pegarEnMensajeChat(evento) {
    var items = (evento.clipboardData && evento.clipboardData.items) || [];
    for (var i = 0; i < items.length; i++) {
        if (items[i].type && items[i].type.indexOf('image/') === 0) {
            var archivo = items[i].getAsFile();
            if (archivo) {
                evento.preventDefault();
                _fijarAdjuntoChat(archivo);
            }
            return;
        }
    }
}

function _fijarAdjuntoChat(archivo) {
    var errorDiv = document.getElementById('error-chat');
    if (archivo.size > TAMANO_MAXIMO_ADJUNTO_CHAT_MB * 1024 * 1024) {
        if (errorDiv) {
            errorDiv.textContent = 'El archivo no puede superar ' + TAMANO_MAXIMO_ADJUNTO_CHAT_MB + ' MB.';
            errorDiv.classList.remove('hidden');
        }
        return;
    }
    if (errorDiv) errorDiv.classList.add('hidden');
    _adjuntoChatSeleccionado = archivo;
    var previsualizacion = document.getElementById('previsualizacion-adjunto-chat');
    var nombreSpan = document.getElementById('nombre-adjunto-chat');
    if (nombreSpan) nombreSpan.textContent = archivo.name || 'Archivo adjunto';
    if (previsualizacion) previsualizacion.classList.remove('hidden');
}

function _quitarAdjuntoChat() {
    _adjuntoChatSeleccionado = null;
    var previsualizacion = document.getElementById('previsualizacion-adjunto-chat');
    if (previsualizacion) previsualizacion.classList.add('hidden');
    var inputArchivo = document.getElementById('input-adjunto-chat');
    if (inputArchivo) inputArchivo.value = '';
}

// 🔎 Buscador de conversaciones (pedido por Tomás): filtra en el momento la barra lateral por
// nombre o usuario, sin golpear al servidor — los contactos ya están todos en el DOM desde que
// cargó la página (con quién se puede chatear no cambia a cada rato), así que basta con
// mostrar/ocultar. Se ignoran tildes/mayúsculas para que "jose" encuentre "José".
function _normalizarBusquedaChat(texto) {
    return (texto || '').toString().toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

// 🟢🔴 Filtro por estado (pedido por Tomás): 'todos' | 'en_linea' | 'desconectado'. Se combina
// con el buscador de texto (ambos criterios deben cumplirse) — ver filtrarContactosChat().
var _filtroEstadoChatActual = 'todos';

function filtrarPorEstadoChat(estado) {
    _filtroEstadoChatActual = estado;
    document.querySelectorAll('.btn-filtro-estado-chat').forEach(function (btn) {
        var activo = btn.getAttribute('data-estado') === estado;
        btn.classList.toggle('bg-sky-600', activo);
        btn.classList.toggle('text-white', activo);
        btn.classList.toggle('bg-slate-800', !activo);
        btn.classList.toggle('text-slate-400', !activo);
    });
    filtrarContactosChat();
}

function filtrarContactosChat() {
    var input = document.getElementById('buscar-chat-contactos');
    var consulta = _normalizarBusquedaChat(input ? input.value : '').trim();

    var itemCanal = document.getElementById('item-canal-general');
    if (itemCanal) {
        // El Canal General no es una persona (no tiene estado en línea/desconectado), así que
        // solo se filtra por el buscador de texto, nunca por el filtro de estado.
        var coincideCanal = !consulta || _normalizarBusquedaChat('Canal General').indexOf(consulta) !== -1;
        itemCanal.classList.toggle('hidden', !coincideCanal);
    }

    var algunoVisible = false;
    document.querySelectorAll('.item-contacto-chat').forEach(function (el) {
        var usuario = _normalizarBusquedaChat(el.getAttribute('data-usuario'));
        var nombre = _normalizarBusquedaChat(el.getAttribute('data-nombre'));
        var coincideTexto = !consulta || usuario.indexOf(consulta) !== -1 || nombre.indexOf(consulta) !== -1;
        var enLinea = el.getAttribute('data-en-linea') === 'true';
        var coincideEstado = _filtroEstadoChatActual === 'todos' ||
            (_filtroEstadoChatActual === 'en_linea' && enLinea) ||
            (_filtroEstadoChatActual === 'desconectado' && !enLinea);
        var coincide = coincideTexto && coincideEstado;
        el.classList.toggle('hidden', !coincide);
        if (coincide) algunoVisible = true;
    });

    var hayFiltroActivo = !!consulta || _filtroEstadoChatActual !== 'todos';
    var sinResultados = document.getElementById('mensaje-sin-resultados-chat');
    if (sinResultados) sinResultados.classList.toggle('hidden', !hayFiltroActivo || algunoVisible);
}

// 📌 Deja los contactos anclados siempre arriba de todo (sort estable: no altera el orden
// relativo entre anclados entre sí, ni entre el resto de contactos entre sí).
function _reordenarContactosChatPorAnclado() {
    var contenedor = document.getElementById('lista-contactos-chat');
    if (!contenedor) return;
    var items = Array.prototype.slice.call(contenedor.querySelectorAll('.item-contacto-chat'));
    items.sort(function (a, b) {
        var ap = a.getAttribute('data-anclado') === 'true';
        var bp = b.getAttribute('data-anclado') === 'true';
        if (ap === bp) return 0;
        return ap ? -1 : 1;
    });
    items.forEach(function (el) { contenedor.appendChild(el); });
}

function _pintarBotonFavoritoChat(boton, activo) {
    var icono = boton.querySelector('i');
    if (icono) {
        icono.classList.toggle('fa-solid', activo);
        icono.classList.toggle('fa-regular', !activo);
    }
    boton.classList.toggle('text-amber-400', activo);
    boton.classList.toggle('text-slate-600', !activo);
    boton.title = activo ? 'Quitar de favoritos' : 'Marcar como favorito';
}

function _pintarBotonAncladoChat(boton, activo) {
    boton.classList.toggle('text-sky-400', activo);
    boton.classList.toggle('text-slate-600', !activo);
    boton.title = activo ? 'Desanclar' : 'Anclar arriba';
}

function _enviarPreferenciaChat(contacto, tipo, valor) {
    var datos = new FormData();
    datos.append('contacto', contacto);
    datos.append('tipo', tipo);
    datos.append('valor', valor ? '1' : '0');
    fetch('/chat/contactos/preferencia', {
        method: 'POST',
        headers: { 'X-CSRFToken': _csrfTokenChat() },
        body: datos
    }).catch(function () { /* silencioso: si falla, el próximo poll corrige el estado visual */ });
}

// ⭐ Favorito (pedido por Tomás): preferencia personal, no reordena la lista — solo marca.
function alternarFavoritoChat(boton, contacto) {
    var item = boton.closest('.item-contacto-chat');
    var activo = !(item && item.getAttribute('data-favorito') === 'true');
    if (item) item.setAttribute('data-favorito', activo ? 'true' : 'false');
    _pintarBotonFavoritoChat(boton, activo);
    _enviarPreferenciaChat(contacto, 'favorito', activo);
}

// 📌 Anclado (pedido por Tomás): preferencia personal, y SÍ reordena — el contacto anclado
// sube de inmediato al tope de la lista, sin esperar al próximo sondeo.
function alternarAncladoChat(boton, contacto) {
    var item = boton.closest('.item-contacto-chat');
    var activo = !(item && item.getAttribute('data-anclado') === 'true');
    if (item) {
        item.setAttribute('data-anclado', activo ? 'true' : 'false');
        var iconoInline = item.querySelector('.icono-anclado-inline-chat');
        if (iconoInline) iconoInline.classList.toggle('hidden', !activo);
    }
    _pintarBotonAncladoChat(boton, activo);
    _reordenarContactosChatPorAnclado();
    _enviarPreferenciaChat(contacto, 'anclado', activo);
}

// 🟢 Pop-up "fulano se conectó" (pedido por Tomás): se dispara comparando, en cada sondeo de
// /chat/contactos, el 'en_linea' de ahora contra el de la vuelta anterior. 'null' significa
// "todavía no hay una foto anterior" (justo después de cargar la página) — a propósito no se
// avisa nada en esa primera vuelta, o parecería que TODO el equipo se acaba de conectar.
var _estadoEnLineaPrevioChat = null;

function _mostrarPopupConexionChat(nombre) {
    var contenedor = document.getElementById('contenedor-popups-conexion-chat');
    if (!contenedor) return;
    var aviso = document.createElement('div');
    aviso.className = 'pointer-events-auto flex items-center gap-2 bg-slate-800 border border-emerald-500/30 text-white text-xs font-semibold px-3.5 py-2.5 rounded-xl shadow-lg shadow-slate-950/40';
    aviso.style.cssText = 'opacity:0; transform:translateY(-6px); transition: opacity .2s ease, transform .2s ease;';
    aviso.innerHTML = '<span class="w-2 h-2 rounded-full bg-emerald-400 flex-shrink-0"></span><span>' + _escapeHtmlChat(nombre) + ' se conectó</span>';
    contenedor.appendChild(aviso);
    requestAnimationFrame(function () {
        aviso.style.opacity = '1';
        aviso.style.transform = 'translateY(0)';
    });
    setTimeout(function () {
        aviso.style.opacity = '0';
        setTimeout(function () { if (aviso.parentNode) aviso.parentNode.removeChild(aviso); }, 250);
    }, 4500);
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

            var estadoEnLineaAhora = {};
            (data.contactos || []).forEach(function (c) {
                estadoEnLineaAhora[c.usuario] = !!c.en_linea;
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
                // 🟢🔴 En línea/desconectado: se recalcula en el servidor en cada respuesta de
                // /chat/contactos (ver _esta_en_linea en app.py), así que basta con reflejar
                // aquí el valor más reciente de 'c.en_linea'.
                var dot = el.querySelector('.dot-en-linea-contacto-chat');
                if (dot) {
                    dot.classList.toggle('bg-emerald-400', !!c.en_linea);
                    dot.classList.toggle('bg-rose-500', !c.en_linea);
                    dot.title = c.en_linea ? 'En línea' : 'Desconectado';
                }
                el.setAttribute('data-en-linea', c.en_linea ? 'true' : 'false');
                // ⭐📌 Favorito/anclado: igual que el resto de esta lista, el servidor manda el
                // valor más reciente de las preferencias personales de quien tiene sesión.
                el.setAttribute('data-favorito', c.favorito ? 'true' : 'false');
                el.setAttribute('data-anclado', c.anclado ? 'true' : 'false');
                var btnFav = el.querySelector('.btn-favorito-chat');
                if (btnFav) _pintarBotonFavoritoChat(btnFav, !!c.favorito);
                var btnPin = el.querySelector('.btn-anclado-chat');
                if (btnPin) _pintarBotonAncladoChat(btnPin, !!c.anclado);
                var iconoInline = el.querySelector('.icono-anclado-inline-chat');
                if (iconoInline) iconoInline.classList.toggle('hidden', !c.anclado);
            });

            _reordenarContactosChatPorAnclado();
            filtrarContactosChat();

            // 🟢 Pop-up de conexión: compara contra la foto del sondeo anterior (ver comentario
            // en _estadoEnLineaPrevioChat) y avisa por cada contacto que pasó de desconectado a
            // en línea — para CUALQUIER contacto, no solo favoritos/anclados (pedido por Tomás).
            if (_estadoEnLineaPrevioChat) {
                Object.keys(estadoEnLineaAhora).forEach(function (usuario) {
                    if (estadoEnLineaAhora[usuario] && _estadoEnLineaPrevioChat[usuario] === false) {
                        var elContacto = document.querySelector('.item-contacto-chat[data-usuario="' + usuario + '"]');
                        _mostrarPopupConexionChat(elContacto ? elContacto.getAttribute('data-nombre') : usuario);
                    }
                });
            }
            _estadoEnLineaPrevioChat = estadoEnLineaAhora;
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
