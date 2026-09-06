"""Pruebas de la página de autoservicio 'Mi Perfil' (/perfil): edición de teléfono, correo
electrónico y foto de perfil. El NOMBRE ya NO es editable aquí (pedido de Tomás, 06/09/2026):
desde que las actas de asignación/devolución de activos quedan con el nombre de quien las genera
o certifica, cambiarlo por autoservicio dejaría esa identidad inconsistente frente a actas ya
generadas — solo un administrador puede corregirlo desde Gestión de Usuarios. La cédula sigue
fuera de alcance por lo de siempre (duplicados, dato sensible)."""
import io


def test_get_perfil_precarga_datos_actuales(sesion_usuario, app, crear_usuario):
    with sesion_usuario.session_transaction() as sess:
        nombre_usuario = sess['username']

    r = sesion_usuario.get('/perfil')

    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'Persona de Prueba' in body  # nombre por defecto de crear_usuario()


def test_post_no_puede_cambiar_el_nombre_aunque_lo_mande_en_el_formulario(sesion_usuario, app):
    """Aunque alguien manipule el formulario y mande un 'nombre' distinto, la ruta lo ignora por
    completo — ni siquiera se lee del form. El nombre en la base no debe cambiar."""
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={
        'nombre': 'Nombre Falsificado', 'telefono': '3011111111', 'correo': 'nuevo.correo@preventivaips.com.co',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'guardaron correctamente' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == 'Persona de Prueba'  # no cambió
    conn.close()


def test_post_actualiza_telefono_y_correo(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co'},
                             content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'guardaron correctamente' in r.get_data(as_text=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT telefono, correo, foto_perfil FROM usuarios WHERE usuario = ?", (usuario,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == '3022222222'
    assert fila[1] == 'juan.carlos@preventivaips.com.co'
    assert fila[2] is None  # no se subió foto: la columna no debe tocarse


def test_post_correo_con_formato_invalido_es_rechazado(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={'telefono': '3022222222', 'correo': 'esto-no-es-un-correo'},
                             content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'correo electrónico' in r.get_data(as_text=True).lower()

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT correo, telefono FROM usuarios WHERE usuario = ?", (usuario,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] != 'esto-no-es-un-correo'  # no se guardó el correo inválido
    assert fila[1] is None  # tampoco se guardó nada más de esa misma petición rechazada


def test_post_extension_de_imagen_invalida_es_rechazada(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT correo FROM usuarios WHERE usuario = ?", (usuario,))
    correo_actual = cur.fetchone()[0]
    conn.close()

    data = {
        'telefono': '3022222222', 'correo': correo_actual,
        'foto_perfil': (io.BytesIO(b'contenido falso'), 'archivo.exe'),
    }

    r = sesion_usuario.post('/perfil', data=data, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'Formato de imagen no permitido' in r.get_data(as_text=True)


def test_post_imagen_mayor_a_5mb_es_rechazada(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT correo FROM usuarios WHERE usuario = ?", (usuario,))
    correo_actual = cur.fetchone()[0]
    conn.close()

    imagen_grande = io.BytesIO(b'0' * (5 * 1024 * 1024 + 10))
    data = {
        'telefono': '3022222222', 'correo': correo_actual,
        'foto_perfil': (imagen_grande, 'foto.jpg'),
    }

    r = sesion_usuario.post('/perfil', data=data, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'no puede superar 5 MB' in r.get_data(as_text=True)


def test_modal_perfil_muestra_el_nombre_deshabilitado_y_el_correo_editable(sesion_usuario):
    texto = sesion_usuario.get('/perfil').get_data(as_text=True)
    assert 'name="correo"' in texto
    assert 'name="nombre"' not in texto  # el nombre ya no se manda como campo editable


def test_perfil_sin_sesion_redirige_a_login(client):
    r = client.get('/perfil', follow_redirects=False)

    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')
