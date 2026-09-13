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
