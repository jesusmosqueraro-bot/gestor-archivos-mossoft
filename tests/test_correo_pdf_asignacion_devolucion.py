"""Envío automático por correo, con el PDF diligenciado ADJUNTO, cuando se asigna un activo a un
colaborador o se certifica la devolución de uno (pedido de Tomás, 08/09/2026): "necesito que
cuando se asigne un activo a un colaborador, se envie el formulario diligenciado al correo
asociado al colaborador, y cuando se de certificado de devolución, haga lo mismo. Estos en
formato pdf" — y, en un mensaje posterior, confirmó que quiere el PDF como adjunto real (no un
enlace de descarga), reutilizando el webhook de Apps Script (GMAIL_SCRIPT_URL) que ya soporta
'adjunto_base64'/'adjunto_nombre'/'adjunto_tipo'.

Cubre tres capas:
  1. _resolver_correo_para_asignacion: resuelve (o no) el correo del colaborador.
  2. _enviar_pdf_acta_por_correo: arma el payload con el adjunto en base64 y registra
     'correos_log' — probado directo, sin pasar por HTTP, mockeando la red.
  3. Los "hooks" en crear_activo/editar_activo/confirmar_devolucion_activo: SOLO se dispara el
     envío cuando corresponde (asignación nueva/realmente cambiada; devolución siempre) — probado
     mockeando las funciones de envío para no tocar la red ni depender de threading.Thread.
"""
import base64
import app as _arkiv_module

# 📌 Referencias a las funciones REALES, capturadas al importar este archivo (antes de que
# cualquier prueba corra) — el fixture autouse '_sin_correos_reales' (conftest.py) las
# reemplaza por no-ops en TODAS las pruebas (para que otros archivos de prueba, que solo
# ejercitan crear_activo/editar_activo/confirmar_devolucion_activo sin querer probar el envío en
# sí, no disparen hilos reales contra la red). Las pruebas de este archivo que llaman estas
# funciones DIRECTO (sin pasar por una ruta HTTP) necesitan la versión real, no el no-op — de
# ahí que se guarde esta referencia estable, ajena a lo que el mock reasigne después.
_ENVIAR_FORMULARIO_ASIGNACION_REAL = _arkiv_module._enviar_formulario_asignacion_por_correo
_ENVIAR_CERTIFICADO_DEVOLUCION_REAL = _arkiv_module._enviar_certificado_devolucion_por_correo


def _crear_activo_inventario(app, nombre='80001', asignado_a=None, estado='Disponible', es_biomedico=False):
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


# ────────────────────────────────────────────────────────────────────────────
# _resolver_correo_para_asignacion
# ────────────────────────────────────────────────────────────────────────────

def test_resolver_correo_encuentra_el_correo_de_la_cuenta(app, crear_usuario):
    crear_usuario(usuario='jperez', nombre='Juan Pérez', correo='jperez@preventivaips.com.co')

    assert app._resolver_correo_para_asignacion('Juan Pérez (jperez)') == 'jperez@preventivaips.com.co'


def test_resolver_correo_texto_libre_sin_usuario_devuelve_none(app):
    assert app._resolver_correo_para_asignacion('Nombre Escrito A Mano') is None


def test_resolver_correo_usuario_inexistente_devuelve_none(app):
    assert app._resolver_correo_para_asignacion('Alguien (no_existe_este_usuario)') is None


def test_resolver_correo_vacio_devuelve_none(app):
    assert app._resolver_correo_para_asignacion('') is None
    assert app._resolver_correo_para_asignacion(None) is None


# ────────────────────────────────────────────────────────────────────────────
# _enviar_pdf_acta_por_correo — el payload del adjunto y el log
# ────────────────────────────────────────────────────────────────────────────

def test_enviar_pdf_por_correo_arma_el_adjunto_en_base64_y_registra_enviado(app, monkeypatch):
    payloads = []

    class _RespuestaFalsa:
        status_code = 200

    def _post_falso(url, json=None, timeout=None):
        payloads.append((url, json))
        return _RespuestaFalsa()

    monkeypatch.setattr(app.requests, 'post', _post_falso)

    pdf_bytes = b'%PDF-1.4 contenido de prueba'
    ok = app._enviar_pdf_acta_por_correo('destino@preventivaips.com.co', 'Asunto de prueba', 'Cuerpo de prueba',
                                          pdf_bytes, 'Arkiv_Acta_Prueba.pdf', 'asignacion')

    assert ok is True
    assert len(payloads) == 1
    url, enviado = payloads[0]
    assert url == app.GMAIL_SCRIPT_URL
    assert enviado['para'] == 'destino@preventivaips.com.co'
    assert enviado['asunto'] == 'Asunto de prueba'
    assert enviado['adjunto_nombre'] == 'Arkiv_Acta_Prueba.pdf'
    assert enviado['adjunto_tipo'] == 'application/pdf'
    assert base64.b64decode(enviado['adjunto_base64']) == pdf_bytes

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT destinatario, tipo, estado FROM correos_log WHERE destinatario = ?", ('destino@preventivaips.com.co',))
    fila = cur.fetchone()
    conn.close()
    assert fila == ('destino@preventivaips.com.co', 'asignacion', 'enviado')


