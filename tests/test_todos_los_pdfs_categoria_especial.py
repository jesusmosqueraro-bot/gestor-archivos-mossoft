"""Verificación exhaustiva (pedida por Tomás: "TODOS LOS PDFS funcionan bien?") de que los 3 PDFs
del módulo de Inventario — Acta de Asignación, Acta de Recibido y Acta/Certificado de Devolución —
se generan correctamente para las 4 categorías especiales (biomédico, SST, ambiental,
laboratorio) y también para un activo de TI normal (sin categoría), incluyendo el flujo de paz y
salvo de 3 firmas en la devolución. No repite las pruebas de contenido detallado que ya existen en
test_acta_recibido_biomedico.py / test_acta_recibido_categoria_especial.py — aquí el objetivo es
confirmar que las 4x3 combinaciones no truenan y traen el título correcto."""
import base64
import io

import cloudinary.uploader
import pdfplumber
import pytest

PNG_1X1_B64 = base64.b64encode(bytes([
    0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
    0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x08, 0x06, 0x00, 0x00, 0x00, 0x1F, 0x15, 0xC4,
    0x89, 0x00, 0x00, 0x00, 0x0A, 0x49, 0x44, 0x41, 0x54, 0x78, 0x9C, 0x63, 0x00, 0x01, 0x00, 0x00,
    0x05, 0x00, 0x01, 0x0D, 0x0A, 0x2D, 0xB4, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4E, 0x44, 0xAE,
    0x42, 0x60, 0x82
])).decode('ascii')
FIRMA_DATAURL_VALIDA = 'data:image/png;base64,' + PNG_1X1_B64

CASOS = [
    # (etiqueta, es_biomedico_form, categoria_especial_form)
    ('ti', False, None),
    ('biomedico', True, None),
    ('sst', False, 'sst'),
    ('ambiental', False, 'ambiental'),
    ('laboratorio', False, 'laboratorio'),
]

# 🪩 Cómo debe verse la "variante" en el título de los PDFs de asignación/devolución para cada
# caso (ver TEXTOS_CATEGORIA_ESPECIAL / _categoria_especial_activo en app.py) — reportlab pone el
# título en mayúsculas, así que se compara ya normalizado.
VARIANTE_ESPERADA = {
    'ti': 'DE ACTIVOS DE TI',
    'biomedico': 'DE EQUIPO BIOMÉDICO',
    'sst': 'DE INSUMO DE SST',
    'ambiental': 'DE INSUMO AMBIENTAL',
    'laboratorio': 'DE INSUMO DE LABORATORIO CLÍNICO',
}


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def _assert_pdf_valido(response):
    assert response.status_code == 200, response.get_data(as_text=True)[:500]
    assert response.headers['Content-Type'] == 'application/pdf'
    assert response.data[:4] == b'%PDF'
    assert len(response.data) > 500  # un PDF real, no un esqueleto vacío


def _texto_pdf(response):
    """El contenido de un PDF de reportlab viene comprimido (Flate) — buscar texto en los bytes
    crudos del response no sirve (ver el primer intento de esta prueba). Hay que extraerlo de
    verdad con pdfplumber, como haría cualquier lector de PDF."""
    with pdfplumber.open(io.BytesIO(response.data)) as pdf:
        return "\n".join(pagina.extract_text() or '' for pagina in pdf.pages)


def _texto_pdf_una_linea(response):
    """Igual que _texto_pdf, pero con todos los saltos de línea colapsados a un solo espacio —
    para comparar frases que en el PDF real quedan partidas en 2 líneas por el ancho de la caja
    (p. ej. un título largo como "...DE INSUMO DE LABORATORIO CLÍNICO"), sin que eso cuente como
    que el texto "no está"."""
    return " ".join(_texto_pdf(response).split())


@pytest.mark.parametrize('etiqueta,es_biomedico,categoria_especial', CASOS)
def test_acta_de_asignacion_se_genera_para_las_4_categorias_mas_ti(admin_session, app, monkeypatch, etiqueta, es_biomedico, categoria_especial):
    _mock_cloudinary_upload(monkeypatch)
    datos = {
        'nombre': f'80100-{etiqueta}', 'tipo_activo': 'Otro', 'estado': 'Asignado',
        'asignado_a': 'Colaborador de Prueba', 'generar_acta_asignacion': 'on',
        'marca': 'Genérica', 'modelo': 'Modelo de Prueba', 'numero_serie': f'SN-80100-{etiqueta}',
        'acta_asignacion_descripcion': f'Prueba PDF asignación — {etiqueta}',
    }
    if es_biomedico:
        datos['es_biomedico'] = 'on'
    if categoria_especial:
        datos['es_categoria_especial'] = 'on'
        datos['categoria_especial'] = categoria_especial

    r = admin_session.post('/tickets/inventario/nuevo', data=datos, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", (f'80100-{etiqueta}',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    acta_id = cur.fetchone()[0]
    conn.close()

    r_pdf = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_id}/pdf')
    _assert_pdf_valido(r_pdf)
    texto_pdf = _texto_pdf_una_linea(r_pdf)
    assert f'ACTA DE ASIGNACIÓN {VARIANTE_ESPERADA[etiqueta]}' in texto_pdf.upper()
    assert 'Colaborador de Prueba' in texto_pdf


