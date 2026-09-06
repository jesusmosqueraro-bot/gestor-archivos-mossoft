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

    # 🔒 Desde este cambio, una tarea no puede saltar directo de 'pendiente' a 'completada'/
    # 'cancelada' sin pasar antes por 'en_progreso' (ver _estados_disponibles_tarea en app.py).
    admin_session.post(f'/tickets/{ticket_id}/tareas/{ids_tareas[0]}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{ids_tareas[0]}/estado', data={'estado': 'completada'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{ids_tareas[1]}/estado', data={'estado': 'en_progreso'})
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
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    r_activas = admin_session.get('/tickets/mis_tareas')
    assert 'Tarea ya resuelta' not in r_activas.get_data(as_text=True)

    r_todas = admin_session.get('/tickets/mis_tareas?todas=1')
    assert 'Tarea ya resuelta' in r_todas.get_data(as_text=True)


def test_mis_tareas_subnav_usa_el_mismo_ancho_que_los_demas_modulos(admin_session):
    """El sub-nav de Mis Tareas usaba max-w-4xl mientras el resto de módulos de Tickets usa
    max-w-7xl para el mismo contenedor — eso forzaba una barra de desplazamiento horizontal que
    no aparece en ninguna otra pestaña. Ver Task de Round 2 (screenshot con el scrollbar
    remarcado en rojo bajo el sub-nav)."""
    texto = admin_session.get('/tickets/mis_tareas').get_data(as_text=True)
    assert 'max-w-4xl mx-auto flex items-center gap-1 overflow-x-auto' not in texto
    assert 'max-w-7xl mx-auto flex items-center gap-1 overflow-x-auto' in texto


def _estado_tarea(app, tarea_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    ph = '%s' if db_type == 'postgres' else '?'
    cur.execute(f"SELECT estado FROM tickets_tareas WHERE id = {ph}", (tarea_id,))
    fila = cur.fetchone()
    conn.close()
    return fila[0] if fila else None


# ────────────────────────────────────────────────────────────────────────────
# Pedido por Tomás: una tarea no se puede marcar 'completada' ni 'cancelada' sin pasar antes
# por 'en_progreso' — mismas condiciones que ya rigen el cierre de un ticket (ver
# _estados_disponibles_tarea en app.py).
# ────────────────────────────────────────────────────────────────────────────

def test_no_se_puede_completar_una_tarea_pendiente_sin_pasar_por_en_progreso(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'}, follow_redirects=True)

    assert r.status_code == 200
    assert 'en progreso' in r.get_data(as_text=True).lower()
    assert _estado_tarea(app, tarea_id) == 'pendiente'


def test_no_se_puede_cancelar_una_tarea_pendiente_sin_pasar_por_en_progreso(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'cancelada'})

    assert _estado_tarea(app, tarea_id) == 'pendiente'


def test_se_puede_completar_una_tarea_que_ya_paso_por_en_progreso(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    assert _estado_tarea(app, tarea_id) == 'completada'


def test_una_tarea_completada_queda_bloqueada_y_no_se_puede_reabrir(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'pendiente'}, follow_redirects=True)

    assert r.status_code == 200
    assert 'ya quedó' in r.get_data(as_text=True).lower()
    assert _estado_tarea(app, tarea_id) == 'completada'  # no se movió


def test_una_tarea_cancelada_queda_bloqueada_y_no_se_puede_reabrir(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'cancelada'})

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})

    assert _estado_tarea(app, tarea_id) == 'cancelada'


