"""Pruebas de Firma Digital: se captura al crear un usuario (dibujada a mano o subida como
imagen, ambas llegan como un data URL — ver static/js/firma-digital.js) y se reutiliza al
asignar un activo del Inventario a esa persona, sin pedirle que vuelva a firmar."""
import base64

import cloudinary.uploader

# Un PNG de 1x1 válido, en base64 — suficiente para pasar la validación de formato sin necesitar
# una imagen real.
PNG_1X1_B64 = base64.b64encode(bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
    0x42, 0x60, 0x82
])).decode('ascii')
FIRMA_DATAURL_VALIDA = 'data:image/png;base64,' + PNG_1X1_B64


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_x.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def _crear_especialidad(app, nombre='Auxiliar Administrativo'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO especialidades_catalogo (nombre, estado) VALUES (%s, 'activo')"
         if db_type == 'postgres' else
         "INSERT INTO especialidades_catalogo (nombre, estado) VALUES (?, 'activo')")
    cur.execute(q, (nombre,))
    conn.commit()
    conn.close()
    return nombre


def test_subir_firma_desde_dataurl_vacio_no_es_error(app):
    import app as arkiv
    url, error = arkiv._subir_firma_desde_dataurl(None)
    assert url is None
    assert error is None
    url, error = arkiv._subir_firma_desde_dataurl('')
    assert url is None
    assert error is None


def test_subir_firma_desde_dataurl_formato_invalido(app):
    import app as arkiv
    url, error = arkiv._subir_firma_desde_dataurl('esto no es un data url')
    assert url is None
    assert error is not None


def test_subir_firma_desde_dataurl_demasiado_grande(app):
    import app as arkiv
    enorme = 'data:image/png;base64,' + ('A' * (5 * 1024 * 1024))
    url, error = arkiv._subir_firma_desde_dataurl(enorme)
    assert url is None
    assert 'MB' in error


def test_subir_firma_desde_dataurl_sube_a_cloudinary(app, monkeypatch):
    import app as arkiv
    _mock_cloudinary_upload(monkeypatch)
    url, error = arkiv._subir_firma_desde_dataurl(FIRMA_DATAURL_VALIDA)
    assert error is None
    assert url == 'https://res.cloudinary.com/demo/image/upload/firma_x.png'


def test_crear_usuario_guarda_la_firma(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    especialidad = _crear_especialidad(app)

    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Marta', 'primer_apellido': 'Ríos',
        'email': 'marta.rios@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
        'firma_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma FROM usuarios WHERE correo = ?", ('marta.rios@preventivaips.com.co',))
    assert cur.fetchone()[0] == 'https://res.cloudinary.com/demo/image/upload/firma_x.png'
    conn.close()


def test_crear_usuario_sin_firma_no_falla(admin_session, app):
    especialidad = _crear_especialidad(app, 'Sin Firma')
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Julian', 'primer_apellido': 'Paz',
        'email': 'julian.paz@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma FROM usuarios WHERE correo = ?", ('julian.paz@preventivaips.com.co',))
    assert cur.fetchone()[0] is None
    conn.close()


def test_crear_usuario_con_firma_invalida_bloquea_el_alta(admin_session, app):
    especialidad = _crear_especialidad(app, 'Firma Invalida')
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Rota', 'primer_apellido': 'Firma',
        'email': 'rota.firma@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
        'firma_dataurl': 'no-es-un-data-url',
    }, follow_redirects=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios WHERE correo = ?", ('rota.firma@preventivaips.com.co',))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_crear_usuario_rapido_guarda_y_devuelve_la_firma(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_rapida.png')
    especialidad = _crear_especialidad(app)

    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Carlos', 'primer_apellido': 'Mena',
        'email': 'carlos.mena@preventivaips.com.co', 'especialidad': especialidad,
        'cedula': '77788899', 'firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    data = r.get_json()
    assert data['ok'] is True
    assert data['firma'] == 'https://res.cloudinary.com/demo/image/upload/firma_rapida.png'


def test_asignar_activo_reutiliza_la_firma_del_usuario(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_asignacion.png')
    especialidad = _crear_especialidad(app, 'Con Firma Para Asignar')

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Diana', 'primer_apellido': 'Vega',
        'email': 'diana.vega@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
        'firma_dataurl': FIRMA_DATAURL_VALIDA,
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT usuario, nombre FROM usuarios WHERE correo = ?", ('diana.vega@preventivaips.com.co',))
    usuario, nombre = cur.fetchone()
    conn.close()

    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '50001', 'tipo_activo': 'Portátil', 'estado': 'Asignado',
        'asignado_a': f'{nombre} ({usuario})',
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma_asignacion_url, firma_asignacion_fecha FROM activos_inventario WHERE nombre = ?", ('50001',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'https://res.cloudinary.com/demo/image/upload/firma_asignacion.png'
    assert fila[1]


def test_asignar_activo_con_texto_libre_no_reutiliza_firma(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '50002', 'tipo_activo': 'Portátil', 'estado': 'Asignado',
        'asignado_a': 'Alguien escrito a mano',
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma_asignacion_url FROM activos_inventario WHERE nombre = ?", ('50002',))
    assert cur.fetchone()[0] is None
    conn.close()


def test_buscar_cedula_incluye_la_firma_en_la_respuesta(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_cedula.png')
    especialidad = _crear_especialidad(app, 'Buscar Con Firma')
    admin_session.post('/usuarios', data={
        'primer_nombre': 'Esteban', 'primer_apellido': 'Ortiz',
        'email': 'esteban.ortiz@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar', 'cedula': '55566677',
        'firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    r = admin_session.get('/usuarios/buscar_cedula?cedula=55566677')
    data = r.get_json()
    assert data['encontrado'] is True
    assert data['firma'] == 'https://res.cloudinary.com/demo/image/upload/firma_cedula.png'


def test_modal_usuarios_incluye_el_capturador_de_firma(admin_session):
    texto = admin_session.get('/usuarios').get_data(as_text=True)
    assert 'firma-nuevo-canvas' in texto
    assert 'name="firma_dataurl"' in texto


def test_panel_inventario_incluye_el_capturador_de_firma(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'firma-rapido-canvas' in texto
