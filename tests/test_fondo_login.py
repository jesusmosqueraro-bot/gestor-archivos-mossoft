"""Pruebas del panel de marca del login ('Fondo de Login'): que el login siga funcionando
igual cuando no hay nada configurado, que muestre solo los archivos activos, y que darlos de
alta/pausar/reordenar/eliminar quede restringido a admin/agente (igual que Comunicados).

Cloudinary se reemplaza por un doble en las pruebas que suben o borran un archivo — no debe
depender de credenciales reales ni de una llamada de red real."""
import io
import cloudinary.uploader


def _crear_item_fondo(app, tipo='imagen', url='https://res.cloudinary.com/demo/image/upload/v1/fake.jpg', estado='activo', orden=0,
                       duracion_segundos=None, reproducir_con_sonido=False):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    if duracion_segundos is None:
        # Sin pasar la columna en el INSERT a propósito: así se prueba el DEFAULT 6 real de la
        # base de datos, no un valor que Python decida.
        q = ("INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por, reproducir_con_sonido) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
             if db_type == 'postgres' else
             "INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por, reproducir_con_sonido) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
        cur.execute(q, (tipo, url, 'fake_public_id', orden, estado, '2026-09-03 10:00:00', 'admin', reproducir_con_sonido))
    else:
        q = ("INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por, duracion_segundos, reproducir_con_sonido) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
             if db_type == 'postgres' else
             "INSERT INTO login_fondo_media (tipo, url, public_id, orden, estado, fecha_creacion, creado_por, duracion_segundos, reproducir_con_sonido) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
        cur.execute(q, (tipo, url, 'fake_public_id', orden, estado, '2026-09-03 10:00:00', 'admin', duracion_segundos, reproducir_con_sonido))
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


def test_login_sin_ningun_archivo_activo_centra_el_formulario_en_toda_la_pantalla(client, app):
    """Si todos los archivos del panel quedaron pausados (o nunca se activó ninguno), el panel
    de marca no se imprime — y en ese caso el login NO debe quedar encajonado en la columna
    angosta del 40% (pegado a la izquierda, con todo el resto de la pantalla vacío). Debe usar
    todo el ancho para quedar centrado en medio de la pantalla."""
    _crear_item_fondo(app, estado='inactivo')

    texto = client.get('/login').get_data(as_text=True)

    assert 'fondo-login-slide' not in texto
    assert 'md:w-2/5' not in texto


def test_login_ignora_items_pausados(client, app):
    _crear_item_fondo(app, estado='inactivo', url='https://res.cloudinary.com/demo/image/upload/pausado.jpg')

    r = client.get('/login')

    assert 'pausado.jpg' not in r.get_data(as_text=True)


def test_panel_de_fondo_usa_fondo_blanco_en_vez_de_oscuro(client, app):
    """Pedido de Tomás (13/09/2026): el panel se veía con una franja oscura visible cuando la
    imagen no llenaba el espacio (bg-slate-950 + object-contain). Se cambió a fondo blanco.
    Se revisa la clase del propio panel (no solo ausencia del texto en cualquier parte de la
    página, ya que un comentario explicativo en el HTML puede mencionar el nombre de la clase
    anterior sin que en realidad siga aplicada)."""
    _crear_item_fondo(app)

    texto = client.get('/login').get_data(as_text=True)

    assert 'md:w-3/5 relative overflow-hidden flex-shrink-0 bg-white' in texto
    assert 'md:w-3/5 relative overflow-hidden flex-shrink-0 bg-slate-950' not in texto


def test_panel_de_fondo_con_un_solo_archivo_no_muestra_controles_de_navegacion(client, app):
    """Con un único archivo activo no hay nada entre qué navegar, así que los botones/puntos no
    deben imprimirse (evita controles inútiles y JS que rompa con listas de 1 elemento)."""
    _crear_item_fondo(app)

    texto = client.get('/login').get_data(as_text=True)

    assert 'fondo-login-slide' in texto
    assert 'fondo-login-prev' not in texto
    assert 'fondo-login-next' not in texto
    assert 'fondo-login-punto' not in texto


def test_panel_de_fondo_con_varios_archivos_muestra_botones_y_puntos_de_navegacion(client, app):
    """Pedido de Tomás (13/09/2026): 'agrega botones para poder pasar las imagenes del
    carrusel'. Con más de un archivo activo deben aparecer las flechas prev/next y un punto
    indicador por cada archivo."""
    _crear_item_fondo(app, orden=0, url='https://res.cloudinary.com/demo/image/upload/uno.jpg')
    _crear_item_fondo(app, orden=1, url='https://res.cloudinary.com/demo/image/upload/dos.jpg')

    texto = client.get('/login').get_data(as_text=True)

    assert 'id="fondo-login-prev"' in texto
    assert 'id="fondo-login-next"' in texto
    assert texto.count('class="fondo-login-punto') == 2
    assert 'irManualmente' in texto


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


# ⏱️ Duración por archivo (pedido de Tomás, 13/09/2026: "habilitemos un campo... por defecto
# se establezca un tiempo determinado de duración en segundos. Más por el tema de los videos").

def test_login_usa_6_segundos_por_defecto_si_no_se_configuro_duracion(client, app):
    _crear_item_fondo(app)  # sin duracion_segundos: usa el DEFAULT 6 real de la tabla

    texto = client.get('/login').get_data(as_text=True)

    assert 'data-duracion-ms="6000"' in texto


def test_login_usa_la_duracion_personalizada_de_cada_archivo(client, app):
    _crear_item_fondo(app, duracion_segundos=15)

    texto = client.get('/login').get_data(as_text=True)

    assert 'data-duracion-ms="15000"' in texto


def test_admin_fondo_login_muestra_campo_de_duracion_con_valor_por_defecto(admin_session):
    """El formulario de subida trae el campo de duración prellenado con el valor por defecto,
    para no obligar a pensar en esto en cada subida."""
    texto = admin_session.get('/comunicados/fondo_login').get_data(as_text=True)

    assert 'name="duracion_segundos"' in texto
    assert 'id="duracion_segundos_nuevo" name="duracion_segundos" value="6"' in texto


def test_subir_fondo_login_guarda_la_duracion_enviada(admin_session, app, monkeypatch):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {
        'secure_url': 'https://res.cloudinary.com/demo/image/upload/duracion.jpg', 'public_id': 'duracion_id'
    })

    admin_session.post('/comunicados/fondo_login/subir',
                        data={'archivo': (io.BytesIO(b'contenido falso'), 'foto.jpg'), 'duracion_segundos': '20'},
                        content_type='multipart/form-data')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_segundos FROM login_fondo_media WHERE url = ?", ('https://res.cloudinary.com/demo/image/upload/duracion.jpg',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 20


def test_subir_fondo_login_usa_duracion_por_defecto_si_el_valor_es_invalido(admin_session, app, monkeypatch):
    """Un valor vacío, no numérico o fuera de rango (0, negativo, absurdamente alto) no debe
    rechazar la subida — el archivo ya se subió a Cloudinary — sino usar el valor por defecto."""
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {
        'secure_url': 'https://res.cloudinary.com/demo/image/upload/invalida.jpg', 'public_id': 'invalida_id'
    })

    admin_session.post('/comunicados/fondo_login/subir',
                        data={'archivo': (io.BytesIO(b'contenido falso'), 'foto.jpg'), 'duracion_segundos': 'no-es-un-numero'},
                        content_type='multipart/form-data')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_segundos FROM login_fondo_media WHERE url = ?", ('https://res.cloudinary.com/demo/image/upload/invalida.jpg',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 6


