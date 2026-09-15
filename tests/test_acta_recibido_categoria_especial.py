"""Pruebas del Acta de Recibido para las categorías especiales SST, Ambiental y Laboratorio
Clínico (pedido por Tomás, 15/09/2026: "igual al de biomédicos, con acta") — mismo flujo que ya
existía para 'es_biomedico', pero disparado por el campo 'categoria_especial' (sst/ambiental/
laboratorio) y una nueva casilla 'es_categoria_especial' en el formulario. Comparte la misma
tabla histórica 'actas_recibido_biomedico', ahora con una columna 'categoria' que distingue de
cuál se trata. Ver TEXTOS_CATEGORIA_ESPECIAL / _categoria_especial_activo /
_registrar_acta_recibido_biomedico en app.py."""
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


def _crear_activo_directo(app, nombre, categoria_especial=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, categoria_especial, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, categoria_especial, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Extintor / Equipo Contra Incendios', 'Disponible', categoria_especial,
                     '2026-09-15 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_sst_con_acta_completa_registra_el_acta(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)

    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70010', 'tipo_activo': 'Extintor / Equipo Contra Incendios', 'estado': 'Asignado',
        'es_categoria_especial': 'on', 'categoria_especial': 'sst',
        'acta_nombre_responsable': 'Carlos Ruiz', 'acta_relacion_responsable': 'colaborador',
        'acta_documento_responsable': '98765432', 'acta_telefono_contacto': '3009998877',
        'acta_direccion_entrega': 'Calle 20 # 8-30, Cali', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, categoria_especial, es_biomedico FROM activos_inventario WHERE nombre = ?", ('70010',))
    activo_id, categoria_especial, es_biomedico = cur.fetchone()
    assert categoria_especial == 'sst'
    assert bool(es_biomedico) is False
    cur.execute(
        "SELECT nombre_responsable, relacion_responsable, documento_responsable, telefono_contacto, "
        "direccion_entrega, firma_url, categoria FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,)
    )
    acta = cur.fetchone()
    conn.close()
    assert acta == ('Carlos Ruiz', 'colaborador', '98765432', '3009998877', 'Calle 20 # 8-30, Cali',
                     'https://res.cloudinary.com/demo/image/upload/firma_acta.png', 'sst')
    texto = r.get_data(as_text=True)
    assert 'Acta de recibido registrada' in texto


def test_crear_activo_sin_categoria_especial_ignora_los_campos_de_acta(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70011', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        # Sin 'es_categoria_especial' — aunque venga 'categoria_especial' y datos de acta, no
        # debe registrarse nada (igual que un activo de TI normal).
        'categoria_especial': 'sst',
        'acta_nombre_responsable': 'Alguien', 'acta_direccion_entrega': 'Una dirección',
        'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, categoria_especial FROM activos_inventario WHERE nombre = ?", ('70011',))
    activo_id, categoria_especial = cur.fetchone()
    assert categoria_especial is None
    cur.execute("SELECT COUNT(*) FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_categoria_especial_invalida_se_ignora(admin_session, app):
    """Un valor de 'categoria_especial' que no sea sst/ambiental/laboratorio se descarta (no se
    guarda un valor arbitrario en la columna, ni se dispara el flujo de acta)."""
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70012', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        'es_categoria_especial': 'on', 'categoria_especial': 'algo-inventado',
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT categoria_especial FROM activos_inventario WHERE nombre = ?", ('70012',))
    assert cur.fetchone()[0] is None
    conn.close()


def test_es_biomedico_tiene_prioridad_sobre_categoria_especial(admin_session, app, monkeypatch):
    """Si por algún motivo llegaran marcadas ambas casillas a la vez (no debería pasar, son
    mutuamente excluyentes en el formulario), 'es_biomedico' manda — ver
    _categoria_especial_activo."""
    _mock_cloudinary_upload(monkeypatch)
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70013', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado',
        'es_biomedico': 'on', 'es_categoria_especial': 'on', 'categoria_especial': 'laboratorio',
        'acta_nombre_responsable': 'Doble Marca', 'acta_relacion_responsable': 'paciente',
        'acta_direccion_entrega': 'Calle 1 # 1-1', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('70013',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT categoria FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'biomedico'
    conn.close()


def test_editar_activo_ambiental_agrega_una_segunda_acta_sin_borrar_la_primera(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/primera.png')
    activo_id = _crear_activo_directo(app, nombre='70014', categoria_especial='ambiental')

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70014', 'tipo_activo': 'Kit Antiderrames', 'estado': 'Asignado',
        'es_categoria_especial': 'on', 'categoria_especial': 'ambiental',
        'acta_nombre_responsable': 'Primer Responsable', 'acta_relacion_responsable': 'colaborador',
        'acta_direccion_entrega': 'Dirección 1', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/segunda.png')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70014', 'tipo_activo': 'Kit Antiderrames', 'estado': 'Asignado',
        'es_categoria_especial': 'on', 'categoria_especial': 'ambiental',
        'acta_nombre_responsable': 'Segundo Responsable', 'acta_relacion_responsable': 'contratista',
        'acta_direccion_entrega': 'Dirección 2', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre_responsable FROM actas_recibido_biomedico WHERE activo_id = ? ORDER BY id", (activo_id,))
    nombres = [f[0] for f in cur.fetchall()]
    conn.close()
    assert nombres == ['Primer Responsable', 'Segundo Responsable']


def test_listar_actas_de_un_activo_de_laboratorio(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    activo_id = _crear_activo_directo(app, nombre='70015', categoria_especial='laboratorio')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70015', 'tipo_activo': 'Equipo de Laboratorio Clínico', 'estado': 'Asignado',
        'es_categoria_especial': 'on', 'categoria_especial': 'laboratorio',
        'acta_nombre_responsable': 'Marta Lima', 'acta_relacion_responsable': 'colaborador',
        'acta_direccion_entrega': 'Carrera 8 # 15-20', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    })

    r = admin_session.get(f'/tickets/inventario/{activo_id}/actas')
    data = r.get_json()
    assert len(data['actas']) == 1
    assert data['actas'][0]['nombre_responsable'] == 'Marta Lima'
    assert data['actas'][0]['categoria'] == 'laboratorio'


def test_acta_pdf_sst_se_genera_con_titulo_propio(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_pdf.png')
    activo_id = _crear_activo_directo(app, nombre='70016', categoria_especial='sst')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70016', 'tipo_activo': 'Elementos de Protección Personal (EPP)', 'estado': 'Asignado',
        'es_categoria_especial': 'on', 'categoria_especial': 'sst',
        'acta_nombre_responsable': 'Jorge Nieto', 'acta_relacion_responsable': 'colaborador',
        'acta_direccion_entrega': 'Avenida Siempre Viva 742', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
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


def test_modal_inventario_incluye_la_seccion_de_categoria_especial(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'name="es_categoria_especial"' in texto
    assert 'name="categoria_especial"' in texto
    assert 'name="acta_direccion_entrega"' in texto


def test_confirmar_devolucion_de_activo_sst_acepta_responsable_de_la_entrega(admin_session, app, monkeypatch):
    """El flujo de certificación de devolución (paz y salvo) también debe aceptar la firma de
    'responsable de la entrega' para un activo con categoria_especial, igual que ya hacía para
    biomédicos con 'familiar/cuidador'."""
    _mock_cloudinary_upload(monkeypatch)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, ('70017', 'Extintor / Equipo Contra Incendios', 'Asignado', 'Un Colaborador', 'sst',
                    '2026-09-15 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'nombre_familiar': 'Quien Recibió En Bodega',
        'firma_familiar_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre_familiar, firma_familiar_url FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    nombre_familiar, firma_familiar_url = cur.fetchone()
    conn.close()
    assert nombre_familiar == 'Quien Recibió En Bodega'
    assert firma_familiar_url == 'https://res.cloudinary.com/demo/image/upload/firma_acta.png'
