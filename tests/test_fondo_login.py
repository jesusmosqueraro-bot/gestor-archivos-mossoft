"""Pruebas del panel de marca del login ('Fondo de Login'): que el login siga funcionando
igual cuando no hay nada configurado, que muestre solo los archivos activos, y que darlos de
alta/pausar/reordenar/eliminar quede restringido a admin/agente (igual que Comunicados).

Cloudinary se reemplaza por un doble en las pruebas que suben o borran un archivo — no debe
depender de credenciales reales ni de una llamada de red real."""
import io
import cloudinary.uploader


def _crear_item_fondo(app, tipo='imagen', url='https://res.cloudinary.com/demo/image/upload/v1/fake.jpg', estado='activo', orden=0):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (tipo, url, 'fake_public_id', orden, estado, '2026-09-03 10:00:00', 'admin'))
    item_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def test_login_sin_fondo_configurado_no_muestra_panel(client):
    r = client.get('/login')

    assert r.status_code == 200
    assert 'fondo-login-slide' not in r.get_data(as_text=True)


def test_login_con_fondo_activo_muestra_el_panel(client, app):
    _crear_item_fondo(app)

    r = client.get('/login')
    texto = r.get_data(as_text=True)

    assert r.status_code == 200
    assert 'fondo-login-slide' in texto
    assert 'fake.jpg' in texto


def test_panel_de_fondo_ocupa_mas_espacio_que_el_login_y_no_toca_el_modulo(client, app):
    """El panel va pegado al borde y es más ancho que la columna del login (60/40, layout de
    borde a borde tipo Facebook/Solvyx) y el módulo de login en sí (acción, csrf, recaptcha)
    debe seguir intacto."""
    _crear_item_fondo(app)

    texto = client.get('/login').get_data(as_text=True)

    assert 'md:w-3/5' in texto
    assert 'md:w-2/5' in texto
    assert 'md:w-80' not in texto and 'lg:w-96' not in texto and 'md:w-1/2' not in texto
    assert 'action="/login"' in texto
    assert 'csrf_token' in texto
    assert 'g-recaptcha' in texto


def test_login_muestra_la_imagen_completa_sin_recortar(client, app):
    """El panel usaba object-cover, que recorta cualquier imagen cuya proporción no calce
    exactamente con la del panel (caso real: una imagen ancha tipo banner quedaba cortada por
    los bordes). Debe usar object-contain para que el archivo se vea completo siempre."""
    _crear_item_fondo(app)

    texto = client.get('/login').get_data(as_text=True)

    assert 'object-contain' in texto
    assert 'object-cover' not in texto


def test_login_ignora_items_pausados(client, app):
    _crear_item_fondo(app, estado='inactivo', url='https://res.cloudinary.com/demo/image/upload/pausado.jpg')

    r = client.get('/login')

    assert 'pausado.jpg' not in r.get_data(as_text=True)


def test_estandar_no_puede_ver_fondo_login(client, sesion_usuario):
    r = client.get('/comunicados/fondo_login')

    assert r.status_code in (302, 403)


def test_admin_puede_ver_fondo_login(admin_session):
    r = admin_session.get('/comunicados/fondo_login')

    assert r.status_code == 200


def test_subir_fondo_login_guarda_registro(admin_session, app, monkeypatch):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {
        'secure_url': 'https://res.cloudinary.com/demo/image/upload/nuevo.jpg', 'public_id': 'nuevo_id'
    })

    r = admin_session.post('/comunicados/fondo_login/subir',
                            data={'archivo': (io.BytesIO(b'contenido falso'), 'foto.jpg')},
                            content_type='multipart/form-data')

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo, url, estado FROM login_fondo_media")
    fila = cur.fetchone()
    conn.close()
    assert fila == ('imagen', 'https://res.cloudinary.com/demo/image/upload/nuevo.jpg', 'activo')


def test_subir_fondo_login_rechaza_formato_no_permitido(admin_session, app):
    r = admin_session.post('/comunicados/fondo_login/subir',
                            data={'archivo': (io.BytesIO(b'contenido falso'), 'documento.pdf')},
                            content_type='multipart/form-data', follow_redirects=True)

    assert 'Formato no permitido' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM login_fondo_media")
    assert cur.fetchone()[0] == 0
    conn.close()


def test_toggle_fondo_login_pausa_el_archivo(admin_session, app):
    item_id = _crear_item_fondo(app)

    admin_session.post(f'/comunicados/fondo_login/{item_id}/toggle')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM login_fondo_media WHERE id = ?", (item_id,))
    estado = cur.fetchone()[0]
    conn.close()
    assert estado == 'inactivo'


def test_eliminar_fondo_login_borra_el_registro(admin_session, app, monkeypatch):
    monkeypatch.setattr(cloudinary.uploader, 'destroy', lambda *a, **k: {'result': 'ok'})
    item_id = _crear_item_fondo(app)

    admin_session.post(f'/comunicados/fondo_login/{item_id}/eliminar')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM login_fondo_media WHERE id = ?", (item_id,))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 0


def test_mover_fondo_login_intercambia_el_orden(admin_session, app):
    id1 = _crear_item_fondo(app, orden=0, url='https://res.cloudinary.com/demo/image/upload/uno.jpg')
    id2 = _crear_item_fondo(app, orden=1, url='https://res.cloudinary.com/demo/image/upload/dos.jpg')

    admin_session.post(f'/comunicados/fondo_login/{id2}/mover/subir')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM login_fondo_media ORDER BY orden ASC, id ASC")
    orden_ids = [f[0] for f in cur.fetchall()]
    conn.close()
    assert orden_ids == [id2, id1]


def test_fondo_login_tiene_boton_de_tema_claro_oscuro(admin_session):
    """Esta pantalla se había quedado sin el botón flotante de tema claro/oscuro que sí tienen
    las demás páginas del sistema — se agrega para que sea consistente."""
    texto = admin_session.get('/comunicados/fondo_login').get_data(as_text=True)

    assert 'action="/perfil/tema"' in texto
    assert 'fa-sun' in texto or 'fa-moon' in texto
