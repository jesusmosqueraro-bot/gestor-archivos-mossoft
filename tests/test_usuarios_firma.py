"""Pruebas de la firma digital de un colaborador desde 'Modificar Usuario' (Gestión de
Usuarios) — reportado por Tomás (06/09/2026): 'usuarios.firma' (la que de verdad se usa en las
actas de asignación y devolución del Inventario, ver _resolver_firma_de_usuario/
_resolver_firma_para_asignacion) solo se podía capturar UNA vez, al crear la cuenta. Si no
quedó guardada entonces, o quedó mal, no había forma de agregarla/corregirla después: el botón
"Editar" de Gestión de Usuarios no tenía ningún campo para eso (la firma de un colaborador que
sí existía era, en realidad, un 'documento' de otro módulo aparte — no la misma columna). Ahora
'Modificar Usuario' también puede agregar, reemplazar o quitar esa firma."""
import cloudinary.uploader


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_nueva.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


FIRMA_DATAURL_VALIDA = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4'
                         '2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def _firma_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _fijar_firma(app, usuario, url):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET firma = ? WHERE usuario = ?", (url, usuario))
    conn.commit()
    conn.close()


def _id_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0]


def test_admin_puede_agregar_firma_a_un_usuario_que_no_tenia(admin_session, app, crear_usuario, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    usuario = crear_usuario(usuario='colaborador_sin_firma')
    assert _firma_de(app, usuario) is None
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    assert r.status_code == 302
    assert _firma_de(app, usuario) == 'https://res.cloudinary.com/demo/image/upload/firma_nueva.png'


def test_admin_puede_reemplazar_una_firma_existente(admin_session, app, crear_usuario, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_reemplazada.png')
    usuario = crear_usuario(usuario='colaborador_con_firma')
    _fijar_firma(app, usuario, 'https://res.cloudinary.com/demo/image/upload/firma_vieja.png')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    assert r.status_code == 302
    assert _firma_de(app, usuario) == 'https://res.cloudinary.com/demo/image/upload/firma_reemplazada.png'


def test_editar_usuario_sin_tocar_firma_conserva_la_existente(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='colaborador_firma_intacta')
    _fijar_firma(app, usuario, 'https://res.cloudinary.com/demo/image/upload/firma_original.png')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'telefono': '3009998877',
    })

    assert r.status_code == 302
    assert _firma_de(app, usuario) == 'https://res.cloudinary.com/demo/image/upload/firma_original.png'


def test_admin_puede_quitar_la_firma_guardada(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='colaborador_quitar_firma')
    _fijar_firma(app, usuario, 'https://res.cloudinary.com/demo/image/upload/firma_a_quitar.png')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'quitar_firma': 'on',
    })

    assert r.status_code == 302
    assert _firma_de(app, usuario) is None


def test_gestion_usuarios_incluye_la_firma_para_precargar_el_modal_de_editar(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='colaborador_listado_firma')
    _fijar_firma(app, usuario, 'https://res.cloudinary.com/demo/image/upload/firma_listado.png')

    texto = admin_session.get('/usuarios').get_data(as_text=True)

    assert 'firma_listado.png' in texto
