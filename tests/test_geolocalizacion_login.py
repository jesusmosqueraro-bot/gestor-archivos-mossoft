"""Pruebas de la geolocalización de inicio de sesión (pedido por Tomás, 12/09/2026):
capturar fecha/hora + lat/lon de cada login exitoso y ofrecer una vista en mapa para
verificar que el acceso ocurrió desde la sede/área correspondiente.

La geolocalización es "mejor esfuerzo": nunca debe bloquear el login, y debe quedar NULL en
la base de datos si el navegador no la envía (permiso denegado, navegador sin soporte, o
usuario que no pasó por el JS del formulario — como estas pruebas, que llaman a /login
directamente sin ejecutar el script de login.html)."""
from werkzeug.security import generate_password_hash


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def _crear_sede(admin_session, nombre, lat, lng, radio_metros=None):
    """Crea una Sede real en /tickets/configuracion (el catálogo que desde el 12/09/2026 también
    usa /admin/geolocalizacion para el mapa y para clasificar dentro/fuera de sede — ya no el
    placeholder SEDES_AUTORIZADAS)."""
    data = {'tipo': 'sede', 'nombre': nombre, 'latitud': str(lat), 'longitud': str(lng)}
    if radio_metros is not None:
        data['radio_metros'] = str(radio_metros)
    admin_session.post('/tickets/configuracion/nuevo', data=data)
    return nombre


def _ultima_geolocalizacion(app, usuario):
    conn, db_type = app.get_db()
    cursor = conn.cursor()
    query = (
        "SELECT usuario, ip, latitud, longitud, fecha FROM login_geolocalizacion "
        "WHERE usuario = %s ORDER BY id DESC LIMIT 1"
        if db_type == 'postgres' else
        "SELECT usuario, ip, latitud, longitud, fecha FROM login_geolocalizacion "
        "WHERE usuario = ? ORDER BY id DESC LIMIT 1"
    )
    cursor.execute(query, (usuario,))
    fila = cursor.fetchone()
    conn.close()
    return fila


def test_login_exitoso_sin_coordenadas_registra_geolocalizacion_con_lat_lon_nulos(client, app, crear_usuario, monkeypatch):
    """Si el navegador no envía latitud/longitud (permiso denegado, sin soporte, o —como en esta
    prueba— un cliente que no ejecutó el script de login.html), el login debe seguir
    funcionando igual, y la fila en login_geolocalizacion debe quedar con lat/lon en NULL."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    r = client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'}, follow_redirects=False)

    assert r.status_code == 302
    assert '/bienvenida' in r.headers.get('Location', '')
    fila = _ultima_geolocalizacion(app, usuario)
    assert fila is not None, "El login exitoso debía registrar una fila en login_geolocalizacion"
    _, ip, lat, lng, fecha = fila
    assert lat is None and lng is None
    assert fecha


def test_login_exitoso_con_coordenadas_las_guarda_correctamente(client, app, crear_usuario, monkeypatch):
    """Cuando login.html sí logra obtener la ubicación, los dos campos ocultos 'latitud'/
    'longitud' viajan en el mismo POST de /login y deben guardarse tal cual (numéricos)."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    r = client.post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '4.710989', 'longitud': '-74.072092',
    }, follow_redirects=False)

    assert r.status_code == 302
    fila = _ultima_geolocalizacion(app, usuario)
    assert fila is not None
    _, ip, lat, lng, fecha = fila
    assert round(float(lat), 6) == 4.710989
    assert round(float(lng), 6) == -74.072092


