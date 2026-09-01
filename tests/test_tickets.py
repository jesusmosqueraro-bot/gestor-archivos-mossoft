"""Pruebas del módulo de Tickets: creación básica y visibilidad por rol — un usuario
'estandar' solo debe ver las solicitudes que él mismo creó, mientras que el equipo operativo
(agente/admin) ve todas."""


def _crear_ticket(client, titulo="Impresora no enciende"):
    return client.post('/tickets/crear', data={
        'titulo': titulo,
        'descripcion': '<p>La impresora del piso 2 no enciende desde esta mañana.</p>',
        'tipo': 'Incidente',
        'categoria': 'Hardware',
        'prioridad': 'Media',
    }, follow_redirects=False)


def test_crear_ticket_redirige_a_listado(sesion_usuario):
    r = _crear_ticket(sesion_usuario)

    assert r.status_code == 302
    assert '/tickets' in r.headers.get('Location', '')


def test_ticket_creado_aparece_en_el_listado_del_creador(sesion_usuario):
    _crear_ticket(sesion_usuario, titulo="Impresora no enciende")

    r = sesion_usuario.get('/tickets')

    assert r.status_code == 200
    assert 'Impresora no enciende' in r.get_data(as_text=True)


def test_usuario_estandar_no_ve_tickets_ajenos(client, app, crear_usuario):
    # Usuario A crea un ticket.
    usuario_a = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_a
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    _crear_ticket(client, titulo="Solicitud confidencial de A")

    # Usuario B (otro estándar) NO debe ver el ticket de A en su propio listado.
    usuario_b = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['username'] = usuario_b

    r = client.get('/tickets')

    assert r.status_code == 200
    assert 'Solicitud confidencial de A' not in r.get_data(as_text=True)


def test_agente_ve_tickets_de_todos_los_usuarios(client, app, crear_usuario):
    usuario_estandar = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_estandar
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    _crear_ticket(client, titulo="Ticket visible para soporte")

    agente = crear_usuario(rol='agente')
    with client.session_transaction() as sess:
        sess['username'] = agente
        sess['rol'] = 'agente'

    r = client.get('/tickets')

    assert r.status_code == 200
    assert 'Ticket visible para soporte' in r.get_data(as_text=True)
