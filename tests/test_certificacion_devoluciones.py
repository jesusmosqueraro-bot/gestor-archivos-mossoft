"""Pruebas de la certificación de devolución de activos: antes de bloquear/liquidar la
cuenta de un colaborador en Gestión de Usuarios, Gestión Humana o TI deben certificar que
ya devolvió el PC u otro activo que tenía asignado en el Inventario."""
import cloudinary.uploader


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/firma_familiar.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def _crear_activo(app, nombre='Laptop de Prueba', estado='Asignado', asignado_a='Juan Pérez', tipo_activo='Portátil', es_biomedico=False):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, tipo_activo, estado, asignado_a, es_biomedico, '2026-09-01 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _sesion_gestion_humana(client, app, usuario='rrhh1'):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'gestion_humana'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def test_gestion_humana_puede_ver_certificacion_devoluciones(client, app, crear_usuario):
    crear_usuario(usuario='rrhh1', rol='gestion_humana')
    _sesion_gestion_humana(client, app)

    r = client.get('/inventario/certificacion_devoluciones')

    assert r.status_code == 200


def test_estandar_no_puede_ver_certificacion_devoluciones(client, app, sesion_usuario):
    r = client.get('/inventario/certificacion_devoluciones')

    assert r.status_code in (302, 403)


def test_pendientes_de_devolucion_lista_activos_asignados(admin_session, app):
    _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    r = admin_session.get('/inventario/certificacion_devoluciones')

    assert r.status_code == 200
    assert 'Duván Cabarcas'.encode('utf-8') in r.data or b'Cabarcas' in r.data


def test_confirmar_devolucion_libera_el_activo_y_certifica(admin_session, app):
    """Desde que se agregó el estado 'Devolución' (pedido por Tomás), certificar la devolución
    ya NO deja el activo 'Disponible' de inmediato: queda en 'Devolución', sin asignar a nadie,
    con la fecha registrada y bloqueado hasta que un admin lo revise (ver test_inventario_
    devolucion.py para el bloqueo en sí)."""
    activo_id = _crear_activo(app, nombre='Laptop HP', asignado_a='María López')

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'observaciones': 'Entregada en buen estado'})

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE id = ?", (activo_id,))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    assert estado == 'Devolución'
    assert asignado_a is None
    assert fecha_devolucion  # se registró la fecha de la devolución
    cur.execute("SELECT colaborador, confirmado_por, observaciones FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'María López'
    assert fila[1] == 'admin'
    assert fila[2] == 'Entregada en buen estado'


def test_gestion_humana_puede_confirmar_devolucion(client, app, crear_usuario):
    crear_usuario(usuario='rrhh1', rol='gestion_humana')
    _sesion_gestion_humana(client, app)
    activo_id = _crear_activo(app, nombre='Monitor LG', asignado_a='Carlos Ruiz')

    r = client.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Devolución'
    conn.close()


def test_no_se_puede_bloquear_usuario_con_activo_pendiente_de_devolucion(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Duván Cabarcas', rol='estandar')
    _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    usuario_id = cur.fetchone()[0]
    conn.close()

    admin_session.post(f'/usuarios/toggle_estado/{usuario_id}', follow_redirects=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM usuarios WHERE id = ?", (usuario_id,))
    estado = cur.fetchone()[0]
    conn.close()
    assert (estado or 'activo') == 'activo'  # sigue activo: el bloqueo quedó rechazado


def test_se_puede_bloquear_usuario_tras_certificar_la_devolucion(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Duván Cabarcas', rol='estandar')
    activo_id = _crear_activo(app, nombre='Laptop Dell', asignado_a='Duván Cabarcas')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    usuario_id = cur.fetchone()[0]
    conn.close()

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})
    admin_session.post(f'/usuarios/toggle_estado/{usuario_id}')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM usuarios WHERE id = ?", (usuario_id,))
    estado = cur.fetchone()[0]
    conn.close()
    assert estado == 'inactivo'


def test_exportar_certificacion_devoluciones_csv(admin_session, app):
    activo_id = _crear_activo(app, nombre='Impresora Epson', asignado_a='Ana Torres')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    r = admin_session.get('/inventario/certificacion_devoluciones/exportar_csv')

    assert r.status_code == 200
    assert 'text/csv' in r.headers.get('Content-Type', '')
    texto = r.get_data(as_text=True)
    assert 'COLABORADOR' in texto and 'Ana Torres' in texto


def test_certificacion_devoluciones_tiene_boton_de_tema_claro_oscuro(admin_session):
    """Esta pantalla se había quedado sin el botón flotante de tema claro/oscuro que sí tienen
    las demás páginas del sistema — se agrega para que sea consistente."""
    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert 'action="/perfil/tema"' in texto
    assert 'fa-sun' in texto or 'fa-moon' in texto


# ────────────────────────────────────────────────────────────────────────────
# ACTA DE DEVOLUCIÓN EN PDF (pedido por Tomás): "ojo, que solo lo genere si se le marca
# generar" — el checkbox 'generar_acta' en la confirmación decide si esa certificación puntual
# queda con un PDF descargable o no. La fila de 'inventario_devoluciones' en sí es siempre el
# certificado, se marque o no la casilla.
# ────────────────────────────────────────────────────────────────────────────

def test_confirmar_devolucion_sin_marcar_generar_acta_no_deja_pdf_descargable(admin_session, app):
    activo_id = _crear_activo(app, nombre='Laptop Acer', asignado_a='Pedro Salas')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, acta_generada FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id, acta_generada = cur.fetchone()
    conn.close()
    assert bool(acta_generada) is False

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf', follow_redirects=True)
    assert r.status_code == 200
    assert r.headers['Content-Type'] != 'application/pdf'


def test_confirmar_devolucion_marcando_generar_acta_permite_descargar_el_pdf(admin_session, app):
    activo_id = _crear_activo(app, nombre='Laptop Lenovo', asignado_a='Sofía Ramírez')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, acta_generada FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id, acta_generada = cur.fetchone()
    conn.close()
    assert bool(acta_generada) is True

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data[:4] == b'%PDF'


def test_historial_de_certificacion_muestra_el_enlace_de_descarga_solo_si_se_genero_acta(admin_session, app):
    activo_con_acta = _crear_activo(app, nombre='PC Con Acta', asignado_a='Con Acta')
    activo_sin_acta = _crear_activo(app, nombre='PC Sin Acta', asignado_a='Sin Acta')
    admin_session.post(f'/inventario/{activo_con_acta}/confirmar_devolucion', data={'generar_acta': 'on'})
    admin_session.post(f'/inventario/{activo_sin_acta}/confirmar_devolucion', data={})

    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)

    assert texto.count('acta_pdf') == 1  # solo una de las dos filas trae el enlace de descarga


def test_devolucion_requiere_rol_valido_para_descargar_acta(sesion_usuario, app):
    activo_id = _crear_activo(app, nombre='Laptop Restringida', asignado_a='Alguien')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones, acta_generada) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones, acta_generada) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (activo_id, 'Alguien', 'admin', '2026-09-06 10:00:00', None, True))
    devolucion_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    r = sesion_usuario.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    assert r.status_code in (302, 403)


