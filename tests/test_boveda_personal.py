"""Pruebas de 'Mi Bóveda Personal' (pedido por Tomás): cada usuario —sin importar su rol— tiene
su propio espacio cifrado de contraseñas/notas, separado de la Bóveda de Accesos institucional
del equipo (esa sigue siendo /credenciales, exclusiva de admin/agente). Reutiliza la MISMA
tabla 'credenciales' con visibilidad='personal' (ver _puede_ver_credencial_item /
_puede_gestionar_credencial_item en app.py), así que estas pruebas también cubren que un
usuario no pueda ver ni gestionar la entrada personal de otro, y que un admin sí conserve
acceso de auditoría."""
import re


def _extraer_csrf_token(html):
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert m, "La página no trae csrf_token en un input oculto — no se puede simular el envío real."
    return m.group(1)


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


# 🐛 Hallazgo reportado por Tomás (video adjunto, 12/09/2026): abrir la Bóveda de Accesos
# (/credenciales) tumbaba TODA la página con un 500 "Internal Server Error" en producción.
# Traceback real (logs de Render): TypeError: 'datetime.datetime' object is not subscriptable,
# en credenciales.html línea 131 (data-fecha="{{ item.fecha[:10] ... }}"). Causa: 'fecha_creacion'
# es VARCHAR(100) en el esquema (ver CREATE TABLE credenciales en app.py), pero al menos una fila
# real en Postgres tenía un datetime.datetime nativo guardado ahí en vez de texto — la plantilla
# asumía que 'fecha' siempre era texto y podía cortarse con [:10].
#
# No se puede reproducir insertando un datetime.datetime "a mano" en sqlite (el propio módulo
# sqlite3 de Python lo adapta a texto ISO automáticamente al guardarlo Y al leerlo de vuelta, así
# que llegaría como str de todas formas — a diferencia de Postgres/psycopg2, donde una columna
# TEXT/VARCHAR con ese valor puede volver como datetime.datetime real según cómo haya quedado
# guardada la fila). Por eso esta prueba envuelve get_db() para que, SOLO en la consulta que arma
# la lista de la Bóveda, la fila de esta credencial vuelva con un datetime.datetime real en la
# posición de fecha_creacion — simulando exactamente la fila real de producción — y verifica que
# la página ya no se caiga con eso.
def test_credencial_con_fecha_datetime_nativo_no_rompe_la_boveda(admin_session, app, monkeypatch):
    import datetime as _dt

    titulo_marcador = 'Con Fecha Datetime Nativo'
    fecha_datetime_real = _dt.datetime(2026, 1, 1, 10, 0, 0)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    pass_cifrada = app.encriptar_texto('ClaveDeEjemplo1')
    q = ("INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (%s, '', 'usr', %s, 'IT', '', '2026-01-01 10:00:00', 'activo', '', 'credencial', NULL, NULL, 'equipo')"
         if db_type == 'postgres' else
         "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (?, '', 'usr', ?, 'IT', '', '2026-01-01 10:00:00', 'activo', '', 'credencial', NULL, NULL, 'equipo')")
    cur.execute(q, (titulo_marcador, pass_cifrada))
    conn.commit()
    conn.close()

    class _CursorQueSimulaDatetimeDePostgres:
        """Envuelve el cursor real: deja pasar todo tal cual, salvo que en la fila de
        'titulo_marcador' devuelta por la consulta de ver_credenciales() reemplaza el texto de
        fecha_creacion (columna índice 6, ver el SELECT en ver_credenciales) por un
        datetime.datetime real, como llegaría desde una fila así en Postgres."""
        def __init__(self, cursor_real):
            self._cursor_real = cursor_real

        def __getattr__(self, nombre):
            return getattr(self._cursor_real, nombre)

        def fetchall(self):
            filas = self._cursor_real.fetchall()
            resultado = []
            for fila in filas:
                fila = list(fila)
                if fila[1] == titulo_marcador:
                    fila[6] = fecha_datetime_real
                resultado.append(tuple(fila))
            return resultado

    class _ConexionQueSimulaDatetimeDePostgres:
        def __init__(self, conexion_real):
            self._conexion_real = conexion_real

        def __getattr__(self, nombre):
            return getattr(self._conexion_real, nombre)

        def cursor(self):
            return _CursorQueSimulaDatetimeDePostgres(self._conexion_real.cursor())

    get_db_original = app.get_db

    def _get_db_envuelto():
        conexion, tipo_db = get_db_original()
        return _ConexionQueSimulaDatetimeDePostgres(conexion), tipo_db

    monkeypatch.setattr(app, 'get_db', _get_db_envuelto)

    r = admin_session.get('/credenciales')

    assert r.status_code == 200
    assert titulo_marcador.encode() in r.data


