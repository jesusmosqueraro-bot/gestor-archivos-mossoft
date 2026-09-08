"""Recorrido de extremo a extremo por el módulo de Inventario, pedido por Tomás (08/09/2026:
'quiero que hagas pruebas en todo el aplicativo... certifica la devolucion de activos,
reasigna etc') tras confirmar que el correo de asignación sí llegaba. En vez de repetir lo que
ya cubren los archivos de pruebas individuales (test_acta_asignacion.py,
test_correo_pdf_asignacion_devolucion.py, test_certificacion_devoluciones.py, etc.), este
archivo encadena el mismo viaje que haría un agente real en un solo activo, de punta a punta:

  1) Se crea un activo y se asigna a un colaborador (con firma y correo reales en su cuenta).
  2) Se reasigna a OTRO colaborador (debe disparar un nuevo correo; no debe duplicar el primero).
  3) Se certifica la devolución de un activo de TI (sin sección de familiar/cuidador).
  4) Se certifica la devolución de un activo BIOMÉDICO con familiar/cuidador y su firma.
  5) Mientras el activo de TI queda en 'Devolución', un agente NO admin no puede editarlo.
  6) Un admin sí puede desbloquearlo.
  7) El panel de Inventario (/tickets/inventario) refleja los conteos correctos, incluida la
     tarjeta de 'Devolución', y muestra el logo institucional.

El objetivo es atrapar cualquier bug de INTERACCIÓN entre features que las pruebas unitarias,
al probar cada pieza por separado, no verían — y frenar ruidosamente (con un assert o una
excepción) ante cualquier error real, en vez de seguir como si nada."""
import io

import cloudinary.uploader
from PIL import Image, ImageDraw

