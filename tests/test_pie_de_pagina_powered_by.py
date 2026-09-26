"""Pie de página institucional 'Powered by MosSoft' + marca de agua del logo de Preventiva Salud
IPS en los PDF de acta de asignación y de acta/certificado de devolución.

El pie de página fue pedido por Tomás el 13/09/2026 ("Powered by MosSoft — Quiero que esto vaya
al pie de la página de las actas de asignación y devolución"). La marca de agua se agregó el
19/09/2026 ("pongamos esta marca de agua a las paginas de Asignación y Devolución", con dos
capturas de referencia de un documento de Word mostrando el logo institucional centrado y casi
transparente).

Ambas se implementaron como callbacks de reportlab (_pdf_pie_de_pagina_powered_by y
_pdf_marca_agua_logo, ver app.py, junto a los demás helpers compartidos de PDF como
_pdf_texto_celda), combinados en _pdf_decoracion_pagina_acta y enganchados vía
onFirstPage/onLaterPages en doc.build(...) de _pdf_bytes_acta_asignacion y
_pdf_bytes_acta_devolucion — así quedan fijos en cada hoja (el pie de página al borde inferior
físico, dentro del margen ya reservado; la marca de agua centrada, detrás del contenido), sin
depender de cuánto ocupe el acta ni de si termina abarcando más de una hoja.

Como reportlab comprime por defecto el contenido de la página (FlateDecode), no basta con buscar
el texto en los bytes crudos del PDF — se usa pdfplumber (ya usado en el resto de la suite para
verificar contenido real de las actas) para extraer el texto ya renderizado, y su propiedad
`page.images` para confirmar que quedó una imagen embebida (la marca de agua) en la página."""
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
        'marca': 'Dell', 'modelo': 'Latitude', 'numero_serie': 'SN-95004',
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


# ---------------------------------------------------------------------------
# Marca de agua del logo institucional (pedido de Tomás, 19/09/2026)
# ---------------------------------------------------------------------------

def test_pdf_de_acta_de_asignacion_incluye_la_marca_de_agua_institucional(admin_session, app):
    """Ninguno de los dos colaboradores de esta acta tiene firma registrada (ver
    '(Sin firma registrada)' en _pdf_elemento_firma), así que la ÚNICA imagen embebida posible en
    la página es la marca de agua — confirma que se dibujó sin ambigüedad."""
    activo_id = _crear_activo(app, nombre='95006')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '95006', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador Marca De Agua',
        'marca': 'Dell', 'modelo': 'Latitude', 'numero_serie': 'SN-95006',
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
        assert len(pdf.pages[0].images) >= 1


def test_pdf_de_certificado_de_devolucion_incluye_la_marca_de_agua_institucional(admin_session, app):
    activo_id = _crear_activo(app, nombre='95007', asignado_a='Colaborador Devolución Marca De Agua')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.data)) as pdf:
        assert len(pdf.pages[0].images) >= 1


def test_marca_agua_logo_imagen_reader_carga_el_logo_institucional(app):
    """Prueba unitaria del helper que prepara la marca de agua: en un entorno normal (el archivo
    static/img/logo_preventiva.png existe) debe devolver un ImageReader utilizable, no None."""
    from reportlab.lib.utils import ImageReader
    app._MARCA_AGUA_LOGO_CACHE.clear()
    lector = app._marca_agua_logo_imagen_reader()
    assert isinstance(lector, ImageReader)


def test_marca_agua_logo_no_rompe_si_el_archivo_no_existe(app, monkeypatch):
    """Si el logo no se pudiera leer (ruta rota, archivo corrupto, etc.), la marca de agua debe
    omitirse en silencio — nunca debe tumbar la generación del acta completa por esto. Sin ningún
    logo/marca de agua personalizados guardados en configuracion_app (BD recién sembrada, ver
    fixture _base_de_datos_limpia), _marca_agua_actas_fuente_pdf cae hasta _RUTA_LOGO_PREVENTIVA
    — se rompe esa ruta a propósito para simular el archivo faltante."""
    app._MARCA_AGUA_LOGO_CACHE.clear()
    monkeypatch.setattr(app, '_RUTA_LOGO_PREVENTIVA', '/ruta/que/no/existe/de/verdad/logo.png')
    assert app._marca_agua_logo_imagen_reader() is None
    app._MARCA_AGUA_LOGO_CACHE.clear()


def test_marca_agua_actas_reutiliza_el_logo_institucional_personalizado(app, monkeypatch):
    """Si un admin sube un logo institucional propio pero NO una marca de agua propia, la marca
    de agua de las actas debe reutilizar esa misma fuente (pedido de Tomás, 19/09/2026, aclarado
    con AskUserQuestion: no hace falta subir dos imágenes distintas si basta con una)."""
    app._guardar_config_app(app.CLAVE_LOGO_INSTITUCIONAL, 'https://res.cloudinary.com/demo/image/upload/logo_personalizado.png')
    assert app._marca_agua_actas_fuente_pdf() == 'https://res.cloudinary.com/demo/image/upload/logo_personalizado.png'


def test_marca_agua_actas_propia_tiene_prioridad_sobre_el_logo(app):
    """Si además se sube una marca de agua propia para las actas, esa gana sobre el logo
    institucional (aunque ambos estén personalizados)."""
    app._guardar_config_app(app.CLAVE_LOGO_INSTITUCIONAL, 'https://res.cloudinary.com/demo/image/upload/logo_personalizado.png')
    app._guardar_config_app(app.CLAVE_MARCA_AGUA_ACTAS, 'https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png')
    assert app._marca_agua_actas_fuente_pdf() == 'https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png'
