"""Pruebas de las Especificaciones técnicas del activo (RAM/disco) — pedido por Tomás,
19/09/2026, para registrar las capacidades del PC (RAM en GB, tipo de RAM DDR3/DDR4/DDR5,
capacidad de disco en GB y tipo de disco SSD/HDD) directamente en el formulario de Nuevo/Editar
Activo de Inventario, en vez de anotarlas sueltas en Observaciones.

Todos los campos son opcionales; 'tipo_ram'/'tipo_disco' se validan contra una lista cerrada en
el backend (ver TIPOS_RAM_ACTIVO/TIPOS_DISCO_ACTIVO/_parsear_specs_tecnicas_activo en app.py) y
cualquier valor que no esté en esa lista se descarta silenciosamente (queda en NULL) en vez de
rechazar el guardado completo del activo — mismo criterio permisivo que ya usan
tipo_costo/costo_compra (ver test_inventario_costos.py)."""


def _crear_activo_directo(app, nombre='40001', ram_gb=None, tipo_ram=None, disco_gb=None, tipo_disco=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, ram_gb, tipo_ram, disco_gb, "
         "tipo_disco, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, ram_gb, tipo_ram, disco_gb, "
         "tipo_disco, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Computador de Escritorio', 'Disponible', ram_gb, tipo_ram, disco_gb,
                     tipo_disco, '2026-09-19 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_guarda_las_specs_tecnicas(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40001', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'ram_gb': '16', 'tipo_ram': 'DDR4', 'disco_gb': '512', 'tipo_disco': 'SSD',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, tipo_ram, disco_gb, tipo_disco FROM activos_inventario WHERE nombre = ?", ('40001',))
    fila = cur.fetchone()
    conn.close()
    assert fila == (16, 'DDR4', 512, 'SSD')


def test_crear_activo_sin_specs_tecnicas_queda_en_none(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40002', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, tipo_ram, disco_gb, tipo_disco FROM activos_inventario WHERE nombre = ?", ('40002',))
    assert cur.fetchone() == (None, None, None, None)
    conn.close()


def test_crear_activo_con_tipo_ram_invalido_lo_descarta(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40003', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'ram_gb': '8', 'tipo_ram': 'DDR2000-no-existe',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, tipo_ram FROM activos_inventario WHERE nombre = ?", ('40003',))
    assert cur.fetchone() == (8, None)
    conn.close()


def test_crear_activo_con_tipo_disco_invalido_lo_descarta(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40004', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'disco_gb': '256', 'tipo_disco': 'algo-raro',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT disco_gb, tipo_disco FROM activos_inventario WHERE nombre = ?", ('40004',))
    assert cur.fetchone() == (256, None)
    conn.close()


def test_crear_activo_con_ram_gb_no_numerico_queda_en_none(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40005', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'ram_gb': 'no-es-un-numero', 'tipo_ram': 'DDR4',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb FROM activos_inventario WHERE nombre = ?", ('40005',))
    assert cur.fetchone()[0] is None
    conn.close()


def test_crear_activo_con_ram_gb_negativo_o_cero_queda_en_none(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '40006', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'ram_gb': '-4', 'disco_gb': '0',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, disco_gb FROM activos_inventario WHERE nombre = ?", ('40006',))
    assert cur.fetchone() == (None, None)
    conn.close()


def test_editar_activo_actualiza_las_specs_tecnicas(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='40007', ram_gb=8, tipo_ram='DDR3', disco_gb=240, tipo_disco='SSD')

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '40007', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
        'ram_gb': '32', 'tipo_ram': 'DDR5', 'disco_gb': '1000', 'tipo_disco': 'HDD',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, tipo_ram, disco_gb, tipo_disco FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone() == (32, 'DDR5', 1000, 'HDD')
    conn.close()


def test_editar_activo_puede_borrar_las_specs_tecnicas_dejandolas_en_blanco(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='40008', ram_gb=16, tipo_ram='DDR4', disco_gb=512, tipo_disco='SSD')

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '40008', 'tipo_activo': 'Computador de Escritorio', 'estado': 'Disponible',
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT ram_gb, tipo_ram, disco_gb, tipo_disco FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone() == (None, None, None, None)
    conn.close()


def test_modal_inventario_incluye_los_campos_de_specs_tecnicas(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'name="ram_gb"' in texto
    assert 'name="tipo_ram"' in texto
    assert 'name="disco_gb"' in texto
    assert 'name="tipo_disco"' in texto
    assert 'DDR3' in texto and 'DDR4' in texto and 'DDR5' in texto
    assert 'SSD' in texto and 'HDD' in texto


def test_tabla_inventario_muestra_las_specs_tecnicas_cuando_estan_cargadas(admin_session, app):
    _crear_activo_directo(app, nombre='40009', ram_gb=16, tipo_ram='DDR4', disco_gb=512, tipo_disco='SSD')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'RAM 16GB DDR4' in texto
    assert 'SSD 512GB' in texto


def test_tabla_inventario_no_muestra_bloque_de_specs_si_no_hay_ninguna_cargada(admin_session, app):
    _crear_activo_directo(app, nombre='40010')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    # 'GB' solo aparece en el bloque de specs cuando hay ram_gb/disco_gb cargados — a diferencia
    # de 'RAM', que también aparece en el comentario HTML del formulario y daría un falso
    # positivo si se buscara esa palabra sola.
    assert 'GB' not in texto.split('40010')[1].split('</tr>')[0]


def test_editar_modal_recibe_las_specs_tecnicas_del_activo_existente(admin_session, app):
    _crear_activo_directo(app, nombre='40011', ram_gb=8, tipo_ram='DDR3', disco_gb=240, tipo_disco='SSD')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    # abrirModalEditar recibe el activo completo serializado con |tojson — las specs deben viajar
    # ahí para que el formulario de edición las precargue correctamente.
    assert '"ram_gb": 8' in texto
    assert '"tipo_ram": "DDR3"' in texto
    assert '"disco_gb": 240' in texto
    assert '"tipo_disco": "SSD"' in texto
