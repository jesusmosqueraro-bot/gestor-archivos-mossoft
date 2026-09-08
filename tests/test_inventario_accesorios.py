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

    # Nota: "Accesorios que regresaron" también aparece dentro de un comentario del <script> de
    # esta página (ver actualizarDetalleAccesorioDevueltoOtro), así que se verifica la ausencia
    # del bloque renderizado en sí, no solo del texto suelto.
    assert 'fa-boxes-packing mr-1 text-teal-400' not in texto


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


# ────────────────────────────────────────────────────────────────────────────
# "Adaptador de red" (pedido por Tomás, 08/09/2026: "falta adaptador de red etc") — un accesorio
# más del catálogo, funciona exactamente igual que los demás.
# ────────────────────────────────────────────────────────────────────────────

def test_inventario_muestra_adaptador_de_red_en_el_modal(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'input-accesorio-adaptador_red' in texto
    assert 'Adaptador de red' in texto


def test_crear_activo_guarda_el_adaptador_de_red_marcado(admin_session, app):
    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15208', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_adaptador_red': 'on',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_asignados FROM activos_inventario WHERE nombre = ?", ('15208',))
    accesorios = cur.fetchone()[0]
    conn.close()
    assert 'adaptador_red' in accesorios.split(',')


# ────────────────────────────────────────────────────────────────────────────
# "Otro" con campo de texto obligatorio (pedido por Tomás, 08/09/2026: "un check que diga otro y
# que habilite un campo de texto si este se marca y que sea obligación diligenciarlo, integrar lo
# que se escriba o diligencie en el formulario de devolución") — ver ACCESORIO_CLAVE_OTRO/
# _detalle_otro_accesorio en app.py.
# ────────────────────────────────────────────────────────────────────────────

def test_inventario_muestra_la_casilla_otro_y_su_campo_de_texto_en_el_modal(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'input-accesorio-otro' in texto
    assert 'input-accesorio-otro-detalle' in texto


def test_crear_activo_marcando_otro_sin_detalle_rechaza_y_no_guarda(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15209', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_otro': 'on',
        # 'accesorio_otro_detalle' no viene: la casilla "Otro" está marcada pero sin especificar
    }, follow_redirects=True)

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'no especificaste cuál' in texto
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('15209',))
    assert cur.fetchone()[0] == 0  # no se creó nada
    conn.close()


def test_crear_activo_marcando_otro_con_detalle_lo_guarda(admin_session, app):
    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15210', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_otro': 'on', 'accesorio_otro_detalle': 'Base refrigerante',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_asignados, accesorio_otro_detalle FROM activos_inventario WHERE nombre = ?", ('15210',))
    accesorios, detalle = cur.fetchone()
    conn.close()
    assert 'otro' in accesorios.split(',')
    assert detalle == 'Base refrigerante'


def test_crear_activo_sin_marcar_otro_ignora_el_texto_que_llegue(admin_session, app):
    """Si la casilla no está marcada, el texto no se guarda aunque venga en el formulario
    (formulario manipulado, o texto que quedó escrito y luego se desmarcó la casilla)."""
    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '15211', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_otro_detalle': 'No debería guardarse',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorio_otro_detalle FROM activos_inventario WHERE nombre = ?", ('15211',))
    detalle = cur.fetchone()[0]
    conn.close()
    assert detalle is None


def test_editar_activo_marcando_otro_sin_detalle_rechaza(admin_session, app):
    activo_id = _crear_activo(app, nombre='15212', estado='Disponible', asignado_a=None)

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '15212', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'accesorio_otro': 'on',
    }, follow_redirects=True)

    assert 'no especificaste cuál' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorio_otro_detalle FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] is None
    conn.close()


def test_pendiente_con_otro_muestra_el_detalle_asignado_y_el_campo_de_texto(admin_session, app):
    _crear_activo(app, nombre='15213', asignado_a='Laura Gómez', accesorios_asignados='teclado,otro')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE activos_inventario SET accesorio_otro_detalle = ? WHERE nombre = ?", ('Base refrigerante', '15213'))
    conn.commit()
    conn.close()

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'accesorio_devuelto_otro_detalle' in texto
    assert 'Base refrigerante' in texto


def test_confirmar_devolucion_marcando_otro_sin_detalle_rechaza_y_no_guarda(admin_session, app):
    activo_id = _crear_activo(app, nombre='15214', asignado_a='Marco Díaz', accesorios_asignados='otro')

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'accesorio_devuelto_otro': 'on',
    }, follow_redirects=True)

    assert 'no especificaste cuál' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0  # no quedó ningún registro a medias
    conn.close()


def test_confirmar_devolucion_marcando_otro_con_detalle_lo_guarda(admin_session, app):
    activo_id = _crear_activo(app, nombre='15215', asignado_a='Nadia Ríos', accesorios_asignados='otro')

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'accesorio_devuelto_otro': 'on', 'accesorio_devuelto_otro_detalle': 'Cable HDMI',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accesorios_devueltos, accesorio_otro_detalle FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    accesorios, detalle = cur.fetchone()
    conn.close()
    assert 'otro' in accesorios.split(',')
    assert detalle == 'Cable HDMI'


def test_historial_muestra_el_detalle_de_otro_junto_a_los_demas_accesorios(admin_session, app):
    activo_id = _crear_activo(app, nombre='15216', asignado_a='Tomás Vera', accesorios_asignados='teclado,otro')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'accesorio_devuelto_teclado': 'on',
        'accesorio_devuelto_otro': 'on', 'accesorio_devuelto_otro_detalle': 'Mousepad',
    })

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'Otro: Mousepad' in texto