def test_login_con_coordenadas_invalidas_no_revienta_y_guarda_nulo(client, app, crear_usuario, monkeypatch):
    """Un campo manipulado o corrupto (no numérico) no debe tumbar el login: la geolocalización
    es informativa, nunca un requisito para poder entrar."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    r = client.post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': 'no-es-un-numero', 'longitud': 'tampoco',
    }, follow_redirects=False)

    assert r.status_code == 302
    fila = _ultima_geolocalizacion(app, usuario)
    assert fila is not None
    _, ip, lat, lng, fecha = fila
    assert lat is None and lng is None


def test_login_contrasena_incorrecta_no_registra_geolocalizacion(client, app, crear_usuario, monkeypatch):
    """Solo un login EXITOSO debe quedar en login_geolocalizacion — de lo contrario cualquiera
    podría llenar la tabla con intentos fallidos con coordenadas arbitrarias."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')

    client.post('/login', data={
        'usuario': usuario, 'password': 'clave-equivocada',
        'latitud': '4.710989', 'longitud': '-74.072092',
    })

    assert _ultima_geolocalizacion(app, usuario) is None


def test_admin_geolocalizacion_requiere_rol_admin(client, app, crear_usuario):
    """Un usuario estándar autenticado no debe poder ver el mapa de accesos de todos."""
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.get('/admin/geolocalizacion', follow_redirects=False)

    assert r.status_code == 302
    assert 'geolocalizacion' not in r.headers.get('Location', '')


def test_admin_geolocalizacion_requiere_sesion_iniciada(client):
    r = client.get('/admin/geolocalizacion', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_admin_geolocalizacion_muestra_los_accesos_registrados(admin_session, app, crear_usuario, monkeypatch):
    """La vista /admin/geolocalizacion (solo admin) debe listar los inicios de sesión con
    ubicación y pintar el mapa Leaflet con las Sedes reales configuradas en
    /tickets/configuracion (ya no con el placeholder SEDES_AUTORIZADAS)."""
    _forzar_recaptcha_ok(monkeypatch, app)
    _crear_sede(admin_session, 'Sede De Prueba Mapa', 6.244203, -75.581215)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    app.app.test_client().post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '6.244203', 'longitud': '-75.581215',
    })

    r = admin_session.get('/admin/geolocalizacion')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert usuario in texto
    assert 'leaflet' in texto.lower()
    assert 'Sede De Prueba Mapa' in texto


def test_admin_geolocalizacion_clasifica_dentro_y_fuera_de_sede_en_las_metricas(admin_session, app, crear_usuario, monkeypatch):
    """Pedido de Tomás (12/09/2026): la vista debe mostrar métricas — aquí se verifica que un
    login con las coordenadas exactas de una Sede real cuenta como 'dentro', y uno con
    coordenadas muy lejanas cuenta como 'fuera' (radio_metros de la Sede: 200 m por defecto).
    Antes esto se comparaba contra el placeholder SEDES_AUTORIZADAS (Bogotá), así que ningún
    login fuera de esas coordenadas de ejemplo podía salir "dentro", sin importar la Sede real
    configurada — caso reportado por Tomás con NUEVO NARANJAL en Medellín."""
    _forzar_recaptcha_ok(monkeypatch, app)
    _crear_sede(admin_session, 'Sede De Prueba Metricas', 6.244203, -75.581215)
    usuario_dentro = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    usuario_fuera = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    # 🔧 Un cliente de prueba POR login: una vez el primero deja 'logged_in' en su sesión,
    # before_request() intercepta cualquier POST siguiente a /login de ese mismo cliente y
    # redirige derecho a /bienvenida sin ejecutar la vista (ver ENDPOINTS_SOLO_SIN_SESION) —
    # reutilizar el mismo cliente para el segundo login lo dejaría sin registrar.
    app.app.test_client().post('/login', data={
        'usuario': usuario_dentro, 'password': 'ClaveSegura123',
        'latitud': '6.244203', 'longitud': '-75.581215',  # exactamente la Sede de prueba
    })
    app.app.test_client().post('/login', data={
        'usuario': usuario_fuera, 'password': 'ClaveSegura123',
        'latitud': '10.0', 'longitud': '-70.0',  # muy lejos de cualquier sede
    })

    r = admin_session.get('/admin/geolocalizacion')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert '"sede": "Sede De Prueba Metricas"' in texto or '"sede":"Sede De Prueba Metricas"' in texto
    assert '"dentro_de_sede": true' in texto or '"dentro_de_sede":true' in texto
    assert '"dentro_de_sede": false' in texto or '"dentro_de_sede":false' in texto


