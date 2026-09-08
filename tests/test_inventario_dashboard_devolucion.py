"""Pruebas del panel de indicadores de /tickets/inventario para el estado 'Devolución'.

Contexto (pedido de Tomás, 08/09/2026): un activo queda en estado 'Devolución' cuando su
devolución fue certificada pero aún no la revisa un admin (ver confirmar_devolucion_activo /
editar_activo — el "🔒 candado" que se ve en la tabla de activos). El backend de
ver_inventario() ya calculaba conteos_estado['Devolución'] y, por sede, estados['Devolución']
correctamente, pero la plantilla nunca los mostraba: ni en las tarjetas de conteo, ni en el
donut 'Por estado', ni en la tabla de Distribución por sede — todos quedaban en 0 aunque hubiera
activos reales en ese estado. Esta prueba cubre que ahora sí aparecen."""


def _crear_activo_en_devolucion(app, nombre='90001', sede='Sede Principal'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, sede, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, sede, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', 'Devolución', sede, '2026-09-08 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_tarjeta_de_devolucion_muestra_el_conteo_correcto(admin_session, app):
    _crear_activo_en_devolucion(app, nombre='90001')
    _crear_activo_en_devolucion(app, nombre='90002')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Devolución' in texto
    # La tarjeta nueva debe mostrar el conteo real (2), no quedarse en 0 como antes del arreglo.
    assert '>2<' in texto.replace('\n', '').replace(' ', '')


def test_donut_por_estado_incluye_devolucion_en_su_data(admin_session, app):
    _crear_activo_en_devolucion(app, nombre='90003')

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert "'Devolución'" in texto  # ahora presente en el arreglo de labels del donut
    assert '#a78bfa' in texto       # color violeta asignado a esta serie, ya usado en el badge de la tabla


def test_distribucion_por_sede_incluye_columna_de_devolucion(admin_session, app):
    _crear_activo_en_devolucion(app, nombre='90004', sede='Sede Norte')
    # Segunda sede para que la tabla de distribución (solo se muestra con >1 sede) se renderice.
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, sede, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s)" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, sede, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, ('90005', 'Portátil', 'Disponible', 'Sede Sur', '2026-09-08 09:00:00', 'admin'))
    conn.commit()
    conn.close()

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Sede Norte' in texto
    assert 'Sede Sur' in texto
    # La columna 'Devolución' de la tabla de distribución por sede ahora existe.
    idx_tabla = texto.find('Distribución por sede')
    assert idx_tabla != -1
    assert 'Devolución' in texto[idx_tabla:]


def test_conteos_estado_incluye_devolucion_cuando_no_hay_activos_en_ese_estado(admin_session, app):
    """Caso base: sin ningún activo en 'Devolución', la tarjeta debe mostrar 0 en vez de que la
    plantilla reviente por acceder a una clave que antes no se leía nunca (conteos_estado siempre
    trae la clave 'Devolución' desde el backend, esto solo confirma que la plantilla no falla)."""
    r = admin_session.get('/tickets/inventario')

    assert r.status_code == 200
    assert 'Devolución' in r.get_data(as_text=True)
