"""Pie de página institucional 'Powered by MosSoft' en los PDF de acta de asignación y de acta/
certificado de devolución (pedido de Tomás, 13/09/2026, mensaje: "Powered by MosSoft — Quiero
que esto vaya al pie de la página de las actas de asignación y devolución").

Se implementó con _pdf_pie_de_pagina_powered_by (ver app.py, junto a los demás helpers
compartidos de PDF como _pdf_texto_celda), enganchado vía onFirstPage/onLaterPages en
doc.build(...) de _pdf_bytes_acta_asignacion y _pdf_bytes_acta_devolucion — así queda fijo al
borde inferior FÍSICO de cada hoja (dentro del margen ya reservado), en vez de ser un renglón
más que solo aparece si el acta ocupa poco espacio.

Como reportlab comprime por defecto el contenido de la página (FlateDecode), no basta con buscar
el texto en los bytes crudos del PDF — se usa pdfplumber (ya usado en el resto de la suite para
verificar contenido real de las actas) para extraer el texto ya renderizado."""
import io
import pdfplumber


def _crear_activo(app, nombre='95004', es_biomedico=False, asignado_a='Colaborador Pie de Página', estado='Asignado'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, es_biomedico, '2026-09-13 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_pdf_de_acta_de_asignacion_incluye_el_pie_powered_by_mossoft(admin_session, app):
    activo_id = _crear_activo(app, nombre='95004')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '95004', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador Pie de Página',
        'generar_acta_asignacion': 'on',
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    acta_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_id}/pdf')
    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.data)) as pdf:
        texto = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'Powered by MosSoft' in texto


def test_pdf_de_certificado_de_devolucion_incluye_el_pie_powered_by_mossoft(admin_session, app):
    activo_id = _crear_activo(app, nombre='95005', asignado_a='Colaborador Devolución Pie de Página')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.data)) as pdf:
        texto = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'Powered by MosSoft' in texto