# ────────────────────────────────────────────────────────────────────────────
# FIRMAS AUTO-RESUELTAS del acta de devolución (pedido de Tomás, 06/09/2026): "quien entrega"
# (el colaborador) y "quien certifica" (el operador logueado) se toman solas de sus perfiles, sin
# ningún widget nuevo; la firma de familiar/cuidador SÍ se captura en el momento, pero solo
# cuenta para activos biomédicos.
# ────────────────────────────────────────────────────────────────────────────

def test_devolucion_incluye_firma_de_quien_entrega_y_quien_certifica_si_las_tienen_guardadas(admin_session, app, crear_usuario):
    colaborador = crear_usuario(nombre='Rita Solano', rol='estandar')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET firma = ? WHERE usuario = ?",
                ('https://res.cloudinary.com/demo/image/upload/firma_colaborador.png', colaborador))
    cur.execute("UPDATE usuarios SET firma = ? WHERE usuario = ?",
                ('https://res.cloudinary.com/demo/image/upload/firma_admin.png', 'admin'))
    conn.commit()
    conn.close()
    activo_id = _crear_activo(app, nombre='Laptop Rita', asignado_a=f'Rita Solano ({colaborador})')

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT firma_entrega_url, firma_certifica_url FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    firma_entrega_url, firma_certifica_url = cur.fetchone()
    conn.close()
    assert firma_entrega_url == 'https://res.cloudinary.com/demo/image/upload/firma_colaborador.png'
    assert firma_certifica_url == 'https://res.cloudinary.com/demo/image/upload/firma_admin.png'


FIRMA_DATAURL_VALIDA = ('data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4'
                         '2mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=')


