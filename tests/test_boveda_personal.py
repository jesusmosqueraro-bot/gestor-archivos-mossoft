"""Pruebas de 'Mi Bóveda Personal' (pedido por Tomás): cada usuario —sin importar su rol— tiene
su propio espacio cifrado de contraseñas/notas, separado de la Bóveda de Accesos institucional
del equipo (esa sigue siendo /credenciales, exclusiva de admin/agente). Reutiliza la MISMA
tabla 'credenciales' con visibilidad='personal' (ver _puede_ver_credencial_item /
_puede_gestionar_credencial_item en app.py), así que estas pruebas también cubren que un
usuario no pueda ver ni gestionar la entrada personal de otro, y que un admin sí conserve
acceso de auditoría."""


def _crear_entrada_personal(app, propietario, servicio='Correo Personal', usuario='yo@correo.com', password='ClaveInicial1'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (%s, '', %s, %s, 'Personal', '', '2026-01-01', 'activo', '', 'credencial', %s, %s, 'personal') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (?, '', ?, ?, 'Personal', '', '2026-01-01', 'activo', '', 'credencial', ?, ?, 'personal')")
    pass_cifrada = app.encriptar_texto(password)
    contenido_cifrado = app.encriptar_texto('')
    cur.execute(q, (servicio, usuario, pass_cifrada, contenido_cifrado, propietario))
    reg_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return reg_id


def test_mi_boveda_disponible_para_usuario_estandar(sesion_usuario):
    """A diferencia de la Bóveda institucional (/credenciales, solo admin/agente), /mi_boveda
    es accesible para cualquier rol autenticado — incluido 'estandar'."""
    r = sesion_usuario.get('/mi_boveda')
    assert r.status_code == 200


def test_crear_entrada_personal_queda_asociada_al_propietario(sesion_usuario, app):
    sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'credencial', 'servicio': 'Banco Personal',
        'usuario': 'yo123', 'password': 'MiClaveSecreta1',
    }, follow_redirects=False)

    with sesion_usuario.session_transaction() as sess:
        propietario_esperado = sess['username']

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT propietario, visibilidad, password_cifrada FROM credenciales WHERE titulo = ?", ('Banco Personal',))
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    propietario, visibilidad, pass_cifrada = fila
    assert propietario == propietario_esperado
    assert visibilidad == 'personal'
    assert app.desencriptar_texto(pass_cifrada) == 'MiClaveSecreta1'


def test_crear_nota_segura_no_exige_usuario_ni_password(sesion_usuario, app):
    r = sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'nota_segura', 'servicio': 'Recordatorio privado',
        'contenido_seguro': 'Código de la caja fuerte: 4821',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo_item, contenido_seguro FROM credenciales WHERE titulo = ?", ('Recordatorio privado',))
    tipo_item, contenido_cifrado = cur.fetchone()
    conn.close()
    assert tipo_item == 'nota_segura'
    assert app.desencriptar_texto(contenido_cifrado) == 'Código de la caja fuerte: 4821'


def test_crear_entrada_incompleta_no_guarda_nada(sesion_usuario, app):
    sesion_usuario.post('/mi_boveda/crear', data={'tipo_item': 'credencial', 'servicio': 'Incompleta'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales WHERE titulo = ?", ('Incompleta',))
    total = cur.fetchone()[0]
    conn.close()
    assert total == 0


def test_mi_boveda_solo_lista_entradas_propias(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    _crear_entrada_personal(app, usuario_a, servicio='Solo de A')
    _crear_entrada_personal(app, usuario_b, servicio='Solo de B')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_a
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.get('/mi_boveda')
    assert b'Solo de A' in r.data
    assert b'Solo de B' not in r.data


def test_revelar_entrada_propia_devuelve_la_password(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, password='ClaveParaRevelar1')

    r = sesion_usuario.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    assert r.status_code == 200
    assert r.get_json()['password'] == 'ClaveParaRevelar1'


def test_revelar_entrada_de_otro_usuario_no_autorizado(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveDeA1')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_b
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})
    assert r.status_code == 403


def test_editar_entrada_de_otro_usuario_no_autorizado(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, servicio='Original de A')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_b
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Intento no autorizado', 'usuario': 'x', 'password': '',
    })
    assert r.status_code == 403
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT titulo FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone()[0] == 'Original de A'
    conn.close()


def test_eliminar_entrada_de_otro_usuario_no_autorizado(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a)

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_b
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.post(f'/mi_boveda/eliminar/{reg_id}')
    assert r.status_code == 403
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(estado, 'activo') FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone()[0] == 'activo'
    conn.close()


def test_editar_entrada_propia_actualiza_los_datos(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, servicio='Antes de Editar')

    r = sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Después de Editar', 'usuario': 'nuevo_usuario', 'password': '',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT titulo, usuario_acceso FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone() == ('Después de Editar', 'nuevo_usuario')
    conn.close()


def test_eliminar_entrada_propia_la_marca_eliminada(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario)

    r = sesion_usuario.post(f'/mi_boveda/eliminar/{reg_id}', follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone()[0] == 'eliminado'
    conn.close()


def test_admin_puede_revelar_entrada_personal_de_otro_usuario(admin_session, app, crear_usuario):
    """Pedido explícito de Tomás: 'visible para auditoría del super-admin' — cualquier cuenta
    con rol 'admin' conserva acceso de auditoría a los ítems personales de los demás, aunque no
    sea la propietaria (consistente con el resto de la Bóveda Fase 3, ver
    _puede_ver_credencial_item)."""
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveAuditable1')

    r = admin_session.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    assert r.status_code == 200
    assert r.get_json()['password'] == 'ClaveAuditable1'


def test_admin_puede_eliminar_entrada_personal_de_otro_usuario(admin_session, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a)

    r = admin_session.post(f'/mi_boveda/eliminar/{reg_id}', follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone()[0] == 'eliminado'
    conn.close()


def test_entradas_personales_no_aparecen_en_boveda_institucional_para_agente(client, app, crear_usuario):
    """La Bóveda de Accesos del equipo (/credenciales, ver ver_credenciales()) sigue sin mostrar
    los ítems 'personal' de otra persona a un 'agente' (ni dueño ni admin): la única cuenta con
    visibilidad de auditoría de por medio es 'admin' (ver test de abajo), tal como pidió Tomás."""
    usuario_a = crear_usuario(rol='estandar')
    _crear_entrada_personal(app, usuario_a, servicio='Estrictamente Personal De A')
    agente = crear_usuario(rol='agente')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = agente
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.get('/credenciales')

    assert b'Estrictamente Personal De A' not in r.data


def test_admin_ve_entradas_personales_en_boveda_institucional(admin_session, app, crear_usuario):
    """Consistente con la auditoría de super-admin pedida por Tomás: un 'admin' sí ve los ítems
    personales de otros usuarios también desde la Bóveda de Accesos institucional (no solo
    revelando la clave puntualmente vía /mi_boveda/<id>/revelar)."""
    usuario_a = crear_usuario(rol='estandar')
    _crear_entrada_personal(app, usuario_a, servicio='Auditable Por Admin')

    r = admin_session.get('/credenciales')

    assert b'Auditable Por Admin' in r.data
