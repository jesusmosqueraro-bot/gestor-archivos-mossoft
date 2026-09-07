"""Pruebas de la conversación en vivo con un agente humano dentro del Asistente de Chat (pedido
por Tomás): al escalar ('Hablar con un agente humano'), la charla deja de ser el árbol de menú y
pasa a reflejar el hilo de comentarios del propio ticket creado — la MISMA conversación que ve
el agente en Mesa de Ayuda (tickets_comentarios / comentar_ticket()), no un canal aparte. Cubre:
que el mensaje de confirmación se quede como última línea (no vuelve al menú de inmediato), que
lo que escriba el usuario se guarde como comentario real del ticket y que la respuesta de un
agente aparezca en la transcripción del Asistente, que elegir la opción de nuevo reutilice el
mismo ticket en vez de duplicar, que los recordatorios de inactividad del menú NO apliquen en
esta espera, y que la conversación termine sola en cuanto el ticket se cierra."""
from tests.test_chat_bot_asistente import _iniciar_sesion, _preparar_estandar_con_asistente_habilitado


def _obtener_ticket_escalado(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT id, estado FROM tickets WHERE creado_por = ? AND titulo = 'Escalado desde el Asistente de Chat'",
        (usuario,)
    )
    fila = cur.fetchone()
    conn.close()
    return fila


