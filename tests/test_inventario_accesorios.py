"""Checklist de accesorios entregados con un activo (pedido por Tomás, 08/09/2026): "incluye
campos como si tiene teclado, mouse, adaptadores, y más esto al momento de la asignación, ojala
sea con check box y que estos también se tomen en el módulo de devolución". Cubre: los accesorios
marcados quedan guardados al crear/editar un activo (activos_inventario.accesorios_asignados),
se muestran en Pendientes de devolución, y lo que se marca como "regresó" en la certificación
queda guardado en inventario_devoluciones.accesorios_devueltos."""


def _crear_activo(app, nombre='Laptop de Prueba', estado='Asignado', asignado_a='Juan Pérez', accesorios_asignados=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por, accesorios_asignados) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por, accesorios_asignados) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, '2026-09-01 09:00:00', 'admin', accesorios_asignados))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_guarda_los_accesorios_marcados(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15200', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_teclado': 'on', 'accesorio_mouse': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_asignados FROM activos_inventario WHERE nombre = ?", ('15200',))
    accesorios = cur.fetchone()[0]
    conn.close()
    assert accesorios is not None
    claves = accesorios.split(',')
    assert 'teclado' in claves and 'mouse' in claves
    assert 'cargador' not in claves


def test_crear_activo_sin_marcar_ningun_accesorio_guarda_none(admin_session, app):
    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15201', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_asignados FROM activos_inventario WHERE nombre = ?", ('15201',))
    accesorios = cur.fetchone()[0]
    conn.close()
    assert accesorios is None


def test_editar_activo_actualiza_los_accesorios_marcados(admin_session, app):
    activo_id = _crear_activo(app, nombre='15202', estado='Disponible', asignado_a=None, accesorios_asignados='teclado')

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '15202', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_mouse': 'on', 'accesorio_maletin': 'on',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_asignados FROM activos_inventario WHERE id = ?", (activo_id,))
    accesorios = cur.fetchone()[0]
    conn.close()
    claves = accesorios.split(',')
    assert 'mouse' in claves and 'maletin' in claves
    assert 'teclado' not in claves  # se reemplaza por completo, no se acumula


def test_inventario_muestra_el_catalogo_de_accesorios_en_el_modal(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'input-accesorio-teclado' in texto
    assert 'input-accesorio-mouse' in texto
    assert 'Accesorios entregados' in texto


def test_pendientes_de_devolucion_muestra_los_accesorios_asignados(admin_session, app):
    _crear_activo(app, nombre='15203', asignado_a='Carlos Ruiz', accesorios_asignados='teclado,mouse')

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'accesorio_devuelto_teclado' in texto
    assert 'accesorio_devuelto_mouse' in texto
    assert 'Accesorios que regresaron' in texto


def test_pendiente_sin_accesorios_asignados_no_muestra_la_seccion(admin_session, app):
    _crear_activo(app, nombre='15204', asignado_a='Ana Torres', accesorios_asignados=None)

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'Accesorios que regresaron' not in texto


def test_confirmar_devolucion_guarda_los_accesorios_que_regresaron(admin_session, app):
    activo_id = _crear_activo(app, nombre='15205', asignado_a='Sofía Ramírez', accesorios_asignados='teclado,mouse,cargador')

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'accesorio_devuelto_teclado': 'on', 'accesorio_devuelto_cargador': 'on',
        # mouse no vuelve marcado: se entiende que no regresó
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_devueltos FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    accesorios_devueltos = cur.fetchone()[0]
    conn.close()
    claves = accesorios_devueltos.split(',')
    assert 'teclado' in claves and 'cargador' in claves
    assert 'mouse' not in claves


def test_confirmar_devolucion_sin_marcar_ningun_accesorio_guarda_none(admin_session, app):
    activo_id = _crear_activo(app, nombre='15206', asignado_a='Pedro Salas', accesorios_asignados='teclado')

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_devueltos FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    accesorios_devueltos = cur.fetchone()[0]
    conn.close()
    assert accesorios_devueltos is None


def test_historial_muestra_los_accesorios_que_regresaron(admin_session, app):
    activo_id = _crear_activo(app, nombre='15207', asignado_a='Rita Solano', accesorios_asignados='teclado,mouse')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'accesorio_devuelto_teclado': 'on'})

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'Teclado' in texto  # aparece en la columna "Accesorios devueltos" del historial