def test_enviar_pdf_por_correo_error_de_red_registra_estado_error(app, monkeypatch):
    def _post_falla(url, json=None, timeout=None):
        raise ConnectionError("sin red, simulado")

    monkeypatch.setattr(app.requests, 'post', _post_falla)

    ok = app._enviar_pdf_acta_por_correo('otro@preventivaips.com.co', 'Asunto', 'Cuerpo', b'%PDF-x', 'x.pdf', 'devolucion')

    assert ok is False
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo, estado, detalle_error FROM correos_log WHERE destinatario = ?", ('otro@preventivaips.com.co',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'devolucion'
    assert fila[1] == 'error'
    assert 'sin red' in (fila[2] or '')


# ────────────────────────────────────────────────────────────────────────────
# _enviar_formulario_asignacion_por_correo / _enviar_certificado_devolucion_por_correo
# llamadas directas (sin threading) — arman su propio PDF y degradan sin correo resoluble.
# ────────────────────────────────────────────────────────────────────────────

def test_enviar_formulario_asignacion_sin_correo_resoluble_registra_sin_correo(app):
    activo_id = _crear_activo_inventario(app, nombre='80010', asignado_a='Nombre Escrito A Mano', estado='Asignado')

    _ENVIAR_FORMULARIO_ASIGNACION_REAL(activo_id, 'Nombre Escrito A Mano', 'admin')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo, estado FROM correos_log WHERE tipo = 'asignacion' ORDER BY id DESC LIMIT 1")
    fila = cur.fetchone()
    conn.close()
    assert fila == ('asignacion', 'sin_correo')


def test_enviar_formulario_asignacion_con_correo_resoluble_envia_el_pdf_adjunto(app, monkeypatch, crear_usuario):
    crear_usuario(usuario='lgomez', nombre='Laura Gómez', correo='lgomez@preventivaips.com.co')
    activo_id = _crear_activo_inventario(app, nombre='80011', asignado_a='Laura Gómez (lgomez)', estado='Asignado')

    payloads = []

    class _RespuestaFalsa:
        status_code = 200

    monkeypatch.setattr(app.requests, 'post', lambda url, json=None, timeout=None: (payloads.append(json), _RespuestaFalsa())[-1])

    _ENVIAR_FORMULARIO_ASIGNACION_REAL(activo_id, 'Laura Gómez (lgomez)', 'admin')

    assert len(payloads) == 1
    assert payloads[0]['para'] == 'lgomez@preventivaips.com.co'
    assert payloads[0]['adjunto_tipo'] == 'application/pdf'
    assert base64.b64decode(payloads[0]['adjunto_base64'])[:4] == b'%PDF'
    assert f'Arkiv_Acta_Asignacion_{activo_id}.pdf' == payloads[0]['adjunto_nombre']


def test_enviar_certificado_devolucion_sin_correo_resoluble_registra_sin_correo(app):
    activo_id = _crear_activo_inventario(app, nombre='80012', asignado_a='Persona Sin Cuenta', estado='Asignado')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, acta_generada) "
         "VALUES (%s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, acta_generada) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (activo_id, 'Persona Sin Cuenta', 'admin', '2026-09-08 10:00:00', False))
    devolucion_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    _ENVIAR_CERTIFICADO_DEVOLUCION_REAL(devolucion_id)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo, estado FROM correos_log WHERE tipo = 'devolucion' ORDER BY id DESC LIMIT 1")
    fila = cur.fetchone()
    conn.close()
    assert fila == ('devolucion', 'sin_correo')


def test_enviar_certificado_devolucion_con_correo_resoluble_envia_el_pdf_adjunto_aunque_no_se_marcara_generar_acta(app, monkeypatch, crear_usuario):
    """Ignora 'acta_generada' a propósito: el certificado de devolución existe siempre, se haya
    marcado o no la casilla 'Generar acta' al certificar (esa casilla solo controla la descarga
    bajo demanda del PDF, ver acta_devolucion_pdf)."""
    crear_usuario(usuario='mduarte', nombre='Mario Duarte', correo='mduarte@preventivaips.com.co')
    activo_id = _crear_activo_inventario(app, nombre='80013', asignado_a='Mario Duarte (mduarte)', estado='Asignado')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, acta_generada) "
         "VALUES (%s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, acta_generada) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (activo_id, 'Mario Duarte (mduarte)', 'admin', '2026-09-08 10:00:00', False))
    devolucion_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    payloads = []

    class _RespuestaFalsa:
        status_code = 200

    monkeypatch.setattr(app.requests, 'post', lambda url, json=None, timeout=None: (payloads.append(json), _RespuestaFalsa())[-1])

    _ENVIAR_CERTIFICADO_DEVOLUCION_REAL(devolucion_id)

    assert len(payloads) == 1
    assert payloads[0]['para'] == 'mduarte@preventivaips.com.co'
    assert base64.b64decode(payloads[0]['adjunto_base64'])[:4] == b'%PDF'


