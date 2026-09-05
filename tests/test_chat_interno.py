"""Pruebas del Chat Interno (pedido por Tomás): un Canal General para todo el equipo con
acceso operativo (admin/agente) más mensajes directos 1 a 1 entre ellos — nadie más (estándar,
gestión humana) puede entrar, y un mensaje directo nuevo debe avisar en la campanita de
notificaciones a quien no tenga el chat abierto."""


def _sesion_como(client, app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def test_estandar_no_puede_entrar_al_chat(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    r = client.get('/chat')

    assert r.status_code in (302, 403)


def test_admin_y_agente_si_pueden_entrar_al_chat(client, app, crear_usuario):
    agente = crear_usuario(usuario='agente_chat1', rol='agente', nombre='Ana Agente')
    _sesion_como(client, app, agente, 'agente')

    r = client.get('/chat')

    assert r.status_code == 200
    assert 'Chat Interno' in r.get_data(as_text=True)


def test_contactos_excluye_a_uno_mismo_y_a_roles_no_operativos(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat1', rol='admin', nombre='Admin Uno')
    crear_usuario(usuario='agente_chat2', rol='agente', nombre='Beto Agente')
    crear_usuario(usuario='estandar_chat1', rol='estandar', nombre='Estándar Cualquiera')
    _sesion_como(client, app, admin1, 'admin')

    r = client.get('/chat/contactos')
    data = r.get_json()
    usuarios_listados = [c['usuario'] for c in data['contactos']]

    assert admin1 not in usuarios_listados  # nunca aparece como su propio contacto
    assert 'agente_chat2' in usuarios_listados
    assert 'estandar_chat1' not in usuarios_listados  # rol sin acceso operativo


def test_contactos_excluye_cuentas_inactivas(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat2', rol='admin')
    inactivo = crear_usuario(usuario='agente_inactivo_chat', rol='agente')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET estado = 'inactivo' WHERE usuario = ?", (inactivo,))
    conn.commit()
    conn.close()
    _sesion_como(client, app, admin1, 'admin')

    r = client.get('/chat/contactos')
    usuarios_listados = [c['usuario'] for c in r.get_json()['contactos']]

    assert inactivo not in usuarios_listados


def test_enviar_y_leer_mensaje_en_el_canal_general(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat3', rol='admin', nombre='Admin Tres')
    agente1 = crear_usuario(usuario='agente_chat3', rol='agente', nombre='Agente Tres')

    _sesion_como(client, app, admin1, 'admin')
    r = client.post('/chat/canal/enviar', data={'mensaje': 'Buenas a todo el equipo'})
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    _sesion_como(client, app, agente1, 'agente')
    r = client.get('/chat/canal/mensajes')
    data = r.get_json()
    assert len(data['mensajes']) == 1
    assert data['mensajes'][0]['mensaje'] == 'Buenas a todo el equipo'
    assert data['mensajes'][0]['remitente'] == admin1
    assert data['mensajes'][0]['remitente_nombre'] == 'Admin Tres'
    assert data['mensajes'][0]['es_mio'] is False


def test_canal_general_no_leidos_baja_a_cero_al_verlo(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat4', rol='admin')
    agente1 = crear_usuario(usuario='agente_chat4', rol='agente')

    _sesion_como(client, app, admin1, 'admin')
    client.post('/chat/canal/enviar', data={'mensaje': 'Mensaje 1'})
    client.post('/chat/canal/enviar', data={'mensaje': 'Mensaje 2'})

    _sesion_como(client, app, agente1, 'agente')
    no_leidos_antes = client.get('/chat/contactos').get_json()['canal_no_leidos']
    assert no_leidos_antes == 2

    client.get('/chat/canal/mensajes')  # entrar al canal lo marca como visto

    no_leidos_despues = client.get('/chat/contactos').get_json()['canal_no_leidos']
    assert no_leidos_despues == 0


def test_mensaje_directo_llega_al_destinatario_y_no_al_resto(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat5', rol='admin', nombre='Admin Cinco')
    agente1 = crear_usuario(usuario='agente_chat5', rol='agente', nombre='Agente Cinco')
    agente2 = crear_usuario(usuario='agente_chat5b', rol='agente', nombre='Agente Cinco B')

    _sesion_como(client, app, admin1, 'admin')
    r = client.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Hola, ¿tienes un momento?'})
    assert r.status_code == 200
    assert r.get_json()['success'] is True

    _sesion_como(client, app, agente1, 'agente')
    data = client.get(f'/chat/directo/{admin1}/mensajes').get_json()
    assert len(data['mensajes']) == 1
    assert data['mensajes'][0]['mensaje'] == 'Hola, ¿tienes un momento?'
    assert data['mensajes'][0]['es_mio'] is False

    # Un tercero (agente2) no ve nada de esta conversación privada.
    _sesion_como(client, app, agente2, 'agente')
    data_tercero = client.get(f'/chat/directo/{admin1}/mensajes').get_json()
    assert data_tercero['mensajes'] == []


def test_mensaje_directo_se_marca_leido_al_abrir_la_conversacion(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat6', rol='admin')
    agente1 = crear_usuario(usuario='agente_chat6', rol='agente')

    _sesion_como(client, app, admin1, 'admin')
    client.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Directo sin leer'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT leido FROM chat_mensajes WHERE tipo = 'directo' AND destinatario = ?", (agente1,))
    assert cur.fetchone()[0] == 0
    conn.close()

    _sesion_como(client, app, agente1, 'agente')
    client.get(f'/chat/directo/{admin1}/mensajes')  # entrar a la conversación lo marca leído

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT leido FROM chat_mensajes WHERE tipo = 'directo' AND destinatario = ?", (agente1,))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_mensaje_directo_crea_notificacion_de_campanita_para_el_destinatario(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat7', rol='admin', nombre='Admin Siete')
    agente1 = crear_usuario(usuario='agente_chat7', rol='agente')

    _sesion_como(client, app, admin1, 'admin')
    client.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Revisa el ticket 123 por favor'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT mensaje, url, tipo FROM notificaciones WHERE usuario = ?", (agente1,))
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    assert 'Admin Siete' in fila[0]
    assert 'Revisa el ticket 123' in fila[0]
    assert fila[1] == f'/chat?con={admin1}'
    assert fila[2] == 'chat'


def test_no_se_puede_chatear_directo_con_un_usuario_estandar(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat8', rol='admin')
    estandar1 = crear_usuario(usuario='estandar_chat8', rol='estandar')
    _sesion_como(client, app, admin1, 'admin')

    r = client.post(f'/chat/directo/{estandar1}/enviar', data={'mensaje': 'hola'})

    assert r.status_code == 404


def test_no_se_puede_enviar_un_mensaje_vacio(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat9', rol='admin')
    _sesion_como(client, app, admin1, 'admin')

    r = client.post('/chat/canal/enviar', data={'mensaje': '   '})

    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_no_se_puede_enviar_un_mensaje_demasiado_largo(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat10', rol='admin')
    _sesion_como(client, app, admin1, 'admin')

    r = client.post('/chat/canal/enviar', data={'mensaje': 'x' * 2001})

    assert r.status_code == 400
    assert r.get_json()['success'] is False


def test_contacto_con_mensaje_reciente_sube_al_principio_de_la_lista(client, app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_chat12', rol='admin')
    crear_usuario(usuario='agente_zzz_chat12', rol='agente', nombre='Zulema Último')
    crear_usuario(usuario='agente_aaa_chat12', rol='agente', nombre='Andrés Primero')

    _sesion_como(client, app, admin1, 'admin')
    # Sin mensajes todavía, deberían venir por orden alfabético.
    orden_inicial = [c['usuario'] for c in client.get('/chat/contactos').get_json()['contactos']]
    assert orden_inicial.index('agente_aaa_chat12') < orden_inicial.index('agente_zzz_chat12')

    # 'Zulema Último' recibe un mensaje directo: debe subir al principio, por encima de Andrés.
    client.post('/chat/directo/agente_zzz_chat12/enviar', data={'mensaje': 'hola Zulema'})
    orden_final = [c['usuario'] for c in client.get('/chat/contactos').get_json()['contactos']]
    assert orden_final[0] == 'agente_zzz_chat12'


def test_desactivar_2fa_no_afecta_el_chat_ni_al_reves(client, app, crear_usuario):
    """Prueba de humo simple para confirmar que el nuevo módulo no rompe rutas ya existentes
    (Gestión de Usuarios, notificaciones) al compartir la misma sesión/decoradores."""
    admin1 = crear_usuario(usuario='admin_chat11', rol='admin')
    _sesion_como(client, app, admin1, 'admin')

    assert client.get('/chat').status_code == 200
    assert client.get('/notificaciones/resumen').status_code == 200


def test_boton_de_chat_aparece_en_la_barra_solo_para_admin_agente(client, app, crear_usuario):
    """El botón de Chat Interno (partials/chat_boton.html, el ícono estilo Messenger en la
    barra de navegación) debe verse en páginas de admin/agente y nunca para un estándar, que
    de todas formas no puede entrar a /chat."""
    admin1 = crear_usuario(usuario='admin_chat13', rol='admin')
    estandar1 = crear_usuario(usuario='estandar_chat13', rol='estandar')

    _sesion_como(client, app, admin1, 'admin')
    html_admin = client.get('/bienvenida').get_data(as_text=True)
    assert 'badge-chat-header' in html_admin
    assert 'Chat Interno' in html_admin  # título del ícono (atributo title)

    _sesion_como(client, app, estandar1, 'estandar')
    html_estandar = client.get('/bienvenida').get_data(as_text=True)
    assert 'badge-chat-header' not in html_estandar


def test_resumen_de_notificaciones_incluye_chat_no_leidos(client, app, crear_usuario):
    """/notificaciones/resumen (la ruta que ya sondea la campanita cada 30s) debe traer también
    'chat_no_leidos' para que ese mismo sondeo pinte el badge del botón de Chat Interno, sin
    agregar una ruta ni un temporizador nuevos."""
    admin1 = crear_usuario(usuario='admin_chat14', rol='admin')
    agente1 = crear_usuario(usuario='agente_chat14', rol='agente')
    estandar1 = crear_usuario(usuario='estandar_chat14', rol='estandar')

    _sesion_como(client, app, admin1, 'admin')
    client.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'hola'})

    _sesion_como(client, app, agente1, 'agente')
    data_agente = client.get('/notificaciones/resumen').get_json()
    assert data_agente['chat_no_leidos'] == 1

    # Un rol sin acceso operativo nunca debe ver un conteo de chat (siempre 0), aunque de
    # todas formas no podría entrar a /chat.
    _sesion_como(client, app, estandar1, 'estandar')
    data_estandar = client.get('/notificaciones/resumen').get_json()
    assert data_estandar['chat_no_leidos'] == 0


def test_burbuja_flotante_de_chat_aparece_solo_para_admin_agente(client, app, crear_usuario):
    """La burbuja flotante estilo Messenger (partials/chat_flotante.html), apilada encima del
    botón de cambiar tema, debe verse en páginas de admin/agente y nunca para un estándar."""
    admin1 = crear_usuario(usuario='admin_chat15', rol='admin')
    estandar1 = crear_usuario(usuario='estandar_chat15', rol='estandar')

    _sesion_como(client, app, admin1, 'admin')
    html_admin = client.get('/bienvenida').get_data(as_text=True)
    assert 'badge-chat-flotante' in html_admin

    _sesion_como(client, app, estandar1, 'estandar')
    html_estandar = client.get('/bienvenida').get_data(as_text=True)
    assert 'badge-chat-flotante' not in html_estandar


def test_buscador_global_encuentra_mensajes_del_canal_general(client, app, crear_usuario):
    """El botón Buscar en Arkiv (/buscar/api) debe encontrar mensajes del Canal General, ya
    que ese canal es de todo el equipo con acceso operativo."""
    admin1 = crear_usuario(usuario='admin_chat16', rol='admin', nombre='Admin Dieciséis')
    agente1 = crear_usuario(usuario='agente_chat16', rol='agente')

    _sesion_como(client, app, admin1, 'admin')
    client.post('/chat/canal/enviar', data={'mensaje': 'Recuerden actualizar el inventario biomédico'})

    _sesion_como(client, app, agente1, 'agente')
    data = client.get('/buscar/api?q=inventario biomedico').get_json()
    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Chat Interno' in categorias
    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Chat Interno')
    assert 'Canal General' in resultado['subtitulo']
    assert '/chat' in resultado['url']


def test_buscador_global_encuentra_directos_propios_pero_no_ajenos(client, app, crear_usuario):
    """Un mensaje directo solo debe aparecer en el buscador de quienes participan en esa
    conversación — nunca para un tercero, ni siquiera si es admin."""
    admin1 = crear_usuario(usuario='admin_chat17', rol='admin')
    agente1 = crear_usuario(usuario='agente_chat17', rol='agente')
    agente2 = crear_usuario(usuario='agente_chat17b', rol='agente')

    _sesion_como(client, app, admin1, 'admin')
    client.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Confidencial: revisar el contrato XYZ789'})

    _sesion_como(client, app, agente1, 'agente')
    data_destinatario = client.get('/buscar/api?q=contrato XYZ789').get_json()
    assert any(r['categoria'] == 'Chat Interno' for r in data_destinatario['resultados'])

    _sesion_como(client, app, agente2, 'agente')
    data_tercero = client.get('/buscar/api?q=contrato XYZ789').get_json()
    assert not any(r['categoria'] == 'Chat Interno' for r in data_tercero['resultados'])


def test_buscador_global_no_muestra_chat_a_roles_sin_acceso_operativo(client, app, crear_usuario):
    """Un estándar nunca debe ver resultados de Chat Interno en el buscador, aunque el texto
    coincida con un mensaje real del Canal General."""
    admin1 = crear_usuario(usuario='admin_chat18', rol='admin')
    estandar1 = crear_usuario(usuario='estandar_chat18', rol='estandar')

    _sesion_como(client, app, admin1, 'admin')
    client.post('/chat/canal/enviar', data={'mensaje': 'Mensaje unico buscable qwerty123'})

    _sesion_como(client, app, estandar1, 'estandar')
    data = client.get('/buscar/api?q=qwerty123').get_json()
    assert not any(r['categoria'] == 'Chat Interno' for r in data['resultados'])


def test_canal_general_no_devuelve_mensajes_duplicados_al_pedirlos_dos_veces_seguidas(client, app, crear_usuario):
    """Reportado por Tomás: al enviar un mensaje al Canal General, a él mismo le aparecía
    duplicado. La causa real era del lado del navegador (chat.js pedía los mensajes nuevos justo
    al enviar, Y tiempo_real.js pedía los mismos otra vez al recibir el aviso del propio socket
    — dos peticiones casi simultáneas con el mismo desde_id). Esta prueba confirma que el
    SERVIDOR nunca fue la causa: pedir /chat/canal/mensajes dos veces con el mismo desde_id
    siempre devuelve exactamente el mismo mensaje una sola vez por respuesta, nunca duplicado
    dentro de una misma respuesta."""
    admin1 = crear_usuario(usuario='admin_chat19', rol='admin')
    _sesion_como(client, app, admin1, 'admin')

    client.post('/chat/canal/enviar', data={'mensaje': 'Aviso importante para todos'})

    # Dos peticiones "en paralelo" con el mismo desde_id=0 (como pasaría si dos disparadores
    # del navegador piden al mismo tiempo, justo la condición de carrera reportada).
    data_1 = client.get('/chat/canal/mensajes?desde_id=0').get_json()
    data_2 = client.get('/chat/canal/mensajes?desde_id=0').get_json()

    assert len(data_1['mensajes']) == 1
    assert len(data_2['mensajes']) == 1
    assert data_1['mensajes'][0]['id'] == data_2['mensajes'][0]['id']


def test_pagina_de_chat_incluye_el_buscador_de_conversaciones(client, app, crear_usuario):
    """Pedido por Tomás: un buscador en /chat para filtrar la lista de conversaciones por
    nombre o usuario. Verifica que el HTML traiga el input y que cada contacto traiga su
    'data-nombre' (además del 'data-usuario' que ya existía) — chat.js filtra por ambos."""
    admin1 = crear_usuario(usuario='admin_chat20', rol='admin')
    crear_usuario(usuario='agente_chat20', rol='agente', nombre='Beto Buscable')
    _sesion_como(client, app, admin1, 'admin')

    html = client.get('/chat').get_data(as_text=True)

    assert 'id="buscar-chat-contactos"' in html
    assert 'filtrarContactosChat()' in html
    assert 'data-nombre="Beto Buscable"' in html
