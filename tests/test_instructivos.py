"""Pruebas de la nueva bitácora de vistas del Gestor de Instructivos: quién vio un instructivo,
con nombre/cédula/fecha, y que se pueda exportar."""


def _crear_galeria(app, galeria_id='instructivo-prueba'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO galerias (id, titulo, descripcion, fecha_subida, estado) VALUES (%s, %s, %s, %s, 'activo')"
         if db_type == 'postgres' else
         "INSERT INTO galerias (id, titulo, descripcion, fecha_subida, estado) VALUES (?, ?, ?, ?, 'activo')")
    cur.execute(q, (galeria_id, 'Unificar Historia Clínica', 'Proceso de unificación', '2026-08-25 15:27:23'))
    conn.commit()
    conn.close()
    return galeria_id


def test_incrementar_vista_registra_quien_vio(admin_session, app):
    galeria_id = _crear_galeria(app)

    admin_session.post(f'/incrementar_vista/{galeria_id}')

    r = admin_session.get(f'/galerias/{galeria_id}/vistas')
    data = r.get_json()
    assert len(data['vistas']) == 1
    assert data['vistas'][0]['usuario'] == 'admin'
    assert data['vistas'][0]['fecha']


def test_incrementar_vista_repetida_no_duplica_al_mismo_usuario(admin_session, app):
    galeria_id = _crear_galeria(app, 'instructivo-repetido')

    admin_session.post(f'/incrementar_vista/{galeria_id}')
    admin_session.post(f'/incrementar_vista/{galeria_id}')
    admin_session.post(f'/incrementar_vista/{galeria_id}')

    r = admin_session.get(f'/galerias/{galeria_id}/vistas')
    assert len(r.get_json()['vistas']) == 1

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT vistas FROM galerias WHERE id = ?", (galeria_id,))
    total_vistas = cur.fetchone()[0]
    conn.close()
    assert total_vistas == 3  # el contador total SÍ sigue sumando cada vista


def test_vistas_de_dos_usuarios_distintos_quedan_ambas(client, app, crear_usuario):
    galeria_id = _crear_galeria(app, 'instructivo-dos-usuarios')
    agente = crear_usuario(rol='agente', nombre='Agente Vistas', cedula='555111')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = agente
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    client.post(f'/incrementar_vista/{galeria_id}')

    with client.session_transaction() as sess:
        sess['username'] = 'admin'
        sess['rol'] = 'admin'
    client.post(f'/incrementar_vista/{galeria_id}')

    r = client.get(f'/galerias/{galeria_id}/vistas')
    data = r.get_json()
    assert len(data['vistas']) == 2
    fila_agente = next(v for v in data['vistas'] if v['usuario'] == agente)
    assert fila_agente['cedula'] == '555111'


def test_exportar_vistas_devuelve_csv(admin_session, app):
    galeria_id = _crear_galeria(app, 'instructivo-exportar')
    admin_session.post(f'/incrementar_vista/{galeria_id}')

    r = admin_session.get(f'/galerias/{galeria_id}/vistas/exportar_csv')

    assert r.status_code == 200
    assert 'text/csv' in r.headers.get('Content-Type', '')
    texto = r.get_data(as_text=True)
    assert 'NOMBRE' in texto and 'DOCUMENTO' in texto
    assert 'admin' in texto
