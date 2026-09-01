"""Pruebas de las mejoras de seguridad/operación agregadas en esta ronda: cabeceras HTTP,
registro detallado de la consola SQL libre de super-admin (hallazgo QA H-04) y paginación de
la bitácora de auditoría (/logs)."""


def test_cabeceras_de_seguridad_presentes(admin_session):
    r = admin_session.get('/bienvenida')

    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert r.headers.get('X-Frame-Options') == 'SAMEORIGIN'
    csp = r.headers.get('Content-Security-Policy', '')
    assert csp  # debe existir
    assert 'res.cloudinary.com' in csp  # el visor de PDF inserta un <iframe> a Cloudinary


def test_consola_sql_registra_select_manual(admin_session, app):
    r = admin_session.post('/admin/db', data={'sql': 'SELECT usuario FROM usuarios LIMIT 1', 'tabla': 'usuarios'})

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT detalles FROM logs WHERE accion = 'Consulta SQL Manual' ORDER BY id DESC LIMIT 1")
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    assert 'SELECT usuario' in fila[0]


def test_consola_sql_registra_sentencia_con_error(admin_session, app):
    r = admin_session.post('/admin/db', data={'sql': 'SELECT columna_inexistente FROM usuarios', 'tabla': 'usuarios'})

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT detalles FROM logs WHERE accion = 'Error en SQL Manual' ORDER BY id DESC LIMIT 1")
    fila = cur.fetchone()
    conn.close()
    assert fila is not None


def test_logs_paginacion_basica(admin_session, app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    for i in range(130):
        cur.execute("INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)",
                    ("usuarioprueba", "Acción de Prueba", f"detalle {i}", f"2026-08-31 10:{i % 60:02d}:00"))
    conn.commit()
    conn.close()

    r1 = admin_session.get('/logs')
    assert r1.status_code == 200
    b1 = r1.get_data(as_text=True)
    assert 'Página 1 de' in b1

    r2 = admin_session.get('/logs?pagina=2')
    b2 = r2.get_data(as_text=True)
    assert r2.status_code == 200
    assert 'Página 2 de' in b2
    assert b1 != b2  # cada página debe mostrar filas distintas


def test_logs_paginacion_con_pagina_invalida_no_rompe(admin_session):
    assert admin_session.get('/logs?pagina=abc').status_code == 200
    assert admin_session.get('/logs?pagina=99999').status_code == 200


def test_login_respeta_limite_de_peticiones_por_minuto(client, app, monkeypatch):
    """Hallazgo QA H-08: /login está limitado a 20 peticiones POST por minuto por IP."""
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: False)  # no importa el resultado, solo contar peticiones

    codigos = [client.post('/login', data={'usuario': 'x', 'password': 'y'}).status_code for _ in range(25)]

    assert 429 in codigos