def _cerrar_ticket(app, ticket_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET estado = 'Cerrado' WHERE id = ?", (ticket_id,))
    conn.commit()
    conn.close()


def _asignar_ticket(app, ticket_id, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE tickets SET asignado_a = ? WHERE id = ?", (usuario, ticket_id))
    conn.commit()
    conn.close()


def _escalar(client):
    client.get('/chat/bot/estado')
    client.post('/chat/bot/enviar', data={'mensaje': '4'})
    return client.post('/chat/bot/enviar', data={'mensaje': 'No puedo entrar al sistema, es urgente.'})


def test_escalar_no_regresa_al_menu_se_queda_esperando_agente(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)

    r = _escalar(client)

    mensajes = r.get_json()['mensajes']
    assert mensajes[-1]['opciones'] is None
    assert 'seguir la conversación aquí mismo' in mensajes[-1]['mensaje']


def test_mensaje_del_usuario_se_guarda_como_comentario_real_del_ticket(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)

    r = client.post('/chat/bot/enviar', data={'mensaje': 'Sigo sin poder entrar, ¿alguna novedad?'})

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT autor, mensaje FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
    autor, mensaje_html = cur.fetchone()
    conn.close()
    assert autor == usuario
    assert 'Sigo sin poder entrar' in mensaje_html
    # No debe haberse guardado también como mensaje del menú (se duplicaría en la transcripción).
    assert 'Sigo sin poder entrar' not in [m['mensaje'] for m in app._bot_transcripcion(usuario)]


def test_respuesta_de_un_agente_aparece_en_la_transcripcion_del_asistente(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)

    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')
    _asignar_ticket(app, ticket_id, agente)
    _iniciar_sesion(client, app, agente, 'agente')
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': '<p>Ya estoy revisando tu caso.</p>'})

    _iniciar_sesion(client, app, usuario, 'estandar')
    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    assert any('Agente de Soporte' in m['mensaje'] and 'Ya estoy revisando tu caso' in m['mensaje'] for m in mensajes)


# 🐛 Hallazgo reportado por Tomás (07/09/2026, con capturas): un comentario del agente con un
# adjunto (por ejemplo una firma/foto) se veía en Mesa de Ayuda (ticket_detalle.html) pero no en
# la ventana del Asistente de Chat del colaborador — solo aparecía el texto de relleno "(adjuntó
# archivo(s) sin comentario)", sin la imagen, porque _bot_transcripcion_ticket() descartaba los
# adjuntos al convertir el comentario a texto plano.

def test_adjunto_de_un_comentario_del_agente_aparece_en_la_transcripcion_del_asistente(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)

    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')
    _asignar_ticket(app, ticket_id, agente)
    _iniciar_sesion(client, app, agente, 'agente')
    # El adjunto real (Cloudinary) no se puede simular fácil vía upload en las pruebas, así que —
    # igual que _crear_entrada_personal en test_boveda_personal.py — se inserta directo en
    # tickets_adjuntos tras crear el comentario mediante la ruta real.
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': 'Te comparto mi firma para el formato.'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
    com_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO tickets_adjuntos (ticket_id, comentario_id, url, nombre_original, subido_por, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (ticket_id, com_id, 'https://res.cloudinary.com/demo/firma.png', 'firma.png', agente, '2026-09-07 07:43:48'),
    )
    conn.commit()
    conn.close()

    _iniciar_sesion(client, app, usuario, 'estandar')
    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    con_adjunto = next((m for m in mensajes if m.get('adjuntos')), None)
    assert con_adjunto is not None, "Ningún mensaje trajo la lista de adjuntos."
    assert con_adjunto['adjuntos'] == [{
        'url': 'https://res.cloudinary.com/demo/firma.png', 'nombre_original': 'firma.png', 'es_imagen': True,
    }]


def test_adjunto_no_imagen_de_un_comentario_se_marca_como_tal(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)

    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')
    _asignar_ticket(app, ticket_id, agente)
    _iniciar_sesion(client, app, agente, 'agente')
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': 'Aquí tienes el manual solicitado.'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
    com_id = cur.fetchone()[0]
    cur.execute(
        "INSERT INTO tickets_adjuntos (ticket_id, comentario_id, url, nombre_original, subido_por, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (ticket_id, com_id, 'https://res.cloudinary.com/demo/manual.pdf', 'manual.pdf', agente, '2026-09-07 07:43:48'),
    )
    conn.commit()
    conn.close()

    _iniciar_sesion(client, app, usuario, 'estandar')
    mensajes = client.get('/chat/bot/estado').get_json()['mensajes']

    con_adjunto = next((m for m in mensajes if m.get('adjuntos')), None)
    assert con_adjunto is not None
    assert con_adjunto['adjuntos'][0]['es_imagen'] is False


def test_elegir_hablar_con_agente_de_nuevo_reusa_el_mismo_ticket(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    # Vuelve al menú sin cerrar el caso.
    client.post('/chat/bot/enviar', data={'mensaje': 'volver'})

    r = client.post('/chat/bot/enviar', data={'mensaje': '4'})

    assert 'Ya tienes una conversación abierta' in r.get_json()['mensajes'][-1]['mensaje']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE creado_por = ? AND titulo = 'Escalado desde el Asistente de Chat'", (usuario,))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 1


def test_volver_desde_esperando_agente_no_comenta_nada_y_deja_el_ticket_abierto(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)

    r = client.post('/chat/bot/enviar', data={'mensaje': 'volver'})

    assert r.get_json()['mensajes'][-1]['opciones'] == [
        'Crear una solicitud de soporte', 'Consultar mis solicitudes',
        'Preguntas frecuentes', 'Hablar con un agente humano',
    ]
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets_comentarios WHERE ticket_id = ?", (ticket_id,))
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT estado FROM tickets WHERE id = ?", (ticket_id,))
    assert cur.fetchone()[0] == 'Abierto'
    conn.close()


def test_recordatorios_de_inactividad_no_aplican_mientras_espera_agente(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    import datetime
    nueva_fecha = (datetime.datetime.now(app.ZONA_HORARIA_COLOMBIA).replace(tzinfo=None) - datetime.timedelta(minutes=app.BOT_MINUTOS_INACTIVIDAD + 1)).strftime('%Y-%m-%d %H:%M:%S')
    cur.execute("UPDATE chat_bot_sesiones SET fecha_ultima_actividad = ? WHERE usuario = ?", (nueva_fecha, usuario))
    conn.commit()
    conn.close()

    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    assert app.BOT_MENSAJE_RECORDATORIO not in [m['mensaje'] for m in mensajes]


def test_conversacion_se_cierra_sola_cuando_el_ticket_se_cierra(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)
    _cerrar_ticket(app, ticket_id)

    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    assert 'fue cerrada' in mensajes[-2]['mensaje']
    assert mensajes[-1]['opciones'] == [
        'Crear una solicitud de soporte', 'Consultar mis solicitudes',
        'Preguntas frecuentes', 'Hablar con un agente humano',
    ]


def test_mensaje_a_ticket_ya_cerrado_termina_la_conversacion_en_vez_de_comentar(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id, _estado = _obtener_ticket_escalado(app, usuario)
    _cerrar_ticket(app, ticket_id)

    r = client.post('/chat/bot/enviar', data={'mensaje': 'Sigues ahi?'})

    assert 'fue cerrada' in r.get_json()['mensajes'][-2]['mensaje']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets_comentarios WHERE ticket_id = ?", (ticket_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


# 🐛 Hallazgo/pedido reportado por Tomás (07/09/2026, con videos): un ticket creado con "Crear
# una solicitud de soporte" (sin pasar por "Hablar con un agente humano") nunca entraba a
# 'esperando_agente', así que aunque un agente (probado con una cuenta 'agente' cualquiera, no
# solo el admin literal) le respondiera desde Mesa de Ayuda, esa respuesta nunca aparecía en el
# Asistente de Chat de la colaboradora — se quedaba viendo el menú de siempre. La intención de
# Tomás es que "cualquier agente o admin que tome un ticket pueda interactuar con el usuario
# desde el asistente de chat" en ambos sentidos, sin necesidad de haber escalado antes.

def _crear_ticket_via_opcion_1(client, titulo, descripcion="Descripción de prueba."):
    client.get('/chat/bot/estado')
    client.post('/chat/bot/enviar', data={'mensaje': '1'})
    client.post('/chat/bot/enviar', data={'mensaje': 'Otro'})
    client.post('/chat/bot/enviar', data={'mensaje': titulo})
    return client.post('/chat/bot/enviar', data={'mensaje': descripcion})


def _obtener_ticket_por_titulo(app, usuario, titulo):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, estado FROM tickets WHERE creado_por = ? AND titulo = ?", (usuario, titulo))
    fila = cur.fetchone()
    conn.close()
    return fila


def test_respuesta_de_un_agente_en_ticket_no_escalado_aparece_solo_en_el_asistente(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _crear_ticket_via_opcion_1(client, "Impresora sin tóner")
    ticket_id, _estado = _obtener_ticket_por_titulo(app, usuario, "Impresora sin tóner")

    # Un agente (cuenta cualquiera con rol 'agente', no el admin literal) responde desde Mesa de
    # Ayuda — el ticket nunca se "tomó" (asignó) explícitamente ni se escaló desde el Asistente.
    agente = crear_usuario(rol='agente', nombre='Otro Agente')
    _iniciar_sesion(client, app, agente, 'agente')
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': '<p>Ya te llevo un repuesto.</p>'})

    _iniciar_sesion(client, app, usuario, 'estandar')
    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    assert any('Otro Agente' in m['mensaje'] and 'Ya te llevo un repuesto' in m['mensaje'] for m in mensajes)
    # El aviso de que ya hay respuesta debe quedar como parte de la transcripción.
    assert any('respondió tu solicitud' in m['mensaje'] for m in mensajes)


def test_respuesta_del_usuario_en_ticket_no_escalado_tambien_se_guarda_como_comentario_real(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _crear_ticket_via_opcion_1(client, "Teclado no responde")
    ticket_id, _estado = _obtener_ticket_por_titulo(app, usuario, "Teclado no responde")

    agente = crear_usuario(rol='agente', nombre='Agente Uno')
    _iniciar_sesion(client, app, agente, 'agente')
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': '<p>¿Ya probaste con otro cable?</p>'})
    _iniciar_sesion(client, app, usuario, 'estandar')
    client.get('/chat/bot/estado')  # dispara el "enganche" automático a esperando_agente

    r = client.post('/chat/bot/enviar', data={'mensaje': 'Sí, y sigue sin funcionar.'})

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT autor, mensaje FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id DESC LIMIT 1", (ticket_id,))
    autor, mensaje_html = cur.fetchone()
    conn.close()
    assert autor == usuario
    assert 'sigue sin funcionar' in mensaje_html


def test_ticket_sin_respuesta_de_staff_no_activa_solo_el_modo_agente(client, app, crear_usuario):
    """Sin que ningún agente/admin haya comentado todavía, quedarse en el menú no debe
    'enganchar' ningún ticket — el Asistente debe seguir comportándose como un menú normal."""
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _crear_ticket_via_opcion_1(client, "Mouse no conecta")

    r = client.post('/chat/bot/enviar', data={'mensaje': '9'})  # opción inválida del menú

    assert 'No reconocí esa opción' in r.get_json()['mensajes'][-1]['mensaje']
    ticket_id, _estado = _obtener_ticket_por_titulo(app, usuario, "Mouse no conecta")
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets_comentarios WHERE ticket_id = ?", (ticket_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_ticket_creado_directo_en_mesa_de_ayuda_tambien_se_engancha_si_un_agente_responde(client, app, crear_usuario):
    """No hace falta que el ticket se haya creado desde el Asistente: cualquier ticket abierto
    del usuario que reciba una respuesta de soporte debe poder seguirse desde aquí."""
    from tests.test_tickets import _crear_ticket

    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _crear_ticket(client, titulo="Ticket creado desde Mesa de Ayuda")
    ticket_id, _estado = _obtener_ticket_por_titulo(app, usuario, "Ticket creado desde Mesa de Ayuda")

    agente = crear_usuario(rol='agente', nombre='Agente Dos')
    _iniciar_sesion(client, app, agente, 'agente')
    client.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': '<p>Quedó asignado a mí.</p>'})

    _iniciar_sesion(client, app, usuario, 'estandar')
    mensajes = client.get('/chat/bot/estado').get_json()['mensajes']

    assert any('Agente Dos' in m['mensaje'] and 'Quedó asignado a mí' in m['mensaje'] for m in mensajes)


def test_elegir_hablar_con_agente_tras_cierre_crea_una_nueva_escalacion(client, app, crear_usuario):
    """Una vez el ticket anterior se cerró, ya no cuenta como 'abierto' — volver a elegir la
    opción de escalar debe crear un caso nuevo en vez de intentar reabrir el cerrado."""
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    _escalar(client)
    ticket_id_1, _estado = _obtener_ticket_escalado(app, usuario)
    _cerrar_ticket(app, ticket_id_1)
    client.get('/chat/bot/estado')  # dispara el cierre automático y regresa al menú

    _escalar(client)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tickets WHERE creado_por = ? AND titulo = 'Escalado desde el Asistente de Chat'", (usuario,))
    assert cur.fetchone()[0] == 2
    conn.close()
