"""Paz y salvo de 3 firmas en Certificación de Devoluciones (pedido de Tomás, 13/09/2026):
"el estándar formal de un paz y salvo laboral integral en una IPS involucra a: Colaborador
(entrega conforme), Soporte TI (recibe activos y revoca accesos) y Gestión Humana (valida y
autoriza liquidación)". Cubre las tres piezas pedidas:

  1) La migración (columnas nuevas en inventario_devoluciones — ver app.py, ALTER TABLE/CREATE
     TABLE): firma_colaborador/fecha_firma_colaborador, firma_ti/ti_usuario_id/fecha_firma_ti,
     firma_gh/gh_usuario_id/fecha_firma_gh, estado.
  2) La ruta firmar_paz_y_salvo_devolucion (/inventario/certificacion_devoluciones/<id>/firmar):
     el flujo 'pendiente_ti' -> 'pendiente_gh' -> 'completado' (o 'rechazado'), con la
     restricción de permisos por paso (solo TI firma el paso técnico, solo GH firma el cierre).
  3) El bloque de firmas del PDF institucional (_pdf_bloque_firmas_paz_y_salvo), que reemplaza
     al bloque de firmas de siempre SOLO cuando esta certificación pasó por este flujo.

Una devolución certificada ANTES de este cambio (o sin que el colaborador firme en el canvas)
sigue teniendo 'estado' en NULL — un certificado de una sola firma, exactamente como antes; eso
ya está cubierto por tests/test_certificacion_devoluciones.py y no se repite aquí."""
import io
import pdfplumber


