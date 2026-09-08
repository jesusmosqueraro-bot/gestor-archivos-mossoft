// 🪪 Autocompletar de persona (nombre/usuario/cédula) — pedido por Tomás (08/09/2026): "al
// ingresar el número de documento, empiece a buscar y mostrar los similares, algo como
// autocompletar (...) y que sea así para todos los campos en los que se pueda filtrar por
// cédula (...) y lo mismo si se desea buscar por nombre". Antes de esto, cada pantalla que
// necesitaba "buscar un colaborador ya registrado en Arkiv" (Inventario, Altas de Credenciales,
// Bóveda Personal del super-admin) tenía su propia copia del mismo fetch + debounce + lista de
// sugerencias — este archivo lo deja en un solo lugar reutilizable, consultando siempre
// /usuarios/buscar (coincidencia parcial por nombre, usuario o cédula).
//
// Uso: activarAutocompletarPersona({
//     inputId: 'id del <input> de texto donde se escribe',
//     listaId: 'id de un <div> vacío (idealmente position:relative en el padre) donde se pinta
//               la lista de sugerencias',
//     onSeleccionar: function(persona) { ... },  // persona = {usuario, nombre, cedula, firma}
//     minLength: 2  // opcional, mínimo de caracteres para empezar a buscar (por defecto 2)
// });
// El campo de texto sigue siendo libre: si la persona no aparece en las sugerencias (porque no
// tiene cuenta en Arkiv todavía), se puede seguir escribiendo su nombre a mano sin que esto
// bloquee nada.

function activarAutocompletarPersona(opciones) {
    var inputEl = document.getElementById(opciones.inputId);
    var listaEl = document.getElementById(opciones.listaId);
    if (!inputEl || !listaEl) { return; }
    var minLength = opciones.minLength || 2;
    var timeoutId = null;
    var resultadosActuales = [];

    function ocultarSugerencias() {
        listaEl.classList.add('hidden');
        listaEl.innerHTML = '';
        resultadosActuales = [];
    }

    function escaparHtml(texto) {
        var div = document.createElement('div');
        div.textContent = texto || '';
        return div.innerHTML;
    }

    function pintarSugerencias(resultados) {
        resultadosActuales = resultados;
        if (!resultados.length) {
            listaEl.innerHTML = '<p class="text-[11px] text-slate-500 px-3 py-2">Sin coincidencias — puedes seguir escribiendo el nombre.</p>';
            listaEl.classList.remove('hidden');
            return;
        }
        listaEl.innerHTML = resultados.map(function (persona, indice) {
            return '<button type="button" data-indice-persona="' + indice + '" ' +
                'class="w-full text-left px-3 py-2 hover:bg-slate-700 text-slate-200 border-b border-slate-700/50 last:border-0 flex items-center justify-between gap-2 text-[11px]">' +
                '<span>' + escaparHtml(persona.nombre) + '</span>' +
                (persona.cedula ? '<span class="text-slate-500 font-mono text-[10px]">' + escaparHtml(persona.cedula) + '</span>' : '') +
                '</button>';
        }).join('');
        // 🖱️ mousedown (no click) para que se dispare ANTES del blur del input — si fuera click,
        // el blur ocultaría la lista primero y el clic nunca llegaría al botón.
        var botones = listaEl.querySelectorAll('button[data-indice-persona]');
        for (var i = 0; i < botones.length; i++) {
            botones[i].addEventListener('mousedown', function (evento) {
                evento.preventDefault();
                var persona = resultadosActuales[parseInt(this.getAttribute('data-indice-persona'), 10)];
                ocultarSugerencias();
                if (persona && typeof opciones.onSeleccionar === 'function') {
                    opciones.onSeleccionar(persona);
                }
            });
        }
        listaEl.classList.remove('hidden');
    }

    inputEl.addEventListener('input', function () {
        clearTimeout(timeoutId);
        var valor = inputEl.value.trim();
        if (valor.length < minLength) {
            ocultarSugerencias();
            return;
        }
        timeoutId = setTimeout(function () {
            fetch('/usuarios/buscar?q=' + encodeURIComponent(valor))
                .then(function (r) { return r.json(); })
                .then(function (data) { pintarSugerencias(data.resultados || []); })
                .catch(function () { ocultarSugerencias(); });
        }, 250);
    });

    inputEl.addEventListener('blur', function () {
        // Pequeño retraso para no ocultar la lista antes de que el mousedown del botón alcance a
        // procesarse en navegadores donde blur llega primero.
        setTimeout(ocultarSugerencias, 150);
    });
}