def test_admin_geolocalizacion_filtra_por_usuario(admin_session, app, crear_usuario, monkeypatch):
    """El selector de usuario (pedido de Tomás) debe acotar el mapa/tabla/métricas a un solo
    usuario, sin mostrar los accesos de los demás."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario_a = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    usuario_b = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    cliente_aux = app.app.test_client()
    cliente_aux.post('/login', data={'usuario': usuario_a, 'password': 'ClaveSegura123'})
    cliente_aux.post('/login', data={'usuario': usuario_b, 'password': 'ClaveSegura123'})

    r = admin_session.get(f'/admin/geolocalizacion?usuario={usuario_a}')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert f'"usuario": "{usuario_a}"' in texto or f'"usuario":"{usuario_a}"' in texto
    # El usuario_b no debe aparecer en los datos embebidos (REGISTROS), que son los únicos que
    # alimentan el mapa, la tabla y las métricas.
    inicio_datos = texto.index('const REGISTROS')
    fin_datos = texto.index('const SEDES')
    assert usuario_b not in texto[inicio_datos:fin_datos]


def test_admin_geolocalizacion_filtra_por_rango_de_fechas_excluye_fuera_de_rango(admin_session, app, crear_usuario, monkeypatch):
    """Un rango de fechas que no incluye hoy debe dejar el listado vacío, sin romper la página."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    app.app.test_client().post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    r = admin_session.get('/admin/geolocalizacion?fecha_inicio=2000-01-01&fecha_fin=2000-01-02')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'Ningún acceso coincide con el filtro actual' in texto
    inicio_datos = texto.index('const REGISTROS')
    fin_datos = texto.index('const SEDES')
    assert usuario not in texto[inicio_datos:fin_datos]


# --- /admin/geolocalizacion/resumen: endpoint JSON para el modal de vista rápida en
# bienvenida.html (pedido de Tomás, 12/09/2026: "dame un modal en el bienvenida.html" /
# "Ambos, por favor" — métricas + mapa embebido). Comparte _datos_geolocalizacion() con la
# página completa, así que aquí solo se verifica el contrato JSON en sí (forma, roles y que
# de verdad refleje los accesos registrados), no de nuevo toda la lógica de filtrado/sede.

def test_resumen_geolocalizacion_requiere_rol_admin(client, app, crear_usuario):
    """Igual que la página completa, el resumen JSON tampoco debe ser visible para un usuario
    estándar autenticado."""
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.get('/admin/geolocalizacion/resumen', follow_redirects=False)

    assert r.status_code == 302


def test_resumen_geolocalizacion_requiere_sesion_iniciada(client):
    r = client.get('/admin/geolocalizacion/resumen', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_resumen_geolocalizacion_devuelve_metricas_y_sedes(admin_session, app, crear_usuario, monkeypatch):
    """El JSON debe traer las Sedes reales (con coordenadas cargadas) y reflejar en las métricas
    un acceso recién registrado, para que el modal pueda pintar el mapa y las tarjetas de
    métricas sin tener que llamar a la página completa."""
    _forzar_recaptcha_ok(monkeypatch, app)
    _crear_sede(admin_session, 'Sede De Prueba Resumen', 6.244203, -75.581215)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    app.app.test_client().post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '6.244203', 'longitud': '-75.581215',  # exactamente la Sede de prueba
    })

    r = admin_session.get('/admin/geolocalizacion/resumen')

    assert r.status_code == 200
    datos = r.get_json()
    assert datos is not None
    assert any(sede['nombre'] == 'Sede De Prueba Resumen' for sede in datos['sedes'])
    assert datos['total_accesos'] >= 1
    assert datos['dentro_de_sede'] >= 1
    assert any(
        reg['usuario'] == usuario and reg['sede'] == 'Sede De Prueba Resumen' and reg['dentro_de_sede'] is True
        for reg in datos['registros']
    )