# 🐛 Hallazgo reportado por el usuario 'prueba_neon' (video adjunto): "No se guardan las
# credenciales aquí" — al llenar "Nueva entrada" y darle Guardar, la página volvía a Mi Bóveda
# Personal sin ningún aviso de error y la lista seguía vacía. Causa real: mi_boveda.html tiene
# protección CSRF real activa en producción (CSRFProtect, ver app.py), pero su formulario de
# crear/editar y su formulario de eliminar NO llevaban el input oculto csrf_token, y su fetch()
# de /revelar tampoco mandaba el encabezado X-CSRFToken (compárese con credenciales.html, que sí
# lo hace en los tres casos). _manejar_csrf_invalido (app.py) responde a un token inválido o
# ausente con un simple redirect a la página anterior — sin flash, sin error visible — así que el
# guardado se descartaba en silencio exactamente como describió el usuario. El mismo hueco existía
# en admin_boveda_personal.html (la ventana de auditoría del Admin Master, recién construida).
# Estas pruebas quedaron INVISIBLES para el resto de la suite porque conftest.py fija
# WTF_CSRF_ENABLED=False para todas las pruebas normales (necesario para no tener que simular el
# token en cada prueba existente) — por eso aquí se reactiva la protección real a propósito, para
# reproducir el fallo tal cual ocurrió y confirmar que las plantillas corregidas ya lo soportan.

def test_guardar_nueva_entrada_funciona_con_proteccion_csrf_real(sesion_usuario, app, monkeypatch):
    monkeypatch.setitem(app.app.config, 'WTF_CSRF_ENABLED', True)
    html = sesion_usuario.get('/mi_boveda').get_data(as_text=True)
    token = _extraer_csrf_token(html)

    r = sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'credencial', 'servicio': 'Cuenta Con CSRF Real',
        'usuario': 'csrf_user', 'password': 'ClaveCsrfReal1',
        'csrf_token': token,
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales WHERE titulo = ?", ('Cuenta Con CSRF Real',))
    assert cur.fetchone()[0] == 1
    conn.close()


def test_guardar_nueva_entrada_sin_token_se_descarta_en_silencio_reproduce_el_bug(sesion_usuario, app, monkeypatch):
    """Reproduce el reporte de 'prueba_neon' tal cual: sin el token (como pasaba antes de este
    arreglo, porque el formulario no lo llevaba), nada se guarda y la respuesta es un redirect
    normal — no un error visible."""
    monkeypatch.setitem(app.app.config, 'WTF_CSRF_ENABLED', True)

    r = sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'credencial', 'servicio': 'Cuenta Sin Token',
        'usuario': 'x', 'password': 'y',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM credenciales WHERE titulo = ?", ('Cuenta Sin Token',))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_revelar_funciona_con_encabezado_x_csrftoken_y_proteccion_real(sesion_usuario, app, monkeypatch):
    monkeypatch.setitem(app.app.config, 'WTF_CSRF_ENABLED', True)
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, password='ClaveRevelada1')

    html = sesion_usuario.get('/mi_boveda').get_data(as_text=True)
    token = _extraer_csrf_token(html)

    r = sesion_usuario.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'},
                             headers={'X-CSRFToken': token})

    assert r.status_code == 200
    assert r.get_json()['password'] == 'ClaveRevelada1'