def test_detalle_de_ticket_solo_ofrece_los_estados_alcanzables_en_el_select(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")

    html = admin_session.get(f'/tickets/{ticket_id}').get_data(as_text=True)

    assert 'value="pendiente"' in html
    assert 'value="en_progreso"' in html
    # Desde 'pendiente' no se debe poder elegir 'completada' ni 'cancelada' directamente.
    assert 'value="completada"' not in html
    assert 'value="cancelada"' not in html


# ────────────────────────────────────────────────────────────────────────────
# Pedido por Tomás: poder editar el asunto/notas/responsable/fecha límite de una tarea ya
# creada (antes solo se podía completar esa información al crearla).
# ────────────────────────────────────────────────────────────────────────────

def test_editar_tarea_actualiza_el_asunto(admin_session, app):
    """Las notas/avances de la tarea ya no se editan por acá — pedido por Tomás: deben
    comportarse como el módulo de Seguimiento de un ticket (ver
    test_agregar_seguimiento_guarda_autor_mensaje_y_fecha más abajo)."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Asunto original")
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/editar', data={
        'asunto': 'Asunto corregido'
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT asunto FROM tickets_tareas WHERE id = ?", (tarea_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Asunto corregido'


def test_editar_tarea_no_permite_asunto_vacio(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Asunto original")
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/editar', data={'asunto': '   '})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT asunto FROM tickets_tareas WHERE id = ?", (tarea_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Asunto original'


def test_editar_tarea_notifica_al_nuevo_responsable(admin_session, app, crear_usuario):
    agente = crear_usuario(rol='agente', nombre='Agente Reasignado')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea sin asignar")
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/editar', data={
        'asunto': 'Tarea sin asignar', 'responsable': agente
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje FROM notificaciones WHERE usuario = ? AND tipo = 'tarea'", (agente,))
    filas = cur.fetchall()
    conn.close()
    assert any('Tarea sin asignar' in m for (m,) in filas)


def _sesion_como(app, usuario, rol):
    """Cliente de pruebas nuevo, con sesión ya iniciada como 'usuario' — para probar acciones
    que dependen de QUIÉN las hace (ver test_editar_tarea_notifica_a_quien_creo_la_tarea_al_responder),
    a diferencia de admin_session que siempre es la cuenta 'admin'."""
    client = app.app.test_client()
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def test_agregar_seguimiento_guarda_autor_mensaje_y_fecha(admin_session, app, crear_usuario):
    """El historial de una tarea (pedido por Tomás: debe comportarse como el módulo de
    Seguimiento de un ticket) guarda cada nota con su autor y su fecha, sin pisar las
    anteriores — a diferencia de las viejas columnas 'descripcion'/'respuesta' que se
    sobrescribían."""
    agente = crear_usuario(rol='agente', nombre='Agente Que Responde')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Revisar con el proveedor", responsable=agente)
    tarea_id = _id_tarea_creada(app, ticket_id)

    cliente_agente = _sesion_como(app, agente, 'agente')
    r = cliente_agente.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Ya hablé con el proveedor, envían la pieza el viernes.'
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT autor, mensaje FROM tickets_tareas_seguimientos WHERE tarea_id = ?", (tarea_id,))
    filas = cur.fetchall()
    conn.close()
    assert len(filas) == 1
    assert filas[0][0] == agente
    assert filas[0][1] == 'Ya hablé con el proveedor, envían la pieza el viernes.'


def test_agregar_seguimiento_no_borra_las_notas_anteriores(admin_session, app, crear_usuario):
    """A diferencia del viejo campo 'respuesta' que se sobrescribía, cada nota nueva se agrega
    al historial sin borrar las que ya estaban."""
    agente = crear_usuario(rol='agente', nombre='Agente Que Responde')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Revisar con el proveedor", responsable=agente)
    tarea_id = _id_tarea_creada(app, ticket_id)

    cliente_agente = _sesion_como(app, agente, 'agente')
    cliente_agente.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={'mensaje': 'Primera nota.'})
    cliente_agente.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={'mensaje': 'Segunda nota.'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje FROM tickets_tareas_seguimientos WHERE tarea_id = ? ORDER BY id ASC", (tarea_id,))
    mensajes = [m for (m,) in cur.fetchall()]
    conn.close()
    assert mensajes == ['Primera nota.', 'Segunda nota.']


def test_agregar_seguimiento_notifica_a_quien_creo_la_tarea(admin_session, app, crear_usuario):
    """Cuando el responsable deja una nota nueva, se le avisa a quien creó la tarea (si es
    alguien distinto) — para que no tenga que estar revisando el ticket a ver si ya
    contestaron."""
    agente = crear_usuario(rol='agente', nombre='Agente Que Responde')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Confirmar con el usuario", responsable=agente)
    tarea_id = _id_tarea_creada(app, ticket_id)

    cliente_agente = _sesion_como(app, agente, 'agente')
    cliente_agente.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Confirmado, el usuario ya puede acceder.'
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje FROM notificaciones WHERE usuario = 'admin' AND tipo = 'tarea'")
    filas = cur.fetchall()
    conn.close()
    assert any('Confirmar con el usuario' in m for (m,) in filas)


def test_agregar_seguimiento_no_notifica_si_el_autor_creo_la_tarea_y_es_el_responsable(admin_session, app):
    """Si la misma persona creó la tarea y es además la responsable (una nota para sí misma), no
    debe autonotificarse."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea de admin para sí mismo", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Ya quedó resuelto.'
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje FROM notificaciones WHERE usuario = 'admin' AND tipo = 'tarea'")
    filas = cur.fetchall()
    conn.close()
    assert not any('Tarea de admin para sí mismo' in m for (m,) in filas)


def test_editar_tarea_completada_no_cambia_su_estado(admin_session, app):
    """Se puede corregir el asunto de una tarea ya terminada sin que eso la reabra."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/editar', data={
        'asunto': 'Tarea nueva (corregida)'
    })

    assert _estado_tarea(app, tarea_id) == 'completada'


def test_agregar_seguimiento_a_una_tarea_completada_no_cambia_su_estado(admin_session, app):
    """Agregar una nota al historial de una tarea ya terminada tampoco debe reabrirla — el
    Seguimiento de un ticket tampoco depende de su estado."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea nueva")
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={'mensaje': 'Nota de cierre'})

    assert _estado_tarea(app, tarea_id) == 'completada'


