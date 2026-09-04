"""Pruebas de las mejoras al módulo de Altas de Credenciales: buscar colaborador por nombre o
cédula en Gestión de Usuarios, dar de alta varios aplicativos a la vez para el mismo colaborador
en una sola acción, y editar/eliminar permanentemente una fila existente."""


def _crear_credencial_colaborador(app, colaborador='Empleado Editable', aplicativo='KUBAPP', password='ClaveInicial1'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO credenciales_colaboradores (colaborador, aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (%s, %s, %s, '2026-01-01', 'activo', '2026-01-01 09:00:00', 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO credenciales_colaboradores (colaborador, aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (?, ?, ?, '2026-01-01', 'activo', '2026-01-01 09:00:00', 'admin')")
    cur.execute(q, (colaborador, aplicativo, app.encriptar_texto(password)))
    reg_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return reg_id


def test_buscar_usuarios_encuentra_por_nombre_parcial(admin_session, crear_usuario):
    crear_usuario(nombre='Ana María Rodríguez', cedula='1020304050')

    r = admin_session.get('/usuarios/buscar?q=ana mar')

    assert r.status_code == 200
    data = r.get_json()
    nombres = [u['nombre'] for u in data['resultados']]
    assert 'Ana María Rodríguez' in nombres


def test_buscar_usuarios_encuentra_por_cedula(admin_session, crear_usuario):
    crear_usuario(nombre='Carlos Pérez', cedula='99887766')

    r = admin_session.get('/usuarios/buscar?q=99887766')

    data = r.get_json()
    assert any(u['cedula'] == '99887766' for u in data['resultados'])


def test_buscar_usuarios_con_query_muy_corto_no_busca(admin_session, crear_usuario):
    crear_usuario(nombre='Alguien')

    r = admin_session.get('/usuarios/buscar?q=a')

    assert r.get_json()['resultados'] == []


def test_alta_credencial_crea_un_registro_por_aplicativo_seleccionado(admin_session, app):
    r = admin_session.post('/credenciales/colaboradores/crear', data={
        'colaborador': 'Empleado de Prueba',
        'aplicativos': ['KUBAPP', 'Moodle', 'SAMI'],
        'password': 'Clave123',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT aplicativo FROM credenciales_colaboradores WHERE colaborador = ? ORDER BY aplicativo ASC", ('Empleado de Prueba',))
    aplicativos = [f[0] for f in cur.fetchall()]
    conn.close()
    assert aplicativos == ['KUBAPP', 'Moodle', 'SAMI']


def test_alta_credencial_sin_aplicativos_no_crea_nada(admin_session, app):
    admin_session.post('/credenciales/colaboradores/crear', data={
        'colaborador': 'Sin Aplicativo',
        'password': 'Clave123',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales_colaboradores WHERE colaborador = ?", ('Sin Aplicativo',))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 0


# --- Editar (Task #126: EDITAR y ELIMINAR en Altas de Credenciales) ---

def test_editar_credencial_actualiza_los_datos(admin_session, app):
    reg_id = _crear_credencial_colaborador(app)

    r = admin_session.post(f'/credenciales/colaboradores/{reg_id}/editar', data={
        'colaborador': 'Empleado Editado',
        'aplicativo': 'Moodle',
        'password': '',
        'solicitado_por': 'Jefe de Área',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT colaborador, aplicativo, solicitado_por FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila == ('Empleado Editado', 'Moodle', 'Jefe de Área')


def test_editar_credencial_sin_password_no_cambia_la_clave_actual(admin_session, app):
    reg_id = _crear_credencial_colaborador(app, password='ClaveOriginal1')

    admin_session.post(f'/credenciales/colaboradores/{reg_id}/editar', data={
        'colaborador': 'Empleado Editable',
        'aplicativo': 'KUBAPP',
        'password': '',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_cifrada FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    pass_cifrada = cur.fetchone()[0]
    conn.close()
    assert app.desencriptar_texto(pass_cifrada) == 'ClaveOriginal1'


def test_editar_credencial_con_password_nueva_si_la_cambia(admin_session, app):
    reg_id = _crear_credencial_colaborador(app, password='ClaveOriginal1')

    admin_session.post(f'/credenciales/colaboradores/{reg_id}/editar', data={
        'colaborador': 'Empleado Editable',
        'aplicativo': 'KUBAPP',
        'password': 'ClaveNueva2',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_cifrada FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    pass_cifrada = cur.fetchone()[0]
    conn.close()
    assert app.desencriptar_texto(pass_cifrada) == 'ClaveNueva2'


def test_editar_credencial_requiere_rol_operativo(sesion_usuario, app):
    reg_id = _crear_credencial_colaborador(app)

    sesion_usuario.post(f'/credenciales/colaboradores/{reg_id}/editar', data={
        'colaborador': 'Intento No Autorizado', 'aplicativo': 'KUBAPP', 'password': '',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT colaborador FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    colaborador = cur.fetchone()[0]
    conn.close()
    assert colaborador == 'Empleado Editable'


# --- Eliminar permanentemente ---

def test_eliminar_credencial_borra_el_registro(admin_session, app):
    reg_id = _crear_credencial_colaborador(app)

    r = admin_session.post(f'/credenciales/colaboradores/{reg_id}/eliminar', follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 0


def test_eliminar_credencial_requiere_rol_operativo(sesion_usuario, app):
    reg_id = _crear_credencial_colaborador(app)

    sesion_usuario.post(f'/credenciales/colaboradores/{reg_id}/eliminar')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 1
