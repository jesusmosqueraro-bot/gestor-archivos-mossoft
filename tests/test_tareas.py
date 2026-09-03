"""Pruebas del módulo de Tareas de Tickets: bloqueo de cierre con tareas pendientes, bitácora
de cambios de estado, la cola personal "Mis Tareas" y la métrica de tareas completadas por
agente en Indicadores — las 4 mejoras inspiradas en la pestaña "Tareas" de Aranda Service Desk
que Tomás pidió construir a partir de esas capturas."""


def _crear_ticket_directo(app, estado='Abierto', asignado_a=None, creado_por='admin'):
    """Inserta un ticket directo en la BD (sin pasar por /tickets/crear, que siempre arranca en
    'Abierto' y no deja elegir el estado inicial) para poder probar el bloqueo de cierre desde
    'En Proceso' sin tener que reproducir aquí toda la máquina de estados de _estados_disponibles_ticket."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    fecha = '2026-08-31 10:00:00'
    if db_type == 'postgres':
        q = ("INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion) "
             "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id")
        cur.execute(q, ('Ticket de prueba', 'Descripción de prueba', 'Incidente', 'Hardware', 'Media', estado, creado_por, asignado_a, fecha, fecha))
        ticket_id = cur.fetchone()[0]
    else:
        q = ("INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion) "
             "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
        cur.execute(q, ('Ticket de prueba', 'Descripción de prueba', 'Incidente', 'Hardware', 'Media', estado, creado_por, asignado_a, fecha, fecha))
        ticket_id = cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def _crear_tarea(client, ticket_id, asunto="Revisar con el proveedor", responsable=None):
    data = {'asunto': asunto}
    if responsable:
        data['responsable'] = responsable
    return client.post(f'/tickets/{ticket_id}/tareas/crear', data=data, follow_redirects=False)


def _estado_ticket(app, ticket_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    ph = '%s' if db_type == 'postgres' else '?'
    cur.execute(f"SELECT estado FROM tickets WHERE id = {ph}", (ticket_id,))
    fila = cur.fetchone()
    conn.close()
    return fila[0] if fila else None


def _id_tarea_creada(app, ticket_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    ph = '%s' if db_type == 'postgres' else '?'
    cur.execute(f"SELECT id FROM tickets_tareas WHERE ticket_id = {ph} ORDER BY id DESC LIMIT 1", (ticket_id,))
    fila = cur.fetchone()
    conn.close()
    return fila[0]


def test_no_se_puede_resolver_ticket_con_tareas_pendientes(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='En Proceso')
    _crear_tarea(admin_session, ticket_id, asunto="Confirmar con el usuario")

    r = admin_session.post(f'/tickets/{ticket_id}/actualizar',
                            data={'estado': 'Resuelto', 'prioridad': 'Media', 'asignado_a': 'admin'},
                            follow_redirects=True)

    assert r.status_code == 200
    assert 'tarea' in r.get_data(as_text=True).lower()  # el mensaje flash explica el motivo
    assert _estado_ticket(app, ticket_id) == 'En Proceso'  # el estado NO cambió


def test_se_puede_resolver_ticket_con_tareas_completadas_o_canceladas(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='En Proceso')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea A")
    _crear_tarea(admin_session, ticket_id, asunto="Tarea B")

    conn, db_type = app.get_db()
    cur = conn.cursor()
    ph = '%s' if db_type == 'postgres' else '?'
    cur.execute(f"SELECT id FROM tickets_tareas WHERE ticket_id = {ph} ORDER BY id ASC", (ticket_id,))
    ids_tareas = [f[0] for f in cur.fetchall()]
    conn.close()
    assert len(ids_tareas) == 2

    admin_session.post(f'/tickets/{ticket_id}/tareas/{ids_tareas[0]}/estado', data={'estado': 'completada'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{ids_tareas[1]}/estado', data={'estado': 'cancelada'})

    r = admin_session.post(f'/tickets/{ticket_id}/actualizar',
                            data={'estado': 'Resuelto', 'prioridad': 'Media', 'asignado_a': 'admin'})

    assert r.status_code == 302
    assert _estado_ticket(app, ticket_id) == 'Resuelto'


def test_cambiar_estado_tarea_registra_en_logs(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Actualizar el servidor")
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT detalles FROM logs WHERE accion = 'Estado de Tarea de Ticket Actualizado' ORDER BY id DESC LIMIT 1")
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    assert 'en_progreso' in fila[0]


def test_mis_tareas_solo_muestra_las_del_agente_responsable(client, app, crear_usuario):
    agente_1 = crear_usuario(rol='agente', nombre='Agente Uno')
    agente_2 = crear_usuario(rol='agente', nombre='Agente Dos')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = agente_1
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    _crear_tarea(client, ticket_id, asunto="Tarea solo de Agente Uno", responsable=agente_1)

    r1 = client.get('/tickets/mis_tareas')
    assert r1.status_code == 200
    assert 'Tarea solo de Agente Uno' in r1.get_data(as_text=True)

    with client.session_transaction() as sess:
        sess['username'] = agente_2

    r2 = client.get('/tickets/mis_tareas')
    assert r2.status_code == 200
    assert 'Tarea solo de Agente Uno' not in r2.get_data(as_text=True)


def test_mis_tareas_oculta_completadas_salvo_que_se_pida_ver_todas(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea ya resuelta", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    r_activas = admin_session.get('/tickets/mis_tareas')
    assert 'Tarea ya resuelta' not in r_activas.get_data(as_text=True)

    r_todas = admin_session.get('/tickets/mis_tareas?todas=1')
    assert 'Tarea ya resuelta' in r_todas.get_data(as_text=True)


def test_indicadores_muestra_top_agentes_por_tareas_completadas(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea completada por admin", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    r = admin_session.get('/tickets/indicadores')

    assert r.status_code == 200
    assert 'Top agentes por tareas completadas' in r.get_data(as_text=True)
