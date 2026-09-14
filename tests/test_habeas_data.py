"""Pruebas del gate obligatorio de Habeas Data (Ley 1581 de 2012): toda cuenta cuyo
fecha_acepto_tratamiento_datos siga en NULL debe quedar forzada a /aceptar-tratamiento-datos
antes de poder usar cualquier otra parte de Arkiv, igual que ya pasaba con el cambio de
contraseña obligatorio y la activación forzada de 2FA (ver validar_instancia_y_sesion en app.py).
"""
from werkzeug.security import generate_password_hash


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def test_login_sin_consentimiento_previo_queda_marcado_para_aceptar(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)

    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    with client.session_transaction() as sess:
        assert sess.get('logged_in') is True
        assert sess.get('debe_aceptar_tratamiento_datos') is True


def test_login_con_consentimiento_previo_no_queda_marcado(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=True)

    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    with client.session_transaction() as sess:
        assert sess.get('debe_aceptar_tratamiento_datos') is False


def test_marcador_activo_redirige_cualquier_ruta_a_aceptar_tratamiento_datos(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.get('/bienvenida', follow_redirects=False)

    assert r.status_code == 302
    assert 'aceptar-tratamiento-datos' in r.headers.get('Location', '')


def test_marcador_activo_permite_llegar_a_la_pagina_de_aceptacion(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.get('/aceptar-tratamiento-datos', follow_redirects=False)

    assert r.status_code == 200
    assert 'tratamiento de datos' in r.get_data(as_text=True).lower()


def test_marcador_activo_permite_consultar_la_politica_publica(client, app, crear_usuario, monkeypatch):
    """La política en sí (/politica-tratamiento-datos) es pública y no exige sesión, así que
    debe seguir siendo accesible incluso con el gate activo (y sin sesión alguna)."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.get('/politica-tratamiento-datos', follow_redirects=False)

    assert r.status_code == 200


def test_politica_es_publica_sin_sesion(client):
    r = client.get('/politica-tratamiento-datos')
    assert r.status_code == 200


def test_aceptar_sin_marcar_la_casilla_muestra_error_y_no_avanza(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.post('/aceptar-tratamiento-datos', data={}, follow_redirects=False)

    assert r.status_code == 200
    assert 'debes marcar' in r.get_data(as_text=True).lower()
    with client.session_transaction() as sess:
        assert sess.get('debe_aceptar_tratamiento_datos') is True


def test_aceptar_marcando_la_casilla_registra_fecha_y_desbloquea_la_navegacion(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.post('/aceptar-tratamiento-datos', data={'acepto': 'on'}, follow_redirects=False)

    assert r.status_code == 302
    assert '/bienvenida' in r.headers.get('Location', '')
    with client.session_transaction() as sess:
        assert sess.get('debe_aceptar_tratamiento_datos') is False

    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = "SELECT fecha_acepto_tratamiento_datos FROM usuarios WHERE usuario = %s" if db_type == 'postgres' else "SELECT fecha_acepto_tratamiento_datos FROM usuarios WHERE usuario = ?"
    cur.execute(q, (usuario,))
    row = cur.fetchone()
    conn.close()
    assert row is not None and row[0]

    # Ya aceptado, cualquier otra ruta vuelve a quedar disponible con normalidad.
    r2 = client.get('/bienvenida', follow_redirects=False)
    assert r2.status_code == 200


def test_visitar_la_pagina_de_aceptacion_ya_habiendo_aceptado_manda_a_bienvenida(client, app, crear_usuario, monkeypatch):
    """Si alguien ya aceptó y de todas formas visita /aceptar-tratamiento-datos a propósito
    (ej. un enlace viejo guardado), no debe volver a mostrarle el formulario."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=True)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.get('/aceptar-tratamiento-datos', follow_redirects=False)

    assert r.status_code == 302
    assert '/bienvenida' in r.headers.get('Location', '')


def test_aceptar_tratamiento_datos_exige_sesion(client):
    r = client.get('/aceptar-tratamiento-datos', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def _marcar_debe_cambiar_password(app, usuario):
    """Pone debe_cambiar_password=True directo en BD, para simular una cuenta a la que un
    admin ya le había asignado una contraseña temporal ANTES de este parche de Habeas Data
    (el caso real que disparó el bug de abajo: toda cuenta preexistente quedó con
    fecha_acepto_tratamiento_datos en NULL al agregar esa columna)."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("UPDATE usuarios SET debe_cambiar_password = TRUE WHERE usuario = %s" if db_type == 'postgres'
         else "UPDATE usuarios SET debe_cambiar_password = 1 WHERE usuario = ?")
    cur.execute(q, (usuario,))
    conn.commit()
    conn.close()


# 🐛 Bug (14/09/2026): una cuenta con debe_aceptar_tratamiento_datos Y debe_cambiar_password
# pendientes A LA VEZ quedaba en bucle infinito de redirecciones entre /aceptar-tratamiento-datos
# y /perfil/cambiar_password (cada puerta sacaba a la persona de la pantalla de la otra), y
# ninguna de las dos llegaba a cargar. Reportado por un usuario real con ERR_TOO_MANY_REDIRECTS
# justo después de iniciar sesión. Las pruebas de abajo cubren la corrección (ver
# ENDPOINTS_PERMITIDOS_CAMBIO_PASSWORD_OBLIGATORIO / ENDPOINTS_PERMITIDOS_2FA_OBLIGATORIO en
# app.py, que ahora también exceptúan 'aceptar_tratamiento_datos').

def test_cuenta_con_ambas_puertas_pendientes_llega_a_la_pantalla_de_tratamiento_de_datos(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    _marcar_debe_cambiar_password(app, usuario)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    with client.session_transaction() as sess:
        assert sess.get('debe_aceptar_tratamiento_datos') is True
        assert sess.get('debe_cambiar_password') is True

    # Antes del fix, esta ruta terminaba redirigiendo de vuelta a /perfil/cambiar_password en
    # vez de dejar cargar la pantalla de tratamiento de datos.
    r = client.get('/aceptar-tratamiento-datos', follow_redirects=False)
    assert r.status_code == 200
    assert 'tratamiento de datos' in r.get_data(as_text=True).lower()


def test_cuenta_con_ambas_puertas_pendientes_no_entra_en_bucle_desde_cambiar_password(client, app, crear_usuario, monkeypatch):
    """Visitar directamente /perfil/cambiar_password con las dos puertas pendientes debe mandar
    una sola vez a /aceptar-tratamiento-datos (prioridad de Habeas Data) y esa pantalla debe
    quedarse ahí — no debe rebotar de vuelta."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    _marcar_debe_cambiar_password(app, usuario)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.get('/perfil/cambiar_password', follow_redirects=False)
    assert r.status_code == 302
    assert 'aceptar-tratamiento-datos' in r.headers.get('Location', '')

    r2 = client.get(r.headers['Location'], follow_redirects=False)
    assert r2.status_code == 200


def test_cuenta_con_ambas_puertas_pendientes_avanza_de_una_a_otra_tras_aceptar(client, app, crear_usuario, monkeypatch):
    """Tras aceptar el tratamiento de datos, la persona debe caer en la SIGUIENTE puerta
    pendiente (cambio de contraseña obligatorio), no en un bucle ni en un error."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar', acepto_tratamiento_datos=False)
    _marcar_debe_cambiar_password(app, usuario)
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = client.post('/aceptar-tratamiento-datos', data={'acepto': 'on'}, follow_redirects=True)

    assert r.status_code == 200
    assert len(r.history) <= 3  # /bienvenida -> /perfil/cambiar_password, nunca de vuelta
    assert '/perfil/cambiar_password' in r.request.path
    with client.session_transaction() as sess:
        assert sess.get('debe_aceptar_tratamiento_datos') is False
        assert sess.get('debe_cambiar_password') is True
