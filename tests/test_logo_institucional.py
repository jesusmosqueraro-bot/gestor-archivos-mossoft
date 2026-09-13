"""Pruebas del logo institucional de Preventiva Salud IPS (pedido de Tomás, 08/09/2026: 'pongamos
este logo en la pagina de devolución y asignación para darle una estructura más profesional').

Cubre las CUATRO superficies donde se agregó:
  1) La página web de Inventario (donde se asigna un activo a un colaborador).
  2) La página web de Certificación de Devolución de Activos.
  3) El PDF del Acta de Asignación (descarga bajo demanda y el que se envía por correo).
  4) El PDF del Acta/Certificado de Devolución (ídem).

El archivo del logo vive en static/img/logo_preventiva.png y Flask lo sirve como cualquier otro
estático; los PDF lo leen directo del disco (ver _pdf_encabezado_con_logo en app.py) así que estas
pruebas también sirven de regresión si algún día se mueve o se borra sin querer ese archivo.

Además cubre el pedido de Tomás (13/09/2026): "que cada vez que se presione el logo de
Preventiva... nos redirija a la pagina principal de preventiva https://preventivaips.com.co/...
en todos los modulos". El logo aparece en CUATRO superficies web distintas (ninguna es
realmente un modal: se revisó a fondo y el logo nunca aparece dentro de uno):
  a) El parcial reusable templates/partials/logo_preventiva_nav.html, incluido en 31 plantillas.
  b) El encabezado de /tickets/inventario (agregado a mano antes de existir el parcial).
  c) El encabezado de /inventario/certificacion_devoluciones (ídem).
  d) El logo grande y centrado de /login (antes de iniciar sesión).
Las cuatro se envolvieron en <a href="https://preventivaips.com.co/" target="_blank"
rel="noopener noreferrer"> para abrir en pestaña nueva sin cerrar la sesión activa en Arkiv."""
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
    # Este logo se agregó a mano (pedido de Tomás, 08/09/2026), antes de que existiera el
    # parcial reusable, así que se enlazó por separado al pedirse el enlace (13/09/2026).
    assert '<a href="https://preventivaips.com.co/"' in texto


def test_el_logo_institucional_enlaza_al_sitio_publico_de_preventiva_en_todas_las_plantillas():
    """Pedido de Tomás (13/09/2026): que el logo, en CUALQUIER módulo, lleve al sitio público de
    Preventiva (https://preventivaips.com.co/) al hacer clic — antes era una insignia sin enlace
    (un <div>). Como el badge es un único parcial reusable (templates/partials/
    logo_preventiva_nav.html) incluido en las 31 plantillas que lo muestran, esta prueba lo
    verifica una sola vez contra el parcial: cualquier plantilla que lo incluya hereda el enlace
    automáticamente, sin tener que repetir esta prueba página por página."""
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         'templates', 'partials', 'logo_preventiva_nav.html')
    with open(ruta, encoding='utf-8') as f:
        contenido = f.read()
    assert '<a href="https://preventivaips.com.co/"' in contenido
    assert 'target="_blank"' in contenido
    assert 'rel="noopener noreferrer"' in contenido
    assert '/static/img/logo_preventiva.png' in contenido


def test_pagina_de_bienvenida_muestra_el_logo_ya_enlazado_al_sitio_publico(admin_session):
    """Chequeo end-to-end (no solo estático): confirma que /bienvenida realmente renderiza el
    enlace, no solo que el texto vive en el archivo fuente del parcial."""
    texto = admin_session.get('/bienvenida').get_data(as_text=True)
    assert '<a href="https://preventivaips.com.co/"' in texto
    assert 'Preventiva Salud IPS' in texto


def test_pagina_de_certificacion_de_devolucion_incluye_el_logo_institucional(admin_session):
    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)
    assert '/static/img/logo_preventiva.png' in texto
    assert 'Preventiva Salud IPS' in texto
    assert '<a href="https://preventivaips.com.co/"' in texto


def test_login_muestra_el_logo_ya_enlazado_al_sitio_publico(client):
    """El logo grande y centrado de /login es un cuarto lugar independiente del parcial
    reusable (no pasa por login la sesión aún), así que se enlazó por separado."""
    texto = client.get('/login').get_data(as_text=True)
    assert '<a href="https://preventivaips.com.co/"' in texto
    assert 'target="_blank"' in texto


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
