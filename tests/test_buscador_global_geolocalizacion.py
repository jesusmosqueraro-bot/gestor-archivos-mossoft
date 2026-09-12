"""Pruebas de cobertura del buscador global ("Buscar en Arkiv") sobre Geolocalización de
Accesos — el segundo de los "últimos dos módulos" que Tomás señaló como faltantes en las
búsquedas (12/09/2026), junto con Mi Bóveda Personal (ver
tests/test_buscador_global_boveda_personal.py). Antes de esta corrección /buscar/api no tenía
ninguna categoría para /admin/geolocalizacion, así que buscar el nombre de un usuario, su IP o
la sede de un acceso puntual no encontraba nada aunque el registro sí existiera."""


def _crear_registro_geolocalizacion(app, usuario, ip='190.85.10.20', lat=6.2506579, lng=-75.5658374,
                                     fecha='2026-09-12 09:00:00', sede='Sede Principal', dentro_de_sede=True):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO login_geolocalizacion (usuario, ip, latitud, longitud, fecha, sede, dentro_de_sede) VALUES (%s, %s, %s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO login_geolocalizacion (usuario, ip, latitud, longitud, fecha, sede, dentro_de_sede) VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (usuario, ip, lat, lng, fecha, sede, dentro_de_sede))
    conn.commit()
    conn.close()


def test_buscador_global_encuentra_acceso_por_nombre_de_usuario(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Rosa Elena Pérez')
    _crear_registro_geolocalizacion(app, usuario)

    data = admin_session.get('/buscar/api?q=rosa elena perez').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Geolocalización de Accesos' in categorias


def test_buscador_global_encuentra_acceso_por_ip(admin_session, app, crear_usuario):
    usuario = crear_usuario()
    _crear_registro_geolocalizacion(app, usuario, ip='203.0.113.77')

    data = admin_session.get('/buscar/api?q=203.0.113.77').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Geolocalización de Accesos' in categorias


def test_buscador_global_encuentra_acceso_por_sede(admin_session, app, crear_usuario):
    usuario = crear_usuario()
    _crear_registro_geolocalizacion(app, usuario, sede='Nuevo Naranjal')

    data = admin_session.get('/buscar/api?q=nuevo naranjal').get_json()

    titulos = [r for r in data['resultados'] if r['categoria'] == 'Geolocalización de Accesos']
    assert titulos
    assert 'Nuevo Naranjal' in titulos[0]['subtitulo']


def test_buscador_global_geolocalizacion_enlaza_a_admin_geolocalizacion_filtrado_por_usuario(admin_session, app, crear_usuario):
    usuario = crear_usuario()
    _crear_registro_geolocalizacion(app, usuario)

    data = admin_session.get(f'/buscar/api?q={usuario}').get_json()

    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Geolocalización de Accesos')
    assert resultado['url'] == f'/admin/geolocalizacion?usuario={usuario}'


def test_agente_no_ve_geolocalizacion_en_el_buscador_global(client, app, crear_usuario):
    usuario = crear_usuario(nombre='Carlos Soporte')
    _crear_registro_geolocalizacion(app, usuario)
    agente = crear_usuario(usuario='agente_prueba', rol='agente')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = agente
        sess['rol'] = 'agente'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    data = client.get('/buscar/api?q=carlos soporte').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Geolocalización de Accesos' not in categorias


def test_estandar_no_ve_geolocalizacion_en_el_buscador_global(sesion_usuario, app, crear_usuario):
    usuario = crear_usuario(nombre='Ana Otra Persona')
    _crear_registro_geolocalizacion(app, usuario)

    data = sesion_usuario.get('/buscar/api?q=ana otra persona').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Geolocalización de Accesos' not in categorias
