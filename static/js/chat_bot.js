// 🤖 Asistente de Chat guiado por menú (usuarios estándar) — ver módulo "ASISTENTE DE CHAT
// GUIADO POR MENÚ" en app.py (chat_pagina, chat_bot_estado, chat_bot_enviar, chat_bot_reiniciar).
// A diferencia de chat.js (chat.html, persona a persona), aquí no hay contactos ni canal: solo
// una conversación con el bot, que este script sondea (POLL_ESTADO_BOT_MS) y refresca en
// pantalla. El token CSRF viaja como header X-CSRFToken, igual que en chat.js.

const POLL_ESTADO_BOT_MS = 10000;
let _ultimoIdMensajeBot = 0;
let _enviandoMensajeBot = false;
let _pollBotIntervalo = null;

function _csrfTokenBot() {
    const w = document.getElementById('wrapper-chat-bot');
    return w ? (w.getAttribute('data-csrf-token') || '') : '';
}

function _escaparHtmlBot(texto) {
    const div = document.createElement('div');
    div.textContent = texto == null ? '' : String(texto);
    return div.innerHTML;
}

// Escapado para un valor puesto directamente en un atributo HTML (ej. alt="...").
function _escaparAtributoBot(texto) {
    return (texto == null ? '' : String(texto))
        .replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

// 🖼️ Pedido de Tomás (07/09/2026): los comentarios del ticket escalado (ver
// _bot_transcripcion_ticket en app.py) ahora traen también su lista de adjuntos — antes solo
// llegaba el texto de relleno "(adjuntó archivo(s) sin comentario)" y la imagen (p. ej. una
// firma) nunca se veía aquí, aunque sí se veía en Mesa de Ayuda. Mismo criterio imagen/archivo
// que ya usa ticket_detalle.html.
function _renderAdjuntosBot(adjuntos) {
    if (!adjuntos || !adjuntos.length) return '';
    return `<div class="flex flex-wrap gap-2 mt-2">${adjuntos.map(a => {
        if (a.es_imagen) {
            return `<a href="${_escaparAtributoBot(a.url)}" target="_blank" rel="noopener" class="block">
                <img src="${_escaparAtributoBot(a.url)}" alt="${_escaparAtributoBot(a.nombre_original)}" class="h-20 w-20 object-cover rounded-xl border border-slate-700">
            </a>`;
        }
        return `<a href="${_escaparAtributoBot(a.url)}" target="_blank" rel="noopener" class="flex items-center gap-2 bg-slate-950/40 border border-slate-700 rounded-xl px-3 py-2 text-[11px] transition-all">
            <i class="fa-solid fa-file-lines"></i>
            <span class="max-w-[10rem] truncate">${_escaparHtmlBot(a.nombre_original)}</span>
        </a>`;
    }).join('')}</div>`;
}

function _pintarMensajesBot(mensajes) {
    const cont = document.getElementById('lista-mensajes-bot');
    if (!cont) return;
    if (!mensajes || !mensajes.length) {
        cont.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-6">Cargando...</p>';
        return;
    }
    const estabaAbajo = (cont.scrollTop + cont.clientHeight) >= (cont.scrollHeight - 40);
    cont.innerHTML = mensajes.map(m => {
        const esBot = m.autor === 'bot';
        return `<div class="flex ${esBot ? 'justify-start' : 'justify-end'}">
            <div class="max-w-[85%] sm:max-w-[70%] px-4 py-2.5 rounded-2xl text-sm burbuja-bot ${esBot ? 'bg-slate-800 text-slate-100 rounded-bl-sm' : 'bg-sky-600 text-white rounded-br-sm'}">
                ${_escaparHtmlBot(m.mensaje)}
                ${_renderAdjuntosBot(m.adjuntos)}
            </div>
        </div>`;
    }).join('');

    const ultimo = mensajes[mensajes.length - 1];
    const cajaOpciones = document.getElementById('opciones-rapidas-bot');
    if (cajaOpciones) {
        if (ultimo && ultimo.autor === 'bot' && ultimo.opciones && ultimo.opciones.length) {
            cajaOpciones.innerHTML = ultimo.opciones.map((op, i) =>
                `<button type="button" onclick="_elegirOpcionRapidaBot(${i + 1})"
                    class="px-3 py-1.5 bg-slate-800 hover:bg-sky-600 border border-slate-700 hover:border-sky-500 text-slate-200 hover:text-white text-xs rounded-xl transition-all">
                    ${i + 1}. ${_escaparHtmlBot(op)}
                </button>`
            ).join('');
            cajaOpciones.classList.remove('hidden');
        } else {
            cajaOpciones.innerHTML = '';
            cajaOpciones.classList.add('hidden');
        }
    }

    _ultimoIdMensajeBot = mensajes[mensajes.length - 1].id || _ultimoIdMensajeBot;
    if (estabaAbajo) cont.scrollTop = cont.scrollHeight;
}

function _mostrarErrorBot(msg) {
    const el = document.getElementById('error-chat-bot');
    if (!el) return;
    el.textContent = msg;
    el.classList.remove('hidden');
}

function _elegirOpcionRapidaBot(numero) {
    const input = document.getElementById('input-mensaje-bot');
    if (!input) return;
    input.value = String(numero);
    document.getElementById('form-enviar-bot').requestSubmit();
}

async function _consultarEstadoBot() {
    try {
        const resp = await fetch('/chat/bot/estado', { headers: { 'X-CSRFToken': _csrfTokenBot() } });
        if (!resp.ok) {
            const data = await resp.json().catch(() => ({}));
            _mostrarErrorBot(data.error || 'El Asistente de Chat no está disponible en este momento.');
            if (_pollBotIntervalo) clearInterval(_pollBotIntervalo);
            return;
        }
        const data = await resp.json();
        _pintarMensajesBot(data.mensajes);
    } catch (e) {
        _mostrarErrorBot('No se pudo conectar con el Asistente. Verifica tu conexión.');
    }
}

async function enviarMensajeBot(event) {
    event.preventDefault();
    if (_enviandoMensajeBot) return false;
    const input = document.getElementById('input-mensaje-bot');
    const texto = (input.value || '').trim();
    if (!texto) return false;
    _enviandoMensajeBot = true;
    input.value = '';
    try {
        const resp = await fetch('/chat/bot/enviar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': _csrfTokenBot() },
            body: `mensaje=${encodeURIComponent(texto)}`,
        });
        const data = await resp.json();
        if (!resp.ok) {
            _mostrarErrorBot(data.error || 'No se pudo enviar el mensaje.');
        } else {
            _pintarMensajesBot(data.mensajes);
        }
    } catch (e) {
        _mostrarErrorBot('No se pudo enviar el mensaje. Verifica tu conexión.');
    } finally {
        _enviandoMensajeBot = false;
    }
    return false;
}

async function reiniciarConversacionBot() {
    if (!confirm('¿Iniciar una conversación nueva? Se volverá a mostrar el menú principal.')) return;
    try {
        const resp = await fetch('/chat/bot/reiniciar', {
            method: 'POST',
            headers: { 'X-CSRFToken': _csrfTokenBot() },
        });
        const data = await resp.json();
        if (resp.ok) _pintarMensajesBot(data.mensajes);
    } catch (e) {
        _mostrarErrorBot('No se pudo reiniciar la conversación.');
    }
}

function _teclaMensajeBot(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        document.getElementById('form-enviar-bot').requestSubmit();
        return false;
    }
    return true;
}

document.addEventListener('DOMContentLoaded', () => {
    if (!document.getElementById('wrapper-chat-bot')) return;
    _consultarEstadoBot();
    _pollBotIntervalo = setInterval(_consultarEstadoBot, POLL_ESTADO_BOT_MS);
});
