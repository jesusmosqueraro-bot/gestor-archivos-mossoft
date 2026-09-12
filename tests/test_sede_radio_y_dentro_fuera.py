"""Pruebas de "dentro/fuera de sede" (pedido de Tomás, 12/09/2026): el catálogo real de Sedes
(/tickets/configuracion) ahora también guarda radio_metros (200m por defecto), y tanto un login
exitoso como el alta de un usuario calculan por Haversine (_sede_real_mas_cercana, en app.py) si
la ubicación detectada cayó dentro de ese radio — si sí, queda "dentro de sede"; si no, se
asigna igual la sede más cercana pero queda marcada "fuera de sede". Ver también
test_sede_mas_cercana.py (la preselección del campo Sede en el formulario) y
test_geolocalizacion_login.py (la captura de lat/lon del login), que estas pruebas no repiten."""
from werkzeug.security import generate_password_hash


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
    cur.execute("SELECT id, latitud, longitud, radio_metros FROM ticket_configuraciones WHERE tipo = 'sede' AND nombre = ?", (nombre,))
    fila = cur.fetchone()
    conn.close()
    return fila


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def _ultima_geolocalizacion(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT sede, dentro_de_sede FROM login_geolocalizacion WHERE usuario = ? ORDER BY id DESC LIMIT 1",
        (usuario,),
    )
    fila = cur.fetchone()
    conn.close()
    return fila


# --- radio_metros en el catálogo de Sedes ---

def test_crear_sede_guarda_el_radio_metros_indicado(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Con Radio', 'latitud': '6.244203', 'longitud': '-75.581215',
        'radio_metros': '350',
    })

    _, _, _, radio = _sede_por_nombre(app, 'Sede Con Radio')
    assert round(radio) == 350


def test_crear_sede_sin_radio_metros_usa_200_por_defecto(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Sin Radio Explicito', 'latitud': '6.244203', 'longitud': '-75.581215',
    })

    _, _, _, radio = _sede_por_nombre(app, 'Sede Sin Radio Explicito')
    assert round(radio) == 200


def test_crear_sede_con_radio_invalido_o_negativo_cae_a_200(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Radio Basura', 'radio_metros': 'no-es-un-numero',
    })
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Radio Negativo', 'radio_metros': '-50',
    })

    assert round(_sede_por_nombre(app, 'Sede Radio Basura')[3]) == 200
    assert round(_sede_por_nombre(app, 'Sede Radio Negativo')[3]) == 200


def test_editar_sede_actualiza_el_radio_metros(admin_session, app):
    admin_session.post('/tickets/configuracion/nuevo', data={'tipo': 'sede', 'nombre': 'Sede A Editar Radio'})
    config_id, _, _, _ = _sede_por_nombre(app, 'Sede A Editar Radio')

    admin_session.post(f'/tickets/configuracion/{config_id}/editar', data={
        'nombre': 'Sede A Editar Radio', 'radio_metros': '500',
    })

    assert round(_sede_por_nombre(app, 'Sede A Editar Radio')[3]) == 500


# --- Dentro/fuera de sede al registrar un acceso (login) ---

def test_login_dentro_del_radio_de_una_sede_real_la_asigna_y_marca_dentro(admin_session, app, monkeypatch):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Login Dentro', 'latitud': '6.244203', 'longitud': '-75.581215',
        'radio_metros': '200',
    })
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario_para_login(app, 'colaborador_login_dentro')

    client = app.app.test_client()
    client.post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '6.244203', 'longitud': '-75.581215',
    })

    sede, dentro = _ultima_geolocalizacion(app, usuario)
    assert sede == 'Sede Login Dentro'
    assert dentro in (True, 1)


def test_login_fuera_del_radio_asigna_la_mas_cercana_pero_marca_fuera(admin_session, app, monkeypatch):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Login Fuera', 'latitud': '6.244203', 'longitud': '-75.581215',
        'radio_metros': '150',
    })
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario_para_login(app, 'colaborador_login_fuera')

    client = app.app.test_client()
    # ~11km de la sede: muy lejos del radio de 150m, pero es la única sede con coordenadas.
    client.post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '6.34', 'longitud': '-75.58',
    })

    sede, dentro = _ultima_geolocalizacion(app, usuario)
    assert sede == 'Sede Login Fuera'
    assert dentro in (False, 0)


