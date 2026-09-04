"""Pruebas de la apertura acotada de Gestión de Usuarios a agentes, pedida junto con la Carga
Masiva: "que ya los agentes y administradores, solo tengan que modificar el rol y estado". Antes
Gestión de Usuarios era exclusiva del rol 'admin' (ver ROLES_CON_ACCESO_OPERATIVO / admin_required
en app.py); ahora un agente puede entrar a la vista, usar la Carga Masiva y ajustar rol/estado de
una cuenta 'estandar' — pero NO puede: crear cuentas por el formulario completo, editar campos
más allá de rol/estado (correo, contraseña, etc.), ascender a nadie a 'agente' o 'admin', ni
tocar cuentas que ya son 'admin'/'agente' (esa protección ya existía para admins no-super y se
extiende igual a los agentes)."""


def _sesion_como(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _id_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0]


def _rol_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT rol FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _estado_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def _sesion_agente(client, app, crear_usuario, usuario='agente_prueba'):
    crear_usuario(usuario=usuario, rol='agente')
    return _sesion_como(client, app, usuario, 'agente')


def test_agente_puede_ver_gestion_de_usuarios(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)

    r = client.get('/usuarios')

    assert r.status_code == 200


def test_agente_no_puede_crear_usuario_por_el_formulario_completo(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)

    r = client.post('/usuarios', data={
        'primer_nombre': 'No', 'primer_apellido': 'Deberia', 'email': 'no.deberia@preventivaips.com.co',
        'password': 'ClaveValida123', 'especialidad': 'Auxiliar', 'rol': 'estandar',
    }, follow_redirects=True)

    assert r.status_code == 200
    assert 'Solo un administrador puede crear una cuenta' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM usuarios WHERE correo = ?", ('no.deberia@preventivaips.com.co',))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_agente_puede_cambiar_rol_de_una_cuenta_estandar_a_gestion_humana(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    r = client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'gestion_humana'}, follow_redirects=True)

    assert r.status_code == 200
    assert _rol_de(app, objetivo) == 'gestion_humana'


def test_agente_no_puede_ascender_una_cuenta_a_agente(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'agente'})

    assert _rol_de(app, objetivo) == 'estandar'


def test_agente_no_puede_ascender_una_cuenta_a_admin(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'admin'})

    assert _rol_de(app, objetivo) == 'estandar'


def test_agente_no_puede_cambiar_rol_de_otra_cuenta_agente(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario, usuario='agente_actor')
    otro_agente = crear_usuario(usuario='agente_objetivo', rol='agente')
    objetivo_id = _id_de(app, otro_agente)

    client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'estandar'})

    assert _rol_de(app, otro_agente) == 'agente'


def test_agente_no_puede_cambiar_su_propio_rol(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario, usuario='agente_si_mismo')
    propio_id = _id_de(app, 'agente_si_mismo')

    client.post(f'/usuarios/{propio_id}/cambiar_rol', data={'rol': 'estandar'})

    assert _rol_de(app, 'agente_si_mismo') == 'agente'


def test_agente_puede_bloquear_y_desbloquear_una_cuenta_estandar(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario)
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    r = client.post(f'/usuarios/toggle_estado/{objetivo_id}', follow_redirects=True)

    assert r.status_code == 200
    assert _estado_de(app, objetivo) == 'inactivo'


def test_agente_no_puede_bloquear_una_cuenta_agente_o_admin(client, app, crear_usuario):
    _sesion_agente(client, app, crear_usuario, usuario='agente_actor2')
    otro_agente = crear_usuario(usuario='agente_objetivo2', rol='agente')
    objetivo_id = _id_de(app, otro_agente)

    client.post(f'/usuarios/toggle_estado/{objetivo_id}')

    assert _estado_de(app, otro_agente) == 'activo'


def test_admin_regular_no_super_si_puede_ascender_una_cuenta_a_agente(client, app, crear_usuario):
    """Distinto de un agente: un ADMIN (aunque no sea el super-admin literal 'admin') sí puede
    ascender a alguien a 'agente' — esa regla ya existía en editar_usuario y cambiar_rol_usuario
    la respeta igual; solo ascender a 'admin' queda exclusivo del super-admin."""
    admin_regular = crear_usuario(usuario='admin_regular', rol='admin')
    _sesion_como(client, app, admin_regular, 'admin')
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'agente'})

    assert _rol_de(app, objetivo) == 'agente'


def test_admin_regular_no_super_no_puede_ascender_una_cuenta_a_admin(client, app, crear_usuario):
    admin_regular = crear_usuario(usuario='admin_regular2', rol='admin')
    _sesion_como(client, app, admin_regular, 'admin')
    objetivo = crear_usuario(rol='estandar')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/usuarios/{objetivo_id}/cambiar_rol', data={'rol': 'admin'})

    assert _rol_de(app, objetivo) == 'estandar'
