"""Pruebas de la funcionalidad de Cumpleaños pedida por Tomás, 26/09/2026:

  1) Campo 'fecha_nacimiento' en el perfil del usuario (BD + Registrar/Editar Usuario).
  2) Si la fecha de hoy coincide con el cumpleaños de un colaborador ACTIVO, se muestra una
     notificación emergente (pop-up) a todos los usuarios activos al cargar la plataforma.
"""
from datetime import datetime


def _hoy_mes_dia(app):
    return datetime.now(app.ZONA_HORARIA_COLOMBIA).date().strftime('%m-%d')


def _crear_usuario_con_nacimiento(app, usuario, nombre, fecha_nacimiento, estado='activo'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre, fecha_nacimiento) "
         "VALUES (%s, 'x', %s, 'estandar', %s, %s, %s)" if db_type == 'postgres' else
         "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre, fecha_nacimiento) "
         "VALUES (?, 'x', ?, 'estandar', ?, ?, ?)")
    cur.execute(q, (usuario, f'{usuario}@preventivaips.com.co', estado, nombre, fecha_nacimiento))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 1) Validación del campo
# ---------------------------------------------------------------------------

def test_fecha_nacimiento_valida_acepta_formato_correcto(app):
    assert app._fecha_nacimiento_valida('1990-05-14') == '1990-05-14'


def test_fecha_nacimiento_valida_rechaza_formato_invalido(app):
    assert app._fecha_nacimiento_valida('14/05/1990') is None
    assert app._fecha_nacimiento_valida('no es una fecha') is None
    assert app._fecha_nacimiento_valida('') is None
    assert app._fecha_nacimiento_valida(None) is None


def test_fecha_nacimiento_valida_rechaza_fecha_futura(app):
    assert app._fecha_nacimiento_valida('2099-01-01') is None


def test_registrar_usuario_guarda_fecha_nacimiento(admin_session, app):
    admin_session.post('/usuarios', data={
        'primer_nombre': 'Con', 'primer_apellido': 'Cumpleanos',
        'email': 'con.cumpleanos@preventivaips.com.co', 'password': 'ClaveSegura123',
        'especialidad': 'Auxiliar Administrativo', 'rol': 'estandar',
        'fecha_nacimiento': '1995-03-20',
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT fecha_nacimiento FROM usuarios WHERE correo = ?", ('con.cumpleanos@preventivaips.com.co',))
    fila = cur.fetchone()
    conn.close()
    assert fila is not None and fila[0] == '1995-03-20'


def test_editar_usuario_guarda_fecha_nacimiento(admin_session, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    usuario_id = cur.fetchone()[0]
    conn.close()

    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'fecha_nacimiento': '1988-11-02',
    })
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT fecha_nacimiento FROM usuarios WHERE id = ?", (usuario_id,))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == '1988-11-02'


# ---------------------------------------------------------------------------
# 2) Cálculo de cumpleaños de hoy + notificación emergente
# ---------------------------------------------------------------------------

def test_colaborador_con_cumpleanos_hoy_aparece_en_la_lista(app):
    mes_dia = _hoy_mes_dia(app)
    _crear_usuario_con_nacimiento(app, 'cumple_hoy', 'Persona Cumpleañera', f'1990-{mes_dia}')
    _crear_usuario_con_nacimiento(app, 'no_cumple_hoy', 'Otra Persona', '1990-01-01' if mes_dia != '01-01' else '1990-06-15')

    resultado = app._colaboradores_de_cumpleanos_hoy()
    assert 'Persona Cumpleañera' in resultado
    assert 'Otra Persona' not in resultado


def test_colaborador_inactivo_no_aparece_aunque_cumpla_hoy(app):
    mes_dia = _hoy_mes_dia(app)
    _crear_usuario_con_nacimiento(app, 'cumple_inactivo', 'Persona Inactiva', f'1990-{mes_dia}', estado='inactivo')
    resultado = app._colaboradores_de_cumpleanos_hoy()
    assert 'Persona Inactiva' not in resultado


def test_sin_fecha_nacimiento_no_rompe_el_calculo(app, crear_usuario):
    crear_usuario(nombre='Sin Fecha')
    resultado = app._colaboradores_de_cumpleanos_hoy()
    assert isinstance(resultado, list)


def test_pagina_muestra_el_popup_de_cumpleanos_si_alguien_cumple_hoy(admin_session, app):
    mes_dia = _hoy_mes_dia(app)
    _crear_usuario_con_nacimiento(app, 'cumple_hoy_vista', 'Visible Hoy', f'1992-{mes_dia}')

    texto = admin_session.get('/bienvenida').get_data(as_text=True)
    assert 'modal-cumpleanos-hoy' in texto
    assert 'Visible Hoy' in texto


def test_pagina_no_muestra_el_popup_si_nadie_cumple_hoy(admin_session, app):
    texto = admin_session.get('/bienvenida').get_data(as_text=True)
    assert 'modal-cumpleanos-hoy' not in texto


def test_popup_no_aparece_sin_sesion_iniciada(client, app):
    """El partial no debe ni intentar consultar la BD (y mucho menos mostrar nombres) en una
    página servida sin sesión iniciada."""
    mes_dia = _hoy_mes_dia(app)
    _crear_usuario_con_nacimiento(app, 'cumple_sin_sesion', 'No Debe Verse', f'1990-{mes_dia}')
    r = client.get('/login')
    texto = r.get_data(as_text=True)
    assert 'modal-cumpleanos-hoy' not in texto
