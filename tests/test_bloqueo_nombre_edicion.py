"""Bloqueo del campo Nombre al EDITAR un usuario ya creado (pedido de Tomás, 20/09/2026):

"Que los Administradores, a excepción del AdminMaster, no se habilite el campo de editar
nombre de ellos, que solo lo pueda cambiar el usuario admin, ojo solo cuando editan el
usuario [...] pero si a los usuarios con rol estandar u otros diferentes a Agente, Admin,
que este bloqueado y que no lo puedan cambiar ni por inspeccionar."

Resumen de la regla (ver editar_usuario en app.py, variable nombre_bloqueado):
- El Nombre de una cuenta 'agente' sigue editable por cualquier admin (sin cambios).
- El Nombre de una cuenta 'admin' (que no sea el AdminMaster) solo lo puede cambiar el
  AdminMaster -- para un admin regular, esa cuenta ya estaba totalmente bloqueada de antes
  (ver el bloqueo completo más abajo en editar_usuario), así que esto queda cubierto igual.
- El Nombre de una cuenta 'estandar' o 'gestion_humana' solo lo puede cambiar el AdminMaster
  -- ANTES cualquier admin podía cambiarlo; esta es la restricción nueva de esta prueba.
- Todo esto se exige en el backend (no solo ocultando el campo en el HTML), para que no se
  pueda saltar manipulando el formulario a mano ("por inspeccionar").
- La creación de usuarios (POST /usuarios) no se toca: al crear, el nombre sigue sin
  restricciones (ver tests/test_usuarios_permisos_agente.py y demás pruebas de creación).
"""


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


def _datos_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre, telefono FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return {'nombre': row[0], 'telefono': row[1]}


def _sesion_admin_regular(client, app, crear_usuario, usuario='admin_regular'):
    crear_usuario(usuario=usuario, rol='admin', nombre='Admin Regular')
    return _sesion_como(client, app, usuario, 'admin')


def test_admin_regular_no_puede_cambiar_nombre_de_cuenta_estandar(client, app, crear_usuario):
    _sesion_admin_regular(client, app, crear_usuario)
    objetivo = crear_usuario(rol='estandar', nombre='Nombre Original')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{objetivo}@preventivaips.com.co', 'rol': 'estandar',
        'nombre': 'Nombre Manipulado', 'telefono': '3001112233',
    }, follow_redirects=True)

    datos = _datos_de(app, objetivo)
    assert datos['nombre'] == 'Nombre Original'
    # El resto de los campos SÍ se actualiza -- el bloqueo es solo sobre Nombre.
    assert datos['telefono'] == '3001112233'


def test_admin_regular_no_puede_cambiar_nombre_de_cuenta_gestion_humana(client, app, crear_usuario):
    _sesion_admin_regular(client, app, crear_usuario, usuario='admin_regular_gh')
    objetivo = crear_usuario(rol='gestion_humana', nombre='Nombre Original GH')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{objetivo}@preventivaips.com.co', 'rol': 'gestion_humana',
        'nombre': 'Nombre Manipulado GH',
    })

    assert _datos_de(app, objetivo)['nombre'] == 'Nombre Original GH'


def test_admin_regular_no_puede_cambiar_nombre_de_otra_cuenta_admin(client, app, crear_usuario):
    """La cuenta objetivo ya con rol 'admin' (no el AdminMaster) sigue totalmente bloqueada para
    un admin regular por la protección existente -- este es un caso límite que confirma que,
    aunque llegara a tocarse esa protección algún día, el nombre nunca se actualiza."""
    _sesion_admin_regular(client, app, crear_usuario, usuario='admin_regular_vs_admin')
    otro_admin = crear_usuario(usuario='otro_admin', rol='admin', nombre='Otro Admin Original')
    objetivo_id = _id_de(app, otro_admin)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{otro_admin}@preventivaips.com.co', 'rol': 'admin',
        'nombre': 'Nombre Manipulado Admin',
    })

    assert _datos_de(app, otro_admin)['nombre'] == 'Otro Admin Original'


def test_admin_regular_si_puede_cambiar_nombre_de_cuenta_agente(client, app, crear_usuario):
    """Sin cambios: Agente queda explícitamente excluido del nuevo bloqueo."""
    _sesion_admin_regular(client, app, crear_usuario, usuario='admin_regular_agente')
    objetivo = crear_usuario(rol='agente', nombre='Nombre Original Agente')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{objetivo}@preventivaips.com.co', 'rol': 'agente',
        'nombre': 'Nombre Actualizado Agente',
    })

    assert _datos_de(app, objetivo)['nombre'] == 'Nombre Actualizado Agente'


def test_adminmaster_si_puede_cambiar_nombre_de_cuenta_estandar(client, app, crear_usuario):
    _sesion_como(client, app, 'admin', 'admin')
    objetivo = crear_usuario(rol='estandar', nombre='Nombre Original Estandar')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{objetivo}@preventivaips.com.co', 'rol': 'estandar',
        'nombre': 'Nombre Actualizado Por AdminMaster',
    })

    assert _datos_de(app, objetivo)['nombre'] == 'Nombre Actualizado Por AdminMaster'


def test_adminmaster_si_puede_cambiar_nombre_de_otra_cuenta_admin(client, app, crear_usuario):
    _sesion_como(client, app, 'admin', 'admin')
    otro_admin = crear_usuario(usuario='otro_admin2', rol='admin', nombre='Otro Admin Original 2')
    objetivo_id = _id_de(app, otro_admin)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{otro_admin}@preventivaips.com.co', 'rol': 'admin',
        'nombre': 'Nombre Actualizado Por AdminMaster 2',
    })

    assert _datos_de(app, otro_admin)['nombre'] == 'Nombre Actualizado Por AdminMaster 2'


def test_admin_regular_dejar_nombre_vacio_no_lo_borra_en_cuenta_estandar(client, app, crear_usuario):
    """Ya sin el bloqueo, dejar el campo Nombre vacío nunca debía borrar el nombre existente
    (conserva el valor previo) -- confirma que ese comportamiento de siempre sigue intacto y no
    quedó enredado con la lógica nueva de nombre_bloqueado."""
    _sesion_admin_regular(client, app, crear_usuario, usuario='admin_regular_vacio')
    objetivo = crear_usuario(rol='estandar', nombre='Nombre Que No Debe Borrarse')
    objetivo_id = _id_de(app, objetivo)

    client.post(f'/editar_usuario/{objetivo_id}', data={
        'email': f'{objetivo}@preventivaips.com.co', 'rol': 'estandar', 'nombre': '',
    })

    assert _datos_de(app, objetivo)['nombre'] == 'Nombre Que No Debe Borrarse'
