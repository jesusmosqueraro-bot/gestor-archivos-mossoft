"""Pruebas de las mejoras al módulo de Altas de Credenciales: buscar colaborador por nombre o
cédula en Gestión de Usuarios, y dar de alta varios aplicativos a la vez para el mismo
colaborador en una sola acción."""


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
