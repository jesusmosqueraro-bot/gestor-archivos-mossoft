"""Pedido por Tomás: pop-up de campanita para el equipo operativo cuando se crea una cuenta
nueva, y pop-up para quien corresponda cuando se publica un Comunicado o un Instructivo — en
ambos casos siguiendo la MISMA clasificación de visibilidad ('todos'/'admin') que ya decide
quién puede VER esa publicación. Comunicados no tenía esa clasificación antes de este cambio
(solo Instructivos la traía) — 'Segun la configuracion de quien lo puede ver, asi mismo puede
salir el pop-up' (respuesta textual de Tomás)."""
import io

import cloudinary.uploader
import pytest


def _mock_cloudinary(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/adjunto.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})
    monkeypatch.setattr(cloudinary.uploader, 'upload_large', lambda *a, **k: {'secure_url': url})


def _notificaciones_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = "SELECT mensaje, tipo FROM notificaciones WHERE usuario = %s" if db_type == 'postgres' else "SELECT mensaje, tipo FROM notificaciones WHERE usuario = ?"
    cur.execute(q, (usuario,))
    filas = cur.fetchall()
    conn.close()
    return filas


# ────────────────────────────────────────────────────────────────────────────
# COMUNICADOS: nueva clasificación de visibilidad + pop-up acorde
# ────────────────────────────────────────────────────────────────────────────

def test_crear_comunicado_todos_notifica_a_usuario_estandar(admin_session, app, crear_usuario):
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')

    r = admin_session.post('/comunicados/crear', data={
        'titulo': 'Mantenimiento programado', 'contenido': '<p>Detalle</p>',
        'nivel': 'info', 'visibilidad': 'todos'
    })
    assert r.status_code == 302

    filas = _notificaciones_de(app, estandar)
    assert any('Mantenimiento programado' in m and t == 'comunicado' for m, t in filas)


def test_crear_comunicado_admin_no_notifica_a_usuario_estandar_pero_si_a_agente(admin_session, app, crear_usuario):
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')
    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')

    r = admin_session.post('/comunicados/crear', data={
        'titulo': 'Cambio interno de procesos', 'contenido': '<p>Solo para el equipo</p>',
        'nivel': 'importante', 'visibilidad': 'admin'
    })
    assert r.status_code == 302

    assert _notificaciones_de(app, estandar) == []
    filas_agente = _notificaciones_de(app, agente)
    assert any('Cambio interno de procesos' in m and t == 'comunicado' for m, t in filas_agente)


def test_crear_comunicado_no_autonotifica_a_quien_lo_publica(admin_session, app):
    admin_session.post('/comunicados/crear', data={
        'titulo': 'Autonotificación', 'contenido': '<p>x</p>', 'nivel': 'info', 'visibilidad': 'todos'
    })
    assert _notificaciones_de(app, 'admin') == []


def test_comunicado_visibilidad_invalida_cae_a_todos(admin_session, app, crear_usuario):
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')
    admin_session.post('/comunicados/crear', data={
        'titulo': 'Valor rarísimo', 'contenido': '<p>x</p>', 'nivel': 'info', 'visibilidad': 'lo-que-sea'
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT visibilidad FROM comunicados WHERE titulo = ?", ('Valor rarísimo',))
    assert cur.fetchone()[0] == 'todos'
    conn.close()
    assert _notificaciones_de(app, estandar) != []


def test_ver_comunicados_oculta_los_de_admin_a_un_usuario_estandar(client, app, crear_usuario):
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO comunicados (titulo, contenido, fecha, autor, visibilidad) VALUES (%s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO comunicados (titulo, contenido, fecha, autor, visibilidad) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, ('Solo para soporte', '<p>x</p>', '2026-09-01 08:00:00', 'admin', 'admin'))
    cur.execute(q, ('Para todos', '<p>y</p>', '2026-09-01 08:00:00', 'admin', 'todos'))
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = estandar
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    html = client.get('/comunicados').get_data(as_text=True)

    assert 'Para todos' in html
    assert 'Solo para soporte' not in html


def test_ver_comunicados_si_muestra_los_de_admin_a_un_agente(client, app, crear_usuario):
    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO comunicados (titulo, contenido, fecha, autor, visibilidad) VALUES (%s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO comunicados (titulo, contenido, fecha, autor, visibilidad) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, ('Solo para soporte', '<p>x</p>', '2026-09-01 08:00:00', 'admin', 'admin'))
    conn.commit()
    conn.close()

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = agente
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    html = client.get('/comunicados').get_data(as_text=True)

    assert 'Solo para soporte' in html


# ────────────────────────────────────────────────────────────────────────────
# INSTRUCTIVOS: pop-up de publicación siguiendo la visibilidad ya existente
# ────────────────────────────────────────────────────────────────────────────

def test_subir_instructivo_todos_notifica_a_usuario_estandar(admin_session, app, crear_usuario, monkeypatch):
    """Los .png de prueba de este archivo llevan la firma real de un PNG al inicio del contenido
    (ver _firma_archivo_coincide en app.py) — desde el hallazgo de seguridad del 06/09/2026,
    archivo_permitido ya no confía solo en la extensión del nombre para decidir si sube el
    archivo (y por lo tanto si se crea/notifica el instructivo)."""
    _mock_cloudinary(monkeypatch)
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')

    data = {
        'titulo': 'Guía de Facturación', 'descripcion': 'Paso a paso', 'categoria': 'General',
        'tipo': 'Instructivo', 'tags': '', 'visibilidad': 'todos',
        'archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido de prueba'), 'guia.png')
    }
    r = admin_session.post('/subir', data=data, content_type='multipart/form-data')
    assert r.status_code == 302

    filas = _notificaciones_de(app, estandar)
    assert any('Guía de Facturación' in m and t == 'instructivo' for m, t in filas)