def test_mis_tareas_pinta_el_formulario_de_editar_y_el_historial(admin_session, app):
    """El lápiz de editar (asunto/responsable/fecha límite) y el cuadro para agregar notas al
    historial de Seguimiento también deben existir en la cola personal 'Mis Tareas', no solo en
    el detalle del ticket — reportado por Tomás: 'Aun no esta abilitado el campo testo para las
    tareas' (probando justo desde esa pantalla)."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea con nota", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.get('/tickets/mis_tareas')
    html = r.get_data(as_text=True)

    assert f'form-editar-tarea-{tarea_id}' in html
    assert f'/tickets/{ticket_id}/tareas/{tarea_id}/editar' in html
    assert f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento' in html
    assert 'Escribe una nota o avance de esta tarea...' in html


def test_editar_tarea_desde_mis_tareas_redirige_a_mis_tareas(admin_session, app):
    """Al guardar la edición desde 'Mis Tareas' (origen=mis_tareas), debe volver ahí y no al
    detalle del ticket — mismo criterio que ya usa el cambio de estado en esa misma pantalla."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea original", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/editar', data={
        'asunto': 'Tarea editada desde Mis Tareas',
        'origen': 'mis_tareas', 'ver_todas': ''
    }, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers['Location'].endswith('/tickets/mis_tareas')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT asunto FROM tickets_tareas WHERE id = ?", (tarea_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Tarea editada desde Mis Tareas'