@pytest.mark.parametrize('etiqueta,es_biomedico,categoria_especial', [c for c in CASOS if c[0] != 'ti'])
def test_acta_de_recibido_se_genera_para_las_4_categorias_especiales(admin_session, app, monkeypatch, etiqueta, es_biomedico, categoria_especial):
    _mock_cloudinary_upload(monkeypatch)
    datos = {
        'nombre': f'80200-{etiqueta}', 'tipo_activo': 'Otro', 'estado': 'Disponible',
        'acta_nombre_responsable': f'Responsable {etiqueta}', 'acta_relacion_responsable': 'otro',
        'acta_direccion_entrega': f'Dirección de prueba {etiqueta}', 'acta_firma_dataurl': FIRMA_DATAURL_VALIDA,
    }
    if es_biomedico:
        datos['es_biomedico'] = 'on'
    if categoria_especial:
        datos['es_categoria_especial'] = 'on'
        datos['categoria_especial'] = categoria_especial

    r = admin_session.post('/tickets/inventario/nuevo', data=datos, follow_redirects=True)
    assert r.status_code == 200
    assert 'Acta de recibido registrada' in r.get_data(as_text=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", (f'80200-{etiqueta}',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT id FROM actas_recibido_biomedico WHERE activo_id = ?", (activo_id,))
    acta_id = cur.fetchone()[0]
    conn.close()

    r_pdf = admin_session.get(f'/tickets/inventario/actas/{acta_id}/pdf')
    _assert_pdf_valido(r_pdf)
    texto_pdf = _texto_pdf_una_linea(r_pdf)
    nombres_esperados = {
        'biomedico': 'Equipo Biomédico',
        'sst': 'Insumo de SST',
        'ambiental': 'Insumo Ambiental',
        'laboratorio': 'Insumo de Laboratorio Clínico',
    }
    assert nombres_esperados[etiqueta] in texto_pdf
    # El título del acta y la fila de "Recibió (nombre)" deben aparecer, con los datos reales.
    assert f'Responsable {etiqueta}' in texto_pdf
    assert f'Dirección de prueba {etiqueta}' in texto_pdf


@pytest.mark.parametrize('etiqueta,es_biomedico,categoria_especial', CASOS)
def test_acta_de_devolucion_sin_paz_y_salvo_se_genera_para_las_4_categorias_mas_ti(admin_session, app, monkeypatch, etiqueta, es_biomedico, categoria_especial):
    """Certificación de devolución 'clásica' (sin firma de colaborador en el canvas — o sea, sin
    disparar el flujo de paz y salvo de 3 firmas), con 'Generar acta' marcado."""
    _mock_cloudinary_upload(monkeypatch)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (f'80300-{etiqueta}', 'Otro', 'Asignado', 'Colaborador de Prueba', es_biomedico,
                     categoria_especial, '2026-09-16 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    datos_devolucion = {'generar_acta': 'on', 'observaciones': f'Prueba PDF devolución — {etiqueta}'}
    if es_biomedico or categoria_especial:
        datos_devolucion['nombre_familiar'] = f'Responsable de entrega {etiqueta}'
        datos_devolucion['firma_familiar_dataurl'] = FIRMA_DATAURL_VALIDA

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data=datos_devolucion, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r_pdf = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    _assert_pdf_valido(r_pdf)
    texto_pdf = _texto_pdf_una_linea(r_pdf)
    assert f'ACTA DE DEVOLUCIÓN {VARIANTE_ESPERADA[etiqueta]}' in texto_pdf.upper()
    if es_biomedico or categoria_especial:
        assert f'Responsable de entrega {etiqueta}' in texto_pdf
    else:
        # En TI no debe aparecer la fila de familiar/responsable — ver _pdf_bytes_acta_devolucion.
        assert 'Familiar/cuidador responsable' not in texto_pdf


@pytest.mark.parametrize('etiqueta,es_biomedico,categoria_especial', CASOS)
def test_acta_de_devolucion_con_paz_y_salvo_se_genera_para_las_4_categorias_mas_ti(admin_session, app, monkeypatch, etiqueta, es_biomedico, categoria_especial):
    """Misma certificación, pero disparando el flujo de paz y salvo de 3 firmas (firma del
    colaborador capturada en el canvas) — para confirmar que la generalización de categoría no
    rompió ese bloque de firmas institucional, que es independiente del bloque simple de arriba."""
    _mock_cloudinary_upload(monkeypatch)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, categoria_especial, "
         "fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (f'80400-{etiqueta}', 'Otro', 'Asignado', 'Colaborador de Prueba', es_biomedico,
                     categoria_especial, '2026-09-16 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    datos_devolucion = {
        'generar_acta': 'on', 'observaciones': f'Prueba PDF devolución paz y salvo — {etiqueta}',
        'firma_colaborador_dataurl': FIRMA_DATAURL_VALIDA,
    }
    if es_biomedico or categoria_especial:
        datos_devolucion['nombre_familiar'] = f'Responsable de entrega {etiqueta}'
        datos_devolucion['firma_familiar_dataurl'] = FIRMA_DATAURL_VALIDA

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data=datos_devolucion, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, estado FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id, estado_paz_y_salvo = cur.fetchone()
    conn.close()
    assert estado_paz_y_salvo == 'pendiente_ti'  # confirma que sí entró al flujo de paz y salvo

    r_pdf = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    _assert_pdf_valido(r_pdf)
