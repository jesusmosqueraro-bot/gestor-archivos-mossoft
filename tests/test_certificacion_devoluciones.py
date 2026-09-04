"""Pruebas de la certificación de devolución de activos: antes de bloquear/liquidar la
cuenta de un colaborador en Gestión de Usuarios, Gestión Humana o TI deben certificar que
ya devolvió el PC u otro activo que tenía asignado en el Inventario."""


def _crear_activo(app, nombre='Laptop de Prueba', estado='Asignado', asignado_a='Juan Pérez', tipo_activo='Portátil'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, tipo_activo, estado, asignado_a, '2026-09-01 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _sesion_gestion_humana(client, app, usuario='rrhh1'):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'gestion_humana'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def test_gestion_humana_puede_ver_certificacion_devoluciones(client, app, crear_usuario):
    crear_usuario(usuario='rrhh1', rol='gestion_humana')
    _sesion_gestion_humana(client, app)

    r = client.get('/inventario/certificacion_devoluciones')

    assert r.status_code == 200


def test_estandar_no_puede_ver_certificacion_devoluciones(client, app, sesion_usuario):
    r = client.get('/inventario/certificacion_devoluciones')

    assert r.status_code in (302, 403)


def test_pendientes_de_devolucion_lista_activos_asignados(admin_session, app):
    _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    r = admin_session.get('/inventario/certificacion_devoluciones')

    assert r.status_code == 200
    assert 'Duván Cabarcas'.encode('utf-8') in r.data or b'Cabarcas' in r.data


def test_confirmar_devolucion_libera_el_activo_y_certifica(admin_session, app):
    """Desde que se agregó el estado 'Devolución' (pedido por Tomás), certificar la devolución
    ya NO deja el activo 'Disponible' de inmediato: queda en 'Devolución', sin asignar a nadie,
    con la fecha registrada y bloqueado hasta que un admin lo revise (ver test_inventario_
    devolucion.py para el bloqueo en sí)."""
    activo_id = _crear_activo(app, nombre='Laptop HP', asignado_a='María López')

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'observaciones': 'Entregada en buen estado'})

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE id = ?", (activo_id,))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    assert estado == 'Devolución'
    assert asignado_a is None
    assert fecha_devolucion  # se registró la fecha de la devolución
    cur.execute("SELECT colaborador, confirmado_por, observaciones FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'María López'
    assert fila[1] == 'admin'
    assert fila[2] == 'Entregada en buen estado'


def test_gestion_humana_puede_confirmar_devolucion(client, app, crear_usuario):
    crear_usuario(usuario='rrhh1', rol='gestion_humana')
    _sesion_gestion_humana(client, app)
    activo_id = _crear_activo(app, nombre='Monitor LG', asignado_a='Carlos Ruiz')

    r = client.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Devolución'
    conn.close()


def test_no_se_puede_bloquear_usuario_con_activo_pendiente_de_devolucion(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Duván Cabarcas', rol='estandar')
    _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    usuario_id = cur.fetchone()[0]
    conn.close()

    admin_session.post(f'/usuarios/toggle_estado/{usuario_id}', follow_redirects=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM usuarios WHERE id = ?", (usuario_id,))
    estado = cur.fetchone()[0]
    conn.close()
    assert (estado or 'activo') == 'activo'  # sigue activo: el bloqueo quedó rechazado


def test_se_puede_bloquear_usuario_tras_certificar_la_devolucion(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Duván Cabarcas', rol='estandar')
    activo_id = _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    usuario_id = cur.fetchone()[0]
    conn.close()

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})
    admin_session.post(f'/usuarios/toggle_estado/{usuario_id}')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM usuarios WHERE id = ?", (usuario_id,))
    estado = cur.fetchone()[0]
    conn.close()
    assert estado == 'inactivo'


def test_exportar_certificacion_devoluciones_csv(admin_session, app):
    activo_id = _crear_activo(app, nombre='Impresora Epson', asignado_a='Ana Torres')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    r = admin_session.get('/inventario/certificacion_devoluciones/exportar_csv')

    assert r.status_code == 200
    assert 'text/csv' in r.headers.get('Content-Type', '')
    texto = r.get_data(as_text=True)
    assert 'COLABORADOR' in texto and 'Ana Torres' in texto


def test_certificacion_devoluciones_tiene_boton_de_tema_claro_oscuro(admin_session):
    """Esta pantalla se había quedado sin el botón flotante de tema claro/oscuro que sí tienen
    las demás páginas del sistema — se agrega para que sea consistente."""
    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'action="/perfil/tema"' in texto
    assert 'fa-sun' in texto or 'fa-moon' in texto
