"""Pruebas del Asistente de Chat guiado por menú para usuarios 'estandar' (pedido por Tomás,
con referencia a un bot de WhatsApp): a diferencia del Chat Interno libre (persona a persona,
exclusivo de admin/agente, ver test_chat_interno.py), este asistente avanza por un árbol de
opciones fijo controlado por el backend, con recordatorios de inactividad y cierre automático.
Cubre: el interruptor general de un admin (CLAVE_CHAT_ESTANDAR / chat_permiso_estandar),
navegación del menú, creación de solicitudes de soporte, consulta de solicitudes propias,
Preguntas Frecuentes desde la Base de Conocimiento, escalar a un agente humano, el comando
universal 'volver', y los recordatorios/cierre por inactividad.

Nota de fixtures: cuando una prueba necesita actuar como admin Y como un usuario 'estandar' en
la misma prueba, se usa un solo 'client' y se alterna la sesión con _iniciar_sesion() —
'admin_session' y 'sesion_usuario' comparten el mismo test client interno (ver conftest.py), así
que combinarlas en una sola prueba pisaría una sesión con la otra en vez de mantener dos
usuarios simultáneos."""
import datetime


def _iniciar_sesion(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _crear_articulo_conocimiento(app, titulo='Cómo restablecer mi contraseña', descripcion='Ve a Perfil y elige "Cambiar contraseña".'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO conocimiento_articulos (titulo, descripcion, url_documento, nombre_archivo, vistas, creado_por, fecha_creacion, estado) "
         "VALUES (%s, %s, 'https://ejemplo.test/doc', 'doc.pdf', 0, 'admin', '2026-01-01', 'activo')"
         if db_type == 'postgres' else
         "INSERT INTO conocimiento_articulos (titulo, descripcion, url_documento, nombre_archivo, vistas, creado_por, fecha_creacion, estado) "
         "VALUES (?, ?, 'https://ejemplo.test/doc', 'doc.pdf', 0, 'admin', '2026-01-01', 'activo')")
    cur.execute(q, (titulo, descripcion))
    conn.commit()
    conn.close()


def _habilitar_asistente(client, app, habilitar=True):
    _iniciar_sesion(client, app, 'admin', 'admin')
    r = client.post('/chat/permiso_estandar', data={'habilitar': '1' if habilitar else '0'}, follow_redirects=False)
    assert r.status_code == 302


def _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario):
    """Habilita el interruptor general como admin y deja la sesión activa como un usuario
    'estandar' recién creado — punto de partida típico de estas pruebas."""
    usuario = crear_usuario(rol='estandar')
    _habilitar_asistente(client, app, habilitar=True)
    _iniciar_sesion(client, app, usuario, 'estandar')
    return usuario


# --- Interruptor general del admin -------------------------------------------------------

def test_asistente_deshabilitado_por_defecto_bloquea_las_rutas_del_bot(sesion_usuario):
    assert sesion_usuario.get('/chat/bot/estado').status_code == 403
    assert sesion_usuario.post('/chat/bot/enviar', data={'mensaje': '1'}).status_code == 403
    assert sesion_usuario.post('/chat/bot/reiniciar').status_code == 403


def test_chat_pagina_de_estandar_muestra_no_disponible_si_esta_deshabilitado(sesion_usuario):
    r = sesion_usuario.get('/chat')
    assert r.status_code == 200
    assert 'no está disponible'.encode('utf-8') in r.data


def test_admin_habilita_el_asistente_para_todos_los_estandar(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)

    r = client.get('/chat/bot/estado')
    assert r.status_code == 200


