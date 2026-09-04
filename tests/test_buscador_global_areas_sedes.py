"""Pruebas de cobertura del buscador global ("Buscar en Arkiv") para las categorías agregadas
tras el reporte de Tomás de que el buscador "no busca áreas, sede" y debía "buscar todo lo que
hay en el aplicativo": Áreas, Sedes y Categorías de Solicitudes (catálogo de
/tickets/configuracion, antes solo se buscaba 'proveedor' de esa misma tabla), Mis Tareas
(subtareas de un ticket) y Actas de Recibido Biomédico."""


def _crear_catalogo(app, tipo, nombre, direccion=None, responsable=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO ticket_configuraciones (tipo, nombre, estado, direccion, responsable) VALUES (%s, %s, 'activo', %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO ticket_configuraciones (tipo, nombre, estado, direccion, responsable) VALUES (?, ?, 'activo', ?, ?)")
    cur.execute(q, (tipo, nombre, direccion, responsable))
    conn.commit()
    conn.close()


def _crear_ticket(app, titulo='Solicitud de prueba', creado_por='admin'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO tickets (titulo, descripcion, tipo, estado, creado_por, fecha_creacion, fecha_actualizacion) VALUES (%s, %s, 'Incidente', 'Abierto', %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO tickets (titulo, descripcion, tipo, estado, creado_por, fecha_creacion, fecha_actualizacion) VALUES (?, ?, 'Incidente', 'Abierto', ?, ?, ?)")
    cur.execute(q, (titulo, 'Descripción de prueba', creado_por, '2026-09-04 09:00:00', '2026-09-04 09:00:00'))
    ticket_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return ticket_id


def _crear_tarea(app, ticket_id, asunto='Configurar impresora en el puesto', responsable='admin', descripcion=''):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO tickets_tareas (ticket_id, asunto, descripcion, responsable, estado, creado_por, fecha_creacion) VALUES (%s, %s, %s, %s, 'pendiente', 'admin', %s)"
         if db_type == 'postgres' else
         "INSERT INTO tickets_tareas (ticket_id, asunto, descripcion, responsable, estado, creado_por, fecha_creacion) VALUES (?, ?, ?, ?, 'pendiente', 'admin', ?)")
    cur.execute(q, (ticket_id, asunto, descripcion, responsable, '2026-09-04 09:00:00'))
    conn.commit()
    conn.close()


def _crear_activo(app, nombre='30030', tipo_activo='Bomba de infusión'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, es_biomedico, fecha_creacion, creado_por) VALUES (%s, %s, 'Asignado', 1, %s, 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, es_biomedico, fecha_creacion, creado_por) VALUES (?, ?, 'Asignado', 1, ?, 'admin')")
    cur.execute(q, (nombre, tipo_activo, '2026-09-04 09:00:00'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _crear_acta(app, activo_id, nombre_responsable='Rosa Pérez', documento_responsable='12345678', direccion_entrega='Calle 10 # 5-20, Cali'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO actas_recibido_biomedico (activo_id, nombre_responsable, relacion_responsable, documento_responsable, telefono_contacto, direccion_entrega, firma_url, fecha, creado_por) "
         "VALUES (%s, %s, 'cuidador', %s, '3000000000', %s, 'https://res.cloudinary.com/demo/image/upload/firma.png', %s, 'admin')"
         if db_type == 'postgres' else
         "INSERT INTO actas_recibido_biomedico (activo_id, nombre_responsable, relacion_responsable, documento_responsable, telefono_contacto, direccion_entrega, firma_url, fecha, creado_por) "
         "VALUES (?, ?, 'cuidador', ?, '3000000000', ?, 'https://res.cloudinary.com/demo/image/upload/firma.png', ?, 'admin')")
    cur.execute(q, (activo_id, nombre_responsable, documento_responsable, direccion_entrega, '2026-09-04 09:00:00'))
    conn.commit()
    conn.close()


# --- Áreas, Sedes y Categorías de Solicitudes ---

def test_buscador_global_encuentra_area_por_nombre(admin_session, app):
    _crear_catalogo(app, 'area', 'Facturación y Cartera', responsable='Laura Gómez')

    data = admin_session.get('/buscar/api?q=facturacion').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Áreas' in categorias


def test_buscador_global_encuentra_sede_por_direccion(admin_session, app):
    _crear_catalogo(app, 'sede', 'Sede Norte', direccion='Carrera 45 # 100-20, Cali')

    data = admin_session.get('/buscar/api?q=carrera 45').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Sedes']
    assert 'Sede Norte' in titulos


def test_buscador_global_encuentra_categoria_de_solicitud(admin_session, app):
    _crear_catalogo(app, 'categoria', 'Soporte de Hardware Biomédico')

    data = admin_session.get('/buscar/api?q=biomedico').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Categorías de Solicitudes' in categorias


def test_estandar_no_ve_areas_ni_sedes_en_el_buscador_global(client, sesion_usuario, app):
    _crear_catalogo(app, 'area', 'Facturación y Cartera')
    _crear_catalogo(app, 'sede', 'Sede Norte')

    data = client.get('/buscar/api?q=cara').get_json()

    categorias = {r['categoria'] for r in data['resultados']}
    assert 'Áreas' not in categorias
    assert 'Sedes' not in categorias


# --- Mis Tareas ---

def test_buscador_global_encuentra_tarea_propia(admin_session, app):
    ticket_id = _crear_ticket(app)
    _crear_tarea(app, ticket_id, asunto='Configurar impresora HP en recepción', responsable='admin')

    data = admin_session.get('/buscar/api?q=impresora hp').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Mis Tareas' in categorias


def test_buscador_global_no_muestra_tareas_de_otro_agente(admin_session, app):
    ticket_id = _crear_ticket(app)
    _crear_tarea(app, ticket_id, asunto='Configurar impresora HP en recepción', responsable='otro_agente')

    data = admin_session.get('/buscar/api?q=impresora hp').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Mis Tareas' not in categorias


def test_estandar_no_ve_mis_tareas_en_el_buscador_global(client, sesion_usuario, app):
    ticket_id = _crear_ticket(app)
    _crear_tarea(app, ticket_id, asunto='Configurar impresora HP en recepción', responsable='admin')

    data = client.get('/buscar/api?q=impresora hp').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Mis Tareas' not in categorias


# --- Actas de Recibido Biomédico ---

def test_buscador_global_encuentra_acta_por_responsable(admin_session, app):
    activo_id = _crear_activo(app, nombre='30031')
    _crear_acta(app, activo_id, nombre_responsable='Rosa Pérez Cuidadora')

    data = admin_session.get('/buscar/api?q=rosa perez').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Actas de Recibido Biomédico' in categorias


def test_buscador_global_encuentra_acta_por_placa_del_activo(admin_session, app):
    activo_id = _crear_activo(app, nombre='30032')
    _crear_acta(app, activo_id, nombre_responsable='Luis Gómez')

    data = admin_session.get('/buscar/api?q=30032').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Actas de Recibido Biomédico']
    assert 'Acta de Luis Gómez' in titulos


def test_estandar_no_ve_actas_de_recibido_en_el_buscador_global(client, sesion_usuario, app):
    activo_id = _crear_activo(app, nombre='30033')
    _crear_acta(app, activo_id, nombre_responsable='Rosa Pérez')

    data = client.get('/buscar/api?q=rosa perez').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Actas de Recibido Biomédico' not in categorias
