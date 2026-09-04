"""Pruebas del campo 'Área' en el Inventario de Activos: al crear/editar un activo se debe
poder indicar en qué área quedó ubicado (Sistemas, Urgencias, Facturación, etc.), reutilizando
el mismo catálogo de Áreas que ya administra el módulo de Tickets (/tickets/configuracion),
igual que ya se hace hoy con 'sede'."""


def _crear_area(app, nombre='Sistemas'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO ticket_configuraciones (tipo, nombre, estado) VALUES (%s, %s, 'activo') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO ticket_configuraciones (tipo, nombre, estado) VALUES (?, ?, 'activo')")
    cur.execute(q, ('area', nombre))
    conn.commit()
    conn.close()
    return nombre


def _crear_activo_directo(app, nombre='15011', area=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, area, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, area, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', 'Disponible', area, '2026-09-04 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_guarda_el_area(admin_session, app):
    _crear_area(app, 'Sistemas')

    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '20001', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'area': 'Sistemas'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT area FROM activos_inventario WHERE nombre = ?", ('20001',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Sistemas'


def test_crear_activo_ignora_area_que_no_esta_en_el_catalogo(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '20002', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'area': 'Area Inventada'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT area FROM activos_inventario WHERE nombre = ?", ('20002',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] is None


def test_editar_activo_actualiza_el_area(admin_session, app):
    _crear_area(app, 'Urgencias')
    activo_id = _crear_activo_directo(app, nombre='20003', area=None)

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '20003', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'area': 'Urgencias'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT area FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Urgencias'
    conn.close()


def test_inventario_muestra_la_columna_area(admin_session, app):
    _crear_area(app, 'Facturación')
    _crear_activo_directo(app, nombre='20004', area='Facturación')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Facturación' in texto
    assert 'name="area"' in texto  # el <select> del formulario de Nuevo/Editar Activo


def test_filtro_por_area_solo_muestra_los_activos_de_esa_area(admin_session, app):
    _crear_area(app, 'Sistemas')
    _crear_area(app, 'Urgencias')
    _crear_activo_directo(app, nombre='20005', area='Sistemas')
    _crear_activo_directo(app, nombre='20006', area='Urgencias')

    texto = admin_session.get('/tickets/inventario?area=Sistemas').get_data(as_text=True)

    # Nota: '20006' de todas formas aparece en el JSON embebido de "candidatos para reemplazo"
    # (ese selector siempre lista TODO el inventario, sin filtrar por la vista actual — es
    # comportamiento existente, no algo que dependa del filtro de área), así que la aserción
    # negativa se hace sobre la celda de la tabla (">20006<"), no sobre el texto completo.
    assert '>20005<' in texto
    assert '>20006<' not in texto


def test_reemplazar_activo_hereda_el_area_del_activo_saliente(admin_session, app):
    _crear_area(app, 'Sistemas')
    saliente_id = _crear_activo_directo(app, nombre='20007', area='Sistemas')
    entrante_id = _crear_activo_directo(app, nombre='20008', area=None)

    r = admin_session.post(f'/tickets/inventario/{saliente_id}/reemplazar', data={
        'motivo': 'Equipo dañado', 'activo_nuevo_id': str(entrante_id),
        'fecha_reemplazo': '2026-09-04', 'estado_anterior_resultante': 'Baja'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT area FROM activos_inventario WHERE id = ?", (entrante_id,))
    assert cur.fetchone()[0] == 'Sistemas'
    conn.close()