def test_admin_deshabilita_el_asistente_de_nuevo(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    assert client.get('/chat/bot/estado').status_code == 200

    _habilitar_asistente(client, app, habilitar=False)
    _iniciar_sesion(client, app, usuario, 'estandar')

    assert client.get('/chat/bot/estado').status_code == 403


def test_interruptor_del_asistente_requiere_rol_admin(sesion_usuario):
    r = sesion_usuario.post('/chat/permiso_estandar', data={'habilitar': '1'})
    assert r.status_code in (302, 403)
    assert sesion_usuario.get('/chat/bot/estado').status_code == 403


def test_agente_no_usa_el_asistente_guiado_sino_el_chat_libre(client, app, crear_usuario):
    """El Chat Interno libre sigue siendo exclusivo de admin/agente — habilitar el interruptor
    del asistente para 'estandar' no cambia lo que ve un 'agente' al entrar a /chat."""
    _habilitar_asistente(client, app, habilitar=True)
    agente = crear_usuario(rol='agente')
    _iniciar_sesion(client, app, agente, 'agente')

    r = client.get('/chat')
    assert r.status_code == 200
    assert b'Canal General' in r.data


# --- Navegacion del menu principal -------------------------------------------------------

def test_primera_visita_crea_sesion_con_saludo_y_menu(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)

    r = client.get('/chat/bot/estado')

    mensajes = r.get_json()['mensajes']
    assert mensajes, "debía sembrar el mensaje de bienvenida"
    assert mensajes[0]['autor'] == 'bot'
    assert 'Asistente de Arkiv' in mensajes[0]['mensaje']
    assert mensajes[0]['opciones'] == [
        'Crear una solicitud de soporte', 'Consultar mis solicitudes',
        'Preguntas frecuentes', 'Hablar con un agente humano',
    ]


def test_elegir_opcion_por_numero_y_por_texto_funcionan_igual(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    _habilitar_asistente(client, app, habilitar=True)

    _iniciar_sesion(client, app, usuario_a, 'estandar')
    client.get('/chat/bot/estado')
    r1 = client.post('/chat/bot/enviar', data={'mensaje': '2'})
    texto_por_numero = r1.get_json()['mensajes'][-1]['mensaje']

    _iniciar_sesion(client, app, usuario_b, 'estandar')
    client.get('/chat/bot/estado')
    r2 = client.post('/chat/bot/enviar', data={'mensaje': 'Consultar mis solicitudes'})
    texto_por_texto = r2.get_json()['mensajes'][-1]['mensaje']

    assert texto_por_numero == texto_por_texto


def test_opcion_no_reconocida_no_avanza_el_estado(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r = client.post('/chat/bot/enviar', data={'mensaje': 'blablabla'})

    assert 'No reconocí esa opción' in r.get_json()['mensajes'][-1]['mensaje']


# --- Crear una solicitud de soporte -------------------------------------------------------

def test_flujo_completo_crear_ticket_desde_el_asistente(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r1 = client.post('/chat/bot/enviar', data={'mensaje': '1'})
    assert 'categoría' in r1.get_json()['mensajes'][-1]['mensaje']

    r2 = client.post('/chat/bot/enviar', data={'mensaje': 'Software'})
    assert 'título' in r2.get_json()['mensajes'][-1]['mensaje']

    r3 = client.post('/chat/bot/enviar', data={'mensaje': 'No me carga el correo'})
    ultimo = r3.get_json()['mensajes'][-1]['mensaje'].lower()
    assert 'descríbeme' in ultimo or 'descripción' in ultimo

    r4 = client.post('/chat/bot/enviar', data={'mensaje': 'Desde ayer no carga la bandeja de entrada.'})
    mensajes = r4.get_json()['mensajes']
    assert 'quedó registrada' in mensajes[-2]['mensaje']

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT titulo, categoria, estado FROM tickets WHERE titulo = ?", ('No me carga el correo',))
    fila = cur.fetchone()
    conn.close()
    assert fila == ('No me carga el correo', 'Software', 'Abierto')


def test_ticket_creado_por_el_asistente_lo_puede_ver_un_agente_en_mesa_de_ayuda(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')
    client.post('/chat/bot/enviar', data={'mensaje': '1'})
    client.post('/chat/bot/enviar', data={'mensaje': 'Otro'})
    client.post('/chat/bot/enviar', data={'mensaje': 'Titulo de prueba del asistente'})
    client.post('/chat/bot/enviar', data={'mensaje': 'Descripcion de prueba del asistente'})

    _iniciar_sesion(client, app, 'admin', 'admin')
    r = client.get('/tickets')
    assert 'Titulo de prueba del asistente'.encode('utf-8') in r.data


# --- Consultar mis solicitudes -------------------------------------------------------------

def test_consultar_mis_solicitudes_sin_tickets_previos(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r = client.post('/chat/bot/enviar', data={'mensaje': '2'})

    assert 'Todavía no tienes solicitudes' in r.get_json()['mensajes'][-2]['mensaje']


def test_consultar_mis_solicitudes_regresa_al_menu_despues(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r = client.post('/chat/bot/enviar', data={'mensaje': '2'})

    assert r.get_json()['mensajes'][-1]['opciones'] is not None


# --- Preguntas frecuentes ------------------------------------------------------------------

def test_faq_sin_articulos_publicados(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r = client.post('/chat/bot/enviar', data={'mensaje': '3'})

    assert 'no hay artículos publicados' in r.get_json()['mensajes'][-2]['mensaje'].lower()


def test_faq_con_articulos_muestra_lista_y_responde_el_elegido(client, app, crear_usuario):
    _crear_articulo_conocimiento(app, titulo='Como restablecer mi contrasena', descripcion='Ve a Perfil y elige "Cambiar contrasena".')
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    r1 = client.post('/chat/bot/enviar', data={'mensaje': '3'})
    assert 'Como restablecer mi contrasena' in r1.get_json()['mensajes'][-1]['mensaje']

    r2 = client.post('/chat/bot/enviar', data={'mensaje': '1'})
    assert 'Cambiar contrasena' in r2.get_json()['mensajes'][-2]['mensaje']


# --- Escalar a un agente humano -------------------------------------------------------------

def test_escalar_a_agente_humano_crea_ticket_de_prioridad_alta(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    client.post('/chat/bot/enviar', data={'mensaje': '4'})
    r = client.post('/chat/bot/enviar', data={'mensaje': 'El sistema no me deja entrar, es urgente.'})

    assert 'prioridad alta' in r.get_json()['mensajes'][-2]['mensaje']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT prioridad FROM tickets WHERE titulo = 'Escalado desde el Asistente de Chat'")
    assert cur.fetchone()[0] == 'Alta'
    conn.close()


# --- Comando universal 'volver' -------------------------------------------------------------

def test_volver_regresa_al_menu_desde_cualquier_punto(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')
    client.post('/chat/bot/enviar', data={'mensaje': '1'})  # entra a crear_ticket_categoria

    r = client.post('/chat/bot/enviar', data={'mensaje': 'volver'})

    assert r.get_json()['mensajes'][-1]['opciones'] == [
        'Crear una solicitud de soporte', 'Consultar mis solicitudes',
        'Preguntas frecuentes', 'Hablar con un agente humano',
    ]


# --- Reiniciar conversación ------------------------------------------------------------------

def test_reiniciar_conversacion_vuelve_a_mostrar_el_saludo(client, app, crear_usuario):
    _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')
    client.post('/chat/bot/enviar', data={'mensaje': '1'})

    r = client.post('/chat/bot/reiniciar')

    assert 'Asistente de Arkiv' in r.get_json()['mensajes'][-1]['mensaje']


# --- Inactividad: recordatorios y cierre automático ------------------------------------------

def test_recordatorio_de_inactividad_tras_los_minutos_configurados(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    _retroceder_ultima_actividad(app, usuario, minutos=app.BOT_MINUTOS_INACTIVIDAD + 1)

    r = client.get('/chat/bot/estado')

    assert r.get_json()['mensajes'][-1]['mensaje'] == app.BOT_MENSAJE_RECORDATORIO


def test_cierre_automatico_tras_agotar_los_recordatorios(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')

    for _ in range(app.BOT_MAX_RECORDATORIOS):
        _retroceder_ultima_actividad(app, usuario, minutos=app.BOT_MINUTOS_INACTIVIDAD + 1)
        client.get('/chat/bot/estado')

    _retroceder_ultima_actividad(app, usuario, minutos=app.BOT_MINUTOS_INACTIVIDAD + 1)
    r = client.get('/chat/bot/estado')

    assert r.get_json()['mensajes'][-1]['mensaje'] == app.BOT_MENSAJE_CIERRE


def test_responder_despues_de_cerrada_reabre_normalmente(client, app, crear_usuario):
    usuario = _preparar_estandar_con_asistente_habilitado(client, app, crear_usuario)
    client.get('/chat/bot/estado')
    app._bot_marcar_cerrada(usuario)

    r = client.post('/chat/bot/enviar', data={'mensaje': '2'})

    assert 'Todavía no tienes solicitudes' in r.get_json()['mensajes'][-2]['mensaje']


def _retroceder_ultima_actividad(app, usuario, minutos):
    """Adelanta el reloj de inactividad de 'usuario' hacia atrás 'minutos' minutos, para poder
    probar los recordatorios/cierre sin esperar de verdad — mismo formato de fecha que
    obtener_fecha_actual()."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    nueva_fecha = (datetime.datetime.now(app.ZONA_HORARIA_COLOMBIA).replace(tzinfo=None) - datetime.timedelta(minutes=minutos)).strftime('%Y-%m-%d %H:%M:%S')
    q = "UPDATE chat_bot_sesiones SET fecha_ultima_actividad = %s WHERE usuario = %s" if db_type == 'postgres' else "UPDATE chat_bot_sesiones SET fecha_ultima_actividad = ? WHERE usuario = ?"
    cur.execute(q, (nueva_fecha, usuario))
    conn.commit()
    conn.close()
