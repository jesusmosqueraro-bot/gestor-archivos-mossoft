"""Pruebas de las mejoras al módulo de Altas de Credenciales: buscar colaborador por nombre o
cédula en Gestión de Usuarios, dar de alta varios aplicativos a la vez para el mismo colaborador
en una sola acción, y editar/eliminar permanentemente una fila existente."""


def _crear_credencial_colaborador(app, colaborador='Empleado Editable', aplicativo='KUBAPP', password='ClaveInicial1', usuario_aplicativo=None):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO credenciales_colaboradores (colaborador, aplicativo, usuario_aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (%s, %s, %s, %s, '2026-01-01', 'activo', '2026-01-01 09:00:00', 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO credenciales_colaboradores (colaborador, aplicativo, usuario_aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (?, ?, ?, ?, '2026-01-01', 'activo', '2026-01-01 09:00:00', 'admin')")
    cur.execute(q, (colaborador, aplicativo, usuario_aplicativo, app.encriptar_texto(password)))
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


# --- Usuario/ID propio de cada aplicativo (pedido por Tomás, 08/09/2026) ---

def test_alta_credencial_guarda_un_usuario_distinto_por_cada_aplicativo(admin_session, app):
    """Cada aplicativo tiene su propia forma de identificar a la persona (cédula en SAMI, un
    correo en Correo...) — a diferencia de la contraseña (compartida entre todos los
    aplicativos marcados), el campo 'usuario_aplicativo__<nombre>' es independiente por
    aplicativo."""
    admin_session.post('/credenciales/colaboradores/crear', data={
        'colaborador': 'Empleado Multi Aplicativo',
        'aplicativos': ['KUBAPP', 'SAMI', 'Correo'],
        'usuario_aplicativo__KUBAPP': '102576169',
        'usuario_aplicativo__SAMI': '1025761690',
        'usuario_aplicativo__Correo': 'empleado.multi@preventivaips.com.co',
        'password': 'Clave123',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT aplicativo, usuario_aplicativo FROM credenciales_colaboradores WHERE colaborador = ? ORDER BY aplicativo ASC",
        ('Empleado Multi Aplicativo',)
    )
    filas = dict(cur.fetchall())
    conn.close()
    assert filas == {
        'Correo': 'empleado.multi@preventivaips.com.co',
        'KUBAPP': '102576169',
        'SAMI': '1025761690',
    }


def test_alta_credencial_usuario_aplicativo_es_opcional(admin_session, app):
    """No siempre se conoce (o aplica) un usuario/ID propio distinto para un aplicativo — el
    campo puede quedar en blanco sin que eso bloquee el alta (a diferencia de la casilla 'Otro'
    del checklist de accesorios en Inventario, que sí es obligatoria cuando se marca)."""
    admin_session.post('/credenciales/colaboradores/crear', data={
        'colaborador': 'Empleado Sin Usuario Puntual',
        'aplicativos': ['Moodle'],
        'password': 'Clave123',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT usuario_aplicativo FROM credenciales_colaboradores WHERE colaborador = ?",
        ('Empleado Sin Usuario Puntual',)
    )
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    assert fila[0] is None


def test_editar_credencial_actualiza_el_usuario_aplicativo(admin_session, app):
    reg_id = _crear_credencial_colaborador(app, usuario_aplicativo='id-viejo')

    admin_session.post(f'/credenciales/colaboradores/{reg_id}/editar', data={
        'colaborador': 'Empleado Editable',
        'aplicativo': 'KUBAPP',
        'usuario_aplicativo': 'id-nuevo-123',
        'password': '',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT usuario_aplicativo FROM credenciales_colaboradores WHERE id = ?", (reg_id,))
    usuario_aplicativo = cur.fetchone()[0]
    conn.close()
    assert usuario_aplicativo == 'id-nuevo-123'


def test_pagina_de_credenciales_muestra_el_usuario_de_cada_aplicativo(admin_session, app):
    _crear_credencial_colaborador(app, colaborador='Empleado Visible', usuario_aplicativo='visible-id-42')

    texto = admin_session.get('/credenciales/colaboradores').get_data(as_text=True)

    assert 'visible-id-42' in texto


# --- Contraseña puntual por aplicativo (pedido por Tomás, 08/09/2026) ---

def test_alta_credencial_usa_la_contrasena_puntual_cuando_se_diligencia(admin_session, app):
    """Por defecto todos los aplicativos marcados comparten la 'Contraseña asignada' — pero si
    un aplicativo puntual trae su propio campo 'password_aplicativo__<nombre>' diligenciado, esa
    fila debe guardar ESA contraseña en vez de la compartida."""
    admin_session.post('/credenciales/colaboradores/crear', data={
        'colaborador': 'Empleado Contraseñas Mixtas',
        'aplicativos': ['KUBAPP', 'Moodle'],
        'password_aplicativo__KUBAPP': 'ClavePuntualKubapp1',
        'password': 'ClaveCompartida1',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT aplicativo, password_cifrada FROM credenciales_colaboradores WHERE colaborador = ? ORDER BY aplicativo ASC",
        ('Empleado Contraseñas Mixtas',)
    )
    filas = {ap: app.desencriptar_texto(pw) for ap, pw in cur.fetchall()}
    conn.close()
    assert filas == {
        'KUBAPP': 'ClavePuntualKubapp1',
        'Moodle': 'ClaveCompartida1',
    }


# --- Filtro y autocompletar por PQRS (pedido por Tomás, 08/09/2026) ---

def test_filtro_por_pqrs_muestra_solo_los_registros_de_ese_pqrs(admin_session, app):
    """Ojo: 'colaboradores_existentes' (para el autocompletar del modal 'Nueva Alta') lista TODOS
    los colaboradores sin importar el filtro activo — por eso la prueba busca el patrón exacto de
    una FILA de la tabla (">Nombre<"), no solo si el nombre aparece en algún lugar de la página
    (podría aparecer igual dentro del <datalist>)."""
    _crear_credencial_colaborador(app, colaborador='Empleado PQRS Uno')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE credenciales_colaboradores SET solicitado_por = ? WHERE colaborador = ?", ('00001', 'Empleado PQRS Uno'))
    conn.commit()
    conn.close()
    _crear_credencial_colaborador(app, colaborador='Empleado PQRS Dos', aplicativo='Moodle')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE credenciales_colaboradores SET solicitado_por = ? WHERE colaborador = ?", ('00002', 'Empleado PQRS Dos'))
    conn.commit()
    conn.close()

    texto = admin_session.get('/credenciales/colaboradores?pqrs=00001&estado=todos').get_data(as_text=True)

    assert '>Empleado PQRS Uno<' in texto
    assert '>Empleado PQRS Dos<' not in texto


def test_pagina_de_credenciales_sugiere_los_pqrs_ya_usados(admin_session, app):
    _crear_credencial_colaborador(app, colaborador='Empleado PQRS Autocompletar')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE credenciales_colaboradores SET solicitado_por = ? WHERE colaborador = ?", ('00099', 'Empleado PQRS Autocompletar'))
    conn.commit()
    conn.close()

    texto = admin_session.get('/credenciales/colaboradores').get_data(as_text=True)

    assert 'lista_pqrs' in texto
    assert '00099' in texto


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