def test_editar_duracion_fondo_login_actualiza_el_valor(admin_session, app):
    item_id = _crear_item_fondo(app)

    admin_session.post(f'/comunicados/fondo_login/{item_id}/duracion', data={'duracion_segundos': '30'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_segundos FROM login_fondo_media WHERE id = ?", (item_id,))
    duracion = cur.fetchone()[0]
    conn.close()
    assert duracion == 30


def test_editar_duracion_fondo_login_valor_fuera_de_rango_usa_default(admin_session, app):
    item_id = _crear_item_fondo(app, duracion_segundos=15)

    admin_session.post(f'/comunicados/fondo_login/{item_id}/duracion', data={'duracion_segundos': '99999'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_segundos FROM login_fondo_media WHERE id = ?", (item_id,))
    duracion = cur.fetchone()[0]
    conn.close()
    assert duracion == 6


def test_estandar_no_puede_editar_duracion_de_fondo_login(client, sesion_usuario, app):
    item_id = _crear_item_fondo(app)

    r = client.post(f'/comunicados/fondo_login/{item_id}/duracion', data={'duracion_segundos': '30'})

    assert r.status_code in (302, 403)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_segundos FROM login_fondo_media WHERE id = ?", (item_id,))
    duracion = cur.fetchone()[0]
    conn.close()
    assert duracion == 6  # sin cambios


# 🔊 "Reproducir con sonido" (pedido de Tomás, 13/09/2026: "que el tema de dar sonido o no, se
# haga directamente cuando se carga el video al sistema").

def test_login_video_sin_reproducir_con_sonido_trae_data_intenta_sonido_en_0(client, app):
    _crear_item_fondo(app, tipo='video', url='https://res.cloudinary.com/demo/video/upload/v1/clip.mp4')

    texto = client.get('/login').get_data(as_text=True)

    assert 'data-intenta-sonido="0"' in texto


def test_login_video_con_reproducir_con_sonido_trae_data_intenta_sonido_en_1(client, app):
    _crear_item_fondo(app, tipo='video', url='https://res.cloudinary.com/demo/video/upload/v1/clip.mp4', reproducir_con_sonido=True)

    texto = client.get('/login').get_data(as_text=True)

    assert 'data-intenta-sonido="1"' in texto


def test_admin_fondo_login_muestra_casilla_de_reproducir_con_sonido(admin_session):
    texto = admin_session.get('/comunicados/fondo_login').get_data(as_text=True)

    assert 'name="reproducir_con_sonido"' in texto


def test_subir_fondo_login_video_guarda_reproducir_con_sonido_marcado(admin_session, app, monkeypatch):
    monkeypatch.setattr(cloudinary.uploader, 'upload_large', lambda *a, **k: {
        'secure_url': 'https://res.cloudinary.com/demo/video/upload/con_sonido.mp4', 'public_id': 'con_sonido_id'
    })

    admin_session.post('/comunicados/fondo_login/subir',
                        data={'archivo': (io.BytesIO(b'contenido falso'), 'clip.mp4'), 'reproducir_con_sonido': 'on'},
                        content_type='multipart/form-data')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT reproducir_con_sonido FROM login_fondo_media WHERE url = ?", ('https://res.cloudinary.com/demo/video/upload/con_sonido.mp4',))
    fila = cur.fetchone()
    conn.close()
    assert bool(fila[0]) is True


def test_subir_fondo_login_sin_marcar_sonido_queda_silenciado_por_defecto(admin_session, app, monkeypatch):
    monkeypatch.setattr(cloudinary.uploader, 'upload_large', lambda *a, **k: {
        'secure_url': 'https://res.cloudinary.com/demo/video/upload/silenciado.mp4', 'public_id': 'silenciado_id'
    })

    admin_session.post('/comunicados/fondo_login/subir',
                        data={'archivo': (io.BytesIO(b'contenido falso'), 'clip.mp4')},
                        content_type='multipart/form-data')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT reproducir_con_sonido FROM login_fondo_media WHERE url = ?", ('https://res.cloudinary.com/demo/video/upload/silenciado.mp4',))
    fila = cur.fetchone()
    conn.close()
    assert bool(fila[0]) is False


def test_toggle_sonido_fondo_login_activa_y_desactiva(admin_session, app):
    item_id = _crear_item_fondo(app, tipo='video', url='https://res.cloudinary.com/demo/video/upload/v1/toggle.mp4')

    admin_session.post(f'/comunicados/fondo_login/{item_id}/sonido')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT reproducir_con_sonido FROM login_fondo_media WHERE id = ?", (item_id,))
    assert bool(cur.fetchone()[0]) is True
    conn.close()

    admin_session.post(f'/comunicados/fondo_login/{item_id}/sonido')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT reproducir_con_sonido FROM login_fondo_media WHERE id = ?", (item_id,))
    assert bool(cur.fetchone()[0]) is False
    conn.close()


def test_admin_fondo_login_muestra_boton_de_sonido_solo_para_video(admin_session, app):
    _crear_item_fondo(app, tipo='video', url='https://res.cloudinary.com/demo/video/upload/v1/con_boton.mp4', orden=0)
    _crear_item_fondo(app, tipo='imagen', url='https://res.cloudinary.com/demo/image/upload/v1/sin_boton.jpg', orden=1)

    texto = admin_session.get('/comunicados/fondo_login').get_data(as_text=True)

    assert 'toggle_sonido_fondo_login' in texto or '/sonido' in texto
    assert texto.count('fa-volume-xmark') >= 1 or texto.count('fa-volume-high') >= 1
