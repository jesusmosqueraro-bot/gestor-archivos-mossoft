"""Pruebas del Acta de Recibido para activos biomédicos entregados a domicilio (bombas de
infusión y similares): un activo marcado 'es_biomedico' puede, al asignarse/editarse, registrar
un acta con quién recibió el equipo (paciente o cuidador), su documento, la dirección de entrega
y su firma — y ese registro queda en un historial aparte (actas_recibido_biomedico), separado de
la firma de asignación normal, porque puede haber más de una entrega a lo largo de la vida del
activo."""
import base64

import cloudinary.uploader

PNG_1X1_B64 = base64.b64encode(bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
    0x42, 0x60, 0x82
])).decode('ascii')
FIRMA_DATAURL_VALIDA = 'data:image/png;base64,' + PNG_1X1_B64


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_acta.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def _crear_activo_directo(app, nombre='60001', es_biomedico=False):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Bomba de infusión', 'Disponible', es_biomedico, '2026-09-04 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_biomedico_con_acta_completa_registra_el_acta(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)

    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '60010', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on',
        'acta_nombre_responsable': 'Rosa Pérez', 'acta_relacion_responsable': 'cuidador',
        'acta_documento_responsable': '12345678', 'acta_telefono_contacto': '3001112233',
        'acta_direccion_entrega': 'Calle 10 # 5-20, Cali', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, es_biomedico FROM activos_inventario WHERE nombre = ?", ('60010',))
    activo_id, es_biomedico = cur.fetchone()
    assert bool(es_biomedico) is True
    cur.execute(
        "SELECT nombre_responsable, relacion_responsable, documento_responsable, telefono_contacto, "
        "direccion_entrega, firma_url FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,)
    )
    acta = cur.fetchone()
    conn.close()
    assert acta == ('Rosa Pérez', 'cuidador', '12345678', '3001112233', 'Calle 10 # 5-20, Cali',
                     'https://res.cloudinary.com/demo/image/upload/firma_acta.png')
    texto = r.get_data(as_text=True)
    assert 'Acta de recibido registrada' in texto


def test_crear_activo_no_biomedico_ignora_los_campos_de_acta(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '60011', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        # Sin 'es_biomedico' — aunque vengan datos de acta, no debe registrarse nada.
        'acta_nombre_responsable': 'Alguien', 'acta_direccion_entrega': 'Una dirección',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('60011',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_biomedico_marcado_sin_datos_de_acta_no_falla_ni_registra_nada(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '60012', 'tipo_activo': 'Bomba de infusión', 'estado': 'Disponible',
        'es_biomedico': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, es_biomedico FROM activos_inventario WHERE nombre = ?", ('60012',))
    activo_id, es_biomedico = cur.fetchone()
    assert bool(es_biomedico) is True
    cur.execute("SELECT COUNT(*) FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_acta_con_datos_incompletos_no_bloquea_el_guardado_del_activo_pero_avisa(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '60013', 'tipo_activo': 'Bomba de infusión', 'estado': 'Disponible',
        'es_biomedico': 'on',
        'acta_nombre_responsable': 'Solo el nombre, falta el resto',
    }, follow_redirects=True)

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('60013',))
    assert cur.fetchone()[0] == 1  # el activo SÍ se guardó
    conn.close()
    texto = r.get_data(as_text=True)
    assert 'ACTA DE RECIBIDO' in texto or 'acta de recibido' in texto.lower()


def test_editar_activo_biomedico_agrega_una_segunda_acta_sin_borrar_la_primera(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/primera.png')
    activo_id = _crear_activo_directo(app, nombre='60014', es_biomedico=True)

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '60014', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on', 'acta_nombre_responsable': 'Primer Paciente',
        'acta_relacion_responsable': 'paciente', 'acta_direccion_entrega': 'Dirección 1',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/segunda.png')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '60014', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on', 'acta_nombre_responsable': 'Segundo Cuidador',
        'acta_relacion_responsable': 'cuidador', 'acta_direccion_entrega': 'Dirección 2',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre_responsable FROM actas_recibido_biomedico WHERE activo_id = ? ORDER BY id", (activo_id,))
    nombres = [f[0] for f in cur.fetchall()]
    conn.close()
    assert nombres == ['Primer Paciente', 'Segundo Cuidador']


def test_listar_actas_de_un_activo(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    activo_id = _crear_activo_directo(app, nombre='60015', es_biomedico=True)
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '60015', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on', 'acta_nombre_responsable': 'Ana Torres',
        'acta_relacion_responsable': 'paciente', 'acta_direccion_entrega': 'Carrera 5 # 10-15',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    r = admin_session.get(f'/tickets/inventario/{activo_id}/actas')
    data = r.get_json()
    assert len(data['actas']) == 1
    assert data['actas'][0]['nombre_responsable'] == 'Ana Torres'


def test_acta_pdf_se_genera_correctamente(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_pdf.png')
    activo_id = _crear_activo_directo(app, nombre='60016', es_biomedico=True)
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '60016', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on', 'acta_nombre_responsable': 'Luis Gómez',
        'acta_relacion_responsable': 'paciente', 'acta_direccion_entrega': 'Avenida Siempre Viva 742',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    acta_id = cur.fetchone()[0]
    conn.close()

    # La firma quedó como una URL falsa de Cloudinary — no existe de verdad, así que incrustarla
    # en el PDF fallará silenciosamente (queda como texto) en vez de romper la generación.
    r = admin_session.get(f'/tickets/inventario/actas/{acta_id}/pdf')
    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data[:4] == b'%PDF'


def test_modal_inventario_incluye_la_seccion_biomedica(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'name="es_biomedico"' in texto
    assert 'name="acta_direccion_entrega"' in texto
    assert 'firma-acta-canvas' in texto


def test_actas_requiere_rol_operativo(sesion_usuario, app):
    activo_id = _crear_activo_directo(app, nombre='60017', es_biomedico=True)
    r = sesion_usuario.get(f'/tickets/inventario/{activo_id}/actas')
    assert r.status_code in (302, 403)