def test_login_sin_sedes_reales_con_coordenadas_deja_sede_nula(admin_session, app, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario_para_login(app, 'colaborador_sin_catalogo_sedes')

    client = app.app.test_client()
    client.post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123',
        'latitud': '6.244203', 'longitud': '-75.581215',
    })

    sede, dentro = _ultima_geolocalizacion(app, usuario)
    assert sede is None
    assert dentro is None


def test_login_sin_coordenadas_no_calcula_sede(admin_session, app, monkeypatch):
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Disponible', 'latitud': '6.244203', 'longitud': '-75.581215',
    })
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario_para_login(app, 'colaborador_sin_coordenadas')

    client = app.app.test_client()
    client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'})

    sede, dentro = _ultima_geolocalizacion(app, usuario)
    assert sede is None
    assert dentro is None


def crear_usuario_para_login(app, usuario):
    """Inserta directo en 'usuarios' (no pasa por _crear_usuario_interno) para estas pruebas de
    LOGIN — igual que hacen las fixtures de conftest, solo que con un nombre de usuario fijo."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre) VALUES (%s, %s, %s, 'estandar', 'activo', %s)"
         if db_type == 'postgres' else
         "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre) VALUES (?, ?, ?, 'estandar', 'activo', ?)")
    cur.execute(q, (usuario, generate_password_hash('ClaveSegura123'), f'{usuario}@preventivaips.com.co', usuario.title()))
    conn.commit()
    conn.close()
    return usuario


# --- Dentro/fuera de sede al crear un usuario (registro) ---

def test_crear_usuario_con_ubicacion_dentro_del_radio_marca_dentro(admin_session, app):
    especialidad = _crear_especialidad(app)
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Alta Dentro', 'latitud': '6.244203', 'longitud': '-75.581215',
        'radio_metros': '200',
    })

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Sofia', 'primer_apellido': 'Reyes',
        'email': 'sofia.reyes@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar', 'sede': 'Sede Alta Dentro',
        'latitud_detectada': '6.244203', 'longitud_detectada': '-75.581215',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede, sede_dentro_de_radio FROM usuarios WHERE correo = 'sofia.reyes@preventivaips.com.co'")
    sede, dentro = cur.fetchone()
    conn.close()
    assert sede == 'Sede Alta Dentro'
    assert dentro in (True, 1)


def test_crear_usuario_con_ubicacion_fuera_del_radio_marca_fuera(admin_session, app):
    especialidad = _crear_especialidad(app, 'Sin Radio Alta')
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Alta Fuera', 'latitud': '6.244203', 'longitud': '-75.581215',
        'radio_metros': '150',
    })

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Mario', 'primer_apellido': 'Luna',
        'email': 'mario.luna@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar', 'sede': 'Sede Alta Fuera',
        'latitud_detectada': '6.34', 'longitud_detectada': '-75.58',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede_dentro_de_radio FROM usuarios WHERE correo = 'mario.luna@preventivaips.com.co'")
    (dentro,) = cur.fetchone()
    conn.close()
    assert dentro in (False, 0)


def test_crear_usuario_sin_ubicacion_detectada_deja_dentro_de_radio_nulo(admin_session, app):
    especialidad = _crear_especialidad(app, 'Sin Ubicacion Alta')
    admin_session.post('/tickets/configuracion/nuevo', data={
        'tipo': 'sede', 'nombre': 'Sede Sin Deteccion', 'latitud': '6.244203', 'longitud': '-75.581215',
    })

    admin_session.post('/usuarios', data={
        'primer_nombre': 'Elena', 'primer_apellido': 'Cruz',
        'email': 'elena.cruz@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar', 'sede': 'Sede Sin Deteccion',
    }, follow_redirects=False)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT sede_dentro_de_radio FROM usuarios WHERE correo = 'elena.cruz@preventivaips.com.co'")
    (dentro,) = cur.fetchone()
    conn.close()
    assert dentro is None
