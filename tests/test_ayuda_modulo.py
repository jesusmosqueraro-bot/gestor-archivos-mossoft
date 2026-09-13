"""Pruebas del botón de ayuda contextual por módulo (pedido por Tomás, 13/09/2026: "habilitar
un boton de ayuda... manual instructivo de las funcionalidades de Arkiv o que se puede hacer?").

Formato elegido (respuesta del usuario a las preguntas de aclaración): ayuda CONTEXTUAL POR
MÓDULO — un botón "?" en cada página que explica solo la funcionalidad de ESA página (no un
modal centralizado ni una página /ayuda aparte), con profundidad completa (descripción + pasos
+ preguntas frecuentes) y adaptada al rol: como cada plantilla ya es alcanzable solo por quien
tiene permiso de ver ese módulo (la ruta de Flask lo exige), el botón queda ajustado al rol sin
lógica de permisos adicional — nunca se ve un botón de ayuda de un módulo al que no se tiene
acceso, porque nunca se llega a esa página.

Piezas del feature:
  - static/js/ayuda-modulo.js: objeto AYUDA_MODULOS (33 claves) + abrirAyudaModulo/cerrarAyudaModulo.
  - templates/partials/ayuda_modulo.html: el botón "?" + el modal, reusable.
  - Cada una de las 33 plantillas de módulo: incluye el parcial pasando su propia clave, y
    enlaza ayuda-modulo.js antes de </body>.

Estas pruebas verifican, en capas:
  1) Que AYUDA_MODULOS es JSON válido y cada entrada tiene contenido completo (sin campos vacíos).
  2) Que no hay claves duplicadas (un duplicado en el objeto JS silenciosamente descarta la
     primera definición y nadie lo notaría con solo mirar el archivo).
  3) Que cada una de las 33 plantillas de módulo incluye el botón con la clave correcta y el
     script, y que las plantillas SIN el botón son exactamente las que se decidió excluir
     (páginas de autenticación/cuenta, no "módulos" de la aplicación).
  4) Que las claves usadas en las plantillas y las claves definidas en el JS coinciden
     exactamente (ni un botón que apunte a una clave inexistente -> "Ayuda no disponible", ni
     una clave del JS que ningún botón use).
  5) Que el parcial reusable tiene los elementos que ayuda-modulo.js espera encontrar en el DOM.
  6) Un puñado de páginas reales, de distintos roles, para confirmar que el include realmente
     se renderiza en producción (no solo que el texto está en el archivo fuente)."""
import glob
import json
import os
import re

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUTA_JS = os.path.join(BASE_DIR, 'static', 'js', 'ayuda-modulo.js')
RUTA_PARCIAL = os.path.join(BASE_DIR, 'templates', 'partials', 'ayuda_modulo.html')

# Mapeo plantilla -> clave de módulo, tal como quedó cada '{% with modulo=... %}' insertado.
# Es la misma clave que scripts/agregar_ayuda_modulo.py usó (o, para las 7 plantillas sin
# partials/buscador.html, la que se agregó a mano siguiendo el mismo criterio).
PLANTILLA_A_CLAVE = {
    'admin_boveda_personal.html': 'admin_boveda_personal',
    'admin_db.html': 'admin_db',
    'admin_geolocalizacion.html': 'geolocalizacion',
    'bienvenida.html': 'bienvenida',
    'chat.html': 'chat',
    'chat_bot.html': 'chat_bot',
    'comunicados.html': 'comunicados',
    'comunicados_cumplimiento.html': 'comunicados_cumplimiento',
    'conocimiento.html': 'conocimiento',
    'credenciales.html': 'credenciales',
    'credenciales_auditoria.html': 'credenciales_auditoria',
    'credenciales_colaboradores.html': 'credenciales_colaboradores',
    'diseno_modales.html': 'diseno_modales',
    'fondo_login.html': 'fondo_login',
    'historial_sesiones.html': 'historial_sesiones',
    'index.html': 'archivos',
    'inventario_certificacion.html': 'certificacion_devoluciones',
    'logs.html': 'logs',
    'logs_correos.html': 'logs_correos',
    'mi_boveda.html': 'mi_boveda',
    'mis_tareas.html': 'mis_tareas',
    'papelera.html': 'papelera',
    'respaldos.html': 'respaldos',
    'tablero_ejecutivo.html': 'tablero_ejecutivo',
    'ticket_detalle.html': 'ticket_detalle',
    'tickets.html': 'tickets',
    'tickets_configuracion.html': 'tickets_configuracion',
    'tickets_indicadores.html': 'tickets_indicadores',
    'tickets_inicio.html': 'tickets_inicio',
    'tickets_inventario.html': 'tickets_inventario',
    'tickets_plantillas.html': 'tickets_plantillas',
    'usuarios.html': 'usuarios',
    'vencimientos.html': 'vencimientos',
}

