"""Pruebas del catálogo de Proveedores (NIT, Razón social) y del campo 'Proveedor' en el
Inventario de Activos: se administra desde /tickets/configuracion (igual que Área/Sede/
Categoría) y se puede asignar/filtrar al crear o editar un activo. También cubre que el
buscador global ("Buscar en Arkiv") ahora encuentra activos del Inventario."""


def _crear_proveedor(app, nombre='Dell Colombia', nit='900123456-7', razon_social='Dell Colombia S.A.S.'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO ticket_configuraciones (tipo, nombre, estado, nit, razon_social) VALUES (%s, %s, 'activo', %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO ticket_configuraciones (tipo, nombre, estado, nit, razon_social) VALUES (?, ?, 'activo', ?, ?)")
    cur.execute(q, ('proveedor', nombre, nit, razon_social))
    proveedor_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return proveedor_id


def _crear_activo_directo(app, nombre='15011', proveedor=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, proveedor, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, proveedor, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', 'Disponible', proveedor, '2026-09-04 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_proveedor_guarda_nit_y_razon_social(admin_session, app):
    r = admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'proveedor', 'nombre': 'HP Inc', 'nit': '800987654-1', 'razon_social': 'HP Inc Colombia Ltda'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre, nit, razon_social FROM ticket_configuraciones WHERE tipo = 'proveedor'")
    fila = cur.fetchone()
    conn.close()
    assert fila == ('HP Inc', '800987654-1', 'HP Inc Colombia Ltda')


def test_editar_proveedor_actualiza_nit_y_razon_social(admin_session, app):
    proveedor_id = _crear_proveedor(app, nombre='Lenovo', nit=None, razon_social=None)

    r = admin_session.post(f'/tickets/configuracion/{proveedor_id}/editar', data={
        'nombre': 'Lenovo', 'nit': '900555111-2', 'razon_social': 'Lenovo Colombia S.A.S.'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nit, razon_social FROM ticket_configuraciones WHERE id = ?", (proveedor_id,))
    assert cur.fetchone() == ('900555111-2', 'Lenovo Colombia S.A.S.')
    conn.close()


def test_eliminar_proveedor_lo_saca_del_catalogo_activo(admin_session, app):
    proveedor_id = _crear_proveedor(app)

    admin_session.post(f'/tickets/configuracion/{proveedor_id}/eliminar')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM ticket_configuraciones WHERE id = ?", (proveedor_id,))
    assert cur.fetchone()[0] == 'eliminado'
    conn.close()


def test_configuracion_de_tickets_muestra_la_seccion_de_proveedores(admin_session, app):
    _crear_proveedor(app, nombre='Dell Colombia', nit='900123456-7')

    texto = admin_session.get('/tickets/configuracion').get_data(as_text=True)

    assert 'Proveedores' in texto
    assert 'Dell Colombia' in texto
    assert 'name="nit"' in texto
    assert 'name="razon_social"' in texto


def test_crear_activo_guarda_el_proveedor(admin_session, app):
    _crear_proveedor(app, nombre='Dell Colombia')

    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '30001', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'proveedor': 'Dell Colombia'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT proveedor FROM activos_inventario WHERE nombre = ?", ('30001',))
    assert cur.fetchone()[0] == 'Dell Colombia'
    conn.close()


def test_crear_activo_ignora_proveedor_que_no_esta_en_el_catalogo(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '30002', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'proveedor': 'Proveedor Inventado'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT proveedor FROM activos_inventario WHERE nombre = ?", ('30002',))
    assert cur.fetchone()[0] is None
    conn.close()


def test_editar_activo_actualiza_el_proveedor(admin_session, app):
    _crear_proveedor(app, nombre='HP Inc')
    activo_id = _crear_activo_directo(app, nombre='30003', proveedor=None)

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '30003', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'proveedor': 'HP Inc'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT proveedor FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'HP Inc'
    conn.close()


def test_inventario_muestra_la_columna_y_el_filtro_de_proveedor(admin_session, app):
    _crear_proveedor(app, nombre='Lenovo')
    _crear_activo_directo(app, nombre='30004', proveedor='Lenovo')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Lenovo' in texto
    assert 'name="proveedor"' in texto


def test_filtro_por_proveedor_solo_muestra_los_activos_de_ese_proveedor(admin_session, app):
    _crear_proveedor(app, nombre='Dell Colombia')
    _crear_proveedor(app, nombre='HP Inc')
    _crear_activo_directo(app, nombre='30005', proveedor='Dell Colombia')
    _crear_activo_directo(app, nombre='30006', proveedor='HP Inc')

    texto = admin_session.get('/tickets/inventario?proveedor=Dell Colombia').get_data(as_text=True)

    # Igual que con sede/área, el selector de "activo de reemplazo" siempre lista todo el
    # inventario sin filtrar por la vista actual (comportamiento existente) — la aserción
    # negativa se hace sobre la celda de la tabla, no sobre el texto completo.
    assert '>30005<' in texto
    assert '>30006<' not in texto


def test_buscador_global_encuentra_un_activo_del_inventario_por_placa(admin_session, app):
    _crear_activo_directo(app, nombre='40010', proveedor=None)

    data = admin_session.get('/buscar/api?q=40010').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Inventario de Activos' in categorias


def test_buscador_global_encuentra_un_activo_por_proveedor(admin_session, app):
    _crear_proveedor(app, nombre='Compulab Distribuciones')
    _crear_activo_directo(app, nombre='40011', proveedor='Compulab Distribuciones')

    data = admin_session.get('/buscar/api?q=compulab').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Inventario de Activos']
    assert any('40011' in t for t in titulos)


def test_estandar_no_ve_inventario_en_el_buscador_global(client, sesion_usuario, app):
    _crear_activo_directo(app, nombre='40012', proveedor=None)

    data = client.get('/buscar/api?q=40012').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Inventario de Activos' not in categorias
