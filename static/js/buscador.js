// 🔍 Buscador global — compartido por todas las páginas autenticadas de Arkiv. Abre un modal
// con un campo de texto; a partir de 2 letras consulta /buscar/api?q=... (con "debounce" para
// no disparar una petición por cada tecla) y pinta los resultados agrupados por módulo. El
// backend ya filtra qué módulos puede ver cada rol — este archivo solo pinta lo que reciba.
// Categorías cubiertas hoy: Solicitudes TI, Comunicados, Base de Conocimiento, Gestor de
// Archivos, Bóveda de Accesos, Accesos de Colaboradores, Inventario de Activos, Proveedores,
// Plantillas de Solicitud, Vencimiento de Documentos, Certificación de Devoluciones y Usuarios.

var _buscadorGlobalTimeout = null;
var _buscadorGlobalUltimaConsulta = '';

function abrirBuscadorGlobal() {
    var modal = document.getElementById('modal-buscador-global');
    var input = document.getElementById('input-buscador-global');
    if (!modal || !input) return;
    modal.classList.remove('hidden');
    input.value = '';
    input.focus();
    var resultados = document.getElementById('resultados-buscador-global');
    if (resultados) {
        resultados.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-8">Escribe al menos 2 letras para buscar en Arkiv...</p>';
    }
}

function cerrarBuscadorGlobal() {
    var modal = document.getElementById('modal-buscador-global');
    if (!modal) return;
    modal.classList.add('hidden');
}

function _escapeHtmlBuscador(texto) {
    var div = document.createElement('div');
    div.textContent = texto || '';
    return div.innerHTML;
}

var _ICONOS_CATEGORIA_BUSCADOR = {
    'Solicitudes TI': 'fa-headset',
    'Comunicados': 'fa-bullhorn',
    'Base de Conocimiento': 'fa-book',
    'Gestor de Archivos': 'fa-folder-open',
    'Bóveda de Accesos': 'fa-key',
    'Accesos de Colaboradores': 'fa-user-shield',
    'Inventario de Activos': 'fa-boxes-stacked',
    'Proveedores': 'fa-truck-field',
    'Plantillas de Solicitud': 'fa-copy',
    'Vencimiento de Documentos': 'fa-calendar-days',
    'Certificación de Devoluciones': 'fa-rotate-left',
    'Usuarios': 'fa-users'
};

function _renderResultadosBuscadorGlobal(data) {
    var contenedor = document.getElementById('resultados-buscador-global');
    if (!contenedor) return;

    if (!data.resultados || !data.resultados.length) {
        contenedor.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-8">Sin resultados para "' + _escapeHtmlBuscador(data.q || '') + '".</p>';
        return;
    }

    var porCategoria = {};
    var orden = [];
    data.resultados.forEach(function (r) {
        if (!porCategoria[r.categoria]) {
            porCategoria[r.categoria] = [];
            orden.push(r.categoria);
        }
        porCategoria[r.categoria].push(r);
    });

    var html = orden.map(function (categoria) {
        var icono = _ICONOS_CATEGORIA_BUSCADOR[categoria] || 'fa-circle';
        var items = porCategoria[categoria].map(function (r) {
            var target = r.externo ? ' target="_blank" rel="noopener"' : '';
            return '<a href="' + r.url + '"' + target + ' class="block px-4 py-2.5 hover:bg-slate-800/70 transition-colors border-b border-slate-800/60">' +
                '<div class="text-sm text-white font-semibold truncate">' + _escapeHtmlBuscador(r.titulo) + '</div>' +
                (r.subtitulo ? '<div class="text-[11px] text-slate-500 truncate mt-0.5">' + _escapeHtmlBuscador(r.subtitulo) + '</div>' : '') +
                '</a>';
        }).join('');
        return '<div class="pt-2">' +
            '<div class="px-4 py-1.5 text-[10px] font-bold text-slate-500 uppercase tracking-wider flex items-center gap-1.5 bg-slate-900/80 sticky top-0"><i class="fa-solid ' + icono + '"></i>' + _escapeHtmlBuscador(categoria) + '</div>' +
            items + '</div>';
    }).join('');

    contenedor.innerHTML = html;
}

function _ejecutarBusquedaGlobal(q) {
    if (q === _buscadorGlobalUltimaConsulta) return;
    _buscadorGlobalUltimaConsulta = q;
    fetch('/buscar/api?q=' + encodeURIComponent(q))
        .then(function (r) { return r.json(); })
        .then(function (data) {
            // Si el usuario ya siguió escribiendo, esta respuesta quedó vieja: se ignora.
            var input = document.getElementById('input-buscador-global');
            if (input && input.value.trim().toLowerCase() !== q) return;
            _renderResultadosBuscadorGlobal(data);
        })
        .catch(function () {
            var contenedor = document.getElementById('resultados-buscador-global');
            if (contenedor) {
                contenedor.innerHTML = '<p class="text-rose-400 text-center text-[11px] py-8">No se pudo completar la búsqueda. Intenta de nuevo.</p>';
            }
        });
}

document.addEventListener('DOMContentLoaded', function () {
    var input = document.getElementById('input-buscador-global');
    if (input) {
        input.addEventListener('input', function () {
            var q = input.value.trim().toLowerCase();
            clearTimeout(_buscadorGlobalTimeout);
            if (q.length < 2) {
                _buscadorGlobalUltimaConsulta = '';
                var contenedor = document.getElementById('resultados-buscador-global');
                if (contenedor) {
                    contenedor.innerHTML = '<p class="text-slate-500 text-center text-[11px] py-8">Escribe al menos 2 letras para buscar en Arkiv...</p>';
                }
                return;
            }
            _buscadorGlobalTimeout = setTimeout(function () { _ejecutarBusquedaGlobal(q); }, 300);
        });
    }

    // Cierra el modal al hacer clic fuera del panel, o con la tecla ESC.
    document.addEventListener('click', function (evento) {
        var modal = document.getElementById('modal-buscador-global');
        var panel = document.getElementById('panel-buscador-global');
        var boton = document.getElementById('btn-buscador-global');
        if (!modal || modal.classList.contains('hidden')) return;
        if (panel && panel.contains(evento.target)) return;
        if (boton && boton.contains(evento.target)) return;
        cerrarBuscadorGlobal();
    });

    document.addEventListener('keydown', function (evento) {
        if (evento.key === 'Escape') {
            var modal = document.getElementById('modal-buscador-global');
            if (modal && !modal.classList.contains('hidden')) {
                cerrarBuscadorGlobal();
            }
        }
    });
});