# Plantillas deliberadamente SIN botón de ayuda: son pantallas de autenticación/cuenta (login,
# recuperación, 2FA, cambio de clave, datos de perfil), no "módulos" de la aplicación con una
# funcionalidad propia que explicar — el usuario ya está fuera de sesión o resolviendo un
# trámite puntual de su cuenta, no navegando la plataforma.
PLANTILLAS_SIN_AYUDA_ESPERADAS = {
    'cambiar_password.html',
    'login.html',
    'login_2fa.html',
    'perfil_2fa.html',
    'perfil_datos.html',
    'recuperar.html',
}


def _cargar_ayuda_modulos():
    with open(RUTA_JS, encoding='utf-8') as f:
        contenido = f.read()
    m = re.search(r'var\s+AYUDA_MODULOS\s*=\s*(\{.*\});', contenido, re.S)
    assert m, "no se encontró 'var AYUDA_MODULOS = {...};' en ayuda-modulo.js"
    return contenido, json.loads(m.group(1))


def test_ayuda_modulos_js_es_json_valido_y_tiene_las_33_claves_esperadas():
    _, datos = _cargar_ayuda_modulos()
    assert set(datos.keys()) == set(PLANTILLA_A_CLAVE.values())
    assert len(datos) == 33


def test_ayuda_modulos_js_no_tiene_claves_duplicadas():
    """json.loads descarta en silencio una clave repetida (se queda con la última definición) —
    esta prueba cuenta las apariciones en el texto crudo para detectar ese caso, que no se vería
    comparando solo el diccionario ya parseado."""
    contenido, datos = _cargar_ayuda_modulos()
    conteos = {}
    for clave in datos.keys():
        patron = re.compile(r'(^|[{,\s])"' + re.escape(clave) + r'"\s*:\s*\{', re.M)
        conteos[clave] = len(patron.findall(contenido))
    duplicadas = {k: v for k, v in conteos.items() if v != 1}
    assert not duplicadas, f"claves con más de una definición en ayuda-modulo.js: {duplicadas}"


def test_cada_entrada_de_ayuda_modulos_tiene_contenido_completo():
    """Ninguna entrada debe quedar a medias: descripción vacía, cero pasos o cero preguntas
    frecuentes serían un panel de ayuda inútil para el usuario."""
    _, datos = _cargar_ayuda_modulos()
    for clave, entrada in datos.items():
        assert isinstance(entrada.get('titulo'), str) and entrada['titulo'].strip(), clave
        assert isinstance(entrada.get('descripcion'), str) and len(entrada['descripcion'].strip()) >= 20, clave
        pasos = entrada.get('pasos')
        assert isinstance(pasos, list) and len(pasos) >= 1, clave
        assert all(isinstance(p, str) and p.strip() for p in pasos), clave
        preguntas = entrada.get('preguntas')
        assert isinstance(preguntas, list) and len(preguntas) >= 1, clave
        for p in preguntas:
            assert isinstance(p.get('q'), str) and p['q'].strip(), clave
            assert isinstance(p.get('a'), str) and p['a'].strip(), clave


def test_todas_las_plantillas_de_modulo_incluyen_el_boton_de_ayuda_con_la_clave_correcta():
    faltantes = []
    for plantilla, clave in PLANTILLA_A_CLAVE.items():
        ruta = os.path.join(BASE_DIR, 'templates', plantilla)
        with open(ruta, encoding='utf-8') as f:
            contenido = f.read()
        include_esperado = f"{{% with modulo='{clave}' %}}{{% include 'partials/ayuda_modulo.html' %}}{{% endwith %}}"
        if include_esperado not in contenido:
            faltantes.append((plantilla, 'include'))
        if '<script src="/static/js/ayuda-modulo.js"></script>' not in contenido:
            faltantes.append((plantilla, 'script'))
    assert not faltantes, f"faltan piezas del botón de ayuda: {faltantes}"