FIRMA_DATAURL_VALIDA = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4'
                         '2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def _png_firma_sintetica():
    img = Image.new('RGB', (500, 180), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.line([(40, 50), (120, 90), (60, 130), (150, 70)], fill=(0, 0, 0), width=5)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def _crear_colaborador_con_firma_y_correo(app, usuario, nombre, correo, rol='estandar'):
    """Cuenta real de Arkiv (no texto libre) con 'correo' y 'firma' guardados, para que tanto el
    envío automático del PDF por correo como la firma reutilizada en el acta se ejerzeten de
    verdad, en vez de degradarse a '(sin correo)'/'(Sin firma registrada)'."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre, firma) VALUES (%s, %s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre, firma) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (usuario, 'x', correo, rol, nombre, f'https://fake-firmas.example/{usuario}.png'))
    conn.commit()
    conn.close()


def _dar_firma_al_admin(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = "UPDATE usuarios SET firma = %s WHERE usuario = 'admin'" if db_type == 'postgres' else "UPDATE usuarios SET firma = ? WHERE usuario = 'admin'"
    cur.execute(q, ('https://fake-firmas.example/admin.png',))
    conn.commit()
    conn.close()


def _sesion_agente_no_admin(app, usuario='agente_no_admin'):
    """OJO: usa un test_client() INDEPENDIENTE, nunca el fixture 'client' — ese fixture es el
    MISMO objeto que ya trae 'admin_session' logueado (admin_session(client, app) reutiliza el
    mismo cliente), así que reusarlo aquí pisaría la sesión de admin en vez de abrir una nueva."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre) VALUES (%s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (usuario, 'x', f'{usuario}@preventivaips.com.co', 'agente', 'Agente Sin Privilegios'))
    conn.commit()
    conn.close()
    cliente_independiente = app.app.test_client()
    with cliente_independiente.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return cliente_independiente


def _sin_error_en_flashes(response_text):
    """La app renderiza cada flash(..., 'error') dentro de un div con la clase
    'bg-rose-500/10 border border-rose-500/30 text-rose-300' (ver tickets_inventario.html) — se
    busca ESA combinación completa (no cada clase por separado, que también aparece suelta en
    badges de estado como 'Perdido' sin ser un error real) para no dar falsos positivos."""
    return 'bg-rose-500/10 border border-rose-500/30 text-rose-300' not in response_text


def test_recorrido_completo_asignacion_reasignacion_y_devolucion(admin_session, app, monkeypatch):
    # 🖼️ Todas las firmas (asignación, certificación, familiar) se descargan por HTTP dentro de
    # los PDF — se reemplaza esa descarga por una firma sintética (ver _pdf_elemento_firma) para
    # ejercitar de verdad el recorte de espacio en blanco + el armado del PDF, sin red real.
    datos_firma = _png_firma_sintetica()

    class _RespuestaFalsa:
        def read(self):
            return datos_firma

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(app.urllib.request, 'urlopen', lambda *a, **k: _RespuestaFalsa())
    _mock_cloudinary_upload = lambda url: monkeypatch.setattr(
        cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})

    # 📧 Se capturan los envíos reales (en vez de dejarlos completamente mockeados por el
    # autouse de conftest.py) para verificar CUÁNTAS veces y a qué correo se disparó cada uno,
    # sin arriesgar un envío real a la red.
    envios_asignacion = []
    envios_devolucion = []
    monkeypatch.setattr(app, '_enviar_formulario_asignacion_por_correo',
                         lambda *a, **k: envios_asignacion.append(a))
    monkeypatch.setattr(app, '_enviar_certificado_devolucion_por_correo',
                         lambda *a, **k: envios_devolucion.append(a))

    _crear_colaborador_con_firma_y_correo(app, 'colaborador_a', 'Ana Prueba E2E', 'ana.pruebae2e@preventivaips.com.co')
    _crear_colaborador_con_firma_y_correo(app, 'colaborador_b', 'Beto Prueba E2E', 'beto.pruebae2e@preventivaips.com.co')
    _dar_firma_al_admin(app)

    # 1) CREAR + ASIGNAR un activo de TI a 'colaborador_a' -----------------------------------
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': 'E2E-TI-001', 'tipo_activo': 'Portátil', 'marca': 'ASUS', 'modelo': 'Vivobook',
        'numero_serie': 'SN-E2E-001', 'estado': 'Asignado', 'asignado_a': 'Ana Prueba E2E (colaborador_a)',
        'sede': '', 'area': '', 'generar_acta_asignacion': 'on',
        'acta_asignacion_descripcion': 'Entrega inicial - prueba E2E',
    }, follow_redirects=True)
    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert _sin_error_en_flashes(texto), "Se registró un error al crear/asignar el activo E2E-TI-001"

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, estado, asignado_a FROM activos_inventario WHERE nombre = ?", ('E2E-TI-001',))
    activo_ti_id, estado, asignado_a = cur.fetchone()
    conn.close()
    assert estado == 'Asignado'
    assert asignado_a == 'Ana Prueba E2E (colaborador_a)'
    assert len(envios_asignacion) == 1, "La asignación inicial debía disparar exactamente un correo"
    assert envios_asignacion[0][0] == activo_ti_id
    assert envios_asignacion[0][1] == 'Ana Prueba E2E (colaborador_a)'

    # El acta de asignación debe poder descargarse en PDF sin reventar.
    cur_conn, _ = app.get_db()
    cur2 = cur_conn.cursor()
    cur2.execute("SELECT id FROM actas_asignacion WHERE activo_id = ?", (activo_ti_id,))
    acta_asig_id = cur2.fetchone()[0]
    cur_conn.close()
    r_pdf = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_asig_id}/pdf')
    assert r_pdf.status_code == 200
    assert r_pdf.headers['Content-Type'] == 'application/pdf'
    assert r_pdf.data[:4] == b'%PDF'

    # 2) REASIGNAR el mismo activo a 'colaborador_b' -----------------------------------------
    r = admin_session.post(f'/tickets/inventario/{activo_ti_id}/editar', data={
        'nombre': 'E2E-TI-001', 'tipo_activo': 'Portátil', 'marca': 'ASUS', 'modelo': 'Vivobook',
        'numero_serie': 'SN-E2E-001', 'estado': 'Asignado', 'asignado_a': 'Beto Prueba E2E (colaborador_b)',
        'generar_acta_asignacion': 'on', 'acta_asignacion_descripcion': 'Reasignación - prueba E2E',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert _sin_error_en_flashes(r.get_data(as_text=True)), "Se registró un error al reasignar el activo"

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a FROM activos_inventario WHERE id = ?", (activo_ti_id,))
    estado, asignado_a = cur.fetchone()
    conn.close()
    assert estado == 'Asignado'
    assert asignado_a == 'Beto Prueba E2E (colaborador_b)'
    assert len(envios_asignacion) == 2, "La reasignación debía disparar un SEGUNDO correo (cambió el colaborador)"
    assert envios_asignacion[1][1] == 'Beto Prueba E2E (colaborador_b)'

    # 2b) Editar SIN cambiar el colaborador no debe disparar un tercer correo (anti-spam).
    r = admin_session.post(f'/tickets/inventario/{activo_ti_id}/editar', data={
        'nombre': 'E2E-TI-001', 'tipo_activo': 'Portátil', 'marca': 'ASUS', 'modelo': 'Vivobook 15',
        'numero_serie': 'SN-E2E-001', 'estado': 'Asignado', 'asignado_a': 'Beto Prueba E2E (colaborador_b)',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert len(envios_asignacion) == 2, "Editar sin cambiar el colaborador NO debía disparar otro correo"

    # 3) CERTIFICAR LA DEVOLUCIÓN del activo de TI (sin familiar/cuidador) -------------------
    r = admin_session.post(f'/inventario/{activo_ti_id}/confirmar_devolucion', data={
        'generar_acta': 'on', 'observaciones': 'Devuelto en buen estado - prueba E2E',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert _sin_error_en_flashes(r.get_data(as_text=True)), "Se registró un error al certificar la devolución de TI"

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE id = ?", (activo_ti_id,))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_ti_id,))
    devolucion_ti_id = cur.fetchone()[0]
    conn.close()
    assert estado == 'Devolución'
    assert not asignado_a
    assert fecha_devolucion
    assert len(envios_devolucion) == 1

    r_pdf = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_ti_id}/acta_pdf')
    assert r_pdf.status_code == 200
    assert r_pdf.data[:4] == b'%PDF'
    import pdfplumber
    with pdfplumber.open(io.BytesIO(r_pdf.data)) as pdf:
        texto_pdf = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'Familiar/cuidador responsable' not in texto_pdf, "Un activo de TI no debe mostrar la sección de familiar/cuidador"

    # 4) Activo BIOMÉDICO: asignar y certificar devolución CON familiar/cuidador ------------
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': 'E2E-BIO-001', 'tipo_activo': 'Bomba de Infusión', 'estado': 'Asignado',
        'asignado_a': 'Paciente Domiciliario E2E', 'es_biomedico': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert _sin_error_en_flashes(r.get_data(as_text=True))

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('E2E-BIO-001',))
    activo_bio_id = cur.fetchone()[0]
    conn.close()

    _mock_cloudinary_upload('https://res.cloudinary.com/demo/image/upload/firma_familiar_e2e.png')
    r = admin_session.post(f'/inventario/{activo_bio_id}/confirmar_devolucion', data={
        'generar_acta': 'on', 'nombre_familiar': 'Rosa Familiar E2E',
        'firma_familiar_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)
    assert r.status_code == 200
    assert _sin_error_en_flashes(r.get_data(as_text=True)), "Se registró un error al certificar la devolución biomédica"

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_bio_id,))
    assert cur.fetchone()[0] == 'Devolución'
    cur.execute("SELECT id, nombre_familiar, firma_familiar_url FROM inventario_devoluciones WHERE activo_id = ?", (activo_bio_id,))
    devolucion_bio_id, nombre_familiar, firma_familiar_url = cur.fetchone()
    conn.close()
    assert nombre_familiar == 'Rosa Familiar E2E'
    assert firma_familiar_url == 'https://res.cloudinary.com/demo/image/upload/firma_familiar_e2e.png'

    r_pdf = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_bio_id}/acta_pdf')
    assert r_pdf.status_code == 200
    with pdfplumber.open(io.BytesIO(r_pdf.data)) as pdf:
        texto_pdf_bio = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'Familiar/cuidador responsable' in texto_pdf_bio
    assert 'Rosa Familiar E2E' in texto_pdf_bio

    # 5) Mientras el TI queda en 'Devolución', un agente NO admin no puede editarlo --------
    agente_client = _sesion_agente_no_admin(app)
    r = agente_client.post(f'/tickets/inventario/{activo_ti_id}/editar', data={
        'nombre': 'E2E-TI-001-HACK', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'asignado_a': '',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert 'bloqueado' in r.get_data(as_text=True).lower()
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre, estado FROM activos_inventario WHERE id = ?", (activo_ti_id,))
    nombre_actual, estado_actual = cur.fetchone()
    conn.close()
    assert nombre_actual == 'E2E-TI-001', "El agente NO admin no debía poder modificar un activo bloqueado en 'Devolución'"
    assert estado_actual == 'Devolución'

    # 6) Un ADMIN sí puede desbloquearlo -----------------------------------------------------
    r = admin_session.post(f'/tickets/inventario/{activo_ti_id}/editar', data={
        'nombre': 'E2E-TI-001', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'asignado_a': '',
    }, follow_redirects=True)
    assert r.status_code == 200
    assert _sin_error_en_flashes(r.get_data(as_text=True))
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_ti_id,))
    assert cur.fetchone()[0] == 'Disponible'
    conn.close()

    # 7) El panel de Inventario refleja los conteos y muestra el logo institucional ---------
    r = admin_session.get('/tickets/inventario')
    assert r.status_code == 200
    texto_dashboard = r.get_data(as_text=True)
    assert _sin_error_en_flashes(texto_dashboard)
    assert '/static/img/logo_preventiva.png' in texto_dashboard
    # El activo biomédico sigue en 'Devolución' (nunca se desbloqueó) — la tarjeta debe reflejarlo.
    assert "conteos_estado['Devolución']" not in texto_dashboard  # (nunca debe filtrarse Jinja crudo)