# ────────────────────────────────────────────────────────────────────────────
# Hooks en crear_activo/editar_activo/confirmar_devolucion_activo: cuándo SÍ y cuándo NO se
# dispara el hilo de envío — mockeando las funciones de envío (evita threading/red reales).
# ────────────────────────────────────────────────────────────────────────────

def _mockear_envios(monkeypatch, app):
    llamadas_asignacion = []
    llamadas_devolucion = []
    monkeypatch.setattr(app, '_enviar_formulario_asignacion_por_correo', lambda *a, **k: llamadas_asignacion.append(a))
    monkeypatch.setattr(app, '_enviar_certificado_devolucion_por_correo', lambda *a, **k: llamadas_devolucion.append(a))
    return llamadas_asignacion, llamadas_devolucion


def test_crear_activo_asignado_dispara_el_envio_de_asignacion(admin_session, app, monkeypatch):
    llamadas_asig, _ = _mockear_envios(monkeypatch, app)

    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '80020', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Nuevo Colaborador (ncolab)',
    })

    assert len(llamadas_asig) == 1
    activo_id, asignado_a, creador = llamadas_asig[0][0], llamadas_asig[0][1], llamadas_asig[0][2]
    assert asignado_a == 'Nuevo Colaborador (ncolab)'
    assert creador == 'admin'


def test_crear_activo_disponible_no_dispara_ningun_envio(admin_session, app, monkeypatch):
    llamadas_asig, _ = _mockear_envios(monkeypatch, app)

    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '80021', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
    })

    assert llamadas_asig == []


def test_editar_activo_reasignando_a_otro_colaborador_dispara_el_envio(admin_session, app, monkeypatch):
    activo_id = _crear_activo_inventario(app, nombre='80022', asignado_a='Primera Persona', estado='Asignado')
    llamadas_asig, _ = _mockear_envios(monkeypatch, app)

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '80022', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Segunda Persona',
    })

    assert len(llamadas_asig) == 1
    assert llamadas_asig[0][1] == 'Segunda Persona'


def test_editar_activo_sin_cambiar_el_asignado_no_dispara_correo_de_asignacion(admin_session, app, monkeypatch):
    """Evita spam: editar cualquier otro dato de un activo que ya estaba asignado a la MISMA
    persona no debe reenviar el formulario de asignación."""
    activo_id = _crear_activo_inventario(app, nombre='80023', asignado_a='Misma Persona', estado='Asignado')
    llamadas_asig, _ = _mockear_envios(monkeypatch, app)

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '80023', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Misma Persona',
        'marca': 'Dell',
    })

    assert llamadas_asig == []


def test_editar_activo_edicion_fallida_no_dispara_correo(admin_session, app, monkeypatch):
    """Si la edición falla (ej. placa duplicada con otro activo), no debe intentarse ningún
    envío — la asignación en sí no se guardó."""
    _crear_activo_inventario(app, nombre='80024-dup', asignado_a=None, estado='Disponible')
    activo_id = _crear_activo_inventario(app, nombre='80024', asignado_a='Alguien', estado='Asignado')
    llamadas_asig, _ = _mockear_envios(monkeypatch, app)

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '80024-dup', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Otra Persona',
    })

    assert llamadas_asig == []


def test_confirmar_devolucion_dispara_el_envio_sin_marcar_generar_acta(admin_session, app, monkeypatch):
    activo_id = _crear_activo_inventario(app, nombre='80025', asignado_a='Colaborador Que Devuelve', estado='Asignado')
    _, llamadas_dev = _mockear_envios(monkeypatch, app)

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    assert len(llamadas_dev) == 1
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id_real = cur.fetchone()[0]
    conn.close()
    assert llamadas_dev[0][0] == devolucion_id_real


def test_confirmar_devolucion_marcando_generar_acta_tambien_dispara_el_envio(admin_session, app, monkeypatch):
    activo_id = _crear_activo_inventario(app, nombre='80026', asignado_a='Otro Colaborador', estado='Asignado')
    _, llamadas_dev = _mockear_envios(monkeypatch, app)

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})

    assert len(llamadas_dev) == 1
