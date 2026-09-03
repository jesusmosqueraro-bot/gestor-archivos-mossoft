"""Pruebas de las mejoras a las lecturas de Novedades y Comunicados: que el modal de "Ver
lecturas" incluya la cédula de quien leyó, y que se puedan exportar a CSV."""


def _crear_comunicado(app, titulo="Aviso de prueba"):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO comunicados (titulo, contenido, fecha, autor) VALUES (%s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO comunicados (titulo, contenido, fecha, autor) VALUES (?, ?, ?, ?)")
    cur.execute(q, (titulo, '<p>Contenido del aviso</p>', '2026-08-31 09:00:00', 'admin'))
    com_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return com_id


def test_lecturas_incluye_cedula_de_quien_leyo(client, app, crear_usuario):
    com_id = _crear_comunicado(app)
    lector = crear_usuario(nombre='Lector de Prueba', cedula='777888999')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = lector
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    client.get('/comunicados')  # visitar el muro marca el comunicado como leído

    with client.session_transaction() as sess:
        sess['username'] = 'admin'
        sess['rol'] = 'admin'
    r = client.get(f'/comunicados/{com_id}/lecturas')

    data = r.get_json()
    fila = next(u for u in data['leyeron'] if u['usuario'] == lector)
    assert fila['cedula'] == '777888999'


def test_exportar_lecturas_devuelve_csv(admin_session, app):
    com_id = _crear_comunicado(app)
    admin_session.get('/comunicados')  # admin también marca lectura al visitar el muro

    r = admin_session.get(f'/comunicados/{com_id}/lecturas/exportar_csv')

    assert r.status_code == 200
    assert 'text/csv' in r.headers.get('Content-Type', '')
    texto = r.get_data(as_text=True)
    assert 'NOMBRE' in texto and 'DOCUMENTO' in texto
