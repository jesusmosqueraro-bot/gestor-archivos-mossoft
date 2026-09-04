"""Pruebas de cobertura del buscador global ("Buscar en Arkiv"): valida que las categorías
agregadas más recientes —Proveedores (por nombre o NIT), Plantillas de Solicitud y
Certificación de Devoluciones— realmente aparezcan en /buscar/api, y que cada una respete el
mismo permiso que ya aplica su página propia.

Se creó después de que un proveedor con NIT registrado no aparecía al buscar ese NIT desde el
buscador global (el catálogo de Proveedores nunca se había conectado a /buscar/api)."""


def _sesion_gestion_humana(client, app, usuario='rrhh1'):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'gestion_humana'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _crear_proveedor(app, nombre='Compulab Distribuciones', nit='811021798-3', razon_social='Compulab Distribuciones S.A.S.'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO ticket_configuraciones (tipo, nombre, estado, nit, razon_social) VALUES (%s, %s, 'activo', %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO ticket_configuraciones (tipo, nombre, estado, nit, razon_social) VALUES (?, ?, 'activo', ?, ?)")
    cur.execute(q, ('proveedor', nombre, nit, razon_social))
    conn.commit()
    conn.close()


def _crear_plantilla(app, nombre='Instalación de impresora', titulo='Instalar impresora nueva', descripcion='Configurar impresora en el equipo del colaborador'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO ticket_plantillas (nombre, tipo, categoria, prioridad, area, sede, titulo, descripcion, estado, creado_por, fecha_creacion) VALUES (%s, 'Incidente', 'Hardware', 'Media', NULL, NULL, %s, %s, 'activo', 'admin', %s)"
         if db_type == 'postgres' else
         "INSERT INTO ticket_plantillas (nombre, tipo, categoria, prioridad, area, sede, titulo, descripcion, estado, creado_por, fecha_creacion) VALUES (?, 'Incidente', 'Hardware', 'Media', NULL, NULL, ?, ?, 'activo', 'admin', ?)")
    cur.execute(q, (nombre, titulo, descripcion, '2026-09-04 09:00:00'))
    conn.commit()
    conn.close()


def _crear_activo(app, nombre='30020', tipo_activo='Portátil'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) VALUES (%s, %s, 'Disponible', %s, 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) VALUES (?, ?, 'Disponible', ?, 'admin')")
    cur.execute(q, (nombre, tipo_activo, '2026-09-04 09:00:00'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _crear_documento_empleado(app, usuario='admin', tipo_documento='Cédula', titulo='Cédula de ciudadanía', fecha_vencimiento='2027-01-01'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO documentos_empleado (usuario, tipo_documento, titulo, fecha_vencimiento, estado, creado_por, fecha_creacion) VALUES (%s, %s, %s, %s, 'activo', 'admin', %s)"
         if db_type == 'postgres' else
         "INSERT INTO documentos_empleado (usuario, tipo_documento, titulo, fecha_vencimiento, estado, creado_por, fecha_creacion) VALUES (?, ?, ?, ?, 'activo', 'admin', ?)")
    cur.execute(q, (usuario, tipo_documento, titulo, fecha_vencimiento, '2026-09-04 09:00:00'))
    conn.commit()
    conn.close()


def _crear_devolucion(app, activo_id, colaborador='Juan Pérez', confirmado_por='rrhh1', observaciones='Entregado en buen estado'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones) VALUES (%s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (activo_id, colaborador, confirmado_por, '2026-09-04 10:00:00', observaciones))
    conn.commit()
    conn.close()


# --- Proveedores ---

def test_buscador_global_encuentra_proveedor_por_nombre(admin_session, app):
    _crear_proveedor(app, nombre='Compulab Distribuciones')

    data = admin_session.get('/buscar/api?q=compulab').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Proveedores' in categorias


def test_buscador_global_encuentra_proveedor_por_nit(admin_session, app):
    _crear_proveedor(app, nombre='Compulab Distribuciones', nit='811021798-3')

    data = admin_session.get('/buscar/api?q=811021798').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Proveedores']
    assert 'Compulab Distribuciones' in titulos


def test_buscador_global_encuentra_proveedor_por_razon_social(admin_session, app):
    _crear_proveedor(app, nombre='HP Inc', razon_social='HP Inc Colombia Ltda')

    data = admin_session.get('/buscar/api?q=colombia ltda').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Proveedores']
    assert 'HP Inc' in titulos


def test_estandar_no_ve_proveedores_en_el_buscador_global(client, sesion_usuario, app):
    _crear_proveedor(app, nombre='Compulab Distribuciones', nit='811021798-3')

    data = client.get('/buscar/api?q=811021798').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Proveedores' not in categorias


# --- Plantillas de Solicitud ---

def test_buscador_global_encuentra_plantilla_de_solicitud(admin_session, app):
    _crear_plantilla(app, nombre='Instalación de impresora')

    data = admin_session.get('/buscar/api?q=instalaci').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Plantillas de Solicitud' in categorias


def test_estandar_no_ve_plantillas_en_el_buscador_global(client, sesion_usuario, app):
    _crear_plantilla(app, nombre='Instalación de impresora')

    data = client.get('/buscar/api?q=instalaci').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Plantillas de Solicitud' not in categorias


# --- Búsqueda insensible a tildes (afecta a todas las categorías por igual) ---

def test_buscador_global_encuentra_proveedor_sin_escribir_la_tilde(admin_session, app):
    _crear_proveedor(app, nombre='Papelería Nacional')

    data = admin_session.get('/buscar/api?q=papeleria').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Proveedores']
    assert 'Papelería Nacional' in titulos


def test_buscador_global_encuentra_ticket_aunque_la_busqueda_traiga_tilde_de_mas(admin_session, app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO tickets (titulo, descripcion, tipo, estado, creado_por, fecha_creacion, fecha_actualizacion) VALUES (%s, %s, 'Incidente', 'Abierto', 'admin', %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO tickets (titulo, descripcion, tipo, estado, creado_por, fecha_creacion, fecha_actualizacion) VALUES (?, ?, 'Incidente', 'Abierto', 'admin', ?, ?)")
    cur.execute(q, ('Solicitud de acceso a Kubapp', 'El area de contabilidad necesita acceso', '2026-09-04 09:00:00', '2026-09-04 09:00:00'))
    conn.commit()
    conn.close()

    # "área" sin tilde en la búsqueda debe encontrar "area" (sin tilde en el texto guardado).
    data = admin_session.get('/buscar/api?q=área').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Solicitudes TI' in categorias


# --- Vencimiento de Documentos ---

def test_buscador_global_encuentra_documento_de_empleado_por_titulo(admin_session, app):
    _crear_documento_empleado(app, titulo='Cédula de ciudadanía')

    data = admin_session.get('/buscar/api?q=cedula de ciudad').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Vencimiento de Documentos' in categorias


def test_buscador_global_encuentra_documento_de_empleado_por_tipo(admin_session, app):
    _crear_documento_empleado(app, tipo_documento='Contrato laboral', titulo='Contrato 2026')

    data = admin_session.get('/buscar/api?q=contrato laboral').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Vencimiento de Documentos']
    assert 'Contrato 2026' in titulos


def test_estandar_no_ve_documentos_de_empleado_en_el_buscador_global(client, sesion_usuario, app):
    _crear_documento_empleado(app, titulo='Cédula de ciudadanía')

    data = client.get('/buscar/api?q=cedula de ciudad').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Vencimiento de Documentos' not in categorias


# --- Certificación de Devoluciones ---

def test_buscador_global_encuentra_devolucion_por_colaborador(admin_session, app):
    activo_id = _crear_activo(app, nombre='30021')
    _crear_devolucion(app, activo_id, colaborador='Maneula Urrea Candamil')

    data = admin_session.get('/buscar/api?q=urrea').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Certificación de Devoluciones' in categorias


def test_gestion_humana_ve_devoluciones_en_el_buscador_global(client, app, crear_usuario):
    crear_usuario(usuario='rrhh1', rol='gestion_humana')
    _sesion_gestion_humana(client, app)
    activo_id = _crear_activo(app, nombre='30022')
    _crear_devolucion(app, activo_id, colaborador='Maneula Urrea Candamil')

    data = client.get('/buscar/api?q=urrea').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Certificación de Devoluciones' in categorias


def test_estandar_no_ve_devoluciones_en_el_buscador_global(client, sesion_usuario, app):
    activo_id = _crear_activo(app, nombre='30023')
    _crear_devolucion(app, activo_id, colaborador='Maneula Urrea Candamil')

    data = client.get('/buscar/api?q=urrea').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Certificación de Devoluciones' not in categorias
