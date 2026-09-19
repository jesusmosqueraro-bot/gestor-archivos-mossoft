"""Pruebas de los ajustes pedidos por Tomás el 19/09/2026 (video adjunto), fuera del contraste
CSS (eso no es verificable con pytest): gestión del tablero desde su propio visor
(powerbi_visor.html: Editar/Bloquear-Desbloquear/Eliminar), el módulo extra 'reportes', y el
ajuste de "Edición de Nombres por Admin" en editar_usuario().
"""
import pytest


def _sesion_como(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _crear_tablero(app, titulo='Tablero de Prueba', roles_permitidos='admin', activo=True, embed_url='https://app.powerbi.com/view?r=xyz'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = (
        "INSERT INTO reportes_powerbi (titulo, descripcion, categoria, embed_url, roles_permitidos, activo) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
        if db_type == 'postgres' else
        "INSERT INTO reportes_powerbi (titulo, descripcion, categoria, embed_url, roles_permitidos, activo) VALUES (?, ?, ?, ?, ?, ?)"
    )
    cur.execute(q, (titulo, 'Descripción de prueba', 'General', embed_url, roles_permitidos, activo))
    if db_type == 'postgres':
        tablero_id = cur.fetchone()[0]
    else:
        tablero_id = cur.lastrowid
    conn.commit()
    conn.close()
    return tablero_id


def _tablero_actual(app, tablero_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = "SELECT titulo, descripcion, categoria, embed_url, roles_permitidos, activo FROM reportes_powerbi WHERE id = ?"
    cur.execute(q, (tablero_id,))
    row = cur.fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# 'reportes' en el catálogo de módulos asignables
# ---------------------------------------------------------------------------

def test_estandar_sin_permiso_no_ve_tablero_fuera_de_sus_roles_permitidos(client, app, crear_usuario):
    _crear_tablero(app, roles_permitidos='admin')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')
    resp = client.get('/indicadores/powerbi')
    html = resp.get_data(as_text=True)
    assert 'Tablero de Prueba' not in html


def test_estandar_con_extra_reportes_ve_todos_los_tableros_activos(client, app, crear_usuario):
    _crear_tablero(app, roles_permitidos='admin')
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
        sess['modulos_extra'] = ['reportes']
    resp = client.get('/indicadores/powerbi')
    html = resp.get_data(as_text=True)
    assert 'Tablero de Prueba' in html


def test_ver_powerbi_respeta_extra_reportes_igual_que_el_listado(client, app, crear_usuario):
    tablero_id = _crear_tablero(app, roles_permitidos='admin')
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
        sess['modulos_extra'] = ['reportes']
    resp = client.get(f'/indicadores/powerbi/{tablero_id}')
    assert resp.status_code == 200
    assert 'Tablero de Prueba' in resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Tablero bloqueado (activo = False): visible solo para admin, con aviso
# ---------------------------------------------------------------------------

def test_admin_puede_ver_tablero_bloqueado_con_aviso(admin_session, app):
    tablero_id = _crear_tablero(app, activo=False)
    resp = admin_session.get(f'/indicadores/powerbi/{tablero_id}')
    html = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert 'Bloqueado' in html
    assert 'bloqueado' in html.lower()


def test_no_admin_no_puede_ver_tablero_bloqueado(client, app, crear_usuario):
    tablero_id = _crear_tablero(app, roles_permitidos='admin,agente', activo=False)
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    resp = client.get(f'/indicadores/powerbi/{tablero_id}', follow_redirects=True)
    assert 'Tablero de Prueba' not in resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Controles admin-only del visor: editar, bloquear/desbloquear, eliminar
# ---------------------------------------------------------------------------

def test_visor_powerbi_muestra_controles_solo_a_admin(admin_session, client, app, crear_usuario):
    tablero_id = _crear_tablero(app, roles_permitidos='admin,agente')
    html_admin = admin_session.get(f'/indicadores/powerbi/{tablero_id}').get_data(as_text=True)
    assert 'abrirModalEditarPowerBI' in html_admin
    assert 'abrirModalEliminarPowerBI' in html_admin

    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    html_agente = client.get(f'/indicadores/powerbi/{tablero_id}').get_data(as_text=True)
    assert 'abrirModalEditarPowerBI' not in html_agente
    assert 'abrirModalEliminarPowerBI' not in html_agente


def test_editar_powerbi_visor_actualiza_y_solo_lo_permite_admin(admin_session, client, app, crear_usuario):
    tablero_id = _crear_tablero(app)
    resp = admin_session.post(f'/indicadores/powerbi/{tablero_id}/editar', data={
        'titulo': 'Tablero Editado',
        'categoria': 'Financiero',
        'descripcion': 'Nueva descripción',
        'embed_url': 'https://app.powerbi.com/view?r=nuevo',
        'roles_permitidos': ['admin', 'agente'],
    }, follow_redirects=True)
    assert resp.status_code == 200
    fila = _tablero_actual(app, tablero_id)
    assert fila[0] == 'Tablero Editado'
    assert fila[2] == 'Financiero'
    assert fila[4] == 'admin,agente'

    # Un agente (rol operativo, pero no admin) no puede usar esta ruta.
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    client.post(f'/indicadores/powerbi/{tablero_id}/editar', data={
        'titulo': 'Intento de Agente', 'embed_url': 'https://x', 'roles_permitidos': ['admin'],
    })
    fila_tras_intento = _tablero_actual(app, tablero_id)
    assert fila_tras_intento[0] == 'Tablero Editado'  # sin cambios


def test_alternar_powerbi_bloquea_y_desbloquea(admin_session, app):
    tablero_id = _crear_tablero(app, activo=True)
    admin_session.post(f'/indicadores/powerbi/{tablero_id}/alternar')
    assert _tablero_actual(app, tablero_id)[5] in (0, False)
    admin_session.post(f'/indicadores/powerbi/{tablero_id}/alternar')
    assert _tablero_actual(app, tablero_id)[5] in (1, True)


def test_alternar_powerbi_rechaza_a_no_admin(client, app, crear_usuario):
    tablero_id = _crear_tablero(app, activo=True)
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    client.post(f'/indicadores/powerbi/{tablero_id}/alternar')
    assert _tablero_actual(app, tablero_id)[5] in (1, True)


def test_eliminar_powerbi_borra_el_registro(admin_session, app):
    tablero_id = _crear_tablero(app)
    resp = admin_session.post(f'/indicadores/powerbi/{tablero_id}/eliminar', follow_redirects=True)
    assert resp.status_code == 200
    assert _tablero_actual(app, tablero_id) is None


def test_eliminar_powerbi_rechaza_a_no_admin(client, app, crear_usuario):
    tablero_id = _crear_tablero(app)
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    client.post(f'/indicadores/powerbi/{tablero_id}/eliminar')
    assert _tablero_actual(app, tablero_id) is not None


# ---------------------------------------------------------------------------
# Edición de Nombres por Admin: un admin (no super-admin) ahora SÍ puede editar
# agente/estandar, pero sigue sin poder tocar OTRA cuenta 'admin'.
# ---------------------------------------------------------------------------

def test_admin_comun_puede_editar_nombre_de_un_agente(client, app, crear_usuario):
    admin_comun = crear_usuario(usuario='admin_comun', rol='admin')
    agente = crear_usuario(usuario='agente_x', rol='agente', nombre='Nombre Viejo')
    _sesion_como(client, app, admin_comun, 'admin')
    agente_id = app.get_db()[0].cursor().execute("SELECT id FROM usuarios WHERE usuario = ?", (agente,)).fetchone()[0]
    client.post(f'/editar_usuario/{agente_id}', data={'nombre': 'Nombre Nuevo', 'rol': 'agente'})
    conn, _ = app.get_db()
    fila = conn.cursor().execute("SELECT nombre FROM usuarios WHERE id = ?", (agente_id,)).fetchone()
    conn.close()
    assert fila[0] == 'Nombre Nuevo'


def test_admin_comun_puede_editar_nombre_de_un_estandar(client, app, crear_usuario):
    admin_comun = crear_usuario(usuario='admin_comun2', rol='admin')
    estandar = crear_usuario(usuario='estandar_x', rol='estandar', nombre='Nombre Viejo')
    _sesion_como(client, app, admin_comun, 'admin')
    conn, _ = app.get_db()
    estandar_id = conn.cursor().execute("SELECT id FROM usuarios WHERE usuario = ?", (estandar,)).fetchone()[0]
    conn.close()
    client.post(f'/editar_usuario/{estandar_id}', data={'nombre': 'Nombre Nuevo', 'rol': 'estandar'})
    conn, _ = app.get_db()
    fila = conn.cursor().execute("SELECT nombre FROM usuarios WHERE id = ?", (estandar_id,)).fetchone()
    conn.close()
    assert fila[0] == 'Nombre Nuevo'


def test_admin_comun_no_puede_editar_a_otro_admin(client, app, crear_usuario):
    admin_comun = crear_usuario(usuario='admin_comun3', rol='admin')
    otro_admin = crear_usuario(usuario='otro_admin', rol='admin', nombre='Nombre Viejo')
    _sesion_como(client, app, admin_comun, 'admin')
    conn, _ = app.get_db()
    otro_admin_id = conn.cursor().execute("SELECT id FROM usuarios WHERE usuario = ?", (otro_admin,)).fetchone()[0]
    conn.close()
    client.post(f'/editar_usuario/{otro_admin_id}', data={'nombre': 'Nombre Nuevo', 'rol': 'admin'})
    conn, _ = app.get_db()
    fila = conn.cursor().execute("SELECT nombre FROM usuarios WHERE id = ?", (otro_admin_id,)).fetchone()
    conn.close()
    assert fila[0] == 'Nombre Viejo'  # sin cambios: sigue bloqueado


def test_superadmin_si_puede_editar_a_otro_admin(admin_session, app, crear_usuario):
    otro_admin = crear_usuario(usuario='otro_admin2', rol='admin', nombre='Nombre Viejo')
    conn, _ = app.get_db()
    otro_admin_id = conn.cursor().execute("SELECT id FROM usuarios WHERE usuario = ?", (otro_admin,)).fetchone()[0]
    conn.close()
    admin_session.post(f'/editar_usuario/{otro_admin_id}', data={'nombre': 'Nombre Nuevo', 'rol': 'admin'})
    conn, _ = app.get_db()
    fila = conn.cursor().execute("SELECT nombre FROM usuarios WHERE id = ?", (otro_admin_id,)).fetchone()
    conn.close()
    assert fila[0] == 'Nombre Nuevo'


# ---------------------------------------------------------------------------
# Contraste de modales: valores por defecto más oscuros/contrastados
# ---------------------------------------------------------------------------

def test_colores_modal_por_defecto_de_texto_secundario_son_mas_contrastados(app):
    # No es una prueba visual (eso se validó manualmente contra el video), pero evita que el
    # valor "seguro" que se calculó aquí se pierda en un futuro refactor sin que nadie lo note.
    assert app.COLORES_MODAL_POR_DEFECTO['claro']['texto_secundario'] == '#475569'
    assert app.COLORES_MODAL_POR_DEFECTO['descanso']['texto_secundario'] == '#4a423c'


def test_css_close_button_no_depende_del_color_personalizable(app):
    import os as _os
    base_dir = _os.path.dirname(_os.path.abspath(app.__file__))
    for nombre_tema in ('tema-claro.css', 'tema-descanso.css'):
        ruta = _os.path.join(base_dir, 'static', 'css', nombre_tema)
        contenido = open(ruta, encoding='utf-8').read()
        assert 'fa-xmark' in contenido and ':has(' in contenido
