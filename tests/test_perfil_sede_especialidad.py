"""Pruebas de autoservicio de Sede y Puesto de Trabajo (especialidad) desde 'Mi Perfil'
(/perfil) — pedido de Tomás, 20/09/2026: "que cada usuario pueda en editar su perfil, su sede o
puesto de trabajo... esto ayuda a tener un control de los cuadros de turnos, si el usuario es
cambiado de sede".

Hasta este cambio, 'usuarios.sede' solo se fijaba una vez al crear la cuenta — ni siquiera un
admin podía corregirla después desde Editar Usuario. Ahora cualquier usuario puede mantenerla al
día él mismo desde su propio perfil, junto con su Puesto de Trabajo (columna 'especialidad',
mismo catálogo 'especialidades_catalogo' que ya administra Gestión de Usuarios). Ambos campos
usan un catálogo cerrado (Sedes de /tickets/configuracion, Especialidades de Gestión de
Usuarios): un valor que no exista en el catálogo correspondiente se descarta y se conserva el
que ya tenía, para no guardar un dato inventado a mano en el formulario."""


def _crear_sede(app, nombre='Sede Norte', estado='activo'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO ticket_configuraciones (tipo, nombre, estado) VALUES ('sede', ?, ?)", (nombre, estado))
    conn.commit()
    conn.close()
    return nombre


def _especialidad_existente(app):
    """Devuelve el nombre de una especialidad ya sembrada por init_db() (ver
    'especialidades_a_sincronizar' en app.py), para no depender de crear una nueva."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre FROM especialidades_catalogo WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY nombre ASC LIMIT 1")
    (nombre,) = cur.fetchone()
    conn.close()
    return nombre


def test_get_perfil_muestra_los_selects_de_sede_y_puesto_con_sus_catalogos(sesion_usuario, app):
    sede = _crear_sede(app, 'Sede Norte')
    especialidad = _especialidad_existente(app)

    body = sesion_usuario.get('/perfil').get_data(as_text=True)

    assert 'name="sede"' in body
    assert 'name="especialidad"' in body
    assert sede in body
    assert especialidad in body
    assert 'Sin sede asignada' in body


def test_post_asigna_una_sede_valida_del_catalogo(sesion_usuario, app):
    sede = _crear_sede(app, 'Sede Norte')
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'sede': sede,
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'guardaron correctamente' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == sede
    conn.close()


def test_post_sede_vacia_limpia_la_sede_asignada(sesion_usuario, app):
    sede = _crear_sede(app, 'Sede Norte')
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET sede = ? WHERE usuario = ?", (sede, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'sede': '',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] is None
    conn.close()


def test_post_sede_inventada_se_descarta_y_conserva_la_anterior(sesion_usuario, app):
    sede_real = _crear_sede(app, 'Sede Norte')
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET sede = ? WHERE usuario = ?", (sede_real, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'sede': 'Sede Que No Existe',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == sede_real  # se conservó, no se guardó el valor inventado
    conn.close()


def test_post_sede_de_otra_sede_inactiva_se_descarta(sesion_usuario, app):
    sede_activa = _crear_sede(app, 'Sede Activa', estado='activo')
    sede_inactiva = _crear_sede(app, 'Sede Inactiva', estado='inactivo')
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET sede = ? WHERE usuario = ?", (sede_activa, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'sede': sede_inactiva,
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == sede_activa  # la sede inactiva no es una opción válida
    conn.close()


def test_post_asigna_un_puesto_de_trabajo_valido_del_catalogo(sesion_usuario, app):
    especialidad = _especialidad_existente(app)
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'especialidad': especialidad,
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    assert 'guardaron correctamente' in r.get_data(as_text=True)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT especialidad FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == especialidad
    conn.close()


def test_post_puesto_de_trabajo_vacio_conserva_el_anterior(sesion_usuario, app):
    """Puesto de Trabajo es obligatorio para toda cuenta desde su creación — dejarlo en blanco
    en el formulario de autoservicio no debe vaciarlo (a diferencia de Sede, que sí es
    opcional)."""
    especialidad = _especialidad_existente(app)
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET especialidad = ? WHERE usuario = ?", (especialidad, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'especialidad': '',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT especialidad FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == especialidad
    conn.close()


def test_post_puesto_de_trabajo_inventado_se_descarta_y_conserva_el_anterior(sesion_usuario, app):
    especialidad = _especialidad_existente(app)
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET especialidad = ? WHERE usuario = ?", (especialidad, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'especialidad': 'Puesto Inventado',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT especialidad FROM usuarios WHERE usuario = ?", (usuario,))
    assert cur.fetchone()[0] == especialidad
    conn.close()


def test_sede_actualizada_desde_perfil_se_refleja_en_colaboradores_por_sede(sesion_usuario, app):
    """Verifica el motivo real del pedido: cambiar la Sede desde /perfil debe reflejarse de
    inmediato en el directorio 'Colaboradores por Sede' del Cuadro de Turnos, sin duplicar el
    dato en ningún otro lado — ambos leen la misma columna 'usuarios.sede'."""
    sede_nueva = _crear_sede(app, 'Sede Trasladado')
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
        sess['modulos_extra'] = ['turnos']

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co', 'sede': sede_nueva,
    }, content_type='multipart/form-data')
    assert r.status_code == 200

    body = sesion_usuario.get('/turnos/por_sede').get_data(as_text=True)
    assert sede_nueva in body
    assert usuario in body or 'Persona de Prueba' in body


def test_post_sin_los_campos_nuevos_limpia_sede_pero_conserva_puesto_de_trabajo(sesion_usuario, app):
    """Un POST que no incluye 'sede'/'especialidad' en absoluto (p. ej. una integración vieja
    anterior a este cambio, o el propio formulario real cuando el select de Sede queda en 'Sin
    sede asignada') se trata igual que enviarlos en blanco: Sede se limpia (es opcional, y así
    es como el propio <select> del formulario envía "Sin sede asignada"), pero Puesto de Trabajo
    se conserva (es obligatorio, nunca se vacía por accidente). En el formulario real esto no es
    un problema práctico: el <select> de Sede siempre viaja con la opción ya seleccionada del
    usuario, a menos que él mismo la cambie a "Sin sede asignada"."""
    sede = _crear_sede(app, 'Sede Norte')
    especialidad = _especialidad_existente(app)
    with sesion_usuario.session_transaction() as sess:
        usuario = sess['username']
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET sede = ?, especialidad = ? WHERE usuario = ?", (sede, especialidad, usuario))
    conn.commit()
    conn.close()

    r = sesion_usuario.post('/perfil', data={
        'telefono': '3022222222', 'correo': 'juan.carlos@preventivaips.com.co',
    }, content_type='multipart/form-data')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede, especialidad FROM usuarios WHERE usuario = ?", (usuario,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] is None  # sede vacía en el form => se limpia, mismo criterio que 'Sin sede asignada'
    assert fila[1] == especialidad  # especialidad vacía en el form => se conserva (obligatoria)
