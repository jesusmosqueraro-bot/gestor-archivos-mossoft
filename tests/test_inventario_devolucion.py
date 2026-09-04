"""Pruebas del estado 'Devolución' del Inventario de Activos, pedido por Tomás: un activo puede
entrar a este estado (a mano desde Editar Activo, o automáticamente al certificar su devolución
en /inventario/<id>/confirmar_devolucion — ver test_certificacion_devoluciones.py) y al hacerlo:
  1) se registra la fecha en que entró ('fecha_devolucion'),
  2) queda sin forma de asociarse a otro usuario ('asignado_a' se limpia siempre),
  3) queda BLOQUEADO: mientras el estado siga siendo 'Devolución', ni editar_activo ni
     reemplazar_activo aceptan cambios de nadie que no sea 'admin' — solo un administrador puede
     "desbloquearlo" (editar el activo y elegirle su siguiente estado real)."""
import io

import openpyxl


def _sesion_agente(client, app, usuario='agente_inventario'):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _crear_activo_directo(app, nombre='30001', estado='Asignado', asignado_a='Juan Pérez'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, '2026-09-01 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _libro_xlsx(filas):
    import app as arkiv
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(arkiv.COLUMNAS_INVENTARIO_XLSX)
    for fila in filas:
        ws.append(fila)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def test_editar_activo_a_devolucion_registra_fecha_y_libera_asignado(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='30001', estado='Asignado', asignado_a='Juan Pérez')

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '30001', 'tipo_activo': 'Portátil', 'estado': 'Devolución', 'asignado_a': 'Juan Pérez'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE id = ?", (activo_id,))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    conn.close()
    assert estado == 'Devolución'
    # 🔒 "que no tenga forma de asociar a otro usuario": aunque el formulario mandó 'asignado_a',
    # el servidor lo ignora por completo cuando el estado que se guarda es 'Devolución'.
    assert asignado_a is None
    assert fecha_devolucion  # se registró la fecha


def test_agente_puede_marcar_un_activo_en_devolucion(client, app):
    _sesion_agente(client, app)
    activo_id = _crear_activo_directo(app, nombre='30002')

    r = client.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '30002', 'tipo_activo': 'Portátil', 'estado': 'Devolución'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Devolución'
    conn.close()


def test_agente_no_puede_editar_un_activo_ya_bloqueado_en_devolucion(client, app):
    _sesion_agente(client, app)
    activo_id = _crear_activo_directo(app, nombre='30003', estado='Devolución', asignado_a=None)

    r = client.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '30003', 'tipo_activo': 'Portátil', 'estado': 'Disponible', 'area': 'Sistemas'
    }, follow_redirects=True)

    assert r.status_code == 200
    assert "Solo un administrador puede desbloquearlo" in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Devolución'  # sigue bloqueado, no cambió nada
    conn.close()


def test_admin_si_puede_desbloquear_un_activo_en_devolucion(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='30004', estado='Devolución', asignado_a=None)

    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '30004', 'tipo_activo': 'Portátil', 'estado': 'Disponible'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Disponible'
    conn.close()


def test_agente_no_puede_reemplazar_un_activo_bloqueado_en_devolucion(client, app):
    _sesion_agente(client, app)
    activo_id = _crear_activo_directo(app, nombre='30005', estado='Devolución', asignado_a=None)

    r = client.post(f'/tickets/inventario/{activo_id}/reemplazar', data={
        'motivo': 'Fin de vida útil', 'fecha_reemplazo': '2026-09-04', 'estado_anterior_resultante': 'Baja'
    }, follow_redirects=True)

    assert r.status_code == 200
    assert "Solo un administrador puede desbloquearlo" in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Devolución'
    conn.close()