def test_devolucion_biomedico_con_familiar_guarda_su_nombre_y_firma(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    activo_id = _crear_activo(app, nombre='Bomba Infusion 1', asignado_a='Paciente X', es_biomedico=True)

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'generar_acta': 'on', 'nombre_familiar': 'Carlos Vega', 'firma_familiar_dataurl': FIRMA_DATAURL_VALIDA,
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre_familiar, firma_familiar_url FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    nombre_familiar, firma_familiar_url = cur.fetchone()
    conn.close()
    assert nombre_familiar == 'Carlos Vega'
    assert firma_familiar_url  # se subió (mock de Cloudinary por defecto en las pruebas del entorno)


def test_devolucion_no_biomedico_ignora_los_datos_de_familiar_aunque_lleguen(admin_session, app):
    """Un activo de TI (no biomédico) no tiene sección de familiar/cuidador en la pantalla — si de
    todas formas llegaran esos campos (formulario manipulado), se ignoran."""
    activo_id = _crear_activo(app, nombre='Laptop TI Familiar', asignado_a='Usuario TI', es_biomedico=False)

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'generar_acta': 'on', 'nombre_familiar': 'No debería guardarse', 'firma_familiar_dataurl': FIRMA_DATAURL_VALIDA,
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre_familiar, firma_familiar_url FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    nombre_familiar, firma_familiar_url = cur.fetchone()
    conn.close()
    assert nombre_familiar is None
    assert firma_familiar_url is None


def test_acta_devolucion_pdf_biomedico_con_firma_familiar_se_genera(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch)
    activo_id = _crear_activo(app, nombre='Bomba Infusion 2', asignado_a='Paciente Y', es_biomedico=True)
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'generar_acta': 'on', 'nombre_familiar': 'Ana Ríos', 'firma_familiar_dataurl': FIRMA_DATAURL_VALIDA,
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')
    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data[:4] == b'%PDF'


def test_pendientes_de_devolucion_incluye_bandera_es_biomedico(admin_session, app):
    _crear_activo(app, nombre='Bomba Infusion 3', asignado_a='Paciente Z', es_biomedico=True)
    texto = admin_session.get('/inventario/certificacion_devoluciones').get_data(as_text=True)
    assert 'nombre_familiar' in texto  # la sección de familiar/cuidador aparece para ese pendiente


def test_confirmar_devolucion_de_activo_asignado_sin_colaborador_explica_el_error(admin_session, app):
    """Causa real reportada por Tomás (06/09/2026): un activo puede quedar en estado 'Asignado'
    sin un colaborador definido (aparece como 'Sin asignar' en la lista de pendientes) — por
    ejemplo, un activo de prueba creado directamente en la base. Antes, al intentar certificar su
    devolución, esto reventaba en un error genérico de base de datos ('No se pudo registrar la
    certificación de devolución') porque 'inventario_devoluciones.colaborador' es NOT NULL. Ahora
    se detecta ANTES de intentar el INSERT y se explica la causa exacta y cómo corregirla, sin
    dejar ningún rastro a medias en 'inventario_devoluciones' ni cambiar el estado del activo."""
    activo_id = _crear_activo(app, nombre='Portatil Sin Colaborador', asignado_a=None)

    r = admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion',
                            data={'observaciones': 'intento de certificación'}, follow_redirects=True)

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert "no tiene un colaborador registrado" in texto
    assert "edita este activo" in texto.lower()
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Asignado'  # no cambió: no se intentó certificar nada
    cur.execute("SELECT COUNT(*) FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0  # no quedó ningún registro a medias
    conn.close()


def test_acta_devolucion_pdf_con_descripcion_larga_no_se_desborda(admin_session, app):
    """Antes, la descripción del ítem en el PDF (equipo/marca/modelo/placa/serie/sede/área) se
    dibujaba como texto plano y podía desbordarse fuera de los bordes de su celda cuando era
    larga (pedido de Tomás, 06/09/2026: 'corregir los saltos, que se ajuste el campo al texto').
    Ahora se envuelve en un Paragraph que ajusta el texto dentro del ancho de la columna — esta
    prueba usa una sede/área/marca/modelo deliberadamente largos y solo verifica que el PDF se
    genere sin reventar (el ajuste de línea en sí no es verificable desde el contenido binario)."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, asignado_a, sede, area, es_biomedico, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, asignado_a, sede, area, es_biomedico, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, ('15098', 'Portátil', 'LENOVO Expertbook de la línea corporativa completa',
                     'Modelo con nombre comercial extremadamente largo para forzar el desborde',
                     'PRUEBA DE PDF CON SERIE MUY LARGA PARA VERIFICAR EL AJUSTE', 'Asignado',
                     'Administrador Master (admin)', 'NUEVO NARANJAL', 'SEDE ADMINISTRATIVA PRINCIPAL',
                     False, '2026-09-06 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'generar_acta': 'on'})
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id = cur.fetchone()[0]
    conn.close()

    r = admin_session.get(f'/inventario/certificacion_devoluciones/{devolucion_id}/acta_pdf')

    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'