def test_las_plantillas_sin_boton_de_ayuda_son_exactamente_las_esperadas():
    """Evita que una plantilla NUEVA (o una ya existente) se quede afuera del rollout sin que
    nadie lo note — igual que test_montserrat_esta_enlazada_globalmente_en_todas_las_plantillas
    hace para la tipografía institucional."""
    todas = {os.path.basename(p) for p in glob.glob(os.path.join(BASE_DIR, 'templates', '*.html'))}
    con_boton = set(PLANTILLA_A_CLAVE.keys())
    sin_boton = todas - con_boton
    assert sin_boton == PLANTILLAS_SIN_AYUDA_ESPERADAS, (
        f"plantillas sin botón de ayuda distintas de las esperadas — "
        f"nuevas sin cubrir: {sin_boton - PLANTILLAS_SIN_AYUDA_ESPERADAS}, "
        f"ya no existen: {PLANTILLAS_SIN_AYUDA_ESPERADAS - sin_boton}"
    )
    assert todas == con_boton | PLANTILLAS_SIN_AYUDA_ESPERADAS


def test_las_claves_usadas_en_plantillas_coinciden_exactamente_con_las_del_js():
    """Ni un botón que apunte a una clave que no existe en AYUDA_MODULOS (mostraría 'Ayuda no
    disponible' en vez de contenido real), ni una entrada del JS que ninguna plantilla usa."""
    _, datos = _cargar_ayuda_modulos()
    claves_js = set(datos.keys())
    claves_plantillas = set()
    for plantilla in PLANTILLA_A_CLAVE:
        ruta = os.path.join(BASE_DIR, 'templates', plantilla)
        with open(ruta, encoding='utf-8') as f:
            contenido = f.read()
        encontradas = re.findall(r"modulo='([a-z_]+)'", contenido)
        claves_plantillas.update(encontradas)

    assert claves_plantillas == set(PLANTILLA_A_CLAVE.values())
    assert claves_plantillas == claves_js, (
        f"en plantillas pero no en el JS: {claves_plantillas - claves_js}; "
        f"en el JS pero ninguna plantilla lo usa: {claves_js - claves_plantillas}"
    )


def test_el_parcial_reusable_tiene_los_elementos_que_espera_ayuda_modulo_js():
    with open(RUTA_PARCIAL, encoding='utf-8') as f:
        contenido = f.read()
    # abrirAyudaModulo/cerrarAyudaModulo (ver ayuda-modulo.js) buscan estos IDs con
    # document.getElementById — si cambian de nombre aquí sin cambiar allá, el botón no rompe
    # visualmente pero tampoco hace nada al hacer clic.
    assert 'data-ayuda-modulo="{{ modulo }}"' in contenido
    assert 'onclick="abrirAyudaModulo(this.dataset.ayudaModulo)"' in contenido
    assert 'onclick="cerrarAyudaModulo()"' in contenido
    assert 'id="modal-ayuda-modulo"' in contenido
    assert 'id="ayuda-modulo-titulo"' in contenido
    assert 'id="ayuda-modulo-contenido"' in contenido


def test_bienvenida_renderiza_el_boton_de_ayuda_para_un_administrador(admin_session):
    texto = admin_session.get('/bienvenida').get_data(as_text=True)
    assert 'data-ayuda-modulo="bienvenida"' in texto
    assert '/static/js/ayuda-modulo.js' in texto


def test_mi_boveda_renderiza_el_boton_de_ayuda_para_un_usuario_estandar(sesion_usuario):
    texto = sesion_usuario.get('/mi_boveda').get_data(as_text=True)
    assert 'data-ayuda-modulo="mi_boveda"' in texto
    assert '/static/js/ayuda-modulo.js' in texto


def test_conocimiento_renderiza_el_boton_de_ayuda(admin_session):
    texto = admin_session.get('/tickets/conocimiento').get_data(as_text=True)
    assert 'data-ayuda-modulo="conocimiento"' in texto


def test_mis_tareas_renderiza_el_boton_de_ayuda(admin_session):
    texto = admin_session.get('/tickets/mis_tareas').get_data(as_text=True)
    assert 'data-ayuda-modulo="mis_tareas"' in texto


def test_chat_renderiza_el_boton_de_ayuda_para_un_agente(admin_session):
    """/chat sirve chat.html (chat libre) a admin/agente y chat_bot.html (asistente guiado) a
    un usuario 'estandar' — ver chat_pagina() en app.py. Esta prueba cubre el primer caso."""
    texto = admin_session.get('/chat').get_data(as_text=True)
    assert 'data-ayuda-modulo="chat"' in texto


def test_chat_bot_renderiza_el_boton_de_ayuda_para_un_usuario_estandar(sesion_usuario):
    """El botón de ayuda queda FUERA del bloque '{% if habilitado %}', así que se ve incluso
    cuando el asistente sigue deshabilitado por defecto (ver test_chat_pagina_de_estandar_
    muestra_no_disponible_si_esta_deshabilitado en test_chat_bot_asistente.py)."""
    texto = sesion_usuario.get('/chat').get_data(as_text=True)
    assert 'data-ayuda-modulo="chat_bot"' in texto
