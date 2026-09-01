"""Pruebas del flujo de inicio de sesión: éxito, contraseña incorrecta, bloqueo automático
tras varios intentos fallidos (UMBRAL_INTENTOS_FALLIDOS_LOGIN), y el paso obligatorio a
verificación en dos pasos para roles operativos (hallazgo QA H-05).

El recaptcha real hace una llamada de red a Google — en estas pruebas se reemplaza por un doble
que siempre aprueba, para no depender de internet ni de credenciales de recaptcha en CI."""
from werkzeug.security import generate_password_hash


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def test_login_exitoso_usuario_estandar(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    r = client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'}, follow_redirects=False)

    assert r.status_code == 302
    assert '/bienvenida' in r.headers.get('Location', '')


def test_login_contrasena_incorrecta_no_abre_sesion(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    r = client.post('/login', data={'usuario': usuario, 'password': 'clave-equivocada'})

    assert r.status_code == 200
    assert 'incorrectos' in r.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert not sess.get('logged_in')


def test_login_usuario_inexistente_no_revela_informacion(client, app, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)

    r = client.post('/login', data={'usuario': 'no-existo-en-el-sistema', 'password': 'lo-que-sea'})

    assert r.status_code == 200
    # El mensaje genérico no debe distinguir "usuario no existe" de "contraseña incorrecta" —
    # si lo hiciera, sería una forma de enumerar cuentas válidas por fuerza bruta.
    assert 'incorrectos' in r.get_data(as_text=True)


def test_bloqueo_automatico_tras_intentos_fallidos(client, app, crear_usuario, monkeypatch):
    """UMBRAL_INTENTOS_FALLIDOS_LOGIN = 3: al tercer intento fallido consecutivo, la cuenta
    debe bloquearse, y desde ese momento ni siquiera la contraseña correcta debe abrir sesión."""
    _forzar_recaptcha_ok(monkeypatch, app)
    assert app.UMBRAL_INTENTOS_FALLIDOS_LOGIN == 3
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    for _ in range(3):
        r = client.post('/login', data={'usuario': usuario, 'password': 'clave-equivocada'})

    assert 'bloqueada' in r.get_data(as_text=True).lower()

    # Ni siquiera la contraseña correcta abre sesión ya bloqueada la cuenta.
    r_correcta = client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})
    assert r_correcta.status_code == 200
    assert 'bloqueó' in r_correcta.get_data(as_text=True) or 'bloqueada' in r_correcta.get_data(as_text=True).lower()
    with client.session_transaction() as sess:
        assert not sess.get('logged_in')


def test_login_admin_queda_marcado_para_activar_2fa(client, app, crear_usuario, monkeypatch):
    """Hallazgo QA H-05: roles operativos (admin/agente) deben quedar forzados a activar 2FA
    en su próximo inicio de sesión si todavía no lo tienen habilitado."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='agente')

    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    with client.session_transaction() as sess:
        assert sess.get('logged_in') is True
        assert sess.get('debe_activar_2fa') is True

    # Y ese marcador realmente redirige a /perfil/2fa en la siguiente petición, sin importar
    # a qué página se intente ir (ver validar_instancia_y_sesion).
    r = client.get('/bienvenida', follow_redirects=False)
    assert r.status_code == 302
    assert 'perfil' in r.headers.get('Location', '') and '2fa' in r.headers.get('Location', '')


def test_login_estandar_no_queda_forzado_a_2fa(client, app, crear_usuario, monkeypatch):
    """Un usuario 'estandar' (no admin/agente) puede navegar con normalidad sin que se le
    exija activar 2FA — esa obligación es solo para roles con acceso operativo."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    with client.session_transaction() as sess:
        assert sess.get('debe_activar_2fa') is False

    r = client.get('/bienvenida', follow_redirects=False)
    assert r.status_code == 200
