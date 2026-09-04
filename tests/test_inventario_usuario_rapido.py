"""Pruebas de la alta rápida de usuario desde el modal de asignación de Inventario (Task:
'Opción de crear si no existe el usuario... al momento de asignar el usuario a un activo').
Reutiliza las mismas reglas de negocio que Gestión de Usuarios (_crear_usuario_interno) —
estas pruebas cubren sobre todo el camino nuevo: la ruta /tickets/inventario/usuarios/crear_rapido
y que el rol quede fijo en 'estandar' sin importar qué se mande."""


def _crear_especialidad(app, nombre='Auxiliar Administrativo'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO especialidades_catalogo (nombre, estado) VALUES (%s, 'activo')"
         if db_type == 'postgres' else
         "INSERT INTO especialidades_catalogo (nombre, estado) VALUES (?, 'activo')")
    cur.execute(q, (nombre,))
    conn.commit()
    conn.close()
    return nombre


def test_crear_usuario_rapido_ok(admin_session, app):
    especialidad = _crear_especialidad(app)

    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Laura', 'primer_apellido': 'Gómez',
        'email': 'laura.gomez@preventivaips.com.co', 'especialidad': especialidad,
        'cedula': '99911122',
    })

    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert 'usuario' in data and data['usuario']
    assert data['nombre'] == 'Laura Gómez'

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT rol, cedula, especialidad FROM usuarios WHERE usuario = ?", (data['usuario'],))
    fila = cur.fetchone()
    conn.close()
    assert fila == ('estandar', '99911122', especialidad)


def test_crear_usuario_rapido_ignora_rol_enviado_y_fuerza_estandar(admin_session, app):
    especialidad = _crear_especialidad(app)

    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Pedro', 'primer_apellido': 'Ruiz',
        'email': 'pedro.ruiz@preventivaips.com.co', 'especialidad': especialidad,
        'rol': 'admin',
    })

    data = r.get_json()
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT rol FROM usuarios WHERE usuario = ?", (data['usuario'],))
    assert cur.fetchone()[0] == 'estandar'
    conn.close()


def test_crear_usuario_rapido_sin_especialidad_falla(admin_session, app):
    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Sin', 'primer_apellido': 'Especialidad',
        'email': 'sinesp@preventivaips.com.co',
    })

    assert r.status_code == 400
    data = r.get_json()
    assert data['ok'] is False
    assert 'especialidad' in data['error'].lower()


def test_crear_usuario_rapido_con_cedula_duplicada_falla(admin_session, app, crear_usuario):
    especialidad = _crear_especialidad(app)
    crear_usuario(cedula='11223344')

    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Otra', 'primer_apellido': 'Persona',
        'email': 'otra@preventivaips.com.co', 'especialidad': especialidad,
        'cedula': '11223344',
    })

    assert r.status_code == 400
    assert 'cédula' in r.get_json()['error'].lower()


def test_crear_usuario_rapido_requiere_rol_operativo(sesion_usuario, app):
    especialidad = _crear_especialidad(app)

    r = sesion_usuario.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Bloqueado', 'primer_apellido': 'Estandar',
        'email': 'bloqueado@preventivaips.com.co', 'especialidad': especialidad,
    })

    # agente_o_admin_required redirige (no deja pasar) en vez de crear la cuenta.
    assert r.status_code in (302, 403)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios WHERE correo = ?", ('bloqueado@preventivaips.com.co',))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_modal_inventario_incluye_el_panel_de_crear_usuario_rapido(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'panel-crear-usuario-rapido' in texto
    assert 'crearUsuarioRapido' in texto


def test_gestion_usuarios_sigue_creando_cuentas_tras_la_refactorización(admin_session, app):
    """Regresión: _crear_usuario_interno se factorizó a partir de gestion_usuarios() — esta
    prueba confirma que el alta completa (con contraseña elegida por el admin) sigue funcionando
    exactamente igual."""
    especialidad = _crear_especialidad(app, 'Auxiliar Contable')

    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Carla', 'primer_apellido': 'Nieto',
        'email': 'carla.nieto@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'agente',
    }, follow_redirects=False)

    assert r.status_code == 302
    assert 'creado=' in r.headers['Location']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT rol, especialidad FROM usuarios WHERE correo = ?", ('carla.nieto@preventivaips.com.co',))
    assert cur.fetchone() == ('agente', especialidad)
    conn.close()
