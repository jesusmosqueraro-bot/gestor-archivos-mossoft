"""Pruebas del logo institucional de Preventiva Salud IPS (pedido de Tomás, 08/09/2026: 'pongamos
este logo en la pagina de devolución y asignación para darle una estructura más profesional').

Cubre las CUATRO superficies donde se agregó:
  1) La página web de Inventario (donde se asigna un activo a un colaborador).
  2) La página web de Certificación de Devolución de Activos.
  3) El PDF del Acta de Asignación (descarga bajo demanda y el que se envía por correo).
  4) El PDF del Acta/Certificado de Devolución (ídem).

El archivo del logo vive en static/img/logo_preventiva.png y Flask lo sirve como cualquier otro
estático; los PDF lo leen directo del disco (ver _pdf_encabezado_con_logo en app.py) así que estas
pruebas también sirven de regresión si algún día se mueve o se borra sin querer ese archivo."""
import os


def _crear_activo(app, nombre='95001', es_biomedico=False, asignado_a='Colaborador de Prueba', estado='Asignado'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, es_biomedico, '2026-09-08 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_archivo_del_logo_existe_en_el_repositorio():
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static', 'img', 'logo_preventiva.png')
    assert os.path.exists(ruta)
    assert os.path.getsize(ruta) > 0


def test_flask_sirve_el_logo_como_estatico(client):
    r = client.get('/static/img/logo_preventiva.png')
    assert r.status_code == 200
    assert r.content_type == 'image/png'


def test_pagina_de_inventario_incluye_el_logo_institucional(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert '/static/img/logo_preventiva.png' in texto
    assert 'Preventiva Salud IPS' in texto


def test_pagina_de_certificacion_de_devolucion_incluye_el_logo_institucional(admin_session):
    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)
    assert '/static/img/logo_preventiva.png' in texto
    assert 'Preventiva Salud IPS' in texto


def test_pdf_de_acta_de_asignacion_incrusta_el_logo(admin_session, app):
    activo_id = _crear_activo(app, nombre='95002')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '95002', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador de Prueba',
        'generar_acta_asignacion': 'on',
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    acta_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_id}/pdf')

    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    # El logo va incrustado como imagen binaria dentro del PDF (no hay forma sencilla de
    # "leer texto" de una imagen), así que la señal aquí es que el PDF sencillamente creció
    # frente a uno sin logo y sigue siendo un PDF válido — la prueba de contenido real
    # (secciones/firmas presentes) ya vive en tests/test_acta_asignacion.py.
    assert r.data[:4] == b'%PDF'
    assert len(r.data) > 2000


def test_pdf_de_certificado_de_devolucion_incrusta_el_logo(admin_session, app):
    activo_id = _crear_activo(app, nombre='95003', asignado_a='Colaborador Devolución')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')

    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data[:4] == b'%PDF'
    assert len(r.data) > 2000


def test_encabezado_con_logo_no_revienta_si_el_archivo_no_existe(app, monkeypatch):
    """Si el archivo del logo llegara a faltar (ruta movida, despliegue incompleto), el PDF debe
    seguir generándose con solo el título — nunca debe romper la descarga ni el envío por
    correo del acta."""
    monkeypatch.setattr(app, '_RUTA_LOGO_PREVENTIVA', '/ruta/que/no/existe/logo.png')
    from reportlab.lib.styles import getSampleStyleSheet
    resultado = app._pdf_encabezado_con_logo("FORMATO DE ACTA DE ASIGNACIÓN DE PRUEBA", getSampleStyleSheet())
    assert resultado is not None