def test_revelar_sin_encabezado_csrf_falla_con_proteccion_real(sesion_usuario, app, monkeypatch):
    monkeypatch.setitem(app.app.config, 'WTF_CSRF_ENABLED', True)
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario)

    r = sesion_usuario.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    assert r.status_code != 200


# 🔗📜 Pedido de Tomás (07/09/2026, junto con dos capturas de Mi Bóveda Personal): "que aquí el
# usuario también pueda pegar la URL o enlace del sitio en el que se valida o usa la credencial,
# adicional, que se habilite la opcion de ir al sitio como en la boveda general y que exista un
# control de versiones o historial con fecha y hora de los cambios de contraseñas o notas". Estas
# pruebas cubren el campo url_acceso (ya usado por la Bóveda institucional, ver credenciales.html
# 'Ir al enlace') y el nuevo control de versiones de Mi Bóveda Personal
# (mi_boveda_historial/mi_boveda_historial_revelar).

def test_guardar_entrada_con_url_la_deja_disponible_para_ir_al_sitio(sesion_usuario, app):
    sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'credencial', 'servicio': 'Correo Con Enlace',
        'usuario': 'yo123', 'password': 'ClaveConEnlace1',
        'url': 'https://correo.ejemplo.com/login',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT url_acceso FROM credenciales WHERE titulo = ?", ('Correo Con Enlace',))
    url_guardada = cur.fetchone()[0]
    conn.close()
    assert url_guardada == 'https://correo.ejemplo.com/login'

    r = sesion_usuario.get('/mi_boveda')
    assert b'https://correo.ejemplo.com/login' in r.data


def test_editar_entrada_puede_agregarle_una_url(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, servicio='Sin Enlace Todavia')

    sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Sin Enlace Todavia', 'usuario': 'yo@correo.com',
        'password': '', 'url': 'https://portal.ejemplo.com',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT url_acceso FROM credenciales WHERE id = ?", (reg_id,))
    assert cur.fetchone()[0] == 'https://portal.ejemplo.com'
    conn.close()


def test_editar_credencial_cambiando_password_crea_version_en_el_historial(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, servicio='Con Historial', password='ClaveVieja1')

    sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Con Historial', 'usuario': 'yo@correo.com',
        'password': 'ClaveNueva2',
    }, follow_redirects=False)

    r = sesion_usuario.get(f'/mi_boveda/{reg_id}/historial')
    assert r.status_code == 200
    historial = r.get_json()['historial']
    assert len(historial) == 1
    assert historial[0]['cambiado_por'] == propietario

    r2 = sesion_usuario.post(f'/mi_boveda/historial/{historial[0]["id"]}/revelar')
    assert r2.status_code == 200
    assert r2.get_json()['password'] == 'ClaveVieja1'

    # La clave ACTUAL (no la del historial) debe ser la nueva.
    r3 = sesion_usuario.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})
    assert r3.get_json()['password'] == 'ClaveNueva2'


def test_editar_credencial_sin_llenar_password_no_crea_version(sesion_usuario, app):
    """Misma convención que editar_credencial: dejar el campo contraseña vacío significa 'no
    cambiarla', así que no debe generar una entrada de historial."""
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    reg_id = _crear_entrada_personal(app, propietario, servicio='Password Sin Tocar')

    sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Password Sin Tocar (renombrada)',
        'usuario': 'yo@correo.com', 'password': '',
    }, follow_redirects=False)

    r = sesion_usuario.get(f'/mi_boveda/{reg_id}/historial')
    assert r.get_json()['historial'] == []


