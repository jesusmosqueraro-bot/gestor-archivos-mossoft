"""Pruebas de la página de autoservicio 'Mi Perfil' (/perfil): edición de nombre completo,
teléfono y foto de perfil, con correo y cédula deliberadamente fuera de alcance (siguen siendo
de resorte exclusivo de un administrador)."""
import io


def test_get_perfil_precarga_datos_actuales(sesion_usuario, app, crear_usuario):
    usuario = sesion_usuario  # el cliente ya trae la sesión activa; usuario está en la sesión
    with sesion_usuario.session_transaction() as sess:
        nombre_usuario = sess['username']

    r = sesion_usuario.get('/perfil')

    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Persona de Prueba' in body  # nombre por defecto de crear_usuario()


def test_post_nombre_de_una_sola_palabra_es_rechazado(sesion_usuario):
    r = sesion_usuario.post('/perfil', data={'nombre': 'Juan', 'telefono': '3011111111'},
                             content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'al menos nombre y apellido' in r.get_data(as_text=True)


def test_post_nombre_valido_actualiza_nombre_y_telefono(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={'nombre': 'Juan Carlos Perez', 'telefono': '3022222222'},
                             content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'guardaron correctamente' in r.get_data(as_text=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre, telefono, foto_perfil FROM usuarios WHERE usuario = ?", (usuario,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Juan Carlos Perez'
    assert fila[1] == '3022222222'
    assert fila[2] is None  # no se subió foto: la columna no debe tocarse


def test_post_extension_de_imagen_invalida_es_rechazada(sesion_usuario):
    data = {
        'nombre': 'Juan Carlos Perez',
        'telefono': '3022222222',
        'foto_perfil': (io.BytesIO(b'contenido falso'), 'archivo.exe'),
    }

    r = sesion_usuario.post('/perfil', data=data, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'Formato de imagen no permitido' in r.get_data(as_text=True)


def test_post_imagen_mayor_a_5mb_es_rechazada(sesion_usuario):
    imagen_grande = io.BytesIO(b'0' * (5 * 1024 * 1024 + 10))
    data = {
        'nombre': 'Juan Carlos Perez',
        'telefono': '3022222222',
        'foto_perfil': (imagen_grande, 'foto.jpg'),
    }

    r = sesion_usuario.post('/perfil', data=data, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'no puede superar 5 MB' in r.get_data(as_text=True)


def test_perfil_sin_sesion_redirige_a_login(client):
    r = client.get('/perfil', follow_redirects=False)

    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')