def test_subir_instructivo_admin_no_notifica_a_usuario_estandar(admin_session, app, crear_usuario, monkeypatch):
    _mock_cloudinary(monkeypatch)
    estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar')
    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')

    data = {
        'titulo': 'Manual Interno TI', 'descripcion': 'Solo soporte', 'categoria': 'General',
        'tipo': 'Instructivo', 'tags': '', 'visibilidad': 'admin',
        'archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido de prueba'), 'manual.png')
    }
    r = admin_session.post('/subir', data=data, content_type='multipart/form-data')
    assert r.status_code == 302

    assert _notificaciones_de(app, estandar) == []
    filas_agente = _notificaciones_de(app, agente)
    assert any('Manual Interno TI' in m and t == 'instructivo' for m, t in filas_agente)


def test_subir_instructivo_no_autonotifica_a_quien_lo_publica(admin_session, app, monkeypatch):
    _mock_cloudinary(monkeypatch)
    data = {
        'titulo': 'Autonotificación Instructivo', 'descripcion': '', 'categoria': 'General',
        'tipo': 'Instructivo', 'tags': '', 'visibilidad': 'todos',
        'archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido de prueba'), 'x.png')
    }
    admin_session.post('/subir', data=data, content_type='multipart/form-data')
    assert _notificaciones_de(app, 'admin') == []


# ────────────────────────────────────────────────────────────────────────────
# USUARIOS: pop-up al equipo operativo cuando se crea una cuenta nueva
# ────────────────────────────────────────────────────────────────────────────

def test_crear_usuario_notifica_a_otros_admin_y_agentes(admin_session, app, crear_usuario):
    otro_admin = crear_usuario(rol='admin', nombre='Otro Administrador')
    agente = crear_usuario(rol='agente', nombre='Agente de Soporte')

    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Carlos', 'primer_apellido': 'Ramírez', 'email': 'carlos.ramirez@preventivaips.com.co',
        'password': 'ClaveSegura123', 'especialidad': 'Sistemas', 'rol': 'estandar'
    })
    assert r.status_code == 302

    for destinatario in (otro_admin, agente):
        filas = _notificaciones_de(app, destinatario)
        assert any('Carlos Ramírez' in m and t == 'usuario_nuevo' for m, t in filas), f"{destinatario} no fue notificado"


def test_crear_usuario_no_notifica_al_creador_ni_a_la_cuenta_nueva(admin_session, app):
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Laura', 'primer_apellido': 'Gómez', 'email': 'laura.gomez@preventivaips.com.co',
        'password': 'ClaveSegura123', 'especialidad': 'Sistemas', 'rol': 'estandar'
    })
    assert r.status_code == 302

    assert not any(t == 'usuario_nuevo' for _, t in _notificaciones_de(app, 'admin'))

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT usuario FROM usuarios WHERE correo = ?", ('laura.gomez@preventivaips.com.co',))
    nuevo_user = cur.fetchone()[0]
    conn.close()
    assert not any(t == 'usuario_nuevo' for _, t in _notificaciones_de(app, nuevo_user))
    # sí recibió su propia bienvenida
    assert any(t == 'bienvenida' for _, t in _notificaciones_de(app, nuevo_user))


def test_crear_usuario_estandar_no_notifica_a_otro_usuario_estandar(admin_session, app, crear_usuario):
    """El pop-up es solo para el equipo operativo (admin/agente) — un usuario estándar no
    necesita enterarse de cada alta de cuenta que hace TI."""
    otro_estandar = crear_usuario(rol='estandar', nombre='Usuario Estandar Existente')

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Marta', 'primer_apellido': 'Ruiz', 'email': 'marta.ruiz@preventivaips.com.co',
        'password': 'ClaveSegura123', 'especialidad': 'Sistemas', 'rol': 'estandar'
    })

    assert _notificaciones_de(app, otro_estandar) == []
