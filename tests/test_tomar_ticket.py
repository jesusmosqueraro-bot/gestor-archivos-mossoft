"""Botón "Tomar caso" — pedido por Tomás (07/09/2026): las notificaciones de un ticket nuevo
sin asignar ya llegan a TODO el equipo de soporte activo (ver _equipo_soporte_activo /
crear_notificacion_para_varios en app.py); esto añade una acción de un solo clic para que el
primer agente que decida atender el caso se lo asigne a sí mismo, en vez de tener que pasar por
el desplegable "Asignar a" del panel de gestión. Cubre: la asignación exitosa y sus avisos, que
no se pueda tomar un ticket ya asignado ni uno cerrado, y que un usuario 'estandar' no tenga
acceso a la ruta."""
from tests.test_tickets import _crear_ticket


def _sesion_como(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _sesion_agente(client, app, crear_usuario, usuario='agente_prueba'):
    crear_usuario(usuario=usuario, rol='agente')
    return _sesion_como(client, app, usuario, 'agente')


def _crear_ticket_como_estandar(client, app, crear_usuario, titulo):
    solicitante = crear_usuario(rol='estandar')
    _sesion_como(client, app, solicitante, 'estandar')
    _crear_ticket(client, titulo=titulo)
    return solicitante


def _estado_ticket(app, titulo):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, asignado_a, estado FROM tickets WHERE titulo = ?", (titulo,))
    fila = cur.fetchone()
    conn.close()
    return fila  # (id, asignado_a, estado)


def test_agente_puede_tomar_un_ticket_sin_asignar(client, app, crear_usuario):
    _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket libre para tomar")
    ticket_id, asignado_antes, _ = _estado_ticket(app, "Ticket libre para tomar")
    assert asignado_antes is None

    _sesion_agente(client, app, crear_usuario, usuario='agente_toma')
    r = client.post(f'/tickets/{ticket_id}/tomar', follow_redirects=True)

    assert r.status_code == 200
    _, asignado_despues, _ = _estado_ticket(app, "Ticket libre para tomar")
    assert asignado_despues == 'agente_toma'
    assert 'Tomaste el caso' in r.get_data(as_text=True)


def test_tomar_el_caso_deja_un_comentario_de_sistema(client, app, crear_usuario):
    _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket con rastro de sistema")
    ticket_id, _, _ = _estado_ticket(app, "Ticket con rastro de sistema")

    _sesion_agente(client, app, crear_usuario, usuario='agente_rastro')
    client.post(f'/tickets/{ticket_id}/tomar')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje, tipo FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
    mensaje, tipo = cur.fetchone()
    conn.close()
    assert tipo == 'sistema'
    assert 'agente_rastro' in mensaje


def test_no_se_puede_tomar_un_ticket_que_ya_tiene_dueno(client, app, crear_usuario):
    _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket ya tomado")
    ticket_id, _, _ = _estado_ticket(app, "Ticket ya tomado")

    _sesion_agente(client, app, crear_usuario, usuario='agente_primero')
    client.post(f'/tickets/{ticket_id}/tomar')

    _sesion_agente(client, app, crear_usuario, usuario='agente_segundo')
    r = client.post(f'/tickets/{ticket_id}/tomar', follow_redirects=True)

    assert 'ya fue tomado por' in r.get_data(as_text=True)
    _, asignado, _ = _estado_ticket(app, "Ticket ya tomado")
    assert asignado == 'agente_primero'


def test_no_se_puede_tomar_un_ticket_cerrado(client, app, crear_usuario):
    _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket cerrado para probar")
    ticket_id, _, _ = _estado_ticket(app, "Ticket cerrado para probar")

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET estado = 'Cerrado' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()

    _sesion_agente(client, app, crear_usuario, usuario='agente_tardio')
    r = client.post(f'/tickets/{ticket_id}/tomar', follow_redirects=True)

    assert 'ya está cerrado' in r.get_data(as_text=True)
    _, asignado, _ = _estado_ticket(app, "Ticket cerrado para probar")
    assert asignado is None


def test_usuario_estandar_no_puede_tomar_un_ticket(client, app, crear_usuario):
    _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket fuera del alcance de estandar")
    ticket_id, _, _ = _estado_ticket(app, "Ticket fuera del alcance de estandar")

    otro_estandar = crear_usuario(rol='estandar')
    _sesion_como(client, app, otro_estandar, 'estandar')
    client.post(f'/tickets/{ticket_id}/tomar')

    _, asignado, _ = _estado_ticket(app, "Ticket fuera del alcance de estandar")
    assert asignado is None


def test_al_tomar_el_caso_se_notifica_al_resto_del_equipo_y_al_solicitante(client, app, crear_usuario):
    solicitante = _crear_ticket_como_estandar(client, app, crear_usuario, "Ticket con avisos")
    ticket_id, _, _ = _estado_ticket(app, "Ticket con avisos")
    crear_usuario(usuario='agente_espectador', rol='agente')

    _sesion_agente(client, app, crear_usuario, usuario='agente_toma_2')
    client.post(f'/tickets/{ticket_id}/tomar')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT usuario, mensaje FROM notificaciones ORDER BY id ASC")
    filas = cur.fetchall()
    conn.close()
    destinatarios = {u: m for u, m in filas}
    assert 'agente_espectador' in destinatarios
    assert 'agente_toma_2' in destinatarios['agente_espectador']
    assert solicitante in destinatarios
    assert 'agente_toma_2' in destinatarios[solicitante]
