"""Búsqueda transversal por nombre/cédula/usuario (pedido por Tomás, 08/09/2026): "este tipo de
búsqueda debe ser transversal en todos los filtros o campos donde se busque por nombre de
usuarios o número de documentos o nombre de usuario, siempre debe traer el nombre del usuario
haciendo uso de un LIKE, o algo así".

Antes de esto, varias búsquedas de "colaborador" en el sistema solo comparaban contra el
usuario de inicio de sesión (o un texto libre tipo 'Nombre (usuario)') y NUNCA contra la cédula
de la persona — así que buscar a alguien por su cédula (o, en Certificación de Devoluciones, a
veces incluso por su nombre) no encontraba nada aunque esa persona sí tuviera registros. Cubre:
Certificación de Devoluciones (pendientes + historial, que antes ni siquiera respetaba la
búsqueda), Inventario de Activos (lista + exportación CSV), el buscador global ("Buscar en
Arkiv") para esas dos categorías, Solicitudes TI (tickets) y la Bitácora de Auditoría (/logs)."""


def _crear_activo_inventario(app, nombre='30099', asignado_a=None, estado='Asignado', tipo_activo='Portátil'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, 'admin')")
    cur.execute(q, (nombre, tipo_activo, estado, asignado_a, '2026-09-08 09:00:00'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


# ────────────────────────────────────────────────────────────────────────────
# Certificación de Devoluciones — /inventario/certificacion_devoluciones
# ────────────────────────────────────────────────────────────────────────────

def test_certificacion_pendientes_encuentra_por_cedula_de_la_persona_asignada(admin_session, app, crear_usuario):
    """'asignado_a' se guarda como texto libre 'Nombre (usuario)' cuando se elige por el
    autocompletar/búsqueda por cédula — buscar la cédula de esa persona debe encontrar el activo
    aunque la cédula en sí nunca se guarde en 'activos_inventario'."""
    crear_usuario(usuario='murrea', nombre='Manuela Urrea Candamil', cedula='1029384756')
    _crear_activo_inventario(app, nombre='14704', asignado_a='Manuela Urrea Candamil (murrea)')

    r = admin_session.get('/inventario/certificacion_devoluciones?q=1029384756')

    assert r.status_code == 200
    assert b'14704' in r.data


def test_certificacion_pendientes_sin_coincidencia_de_cedula_no_aparece(admin_session, app, crear_usuario):
    crear_usuario(usuario='murrea', nombre='Manuela Urrea Candamil', cedula='1029384756')
    _crear_activo_inventario(app, nombre='14704', asignado_a='Manuela Urrea Candamil (murrea)')

    r = admin_session.get('/inventario/certificacion_devoluciones?q=9999999999')

    assert b'14704' not in r.data


def test_certificacion_historial_tambien_respeta_la_busqueda(admin_session, app):
    """Antes de esta corrección, el cuadro de búsqueda de esta pantalla solo filtraba
    'Pendientes de devolución' — la tabla de 'Certificados de devolución' de abajo mostraba
    siempre TODO el historial sin importar lo escrito."""
    activo_uno = _crear_activo_inventario(app, nombre='30001', asignado_a='Carlos Ruiz')
    activo_dos = _crear_activo_inventario(app, nombre='30002', asignado_a='Andrea Salcedo')
    admin_session.post(f'/inventario/{activo_uno}/confirmar_devolucion', data={})
    admin_session.post(f'/inventario/{activo_dos}/confirmar_devolucion', data={})

    r = admin_session.get('/inventario/certificacion_devoluciones?q=carlos')

    assert b'Carlos Ruiz' in r.data
    assert b'Andrea Salcedo' not in r.data


# ────────────────────────────────────────────────────────────────────────────
# Inventario de Activos — /tickets/inventario (lista + exportación CSV)
# ────────────────────────────────────────────────────────────────────────────

def test_inventario_lista_encuentra_activo_por_cedula_del_colaborador_asignado(admin_session, app, crear_usuario):
    crear_usuario(usuario='jperez', nombre='Juan Pérez Gómez', cedula='1122334455')
    _crear_activo_inventario(app, nombre='20050', asignado_a='Juan Pérez Gómez (jperez)', estado='Asignado')

    r = admin_session.get('/tickets/inventario?q=1122334455')

    assert b'20050' in r.data


def test_inventario_exportar_csv_encuentra_activo_por_cedula(admin_session, app, crear_usuario):
    crear_usuario(usuario='jperez', nombre='Juan Pérez Gómez', cedula='1122334455')
    _crear_activo_inventario(app, nombre='20050', asignado_a='Juan Pérez Gómez (jperez)', estado='Asignado')

    r = admin_session.get('/tickets/inventario/exportar_csv?q=1122334455')

    assert r.status_code == 200
    assert '20050' in r.get_data(as_text=True)


# ────────────────────────────────────────────────────────────────────────────
# Buscador global ("Buscar en Arkiv") — /buscar/api
# ────────────────────────────────────────────────────────────────────────────

def test_buscador_global_inventario_encuentra_por_cedula_del_asignado(admin_session, app, crear_usuario):
    crear_usuario(usuario='amaria', nombre='Ana María Torres', cedula='1000111222')
    _crear_activo_inventario(app, nombre='40010', asignado_a='Ana María Torres (amaria)', estado='Asignado')

    data = admin_session.get('/buscar/api?q=1000111222').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Inventario de Activos' in categorias


def test_buscador_global_certificacion_devoluciones_encuentra_por_cedula(admin_session, app, crear_usuario):
    crear_usuario(usuario='amaria', nombre='Ana María Torres', cedula='1000111222')
    activo_id = _crear_activo_inventario(app, nombre='40011', asignado_a='Ana María Torres (amaria)')
    admin_session.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    data = admin_session.get('/buscar/api?q=1000111222').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Certificación de Devoluciones' in categorias


# ────────────────────────────────────────────────────────────────────────────
# Solicitudes TI — /tickets
# ────────────────────────────────────────────────────────────────────────────

def _crear_ticket(app, titulo='Impresora no imprime', creado_por='estandar1'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, fecha_creacion, fecha_actualizacion) "
         "VALUES (%s, %s, 'Incidente', 'Hardware', 'Media', 'Abierto', %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, fecha_creacion, fecha_actualizacion) "
         "VALUES (?, ?, 'Incidente', 'Hardware', 'Media', 'Abierto', ?, ?, ?)")
    cur.execute(q, (titulo, 'Descripción de prueba', creado_por, '2026-09-08 09:00:00', '2026-09-08 09:00:00'))
    ticket_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def test_tickets_encuentra_solicitud_por_nombre_real_de_quien_la_creo(admin_session, app, crear_usuario):
    """Antes, el cuadro de búsqueda de /tickets solo comparaba contra el USUARIO de quien creó
    el ticket (ej. 'estandar1'), nunca contra su nombre real — aunque la tabla ya mostraba el
    nombre resuelto en la columna 'Creado por'."""
    usuario = crear_usuario(usuario='dcabarcas', nombre='Duván Cabarcas', cedula='555666777')
    _crear_ticket(app, titulo='Solicitud de prueba', creado_por=usuario)

    r = admin_session.get('/tickets?q=duván')

    assert b'Solicitud de prueba' in r.data


def test_tickets_encuentra_solicitud_por_cedula_de_quien_la_creo(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='dcabarcas', nombre='Duván Cabarcas', cedula='555666777')
    _crear_ticket(app, titulo='Solicitud de prueba', creado_por=usuario)

    r = admin_session.get('/tickets?q=555666777')

    assert b'Solicitud de prueba' in r.data


# ────────────────────────────────────────────────────────────────────────────
# Bitácora de Auditoría — /logs
# ────────────────────────────────────────────────────────────────────────────

def _registrar_log(app, usuario, accion='Prueba', detalles='Detalle de prueba'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (%s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)")
    cur.execute(q, (usuario, accion, detalles, '2026-09-08 09:00:00'))
    conn.commit()
    conn.close()


def test_logs_dropdown_de_usuario_muestra_el_nombre_real_no_el_usuario_crudo(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='tmira', nombre='Tatiana Mira Londoño')
    _registrar_log(app, usuario)

    texto = admin_session.get('/logs').get_data(as_text=True)

    assert 'Tatiana Mira Londoño' in texto


def test_logs_busqueda_libre_encuentra_por_nombre(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='tmira', nombre='Tatiana Mira Londoño', cedula='999888777')
    _registrar_log(app, usuario, detalles='Cambio de contraseña')

    r = admin_session.get('/logs?q=tatiana')

    assert r.status_code == 200
    assert 'Cambio de contraseña' in r.get_data(as_text=True)


def test_logs_busqueda_libre_encuentra_por_cedula(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='tmira', nombre='Tatiana Mira Londoño', cedula='999888777')
    _registrar_log(app, usuario, detalles='Cambio de contraseña')

    r = admin_session.get('/logs?q=999888777')

    assert r.status_code == 200
    assert 'Cambio de contraseña' in r.get_data(as_text=True)


def test_logs_exportar_csv_incluye_columna_de_nombre(admin_session, app, crear_usuario):
    usuario = crear_usuario(usuario='tmira', nombre='Tatiana Mira Londoño')
    _registrar_log(app, usuario, detalles='Cambio de contraseña')

    r = admin_session.get('/exportar_logs_csv')

    texto = r.get_data(as_text=True)
    assert 'NOMBRE' in texto
    assert 'Tatiana Mira Londoño' in texto
