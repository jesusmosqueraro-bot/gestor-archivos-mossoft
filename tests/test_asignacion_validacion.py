"""Pruebas de la validación de campos en el Formato de Asignación de Equipos (pedido de Tomás,
26/09/2026):

  1) Autocompletar de un activo YA REGISTRADO por Placa o N° de serie
     (buscar_activo_por_placa_o_serie), para reutilizar sus datos técnicos.
  2) Marca/Modelo/N° de serie pasan a ser obligatorios cuando se marca 'Generar acta de
     asignación (PDF)' — si faltan, el activo NO se guarda y se explica qué falta.
"""


def _crear_activo_directo(app, nombre='80500', marca=None, modelo=None, numero_serie=None, estado='Disponible'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', marca, modelo, numero_serie, estado, '2026-09-26 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


# ---------------------------------------------------------------------------
# 1) Autocompletar por Placa/Serie
# ---------------------------------------------------------------------------

def test_buscar_activo_encuentra_por_placa(admin_session, app):
    _crear_activo_directo(app, nombre='15099', marca='HP', modelo='ProBook', numero_serie='SNXYZ')
    r = admin_session.get('/tickets/inventario/buscar_activo?q=15099')
    assert r.status_code == 200
    data = r.get_json()
    assert len(data['resultados']) == 1
    assert data['resultados'][0]['marca'] == 'HP'
    assert data['resultados'][0]['numero_serie'] == 'SNXYZ'


def test_buscar_activo_encuentra_por_numero_de_serie(admin_session, app):
    _crear_activo_directo(app, nombre='15100', marca='Lenovo', modelo='ThinkPad', numero_serie='SN-BUSCAME')
    r = admin_session.get('/tickets/inventario/buscar_activo?q=SN-BUSCAME')
    data = r.get_json()
    assert any(a['nombre'] == '15100' for a in data['resultados'])


def test_buscar_activo_con_query_muy_corta_no_busca(admin_session, app):
    _crear_activo_directo(app, nombre='15101')
    r = admin_session.get('/tickets/inventario/buscar_activo?q=1')
    assert r.get_json()['resultados'] == []


def test_buscar_activo_requiere_permiso_de_inventario(sesion_usuario):
    r = sesion_usuario.get('/tickets/inventario/buscar_activo?q=algo')
    assert r.status_code in (302, 403)


# ---------------------------------------------------------------------------
# 2) Campos técnicos obligatorios al generar el acta
# ---------------------------------------------------------------------------

def test_crear_activo_generando_acta_sin_marca_modelo_serie_no_se_guarda(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '80501', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador X',
        'generar_acta_asignacion': 'on',
        # Sin marca/modelo/numero_serie a propósito.
    }, follow_redirects=True)
    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'Marca' in texto and 'Modelo' in texto and 'serie' in texto.lower()

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('80501',))
    assert cur.fetchone()[0] == 0  # no se guardó NADA — ni el activo ni el acta
    conn.close()


def test_crear_activo_generando_acta_con_todos_los_campos_se_guarda(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '80502', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador Y',
        'marca': 'Dell', 'modelo': 'Latitude 5420', 'numero_serie': 'SN-80502',
        'generar_acta_asignacion': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('80502',))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_crear_activo_sin_generar_acta_no_exige_marca_modelo_serie(admin_session, app):
    """Sin marcar la casilla, esos campos siguen siendo opcionales (p. ej. un activo que solo se
    registra en bodega, sin entregarse todavía a nadie)."""
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '80503', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
    }, follow_redirects=True)
    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('80503',))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_editar_activo_generando_acta_sin_serie_no_guarda_cambios(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='80504', marca='Dell', modelo='Latitude', numero_serie='SN-ORIGINAL')
    r = admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '80504', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Colaborador Z',
        'marca': 'Dell', 'modelo': 'Latitude',
        # numero_serie vacío a propósito.
        'generar_acta_asignacion': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'Número de serie' in texto

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, numero_serie FROM activos_inventario WHERE id = ?", (activo_id,))
    estado, numero_serie = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    total_actas = cur.fetchone()[0]
    conn.close()
    assert estado == 'Disponible'  # no cambió a 'Asignado': la edición completa se abortó
    assert numero_serie == 'SN-ORIGINAL'
    assert total_actas == 0
