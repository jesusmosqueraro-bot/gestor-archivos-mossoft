"""Pruebas del "empujón" en tiempo real (Socket.IO) — pedido por Tomás: los mensajes del Chat
Interno y las notificaciones de campanita deben llegar sin tener que refrescar o salir y volver
a entrar (ver static/js/tiempo_real.js y _emitir_evento_tiempo_real en app.py).

Estas pruebas usan flask_socketio.test_client(), que abre una conexión de socket "de verdad"
contra la app de pruebas (comparte la sesión del client HTTP normal vía flask_test_client=),
así que cubren tanto la sala a la que cada quien se une al conectarse (_socketio_conectar) como
el evento que de verdad se emite al enviar un mensaje o crear una notificación — no solo que se
llamó a una función mockeada."""
import pytest

flask_socketio = pytest.importorskip('flask_socketio', reason='Flask-SocketIO no está instalado en este entorno')


def _sesion_como(client, app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _nombres_de_eventos(recibidos):
    return [ev['name'] for ev in recibidos]


def test_conexion_de_socket_rechazada_sin_sesion_iniciada(app):
    """_socketio_conectar() debe rechazar (return False) a quien no tenga sesión — igual que
    login_required en las rutas normales, pero para el socket."""
    cliente_anonimo = app.app.test_client()

    sio = app.socketio.test_client(app.app, flask_test_client=cliente_anonimo)

    assert sio.is_connected() is False


def test_conexion_de_socket_aceptada_con_sesion_valida(app, crear_usuario):
    agente = crear_usuario(usuario='agente_tr1', rol='agente')
    client = app.app.test_client()
    _sesion_como(client, app, agente, 'agente')

    sio = app.socketio.test_client(app.app, flask_test_client=client)

    assert sio.is_connected() is True
    sio.disconnect()


def test_mensaje_de_canal_general_llega_en_vivo_a_otro_conectado(app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_tr1', rol='admin', nombre='Admin Uno')
    agente1 = crear_usuario(usuario='agente_tr2', rol='agente', nombre='Agente Dos')

    client_admin = app.app.test_client()
    _sesion_como(client_admin, app, admin1, 'admin')
    client_agente = app.app.test_client()
    _sesion_como(client_agente, app, agente1, 'agente')

    # Ambos con acceso operativo: ambos se unen solos a la sala 'chat_canal_general' al conectar.
    sio_admin = app.socketio.test_client(app.app, flask_test_client=client_admin)
    sio_agente = app.socketio.test_client(app.app, flask_test_client=client_agente)
    sio_admin.get_received()  # limpia cualquier evento de bienvenida/ruido de la conexión misma

    r = client_admin.post('/chat/canal/enviar', data={'mensaje': 'Aviso para todo el equipo'})
    assert r.status_code == 200

    recibidos_agente = sio_agente.get_received()
    assert 'chat_canal_mensaje' in _nombres_de_eventos(recibidos_agente)
    evento = next(ev for ev in recibidos_agente if ev['name'] == 'chat_canal_mensaje')
    datos = evento['args'][0]
    assert datos['mensaje'] == 'Aviso para todo el equipo'
    assert datos['remitente'] == admin1

    # El Canal General NUNCA dispara notificación de campanita (para no saturar un canal de
    # equipo activo) — solo el evento de chat en sí.
    assert 'notificacion_nueva' not in _nombres_de_eventos(recibidos_agente)


def test_mensaje_de_canal_general_no_llega_a_quien_no_tiene_acceso_operativo(app, crear_usuario):
    """Un rol 'estandar' puede tener sesión iniciada (por otras partes de Arkiv), pero
    _socketio_conectar() solo lo une a SU PROPIA sala de usuario, nunca a 'chat_canal_general'
    — así que un mensaje del canal no debe llegarle aunque esté con el socket conectado."""
    admin1 = crear_usuario(usuario='admin_tr2', rol='admin')
    estandar1 = crear_usuario(usuario='estandar_tr1', rol='estandar')

    client_admin = app.app.test_client()
    _sesion_como(client_admin, app, admin1, 'admin')
    client_estandar = app.app.test_client()
    _sesion_como(client_estandar, app, estandar1, 'estandar')

    sio_estandar = app.socketio.test_client(app.app, flask_test_client=client_estandar)
    assert sio_estandar.is_connected() is True
    sio_estandar.get_received()

    client_admin.post('/chat/canal/enviar', data={'mensaje': 'Mensaje solo para el equipo'})

    assert _nombres_de_eventos(sio_estandar.get_received()) == []


def test_mensaje_directo_llega_al_destinatario_y_al_remitente_pero_no_a_un_tercero(app, crear_usuario):
    admin1 = crear_usuario(usuario='admin_tr3', rol='admin', nombre='Admin Tres')
    agente1 = crear_usuario(usuario='agente_tr3', rol='agente', nombre='Agente Tres')
    agente2 = crear_usuario(usuario='agente_tr3b', rol='agente', nombre='Agente Tres B (ajeno)')

    client_admin = app.app.test_client()
    _sesion_como(client_admin, app, admin1, 'admin')
    client_agente1 = app.app.test_client()
    _sesion_como(client_agente1, app, agente1, 'agente')
    client_agente2 = app.app.test_client()
    _sesion_como(client_agente2, app, agente2, 'agente')

    sio_admin = app.socketio.test_client(app.app, flask_test_client=client_admin)
    sio_agente1 = app.socketio.test_client(app.app, flask_test_client=client_agente1)
    sio_agente2 = app.socketio.test_client(app.app, flask_test_client=client_agente2)
    sio_admin.get_received()

    r = client_admin.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Hola, ¿tienes un momento?'})
    assert r.status_code == 200

    # Al destinatario: le llega el mensaje en vivo, pero SIN notificación de campanita — pedido
    # por Tomás, para que los mensajes no saturen la campanita general, solo el ícono del chat
    # (igual que ya pasaba con el Canal General, ver el test de arriba).
    recibidos_destinatario = _nombres_de_eventos(sio_agente1.get_received())
    assert 'chat_directo_mensaje' in recibidos_destinatario
    assert 'notificacion_nueva' not in recibidos_destinatario

    # A quien envía (otra pestaña/dispositivo suyo): también le llega el mensaje, y tampoco
    # notificación de campanita para sí mismo.
    recibidos_remitente = _nombres_de_eventos(sio_admin.get_received())
    assert 'chat_directo_mensaje' in recibidos_remitente
    assert 'notificacion_nueva' not in recibidos_remitente

    # A un tercero ajeno a la conversación: no le llega nada.
    assert _nombres_de_eventos(sio_agente2.get_received()) == []


def test_mensaje_directo_no_crea_notificacion_de_campanita_solo_actualiza_el_icono_del_chat(app, crear_usuario):
    """Pedido por Tomás: un mensaje directo no debe aparecer en la campanita general (ni en su
    contador 'no_leidas' ni en su lista 'recientes') — solo debe reflejarse en 'chat_no_leidos',
    el contador que pinta el ícono de Chat Interno. Verificado a nivel HTTP (no solo del socket),
    consultando la misma ruta que usa la campanita de verdad."""
    admin1 = crear_usuario(usuario='admin_tr4', rol='admin', nombre='Admin Cuatro')
    agente1 = crear_usuario(usuario='agente_tr4', rol='agente', nombre='Agente Cuatro')

    client_admin = app.app.test_client()
    _sesion_como(client_admin, app, admin1, 'admin')
    client_agente = app.app.test_client()
    _sesion_como(client_agente, app, agente1, 'agente')

    r = client_admin.post(f'/chat/directo/{agente1}/enviar', data={'mensaje': 'Mensaje que no debe saturar la campanita'})
    assert r.status_code == 200

    data = client_agente.get('/notificaciones/resumen').get_json()
    assert data['no_leidas'] == 0
    assert data['recientes'] == []
    assert data['chat_no_leidos'] == 1
