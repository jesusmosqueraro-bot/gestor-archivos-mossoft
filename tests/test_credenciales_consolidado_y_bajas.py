"""Pruebas de las mejoras a Altas/Bajas de Credenciales pedidas por Tomás, 26/09/2026:

  1) Crear usuario en Arkiv directamente desde el formulario de 'Nueva Alta' si no existe todavía.
  2) La vista principal consolida a 1 fila por colaborador (antes era 1 fila por
     colaborador+aplicativo).
  3) Botón/filtro para el histórico de colaboradores COMPLETAMENTE dados de baja (sin ningún
     acceso activo en ningún aplicativo) — distinto del filtro de Estado normal, que es por fila.
"""


def _crear_credencial_colaborador(app, colaborador='Empleado Editable', aplicativo='KUBAPP', password='ClaveInicial1',
                                   usuario_aplicativo=None, estado='activo'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO credenciales_colaboradores (colaborador, aplicativo, usuario_aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (%s, %s, %s, %s, '2026-01-01', %s, '2026-01-01 09:00:00', 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO credenciales_colaboradores (colaborador, aplicativo, usuario_aplicativo, password_cifrada, fecha_creacion, "
         "estado, fecha_registro, registrado_por) VALUES (?, ?, ?, ?, '2026-01-01', ?, '2026-01-01 09:00:00', 'admin')")
    cur.execute(q, (colaborador, aplicativo, usuario_aplicativo, app.encriptar_texto(password), estado))
    reg_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return reg_id


# ---------------------------------------------------------------------------
# 1) Alta rápida de usuario desde el formulario
# ---------------------------------------------------------------------------

def test_crear_usuario_rapido_desde_credenciales_crea_la_cuenta(admin_session, app):
    r = admin_session.post('/credenciales/colaboradores/usuarios/crear_rapido', data={
        'primer_nombre': 'Nueva', 'primer_apellido': 'Persona',
        'email': 'nueva.persona@preventivaips.com.co', 'especialidad': 'Auxiliar Administrativo',
    })
    assert r.status_code == 200
    data = r.get_json()
    assert data['ok'] is True
    assert data['usuario']

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT rol FROM usuarios WHERE correo = ?", ('nueva.persona@preventivaips.com.co',))
    fila = cur.fetchone()
    conn.close()
    assert fila is not None and fila[0] == 'estandar'


def test_crear_usuario_rapido_desde_credenciales_exige_campos_minimos(admin_session):
    r = admin_session.post('/credenciales/colaboradores/usuarios/crear_rapido', data={
        'primer_nombre': 'Incompleto',
    })
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_crear_usuario_rapido_desde_credenciales_requiere_permiso(client, app, crear_usuario):
    """Sin acceso a Bóveda de Accesos/Turnos/Inventario (el mismo candado que ya protege el resto
    del módulo), no se puede colar la creación de cuentas por esta puerta."""
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    r = client.post('/credenciales/colaboradores/usuarios/crear_rapido', data={
        'primer_nombre': 'X', 'primer_apellido': 'Y', 'email': 'x@preventivaips.com.co', 'especialidad': 'Algo',
    })
    assert r.status_code in (302, 403)


# ---------------------------------------------------------------------------
# 2) Vista consolidada: 1 fila por colaborador
# ---------------------------------------------------------------------------

def test_vista_consolidada_agrupa_varios_aplicativos_del_mismo_colaborador(admin_session, app):
    _crear_credencial_colaborador(app, colaborador='Ana Consolidada', aplicativo='KUBAPP')
    _crear_credencial_colaborador(app, colaborador='Ana Consolidada', aplicativo='SAMI')
    _crear_credencial_colaborador(app, colaborador='Otro Colaborador', aplicativo='Moodle')

    r = admin_session.get('/credenciales/colaboradores')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # Debe aparecer 'Ana Consolidada' UNA sola vez en la tabla principal, no dos.
    assert html.count('mr-1.5"></i>Ana Consolidada') == 1
    assert 'KUBAPP, SAMI' in html or 'KUBAPP' in html


def test_helper_colaboradores_consolidados_agrupa_por_colaborador(app):
    registros = [
        {'colaborador': 'Ana', 'aplicativo': 'KUBAPP', 'estado': 'activo'},
        {'colaborador': 'Ana', 'aplicativo': 'SAMI', 'estado': 'deshabilitado'},
        {'colaborador': 'Beto', 'aplicativo': 'Moodle', 'estado': 'activo'},
    ]
    grupos = app._colaboradores_consolidados(registros)
    assert len(grupos) == 2
    ana = next(g for g in grupos if g['colaborador'] == 'Ana')
    assert ana['total'] == 2 and ana['activos'] == 1 and ana['deshabilitados'] == 1
    assert ana['estado_resumen'] == 'activo'  # tiene al menos un acceso activo
    beto = next(g for g in grupos if g['colaborador'] == 'Beto')
    assert beto['estado_resumen'] == 'activo'


# ---------------------------------------------------------------------------
# 3) Histórico de bajas: colaborador SIN ningún acceso activo
# ---------------------------------------------------------------------------

def test_colaborador_completamente_deshabilitado_aparece_en_historico_de_bajas(admin_session, app):
    _crear_credencial_colaborador(app, colaborador='Persona De Baja', aplicativo='KUBAPP', estado='deshabilitado')
    _crear_credencial_colaborador(app, colaborador='Persona De Baja', aplicativo='SAMI', estado='deshabilitado')
    _crear_credencial_colaborador(app, colaborador='Persona Activa', aplicativo='KUBAPP', estado='activo')

    r = admin_session.get('/credenciales/colaboradores?vista=bajas')
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # 🔎 Se busca la marca del NOMBRE EN LA FILA de la tabla (no en el <datalist> de
    # autocompletar del modal "Nueva Alta", que sigue listando a todo el mundo).
    assert 'mr-1.5"></i>Persona De Baja' in html
    assert 'mr-1.5"></i>Persona Activa' not in html


def test_colaborador_con_un_solo_aplicativo_deshabilitado_no_es_baja_completa(admin_session, app):
    """Pierde acceso a UN aplicativo pero sigue activo en otro — NO debe contar como 'de baja'
    completa (distinto del filtro de Estado normal, que sí lo mostraría como deshabilitado en esa
    fila puntual)."""
    _crear_credencial_colaborador(app, colaborador='Persona Parcial', aplicativo='KUBAPP', estado='deshabilitado')
    _crear_credencial_colaborador(app, colaborador='Persona Parcial', aplicativo='SAMI', estado='activo')

    r = admin_session.get('/credenciales/colaboradores?vista=bajas')
    html = r.get_data(as_text=True)
    assert 'mr-1.5"></i>Persona Parcial' not in html

    r2 = admin_session.get('/credenciales/colaboradores')
    html2 = r2.get_data(as_text=True)
    assert 'mr-1.5"></i>Persona Parcial' in html2


def test_total_colaboradores_de_baja_se_muestra_como_contador(admin_session, app):
    _crear_credencial_colaborador(app, colaborador='Solo De Baja', aplicativo='KUBAPP', estado='deshabilitado')
    r = admin_session.get('/credenciales/colaboradores')
    html = r.get_data(as_text=True)
    assert 'Histórico de bajas' in html