def test_agregar_seguimiento_desde_mis_tareas_redirige_a_mis_tareas(admin_session, app):
    """Igual que al editar asunto/responsable/fecha límite: agregar una nota desde 'Mis Tareas'
    (origen=mis_tareas) debe volver ahí y no al detalle del ticket."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea original", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Nota desde mis tareas', 'origen': 'mis_tareas', 'ver_todas': ''
    }, follow_redirects=False)

    assert r.status_code == 302
    assert r.headers['Location'].endswith('/tickets/mis_tareas')


def test_el_historial_de_la_tarea_esta_disponible_sin_importar_el_estado_ticket_detalle(admin_session, app):
    """Pedido por Tomás: el historial de una tarea debe comportarse como el módulo de
    Seguimiento de un ticket, que no depende de ningún estado — se puede agregar una nota
    aunque la tarea siga 'pendiente', sin tener que pasarla antes a 'En progreso'."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea pendiente", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    html_pendiente = admin_session.get(f'/tickets/{ticket_id}').get_data(as_text=True)
    assert f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento' in html_pendiente
    assert 'Escribe una nota o avance de esta tarea...' in html_pendiente

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={'mensaje': 'Nota en pendiente'})
    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje FROM tickets_tareas_seguimientos WHERE tarea_id = ?", (tarea_id,))
    filas = cur.fetchall()
    conn.close()
    assert any(m == 'Nota en pendiente' for (m,) in filas)


def test_el_historial_de_la_tarea_esta_disponible_sin_importar_el_estado_mis_tareas(admin_session, app):
    """Mismo criterio que en ticket_detalle.html, pero desde la cola personal 'Mis Tareas'."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea pendiente", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    html_pendiente = admin_session.get('/tickets/mis_tareas').get_data(as_text=True)
    assert f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento' in html_pendiente
    assert 'Escribe una nota o avance de esta tarea...' in html_pendiente


def test_agregar_seguimiento_no_toca_asunto_responsable_ni_fecha_limite(admin_session, app, crear_usuario):
    """Agregar una nota al historial no debe tocar el resto de los campos de la tarea —
    reproduce el caso que antes cubría el cuadro rápido de respuesta, ahora contra el nuevo
    historial de Seguimiento."""
    agente = crear_usuario(rol='agente', nombre='Agente En Progreso')
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    admin_session.post(f'/tickets/{ticket_id}/tareas/crear', data={
        'asunto': 'Revisar impresora', 'responsable': agente, 'fecha_limite': '2026-12-31'
    })
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})

    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Ya se cambió el tóner.'
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT asunto, responsable, fecha_limite FROM tickets_tareas WHERE id = ?", (tarea_id,))
    fila = cur.fetchone()
    cur.execute("SELECT mensaje FROM tickets_tareas_seguimientos WHERE tarea_id = ?", (tarea_id,))
    seguimiento = cur.fetchone()
    conn.close()
    assert fila[0] == 'Revisar impresora'
    assert fila[1] == agente
    assert fila[2] == '2026-12-31'
    assert seguimiento[0] == 'Ya se cambió el tóner.'


def test_agregar_seguimiento_confirma_con_un_mensaje(admin_session, app):
    """Reportado por Tomás con video: al presionar 'enviar' en el cuadro de respuesta rápida no
    pasaba nada visible — el texto se guardaba, pero como el mismo cuadro se vuelve a llenar con
    ese mismo valor al recargar, en pantalla parecía que 'no se publicaba'. Debe confirmarse con
    un mensaje, igual que el resto de acciones de la app (p. ej. cambiar el estado de la tarea)."""
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea con respuesta", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)

    r = admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/seguimiento', data={
        'mensaje': 'Ya revisé el switch y sigue sin señal.'
    }, follow_redirects=True)

    assert 'nota agregada' in r.get_data(as_text=True).lower()


def test_indicadores_muestra_top_agentes_por_tareas_completadas(admin_session, app):
    ticket_id = _crear_ticket_directo(app, estado='Abierto')
    _crear_tarea(admin_session, ticket_id, asunto="Tarea completada por admin", responsable='admin')
    tarea_id = _id_tarea_creada(app, ticket_id)
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'en_progreso'})
    admin_session.post(f'/tickets/{ticket_id}/tareas/{tarea_id}/estado', data={'estado': 'completada'})

    r = admin_session.get('/tickets/indicadores')

    assert r.status_code == 200
    assert 'Top agentes por tareas completadas' in r.get_data(as_text=True)
