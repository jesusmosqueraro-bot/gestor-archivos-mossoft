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
    """Hallazgo QA H-08: /login está limitado a 5 peticiones POST por minuto por IP (endurecido
    desde 20, específicamente contra fuerza bruta de contraseñas)."""
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: False)  # no importa el resultado, solo contar peticiones

    codigos = [client.post('/login', data={'usuario': 'x', 'password': 'y'}).status_code for _ in range(25)]

    assert 429 in codigos


def test_ip_cliente_usa_el_ultimo_valor_de_x_forwarded_for(app):
    """🔒 Hallazgo crítico de auditoría de seguridad (12/09/2026, reportado por Tomás, confirmado
    en vivo contra arkivapp.co con fetch() desde el navegador): _obtener_ip_cliente() tomaba el
    PRIMER valor de X-Forwarded-For, que cualquier cliente puede mandar con lo que quiera (no es
    un header prohibido en fetch()/curl) — Render, al recibir la petición, AGREGA la IP real al
    FINAL de ese header en vez de reemplazarlo, así que el primer valor podía ser una IP
    inventada, distinta en cada intento. Como Flask-Limiter usa _obtener_ip_cliente() como
    key_func del límite de /login, esto anulaba por completo el límite de 5 intentos/minuto: cada
    intento con una IP falsa distinta contaba como "otro visitante". El arreglo usa el ÚLTIMO
    valor (el que agrega el único proxy de confianza delante de la app, el balanceador de
    Render) en vez del primero (que puede venir falsificado por quien hizo la petición)."""
    with app.app.test_request_context(
        '/login', headers={'X-Forwarded-For': '203.0.113.99, 198.51.100.7'}
    ):
        # 203.0.113.99: lo que un atacante podría inventarse y variar en cada intento.
        # 198.51.100.7: la IP real que Render vio en la conexión TCP y agregó al final.
        assert app._obtener_ip_cliente() == '198.51.100.7'


def test_login_sigue_limitado_aunque_se_falsifique_x_forwarded_for(client, app, monkeypatch):
    """Extremo a extremo del hallazgo de arriba: un atacante que manda un X-Forwarded-For DISTINTO
    en cada intento (para intentar que Flask-Limiter los cuente como visitantes distintos) sigue
    topándose con el límite de 5/minuto, porque la IP real (la que un proxy de confianza como
    Render agregaría al final del header) es la misma en los 8 intentos."""
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: False)

    codigos = []
    for i in range(8):
        ip_falsa_del_atacante = f'10.10.10.{i}'  # distinta en cada intento
        ip_real_segun_render = '198.51.100.42'    # la misma en los 8 (es el mismo atacante)
        r = client.post(
            '/login', data={'usuario': 'x', 'password': 'y'},
            headers={'X-Forwarded-For': f'{ip_falsa_del_atacante}, {ip_real_segun_render}'},
        )
        codigos.append(r.status_code)

    assert 429 in codigos, f"El límite debía activarse pese al X-Forwarded-For falsificado; códigos: {codigos}"


def test_codigo_de_recuperacion_es_numerico_de_seis_digitos_y_queda_en_sesion(client, app, crear_usuario, monkeypatch):
    """Hallazgo de auditoría de seguridad (06/09/2026): el código de recuperación de clave se
    generaba con `random.randint` (Mersenne Twister, no apto para nada de seguridad) en vez de
    con el módulo `secrets` (aleatoriedad criptográficamente segura) que ya se usa en el resto
    del archivo para tokens/códigos sensibles. Se corrigió a `secrets.randbelow`; esta prueba
    solo blinda que el formato y rango del código (6 dígitos, 100000-999999) sigue igual — el
    comportamiento externo del flujo de recuperación no debía cambiar."""
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)
    correo = 'colaborador.recupera@preventivaips.com.co'
    crear_usuario(usuario='colaborador_recupera', correo=correo)

    r = client.post('/recuperar', data={'email': correo, 'g-recaptcha-response': 'x'})

    assert r.status_code == 200
    with client.session_transaction() as sess:
        codigo = sess.get('reset_code')
    assert codigo is not None
    assert codigo.isdigit()
    assert len(codigo) == 6
    assert 100000 <= int(codigo) <= 999999
