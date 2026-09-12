"""Pruebas de /admin/diseno (personalización de colores de los modales, pedido por Tomás,
12/09/2026: "un modal de diseño para poder modificar a gusto los colores de los modales").

Cubre: que solo la cuenta super-admin ('admin') puede ver/guardar/restablecer los colores, que
guardar valida cada campo como '#rrggbb' (cayendo al valor por defecto si no lo es), que lo
guardado se refleja de inmediato en cualquier página (vía el context_processor
_inyectar_colores_modal + partials/colores_modal_personalizados.html), y que restablecer vuelve
exactamente a los valores de fábrica.
"""
import json


def test_ver_diseno_modales_solo_superadmin(admin_session, app):
    """La cuenta super-admin 'admin' (sembrada por init_db()) sí puede ver la pantalla."""
    resp = admin_session.get('/admin/diseno')
    assert resp.status_code == 200
    texto = resp.data.decode('utf-8')
    assert 'Diseño de Modales' in texto
    assert 'name="acentos__azul_primario"' in texto
    assert 'name="oscuro__fondo"' in texto
    assert 'name="claro__texto_secundario"' in texto
    assert 'name="descanso__borde"' in texto


def test_ver_diseno_modales_admin_comun_no_puede(client, app, crear_usuario):
    """Un usuario con rol 'admin' pero que NO es la cuenta literal 'admin' (super-admin) es
    redirigido — mismo nivel de acceso que Respaldos/Gestor de BD (@superadmin_required)."""
    usuario = crear_usuario(rol='admin')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'admin'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    resp = client.get('/admin/diseno')
    assert resp.status_code == 302
    assert '/admin/diseno' not in resp.headers.get('Location', '')


def test_ver_diseno_modales_estandar_no_puede(sesion_usuario):
    resp = sesion_usuario.get('/admin/diseno')
    assert resp.status_code == 302


def test_ver_diseno_modales_requiere_login(client):
    resp = client.get('/admin/diseno')
    assert resp.status_code == 302


def test_valores_por_defecto_coinciden_con_los_colores_originales(app):
    """Antes de que cualquier admin toque /admin/diseno, _colores_modal_actuales() debe devolver
    exactamente COLORES_MODAL_POR_DEFECTO (los colores que los modales ya tenían) — es lo que
    garantiza que desplegar este feature no cambia nada visualmente todavía."""
    assert app._colores_modal_actuales() == app.COLORES_MODAL_POR_DEFECTO


def test_guardar_colores_modal_persiste_y_se_refleja_en_cualquier_pagina(admin_session, app):
    form = {}
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        for clave in valores:
            form[f'{grupo}__{clave}'] = '#ff00aa' if (grupo, clave) == ('acentos', 'azul_primario') else valores[clave]

    resp = admin_session.post('/admin/diseno/guardar', data=form, follow_redirects=True)
    assert resp.status_code == 200

    actuales = app._colores_modal_actuales()
    assert actuales['acentos']['azul_primario'] == '#ff00aa'
    # el resto de campos no tocados por esta prueba deben seguir en su valor por defecto
    assert actuales['oscuro']['fondo'] == app.COLORES_MODAL_POR_DEFECTO['oscuro']['fondo']

    # Se refleja en CUALQUIER plantilla renderizada (context_processor + partial), no solo en
    # /admin/diseno: /bienvenida es una buena prueba porque no pasa 'colores_modal' explícito.
    pagina = admin_session.get('/bienvenida')
    assert '--marca-azul-primario: #ff00aa;' in pagina.data.decode('utf-8')


def test_guardar_colores_modal_rechaza_valores_invalidos(admin_session, app):
    """Un color inválido (no '#rrggbb') en un campo cae a su valor por defecto, sin tumbar el
    guardado del resto de campos ni dejar basura en la BD."""
    form = {}
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        for clave in valores:
            form[f'{grupo}__{clave}'] = valores[clave]
    form['claro__fondo'] = 'javascript:alert(1)'  # intento de valor inválido/malicioso

    admin_session.post('/admin/diseno/guardar', data=form, follow_redirects=True)

    actuales = app._colores_modal_actuales()
    assert actuales['claro']['fondo'] == app.COLORES_MODAL_POR_DEFECTO['claro']['fondo']


def test_guardar_colores_modal_con_formulario_incompleto_completa_con_defectos(admin_session, app):
    """Si el formulario llega sin todos los 16 campos (ej. un POST manual recortado), el JSON
    guardado de todas formas queda completo — cada campo faltante cae a su valor por defecto."""
    admin_session.post('/admin/diseno/guardar', data={'acentos__cian': '#00ff00'}, follow_redirects=True)

    actuales = app._colores_modal_actuales()
    assert actuales['acentos']['cian'] == '#00ff00'
    assert actuales['descanso']['texto'] == app.COLORES_MODAL_POR_DEFECTO['descanso']['texto']
    guardado = json.loads(app._config_app_valor(app.CLAVE_COLORES_MODAL))
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        assert set(guardado[grupo].keys()) == set(valores.keys())


def test_restablecer_diseno_modales_vuelve_a_los_valores_de_fabrica(admin_session, app):
    admin_session.post('/admin/diseno/guardar', data={'acentos__naranja': '#123456'}, follow_redirects=True)
    assert app._colores_modal_actuales()['acentos']['naranja'] == '#123456'

    admin_session.post('/admin/diseno/restablecer', follow_redirects=True)
    assert app._colores_modal_actuales() == app.COLORES_MODAL_POR_DEFECTO