FIRMA_DATAURL_VALIDA = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4'
                         '2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def _crear_activo(app, nombre='Laptop de Prueba', estado='Asignado', asignado_a='Juan Pérez', es_biomedico=False):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, es_biomedico, '2026-09-13 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _sesion_como(client, app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _estado_y_columnas(app, devolucion_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT estado, firma_colaborador, fecha_firma_colaborador, firma_ti, ti_usuario_id, "
        "fecha_firma_ti, firma_gh, gh_usuario_id, fecha_firma_gh FROM inventario_devoluciones WHERE id = ?",
        (devolucion_id,))
    fila = cur.fetchone()
    conn.close()
    return fila


def _certificar_con_firma_colaborador(client, app, activo_id, generar_acta='on'):
    """Certifica la devolución del activo YA firmando el colaborador en el canvas (arranca el
    flujo de 3 firmas en 'pendiente_ti') y devuelve el id de esa devolución."""
    data = {'firma_colaborador_dataurl': FIRMA_DATAURL_VALIDA}
    if generar_acta:
        data['generar_acta'] = generar_acta
    client.post(f'/inventario/{activo_id}/confirmar_devolucion', data=data)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()
    return devolucion_id


# ────────────────────────────────────────────────────────────────────────────
# 1) MIGRACIÓN: las columnas nuevas existen y el flujo arranca/no arranca según corresponda.
# ────────────────────────────────────────────────────────────────────────────

def test_la_migracion_agrega_las_columnas_del_paz_y_salvo(app):
    """Chequeo directo de esquema: si alguna de estas columnas faltara, este SELECT reventaría."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT firma_colaborador, fecha_firma_colaborador, firma_ti, ti_usuario_id, fecha_firma_ti, "
        "firma_gh, gh_usuario_id, fecha_firma_gh, estado FROM inventario_devoluciones LIMIT 0")
    conn.close()


def test_certificar_sin_firma_de_colaborador_deja_estado_en_null(admin_session, app):
    """Comportamiento previo a este cambio, intacto: sin firma del colaborador en el canvas, no
    hay flujo de 3 firmas que arrancar — 'estado' queda en NULL, como cualquier certificación de
    antes de este feature."""
    activo_id = _crear_activo(app, nombre='Laptop Sin Firma Colaborador')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, firma_colaborador FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    estado, firma_colaborador = cur.fetchone()
    conn.close()
    assert estado is None
    assert firma_colaborador is None


def test_certificar_con_firma_de_colaborador_arranca_pendiente_ti(admin_session, app):
    activo_id = _crear_activo(app, nombre='Laptop Con Firma Colaborador')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)

    estado, firma_colaborador, fecha_firma_colaborador = _estado_y_columnas(app, devolucion_id)[:3]
    assert estado == 'pendiente_ti'
    assert firma_colaborador == FIRMA_DATAURL_VALIDA
    assert fecha_firma_colaborador  # se registró la fecha de esa firma


# ────────────────────────────────────────────────────────────────────────────
# 2) LA RUTA: firmar_paz_y_salvo_devolucion — permisos y transiciones de estado.
# ────────────────────────────────────────────────────────────────────────────

def test_agente_puede_firmar_el_paso_de_ti(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Paso TI')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='agenteti1', rol='agente')
    _sesion_como(client, app, 'agenteti1', 'agente')

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA}, follow_redirects=True)

    assert r.status_code == 200
    estado, _, _, firma_ti, ti_usuario_id, fecha_firma_ti = _estado_y_columnas(app, devolucion_id)[:6]
    assert estado == 'pendiente_gh'
    assert firma_ti == FIRMA_DATAURL_VALIDA
    assert ti_usuario_id is not None
    assert fecha_firma_ti


def test_gestion_humana_no_puede_firmar_el_paso_de_ti(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop GH No Puede TI')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='rrhh_ti', rol='gestion_humana')
    _sesion_como(client, app, 'rrhh_ti', 'gestion_humana')

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA}, follow_redirects=True)

    assert r.status_code == 200
    assert 'Solo un usuario de Soporte TI' in r.get_data(as_text=True)
    estado = _estado_y_columnas(app, devolucion_id)[0]
    assert estado == 'pendiente_ti'  # sin cambios


def test_estandar_no_puede_firmar_ningun_paso(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Estandar No Firma')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA})

    # certificacion_devolucion_required ya bloquea antes de llegar a la lógica de la ruta.
    assert r.status_code in (302, 403)
    estado = _estado_y_columnas(app, devolucion_id)[0]
    assert estado == 'pendiente_ti'


def test_gestion_humana_puede_firmar_el_cierre_tras_ti(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Cierre GH')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='agenteti2', rol='agente')
    _sesion_como(client, app, 'agenteti2', 'agente')
    client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA})

    crear_usuario(usuario='rrhh_cierre', rol='gestion_humana')
    _sesion_como(client, app, 'rrhh_cierre', 'gestion_humana')
    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'gh', 'firma_dataurl': FIRMA_DATAURL_VALIDA}, follow_redirects=True)

    assert r.status_code == 200
    estado, *_resto, firma_gh, gh_usuario_id, fecha_firma_gh = _estado_y_columnas(app, devolucion_id)
    assert estado == 'completado'
    assert firma_gh == FIRMA_DATAURL_VALIDA
    assert gh_usuario_id is not None
    assert fecha_firma_gh


def test_agente_no_puede_firmar_el_cierre_de_gh(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Agente No GH')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='agenteti3', rol='agente')
    _sesion_como(client, app, 'agenteti3', 'agente')
    client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA})

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'gh', 'firma_dataurl': FIRMA_DATAURL_VALIDA}, follow_redirects=True)

    assert r.status_code == 200
    assert 'Solo Gestión Humana' in r.get_data(as_text=True)
    estado = _estado_y_columnas(app, devolucion_id)[0]
    assert estado == 'pendiente_gh'  # sin cambios: sigue esperando a Gestión Humana


def test_firmar_gh_fuera_de_orden_sin_haber_firmado_ti_falla(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Fuera De Orden')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='rrhh_orden', rol='gestion_humana')
    _sesion_como(client, app, 'rrhh_orden', 'gestion_humana')

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'gh', 'firma_dataurl': FIRMA_DATAURL_VALIDA}, follow_redirects=True)

    assert r.status_code == 200
    assert 'esperando la firma de Soporte TI' in r.get_data(as_text=True)
    estado = _estado_y_columnas(app, devolucion_id)[0]
    assert estado == 'pendiente_ti'  # sin cambios


def test_rechazar_no_exige_firma_y_deja_estado_rechazado(admin_session, app):
    """admin está en ambos ROLES_FIRMA_TI_PAZ_Y_SALVO y ROLES_FIRMA_GH_PAZ_Y_SALVO, así que
    puede rechazar en cualquiera de los dos pasos."""
    activo_id = _crear_activo(app, nombre='Laptop Rechazo')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)

    r = admin_session.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                            data={'rol_firma': 'ti', 'accion': 'rechazar'}, follow_redirects=True)

    assert r.status_code == 200
    fila = _estado_y_columnas(app, devolucion_id)
    assert fila[0] == 'rechazado'  # estado
    assert fila[3] is None  # firma_ti: rechazar no guarda ninguna firma


def test_firmar_sin_firma_dataurl_falla_con_mensaje_claro(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop Sin Dataurl')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)
    crear_usuario(usuario='agenteti4', rol='agente')
    _sesion_como(client, app, 'agenteti4', 'agente')

    r = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                     data={'rol_firma': 'ti'}, follow_redirects=True)

    assert r.status_code == 200
    assert 'Falta la firma digital' in r.get_data(as_text=True)
    estado = _estado_y_columnas(app, devolucion_id)[0]
    assert estado == 'pendiente_ti'


# ────────────────────────────────────────────────────────────────────────────
# 3) EL PDF: el bloque institucional de 3 firmas reemplaza al bloque de siempre cuando el flujo
#    de 3 firmas está activo — y solo entonces.
# ────────────────────────────────────────────────────────────────────────────

def test_pdf_con_paz_y_salvo_pendiente_incluye_el_bloque_de_3_firmas(admin_session, app):
    activo_id = _crear_activo(app, nombre='Laptop PDF Pendiente')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')

    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'
    with pdfplumber.open(io.BytesIO(r.data)) as pdf:
        texto = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'PAZ Y SALVO' in texto
    assert 'Soporte TI que recibe' in texto
    assert 'Gestión Humana que liquida' in texto
    assert 'PENDIENTE' in texto


def test_pdf_con_paz_y_salvo_completado_muestra_las_3_firmas_y_datos_del_firmante(client, app, crear_usuario, admin_session):
    activo_id = _crear_activo(app, nombre='Laptop PDF Completado')
    devolucion_id = _certificar_con_firma_colaborador(admin_session, app, activo_id)

    crear_usuario(usuario='agenteti5', rol='agente', nombre='Luis Soporte', cedula='1000111222')
    _sesion_como(client, app, 'agenteti5', 'agente')
    client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                data={'rol_firma': 'ti', 'firma_dataurl': FIRMA_DATAURL_VALIDA})

    crear_usuario(usuario='rrhh_pdf', rol='gestion_humana', nombre='Marta Humana', cedula='2000333444')
    _sesion_como(client, app, 'rrhh_pdf', 'gestion_humana')
    client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar',
                data={'rol_firma': 'gh', 'firma_dataurl': FIRMA_DATAURL_VALIDA})

    _sesion_como(client, app, 'admin', 'admin')
    r = client.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')

    assert r.status_code == 200
    with pdfplumber.open(io.BytesIO(r.data)) as pdf:
        texto = "\n".join(p.extract_text() or '' for p in pdf.pages)
    assert 'COMPLETADO' in texto
    assert 'Luis Soporte' in texto
    assert '1000111222' in texto
    assert 'Marta Humana' in texto
    assert '2000333444' in texto


def test_pdf_de_devolucion_sin_flujo_de_3_firmas_no_cambia(admin_session, app):
    """Regresión explícita: una certificación que NUNCA pasó por el flujo de 3 firmas
    ('estado' en NULL) no debe mostrar nada del bloque institucional nuevo."""
    activo_id = _crear_activo(app, nombre='Laptop PDF Sin Flujo Nuevo')
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
    assert 'PAZ Y SALVO' not in texto
    assert 'Firma responsable de devolución' in texto  # el bloque de siempre, intacto