def test_editar_nota_segura_con_contenido_distinto_crea_version_en_el_historial(sesion_usuario, app):
    sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'nota_segura', 'servicio': 'Nota Con Historial',
        'contenido_seguro': 'Contenido original',
    }, follow_redirects=False)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM credenciales WHERE titulo = ?", ('Nota Con Historial',))
    reg_id = cur.fetchone()[0]
    conn.close()

    sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'nota_segura', 'servicio': 'Nota Con Historial',
        'contenido_seguro': 'Contenido actualizado',
    }, follow_redirects=False)

    r = sesion_usuario.get(f'/mi_boveda/{reg_id}/historial')
    historial = r.get_json()['historial']
    assert len(historial) == 1

    r2 = sesion_usuario.post(f'/mi_boveda/historial/{historial[0]["id"]}/revelar')
    assert r2.get_json()['contenido'] == 'Contenido original'


def test_editar_nota_segura_reenviando_el_mismo_contenido_no_crea_version(sesion_usuario, app):
    """A diferencia de una credencial (que tiene el convenio 'vacío = no cambiar'), una nota
    segura siempre reenvía su contenido en el formulario — por eso el versionado compara el
    texto descifrado, no solo si el campo llegó con algo."""
    sesion_usuario.post('/mi_boveda/crear', data={
        'tipo_item': 'nota_segura', 'servicio': 'Nota Sin Cambios',
        'contenido_seguro': 'Mismo contenido de siempre',
    }, follow_redirects=False)
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM credenciales WHERE titulo = ?", ('Nota Sin Cambios',))
    reg_id = cur.fetchone()[0]
    conn.close()

    sesion_usuario.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'nota_segura', 'servicio': 'Nota Sin Cambios',
        'contenido_seguro': 'Mismo contenido de siempre',
    }, follow_redirects=False)

    r = sesion_usuario.get(f'/mi_boveda/{reg_id}/historial')
    assert r.get_json()['historial'] == []


def test_historial_de_entrada_de_otro_usuario_no_autorizado(client, app, crear_usuario):
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

    r = client.get(f'/mi_boveda/{reg_id}/historial')
    assert r.status_code == 403


def test_revelar_historial_de_entrada_de_otro_usuario_no_autorizado(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    usuario_b = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveVieja1')

    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario_a
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    client.post(f'/mi_boveda/editar/{reg_id}', data={
        'tipo_item': 'credencial', 'servicio': 'Cualquiera', 'usuario': 'x', 'password': 'ClaveNueva2',
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM credenciales_historial WHERE credencial_id = ?", (reg_id,))
    historial_id = cur.fetchone()[0]
    conn.close()

    with client.session_transaction() as sess:
        sess['username'] = usuario_b

    r = client.post(f'/mi_boveda/historial/{historial_id}/revelar')
    assert r.status_code == 403


def test_admin_puede_consultar_y_revelar_historial_de_otro_usuario(admin_session, app, crear_usuario):
    """Consistente con el resto de Mi Bóveda Personal: un 'admin' conserva acceso de auditoría,
    también sobre el historial de versiones."""
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveAuditableVieja1')

    # Inserta la versión directo en la BD (simulando un cambio de contraseña anterior de A):
    # admin_session no es el propietario, así que editar por esa vía daría 403 -lo correcto-.
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO credenciales_historial (credencial_id, password_cifrada, fecha_cambio, cambiado_por) VALUES (?, ?, ?, ?)",
        (reg_id, app.encriptar_texto('ClaveAuditableVieja1'), '2026-01-02 10:00:00', usuario_a),
    )
    conn.commit()
    conn.close()

    r = admin_session.get(f'/mi_boveda/{reg_id}/historial')
    assert r.status_code == 200
    historial = r.get_json()['historial']
    assert len(historial) == 1

    r2 = admin_session.post(f'/mi_boveda/historial/{historial[0]["id"]}/revelar')
    assert r2.status_code == 200
    assert r2.get_json()['password'] == 'ClaveAuditableVieja1'
