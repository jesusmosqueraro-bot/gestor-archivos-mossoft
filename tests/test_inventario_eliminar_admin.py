"""Pruebas de la restricción pedida por Tomás: 'que el botón de eliminar un activo, solo quede
activo para los usuarios con rol administradores'. Antes cualquier agente con acceso operativo
podía eliminar (soft-delete) un activo del Inventario; ahora esa acción queda reservada a admin."""


def _sesion_agente(client, app, usuario='agente_eliminar'):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _crear_activo_directo(app, nombre='50001'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', 'Disponible', '2026-09-01 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_agente_no_puede_eliminar_un_activo(client, app):
    activo_id = _crear_activo_directo(app, nombre='50001')
    _sesion_agente(client, app)

    r = client.post(f'/tickets/inventario/{activo_id}/eliminar', follow_redirects=False)

    assert r.status_code in (302, 403)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT eliminado FROM activos_inventario WHERE id = ?", (activo_id,))
    eliminado = cur.fetchone()[0]
    conn.close()
    assert not eliminado  # sigue existiendo: el agente NO pudo eliminarlo


def test_admin_si_puede_eliminar_un_activo(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='50002')

    r = admin_session.post(f'/tickets/inventario/{activo_id}/eliminar', follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT eliminado FROM activos_inventario WHERE id = ?", (activo_id,))
    eliminado = cur.fetchone()[0]
    conn.close()
    assert eliminado


def test_boton_eliminar_no_aparece_para_agente_en_la_tabla(client, app):
    activo_id = _crear_activo_directo(app, nombre='50003')
    _sesion_agente(client, app)

    texto = client.get('/tickets/inventario').get_data(as_text=True)

    assert f'/tickets/inventario/{activo_id}/eliminar' not in texto


def test_boton_eliminar_si_aparece_para_admin_en_la_tabla(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='50004')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert f'/tickets/inventario/{activo_id}/eliminar' in texto
