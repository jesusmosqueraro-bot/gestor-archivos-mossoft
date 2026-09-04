"""Pruebas del 'dispositivo de confianza' del 2FA (pedido por Tomás): una cuenta con la
verificación en dos pasos activa no debe tener que ingresar el código de la app autenticadora en
CADA inicio de sesión. Al completarlo una vez, ese dispositivo/navegador queda "de confianza" por
DURACION_DISPOSITIVO_CONFIABLE_2FA_DIAS (10 días) — pero solo mientras la IP siga siendo la misma;
un dispositivo distinto (sin la cookie) o la misma cookie desde otra IP sí vuelven a pedir el
código, y desactivar el 2FA de la cuenta revoca cualquier dispositivo que hubiera quedado de
confianza."""
import pyotp
from werkzeug.security import generate_password_hash


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def _crear_usuario_2fa(app, crear_usuario, usuario='con2fa1', password='ClaveSegura123', rol='agente'):
    secreto = pyotp.random_base32()
    usuario = crear_usuario(usuario=usuario, password_hash=generate_password_hash(password), rol=rol)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("UPDATE usuarios SET totp_habilitado = %s, totp_secret = %s WHERE usuario = %s" if db_type == 'postgres'
         else "UPDATE usuarios SET totp_habilitado = ?, totp_secret = ? WHERE usuario = ?")
    cur.execute(q, (True if db_type == 'postgres' else 1, app.encriptar_texto(secreto), usuario))
    conn.commit()
    conn.close()
    return usuario, secreto


def _login(client, usuario, password='ClaveSegura123', ip='203.0.113.10'):
    return client.post('/login', data={'usuario': usuario, 'password': password},
                        headers={'X-Forwarded-For': ip}, follow_redirects=False)


def _completar_2fa(client, secreto, ip='203.0.113.10'):
    codigo = pyotp.TOTP(secreto).now()
    return client.post('/login/2fa', data={'codigo': codigo},
                        headers={'X-Forwarded-For': ip}, follow_redirects=False)


def test_cuenta_con_2fa_se_manda_a_login_2fa_la_primera_vez(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)

    r = _login(client, usuario)

    assert r.status_code == 302
    assert 'login/2fa' in r.headers.get('Location', '')
    with client.session_transaction() as sess:
        assert not sess.get('logged_in')


def test_completar_2fa_deja_una_cookie_de_dispositivo_de_confianza(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)

    r = _completar_2fa(client, secreto)

    assert r.status_code == 302
    assert 'bienvenida' in r.headers.get('Location', '')
    assert app.NOMBRE_COOKIE_DISPOSITIVO_2FA in r.headers.get('Set-Cookie', '')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dispositivos_confiables_2fa WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_mismo_dispositivo_y_misma_ip_no_vuelve_a_pedir_el_codigo(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)
    _completar_2fa(client, secreto)
    with client.session_transaction() as sess:
        sess.clear()  # simula cerrar el navegador: se pierde la sesión, pero NO la cookie de dispositivo

    r = _login(client, usuario)

    assert r.status_code == 302
    assert 'bienvenida' in r.headers.get('Location', '')
    with client.session_transaction() as sess:
        assert sess.get('logged_in') is True
        assert sess.get('debe_activar_2fa') is False


def test_dispositivo_sin_cookie_si_vuelve_a_pedir_el_codigo(client, app, crear_usuario, monkeypatch):
    """Un dispositivo/navegador distinto (sin la cookie de confianza) debe seguir pasando por
    /login/2fa aunque otro dispositivo de la misma cuenta ya la tenga."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)
    _completar_2fa(client, secreto)

    otro_cliente = app.app.test_client()  # sin la cookie que dejó 'client'
    r = _login(otro_cliente, usuario)

    assert r.status_code == 302
    assert 'login/2fa' in r.headers.get('Location', '')


def test_misma_cookie_desde_otra_ip_si_vuelve_a_pedir_el_codigo(client, app, crear_usuario, monkeypatch):
    """La IP es la señal adicional pedida por Tomás: si la cookie viaja a otra red, ese
    dispositivo igual debe volver a verificarse."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario, ip='203.0.113.10')
    _completar_2fa(client, secreto, ip='203.0.113.10')
    with client.session_transaction() as sess:
        sess.clear()

    r = _login(client, usuario, ip='198.51.100.20')  # IP distinta

    assert r.status_code == 302
    assert 'login/2fa' in r.headers.get('Location', '')


def test_dispositivo_de_confianza_vencido_vuelve_a_pedir_el_codigo(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)
    _completar_2fa(client, secreto)

    # Se adelanta artificialmente la fecha de expiración a un día ya pasado.
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE dispositivos_confiables_2fa SET fecha_expiracion = '2000-01-01 00:00:00' WHERE usuario = ?", (usuario,))
    conn.commit()
    conn.close()
    with client.session_transaction() as sess:
        sess.clear()

    r = _login(client, usuario)

    assert r.status_code == 302
    assert 'login/2fa' in r.headers.get('Location', '')


def test_desactivar_2fa_revoca_los_dispositivos_de_confianza(client, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)
    _completar_2fa(client, secreto)

    app._desactivar_2fa_cuenta(usuario)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM dispositivos_confiables_2fa WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_reactivar_2fa_tras_desactivarlo_vuelve_a_pedir_el_codigo_a_todos(client, app, crear_usuario, monkeypatch):
    """Si el 2FA se desactiva y se vuelve a activar, el dispositivo que antes era 'de confianza'
    ya no debería serlo — _desactivar_2fa_cuenta ya lo borró, y activar 2FA de nuevo no debe
    revivir dispositivos viejos."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario, secreto = _crear_usuario_2fa(app, crear_usuario)
    _login(client, usuario)
    _completar_2fa(client, secreto)

    app._desactivar_2fa_cuenta(usuario)
    nuevo_secreto = pyotp.random_base32()
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("UPDATE usuarios SET totp_habilitado = %s, totp_secret = %s WHERE usuario = %s" if db_type == 'postgres'
         else "UPDATE usuarios SET totp_habilitado = ?, totp_secret = ? WHERE usuario = ?")
    cur.execute(q, (True if db_type == 'postgres' else 1, app.encriptar_texto(nuevo_secreto), usuario))
    conn.commit()
    conn.close()
    with client.session_transaction() as sess:
        sess.clear()

    r = _login(client, usuario)

    assert r.status_code == 302
    assert 'login/2fa' in r.headers.get('Location', '')
