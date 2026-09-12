/* tabla-interactiva.js
 * ---------------------------------------------------------------------------
 * Componente genérico y reutilizable (sin dependencias externas) que agrega a
 * cualquier <table> marcada con data-tabla-interactiva="<id-unico>" tres
 * funciones pedidas por Tomás (12/09/2026, sobre "Soporte TI" y el visor de
 * base de datos): reordenar columnas (arrastrando el encabezado), ocultar/
 * mostrar columnas, y filtrar por columna. La preferencia de orden/columnas
 * ocultas se guarda en localStorage por tabla, así que persiste entre visitas
 * (pero es solo del navegador de cada persona, no se sincroniza entre equipos).
 *
 * Uso: agregar data-tabla-interactiva="algun-id" al <table> e incluir este
 * script. No requiere ninguna otra configuración; se auto-inicializa con
 * todas las tablas marcadas que haya en la página al cargar.
 * --------------------------------------------------------------------------- */
(function () {
    'use strict';

    var PREFIJO_STORAGE = 'arkiv_tabla_v1_';

    function cargarPrefs(id) {
        try {
            var crudo = localStorage.getItem(PREFIJO_STORAGE + id);
            return crudo ? JSON.parse(crudo) : null;
        } catch (e) {
            return null;
        }
    }

    function guardarPrefs(id, prefs) {
        try {
            localStorage.setItem(PREFIJO_STORAGE + id, JSON.stringify(prefs));
        } catch (e) {
            /* localStorage puede fallar (modo privado, cuota llena, etc.) — no es crítico */
        }
    }

    function textoEncabezado(th) {
        // Clona y quita cualquier control interactivo (checkbox, input) antes de leer el texto,
        // para que la identidad de la columna no incluya basura de esos controles.
        var clon = th.cloneNode(true);
        var controles = clon.querySelectorAll('input, select, button');
        controles.forEach ? controles.forEach(function (c) { c.remove(); }) : Array.prototype.forEach.call(controles, function (c) { c.remove(); });
        return clon.textContent.trim();
    }

    function inicializarTabla(table) {
        var id = table.getAttribute('data-tabla-interactiva');
        if (!id || table.__arkivInteractivaInicializada) return;
        table.__arkivInteractivaInicializada = true;

        var headRow = table.tHead && table.tHead.rows[0];
        if (!headRow) return;
        var n = headRow.cells.length;
        if (n === 0) return;

        var nombresOriginales = Array.prototype.map.call(headRow.cells, textoEncabezado);

        function filasDeDatos() {
            var cuerpo = table.tBodies[0];
            if (!cuerpo) return [];
            return Array.prototype.filter.call(cuerpo.rows, function (r) { return r.cells.length === n; });
        }

        // ---------- Fila de filtros por columna (dentro del thead) ----------
        var filaFiltro = document.createElement('tr');
        filaFiltro.className = 'arkiv-fila-filtro';
        for (var i = 0; i < n; i++) {
            (function () {
                var th = document.createElement('th');
                th.className = 'p-1.5 font-normal bg-slate-900/40';
                var input = document.createElement('input');
                input.type = 'text';
                input.placeholder = 'Filtrar…';
                input.autocomplete = 'off';
                input.className = 'w-full min-w-[70px] bg-slate-900 border border-slate-700 rounded-lg px-2 py-1 text-[10px] text-slate-300 font-normal focus:outline-none focus:ring-1 focus:ring-cyan-500';
                input.addEventListener('click', function (e) { e.stopPropagation(); });
                input.addEventListener('mousedown', function (e) { e.stopPropagation(); });
                input.addEventListener('keydown', function (e) { e.stopPropagation(); });
                input.addEventListener('input', aplicarFiltros);
                th.appendChild(input);
                filaFiltro.appendChild(th);
            })();
        }
        headRow.parentNode.insertBefore(filaFiltro, headRow.nextSibling);

        function aplicarFiltros() {
            var filtros = Array.prototype.map.call(filaFiltro.cells, function (th) {
                return th.querySelector('input').value.trim().toLowerCase();
            });
            filasDeDatos().forEach(function (row) {
                var visible = true;
                for (var i = 0; i < n; i++) {
                    if (!filtros[i]) continue;
                    var celda = row.cells[i];
                    var texto = (celda ? celda.textContent : '').toLowerCase();
                    if (texto.indexOf(filtros[i]) === -1) { visible = false; break; }
                }
                row.classList.toggle('arkiv-fila-oculta-por-filtro', !visible);
            });
        }

        // ---------- Reordenar columnas (arrastrar encabezado) ----------
        function indiceActual(th) {
            return Array.prototype.indexOf.call(headRow.cells, th);
        }

        function reordenarColumna(origen, destino) {
            if (origen === destino) return;
            var orden = [];
            for (var k = 0; k < n; k++) orden.push(k);
            var item = orden.splice(origen, 1)[0];
            orden.splice(destino, 0, item);

            var filas = [headRow, filaFiltro].concat(filasDeDatos());
            filas.forEach(function (row) {
                var celdas = Array.prototype.slice.call(row.cells);
                if (celdas.length !== n) return;
                celdas.forEach(function (c) { c.remove(); });
                orden.forEach(function (idxOriginal) { row.appendChild(celdas[idxOriginal]); });
            });
        }

        Array.prototype.forEach.call(headRow.cells, function (th) {
            th.setAttribute('draggable', 'true');
            th.classList.add('arkiv-th-arrastrable');
            th.title = (th.title ? th.title + ' — ' : '') + 'Arrastra para reordenar esta columna';
            th.addEventListener('dragstart', function (e) {
                e.dataTransfer.effectAllowed = 'move';
                try { e.dataTransfer.setData('text/plain', String(indiceActual(th))); } catch (err) { /* Safari a veces exige setData con MIME text/plain, ya lo hacemos */ }
                th.classList.add('arkiv-th-arrastrando');
            });
            th.addEventListener('dragend', function () { th.classList.remove('arkiv-th-arrastrando'); });
            th.addEventListener('dragover', function (e) {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            });
            th.addEventListener('drop', function (e) {
                e.preventDefault();
                var origen = parseInt(e.dataTransfer.getData('text/plain'), 10);
                var destino = indiceActual(th);
                if (isNaN(origen)) return;
                reordenarColumna(origen, destino);
                guardarEstado();
            });
        });

        // ---------- Mostrar / ocultar columnas ----------
        function establecerVisibilidad(nombreColumna, visible) {
            var th = Array.prototype.filter.call(headRow.cells, function (c) { return textoEncabezado(c) === nombreColumna; })[0];
            if (!th) return;
            var idx = indiceActual(th);
            var display = visible ? '' : 'none';
            th.style.display = display;
            if (filaFiltro.cells[idx]) filaFiltro.cells[idx].style.display = display;
            filasDeDatos().forEach(function (row) {
                if (row.cells[idx]) row.cells[idx].style.display = display;
            });
        }

        // ---------- Barra de herramientas (botón "Columnas") ----------
        var wrapper = table.closest('.overflow-x-auto') || table.parentElement;
        var contenedorBarra = wrapper.parentElement;

        var barra = document.createElement('div');
        barra.className = 'flex items-center justify-end gap-2 mb-2 relative';
        barra.innerHTML =
            '<span class="text-[10px] text-slate-500 mr-auto">' +
            '<i class="fa-solid fa-arrows-left-right-to-line mr-1"></i>Arrastra un encabezado para reordenar · usa los campos bajo cada encabezado para filtrar' +
            '</span>' +
            '<button type="button" class="arkiv-btn-columnas bg-slate-700/60 hover:bg-slate-600 text-slate-200 text-[11px] font-bold px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition-all">' +
            '<i class="fa-solid fa-table-columns"></i> Columnas' +
            '</button>' +
            '<div class="arkiv-panel-columnas hidden absolute right-0 top-full mt-1 z-30 bg-slate-800 border border-slate-700 rounded-xl shadow-2xl p-3 w-56 max-h-72 overflow-y-auto"></div>';
        contenedorBarra.insertBefore(barra, wrapper);

        var botonColumnas = barra.querySelector('.arkiv-btn-columnas');
        var panel = barra.querySelector('.arkiv-panel-columnas');

        function reconstruirPanel() {
            panel.innerHTML = '';
            var titulo = document.createElement('div');
            titulo.className = 'text-[10px] font-bold uppercase tracking-wider text-slate-500 mb-2';
            titulo.textContent = 'Mostrar columnas';
            panel.appendChild(titulo);

            nombresOriginales.forEach(function (nombre) {
                var th = Array.prototype.filter.call(headRow.cells, function (c) { return textoEncabezado(c) === nombre; })[0];
                var oculta = th && th.style.display === 'none';
                var label = document.createElement('label');
                label.className = 'flex items-center gap-2 py-1 text-xs text-slate-300 cursor-pointer';
                label.innerHTML = '<input type="checkbox" class="rounded border-slate-600 bg-slate-900 text-cyan-500 focus:ring-cyan-500" ' + (oculta ? '' : 'checked') + '> <span class="truncate">' + nombre.replace(/</g, '&lt;') + '</span>';
                var checkbox = label.querySelector('input');
                checkbox.addEventListener('change', function () {
                    establecerVisibilidad(nombre, checkbox.checked);
                    guardarEstado();
                });
                panel.appendChild(label);
            });

            var restablecer = document.createElement('button');
            restablecer.type = 'button';
            restablecer.className = 'mt-2 w-full text-center text-[10px] font-bold text-cyan-400 hover:text-cyan-300 border-t border-slate-700 pt-2';
            restablecer.textContent = 'Restablecer orden y columnas';
            restablecer.addEventListener('click', function () {
                localStorage.removeItem(PREFIJO_STORAGE + id);
                location.reload();
            });
            panel.appendChild(restablecer);
        }

        botonColumnas.addEventListener('click', function (e) {
            e.stopPropagation();
            reconstruirPanel();
            panel.classList.toggle('hidden');
        });
        document.addEventListener('click', function (e) {
            if (!panel.contains(e.target) && e.target !== botonColumnas) panel.classList.add('hidden');
        });

        // ---------- Guardar / aplicar preferencias ----------
        function guardarEstado() {
            var ordenActual = Array.prototype.map.call(headRow.cells, textoEncabezado);
            var ocultas = Array.prototype.filter.call(headRow.cells, function (c) { return c.style.display === 'none'; }).map(textoEncabezado);
            guardarPrefs(id, { orden: ordenActual, ocultas: ocultas });
        }

        function aplicarPrefs() {
            var prefs = cargarPrefs(id);
            if (!prefs || !prefs.orden || prefs.orden.length !== n) return;
            var mismasColumnas = prefs.orden.slice().sort().join('|') === nombresOriginales.slice().sort().join('|');
            if (!mismasColumnas) return;

            prefs.orden.forEach(function (nombre, posicionDeseada) {
                var th = Array.prototype.filter.call(headRow.cells, function (c) { return textoEncabezado(c) === nombre; })[0];
                if (!th) return;
                var posicionActual = indiceActual(th);
                if (posicionActual !== posicionDeseada) reordenarColumna(posicionActual, posicionDeseada);
            });

            (prefs.ocultas || []).forEach(function (nombre) { establecerVisibilidad(nombre, false); });
        }

        aplicarPrefs();

        // Insertamos también un estilo mínimo una sola vez por página (no por tabla).
        if (!document.getElementById('arkiv-tabla-interactiva-estilos')) {
            var estilo = document.createElement('style');
            estilo.id = 'arkiv-tabla-interactiva-estilos';
            estilo.textContent =
                '.arkiv-th-arrastrable{cursor:grab;user-select:none;}' +
                '.arkiv-th-arrastrando{opacity:.4;}' +
                '.arkiv-fila-oculta-por-filtro{display:none!important;}';
            document.head.appendChild(estilo);
        }
    }

    function inicializarTodas() {
        var tablas = document.querySelectorAll('table[data-tabla-interactiva]');
        Array.prototype.forEach.call(tablas, inicializarTabla);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', inicializarTodas);
    } else {
        inicializarTodas();
    }
})();
