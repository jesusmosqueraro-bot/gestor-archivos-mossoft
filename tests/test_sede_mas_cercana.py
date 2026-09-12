"""Pruebas de "sede más cercana" al crear un usuario (pedido de Tomás, 12/09/2026): el catálogo
de Sedes de /tickets/configuracion ahora puede guardar latitud/longitud, y el formulario de
alta de Gestión de Usuarios (templates/usuarios.html) usa esas coordenadas + la ubicación que
reporte el navegador para preseleccionar sola la Sede más cercana (cálculo de Haversine en
JS — ver _distanciaHaversineMetros/_sedeMasCercana/_preseleccionarSedeMasCercana). Estas
pruebas cubren la parte de backend: que las coordenadas se guarden bien (o se descarten si son
basura) y que la plantilla exponga los data-lat/data-lng que ese JS necesita."""


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


def _sede_por_nombre(app, nombre):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, latitud, longitud FROM ticket_configuraciones WHERE tipo = 'sede' AND nombre = ?", (nombre,))
    fila = cur.fetchone()
    conn.close()
    return fila


def test_crear_sede_guarda_latitud_y_longitud(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Conquistadores',
        'direccion': 'Calle 34B # 65D 46', 'latitud': '6.244203', 'longitud': '-75.581215',
    }, follow_redirects=False)

    fila = _sede_por_nombre(app, 'Sede Conquistadores')
    assert fila is not None
    assert round(fila[1], 6) == 6.244203
    assert round(fila[2], 6) == -75.581215


def test_crear_sede_admite_hasta_8_decimales_en_latitud_y_longitud(admin_session, app):
    """Google Maps suele copiar coordenadas con 7-8 decimales; antes se guardaban truncadas a 6
    (NUMERIC(9,6)) y el input HTML las rechazaba de entrada (step=0.000001). Pedido de Tomás,
    12/09/2026."""
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Ocho Decimales',
        'latitud': '6.25065790', 'longitud': '-75.58284550',
    }, follow_redirects=False)

    fila = _sede_por_nombre(app, 'Sede Ocho Decimales')
    assert fila is not None
    assert round(fila[1], 8) == 6.2506579
    assert round(fila[2], 8) == -75.5828455


def test_crear_sede_con_coordenada_invalida_no_revienta_y_queda_sin_coordenadas(admin_session, app):
    r = admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Sin Coordenadas Válidas',
        'latitud': 'no-es-un-numero', 'longitud': '',
    }, follow_redirects=False)

    assert r.status_code == 302
    fila = _sede_por_nombre(app, 'Sede Sin Coordenadas Válidas')
    assert fila is not None
    assert fila[1] is None
    assert fila[2] is None


def test_editar_sede_actualiza_sus_coordenadas(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={'tipo': 'sede', 'nombre': 'Sede La Playa'})
    config_id, _, _ = _sede_por_nombre(app, 'Sede La Playa')

    admin_session.post(f'/tickets/configuracion/{config_id}/editar', data={
        'nombre': 'Sede La Playa', 'latitud': '6.252341', 'longitud': '-75.573920',
    }, follow_redirects=False)

    _, lat, lng = _sede_por_nombre(app, 'Sede La Playa')
    assert round(lat, 6) == 6.252341
    assert round(lng, 6) == -75.573920


def test_editar_sede_admite_hasta_8_decimales(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={'tipo': 'sede', 'nombre': 'Sede Ocho Decimales Editar'})
    config_id, _, _ = _sede_por_nombre(app, 'Sede Ocho Decimales Editar')

    admin_session.post(f'/tickets/configuracion/{config_id}/editar', data={
        'nombre': 'Sede Ocho Decimales Editar', 'latitud': '6.25065790', 'longitud': '-75.58284550',
    }, follow_redirects=False)

    _, lat, lng = _sede_por_nombre(app, 'Sede Ocho Decimales Editar')
    assert round(lat, 8) == 6.2506579
    assert round(lng, 8) == -75.5828455


def test_crear_area_ignora_latitud_y_longitud(admin_session, app):
    """Latitud/longitud solo tienen sentido para Sedes — un Área no entra en el cálculo de
    "sede más cercana", así que aunque lleguen esos campos en el formulario (no debería pasar,
    el formulario de Áreas no los incluye) se descartan igual que ya se hacía con dirección."""
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'area', 'nombre': 'Área de Prueba', 'latitud': '6.2', 'longitud': '-75.5',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT latitud, longitud FROM ticket_configuraciones WHERE tipo = 'area' AND nombre = 'Área de Prueba'")
    fila = cur.fetchone()
    conn.close()
    assert fila == (None, None)


def test_crear_usuario_guarda_la_sede_asignada(admin_session, app):
    especialidad = _crear_especialidad(app)
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Conquistadores', 'latitud': '6.244203', 'longitud': '-75.581215',
    })

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Ana', 'primer_apellido': 'Ruiz',
        'email': 'ana.ruiz@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar', 'sede': 'Sede Conquistadores',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE correo = 'ana.ruiz@preventivaips.com.co'")
    assert cur.fetchone()[0] == 'Sede Conquistadores'
    conn.close()


def test_crear_usuario_sin_elegir_sede_no_falla(admin_session, app):
    especialidad = _crear_especialidad(app, 'Sin Sede')
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Bruno', 'primer_apellido': 'Cano',
        'email': 'bruno.cano@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede FROM usuarios WHERE correo = 'bruno.cano@preventivaips.com.co'")
    assert cur.fetchone()[0] is None
    conn.close()


def test_formulario_de_usuarios_expone_las_coordenadas_de_cada_sede(admin_session, app):
    """El JS de _sede_mas_cercana (usuarios.html) lee data-lat/data-lng de cada <option> del
    select de Sede — sin esto no tiene con qué calcular la distancia en el navegador."""
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Con Coordenadas', 'latitud': '6.244203', 'longitud': '-75.581215',
    })

    texto = admin_session.get('/usuarios').get_data(as_text=True)

    assert 'select-sede-nuevo-usuario' in texto
    assert 'data-lat="6.244203"' in texto
    assert 'data-lng="-75.581215"' in texto
    assert '_preseleccionarSedeMasCercana' in texto


def test_formulario_de_usuarios_incluye_sede_sin_coordenadas_pero_sin_data_lat(admin_session, app):
    """Una sede que todavía no tiene coordenadas cargadas (el caso de las que ya existían antes
    de este cambio) debe seguir apareciendo como opción elegible a mano, solo que el JS la salta
    al calcular la más cercana (ver el 'continue' en _sedeMasCercana por falta de data-lat)."""
    admin_session.post('/tickets/configuracion/nuevo', data={'tipo': 'sede', 'nombre': 'Sede Sin GPS Todavía'})

    texto = admin_session.get('/usuarios').get_data(as_text=True)

    assert 'Sede Sin GPS Todavía' in texto