def test_admin_si_puede_reemplazar_un_activo_en_devolucion(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='30006', estado='Devolución', asignado_a=None)

    r = admin_session.post(f'/tickets/inventario/{activo_id}/reemplazar', data={
        'motivo': 'Fin de vida útil', 'fecha_reemplazo': '2026-09-04', 'estado_anterior_resultante': 'Baja'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    assert cur.fetchone()[0] == 'Baja'
    conn.close()


def test_agente_no_puede_usar_un_activo_en_devolucion_como_reemplazo_de_otro(client, app):
    """Bloqueo del 'lado de entrada': un agente no puede desbloquear por la puerta de atrás un
    activo en 'Devolución' escogiéndolo como el activo de reemplazo de OTRO activo cualquiera
    (eso también lo reasignaría y le cambiaría el estado, sin pasar por editar_activo)."""
    _sesion_agente(client, app)
    saliente_id = _crear_activo_directo(app, nombre='30007', estado='Asignado', asignado_a='Ana Ruiz')
    bloqueado_id = _crear_activo_directo(app, nombre='30008', estado='Devolución', asignado_a=None)

    r = client.post(f'/tickets/inventario/{saliente_id}/reemplazar', data={
        'motivo': 'Renovación', 'activo_nuevo_id': str(bloqueado_id),
        'fecha_reemplazo': '2026-09-04', 'estado_anterior_resultante': 'Baja'
    }, follow_redirects=True)

    assert r.status_code == 200
    assert "Solo un administrador puede desbloquearlo" in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a FROM activos_inventario WHERE id = ?", (bloqueado_id,))
    estado, asignado_a = cur.fetchone()
    assert estado == 'Devolución'
    assert asignado_a is None
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (saliente_id,))
    assert cur.fetchone()[0] == 'Asignado'  # tampoco se completó el reemplazo del saliente
    conn.close()


def test_admin_si_puede_usar_un_activo_en_devolucion_como_reemplazo_de_otro(admin_session, app):
    saliente_id = _crear_activo_directo(app, nombre='30009', estado='Asignado', asignado_a='Ana Ruiz')
    bloqueado_id = _crear_activo_directo(app, nombre='30010', estado='Devolución', asignado_a=None)

    r = admin_session.post(f'/tickets/inventario/{saliente_id}/reemplazar', data={
        'motivo': 'Renovación', 'activo_nuevo_id': str(bloqueado_id),
        'fecha_reemplazo': '2026-09-04', 'estado_anterior_resultante': 'Baja'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a FROM activos_inventario WHERE id = ?", (bloqueado_id,))
    estado, asignado_a = cur.fetchone()
    conn.close()
    assert estado == 'Asignado'  # heredó el responsable del saliente, como cualquier reemplazo
    assert asignado_a == 'Ana Ruiz'


def test_crear_activo_en_devolucion_no_permite_asignado_a(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '30011', 'tipo_activo': 'Portátil', 'estado': 'Devolución', 'asignado_a': 'Alguien'
    })

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE nombre = ?", ('30011',))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    conn.close()
    assert estado == 'Devolución'
    assert asignado_a is None
    assert fecha_devolucion


def test_carga_masiva_en_devolucion_no_permite_asignado_a(admin_session, app):
    buffer = _libro_xlsx([
        ['30012', 'Portátil', 'Dell', 'Latitude', 'SN-9', 'Devolución', 'Alguien', '', '', '', '', '', '', ''],
    ])

    r = admin_session.post('/tickets/inventario/importar_xlsx', data={
        'archivo': (buffer, 'inventario.xlsx')
    }, content_type='multipart/form-data')

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, asignado_a, fecha_devolucion FROM activos_inventario WHERE nombre = ?", ('30012',))
    estado, asignado_a, fecha_devolucion = cur.fetchone()
    conn.close()
    assert estado == 'Devolución'
    assert asignado_a is None
    assert fecha_devolucion


def test_inventario_muestra_el_badge_devolucion_con_su_fecha(admin_session, app):
    _crear_activo_directo(app, nombre='30013', estado='Devolución', asignado_a=None)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE activos_inventario SET fecha_devolucion = ? WHERE nombre = ?", ('2026-09-04 10:00:00', '30013'))
    conn.commit()
    conn.close()

    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Devolución' in texto
    assert '2026-09-04 10:00:00' in texto


def test_inventario_muestra_candado_en_vez_de_editar_para_agente_en_fila_bloqueada(client, app):
    _sesion_agente(client, app)
    _crear_activo_directo(app, nombre='30014', estado='Devolución', asignado_a=None)

    texto = client.get('/tickets/inventario').get_data(as_text=True)

    assert 'bloqueado en' in texto.lower() or "solo un administrador puede desbloquearlo" in texto.lower()
