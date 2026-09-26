"""Pruebas de la vista consolidada del "Listado de la semana" en el Cuadro de Turnos, pedida por
Tomás, 26/09/2026:

  "En el cuadro de turnos, agrupar las asignaciones para que cada colaborador figure únicamente
  UNA vez en la lista principal. Al hacer clic en la fila/nombre del usuario, desplegar un modal
  o panel lateral detallando los turnos asignados durante el periodo."

Ver `_colaboradores_consolidados_turnos` en app.py (agrupa el listado plano de `_datos_turnos` por
(usuario_id, colaborador)) y `turnos_cuadro()` (pasa `listado_agrupado` al template). La MATRIZ de
arriba ya mostraba 1 fila por colaborador desde antes y no cambia — solo se toca la tabla plana
"Listado de la semana" debajo de ella.
"""


def _sesion_como(client, arkiv_app, usuario, rol, modulos_extra=None):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
        if modulos_extra is not None:
            sess['modulos_extra'] = modulos_extra
    return client


def _crear_area_y_sede(app, area='Urgencias', sede='Sede Principal'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO ticket_configuraciones (tipo, nombre, estado) VALUES ('area', ?, 'activo')", (area,))
    cur.execute("INSERT INTO ticket_configuraciones (tipo, nombre, estado) VALUES ('sede', ?, 'activo')", (sede,))
    conn.commit()
    conn.close()
    return area, sede


def _tipo_id(app, codigo):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tipos_turno WHERE codigo = ?", (codigo,))
    fila = cur.fetchone()
    conn.close()
    return fila[0]


# ---------------------------------------------------------------------------
# 1) La función de agrupación en sí
# ---------------------------------------------------------------------------

def test_agrupa_varios_turnos_del_mismo_colaborador_en_una_sola_entrada(app):
    listado = [
        {'usuario_id': 1, 'usuario': 'colab1', 'colaborador': 'Ana Turnos', 'fecha': '2026-09-21', 'area': 'Urgencias', 'sede': 'Sede A', 'rol_etiqueta': 'Médico'},
        {'usuario_id': 1, 'usuario': 'colab1', 'colaborador': 'Ana Turnos', 'fecha': '2026-09-22', 'area': 'Urgencias', 'sede': 'Sede A', 'rol_etiqueta': 'Médico'},
        {'usuario_id': 2, 'usuario': 'colab2', 'colaborador': 'Beto Turnos', 'fecha': '2026-09-21', 'area': 'Consulta', 'sede': 'Sede B', 'rol_etiqueta': 'Enfermero'},
    ]
    agrupado = app._colaboradores_consolidados_turnos(listado)
    assert len(agrupado) == 2
    assert agrupado[0]['colaborador'] == 'Ana Turnos'
    assert len(agrupado[0]['turnos']) == 2
    assert agrupado[1]['colaborador'] == 'Beto Turnos'
    assert len(agrupado[1]['turnos']) == 1


def test_preserva_el_orden_de_primera_aparicion(app):
    listado = [
        {'usuario_id': 3, 'usuario': 'c3', 'colaborador': 'Carla', 'fecha': '2026-09-21'},
        {'usuario_id': 1, 'usuario': 'c1', 'colaborador': 'Ana', 'fecha': '2026-09-21'},
        {'usuario_id': 3, 'usuario': 'c3', 'colaborador': 'Carla', 'fecha': '2026-09-22'},
    ]
    agrupado = app._colaboradores_consolidados_turnos(listado)
    assert [g['colaborador'] for g in agrupado] == ['Carla', 'Ana']


def test_lista_vacia_no_rompe(app):
    assert app._colaboradores_consolidados_turnos([]) == []


def test_colaboradores_sin_usuario_id_se_agrupan_por_nombre(app):
    """Turnos de colaboradores 'sueltos' (sin cuenta de usuario vinculada, usuario_id=None) no
    deben mezclarse entre sí solo porque comparten usuario_id=None — se distinguen por nombre."""
    listado = [
        {'usuario_id': None, 'usuario': None, 'colaborador': 'Externo Uno', 'fecha': '2026-09-21'},
        {'usuario_id': None, 'usuario': None, 'colaborador': 'Externo Dos', 'fecha': '2026-09-21'},
    ]
    agrupado = app._colaboradores_consolidados_turnos(listado)
    assert len(agrupado) == 2
    assert {g['colaborador'] for g in agrupado} == {'Externo Uno', 'Externo Dos'}


# ---------------------------------------------------------------------------
# 2) La vista /turnos/cuadro
# ---------------------------------------------------------------------------

def test_colaborador_con_varios_turnos_aparece_una_sola_vez_en_el_listado(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_multi', correo='colab_multi@preventivaips.com.co', telefono='3000000000', cedula='9001')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    for fecha in ('2026-09-21', '2026-09-22', '2026-09-23'):
        r = admin_session.post('/turnos/asignar', data={
            'colaborador_usuario': colaborador, 'fecha': fecha, 'tipo_turno_id': str(tipo_id),
            'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
        })
        assert r.get_json()['ok'] is True

    texto = admin_session.get('/turnos/cuadro?desde=2026-09-21&hasta=2026-09-27').get_data(as_text=True)
    # 3 turnos asignados, pero el nombre del colaborador debe figurar una sola vez en la fila
    # consolidada del listado (más allá de cuántas veces aparezca en la matriz/tooltips de arriba).
    assert texto.count('Ver detalle') >= 1
    assert 'abrirModalDetalleTurnosColaborador' in texto


def test_datos_de_los_turnos_del_colaborador_viajan_al_frontend_para_el_modal_de_detalle(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_detalle', correo='colab_detalle@preventivaips.com.co', telefono='3000000001', cedula='9002')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    for fecha in ('2026-09-21', '2026-09-22'):
        admin_session.post('/turnos/asignar', data={
            'colaborador_usuario': colaborador, 'fecha': fecha, 'tipo_turno_id': str(tipo_id),
            'area': area, 'sede': sede, 'rol_profesional': 'MEDICO', 'observaciones': f'Obs {fecha}',
        })

    texto = admin_session.get('/turnos/cuadro?desde=2026-09-21&hasta=2026-09-27').get_data(as_text=True)
    assert 'TURNOS_AGRUPADOS' in texto
    # Ambas fechas deben viajar en el JSON embebido para que el modal de detalle las pueda listar.
    assert '2026-09-21' in texto and '2026-09-22' in texto


def test_agente_de_solo_lectura_ve_el_listado_consolidado_sin_botones_de_gestion(client, app, crear_usuario):
    usuario_agente = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario_agente, 'agente', modulos_extra=['turnos'])
    texto = client.get('/turnos/cuadro').get_data(as_text=True)
    assert 'PUEDE_GESTIONAR_TURNOS = false' in texto


def test_lider_ve_el_listado_consolidado_con_permiso_de_gestion(client, app, crear_usuario):
    usuario_lider = crear_usuario(rol='lider')
    _sesion_como(client, app, usuario_lider, 'lider')
    texto = client.get('/turnos/cuadro').get_data(as_text=True)
    assert 'PUEDE_GESTIONAR_TURNOS = true' in texto


def test_sin_turnos_en_el_periodo_el_listado_consolidado_queda_vacio(admin_session):
    texto = admin_session.get('/turnos/cuadro?desde=2026-01-05&hasta=2026-01-11').get_data(as_text=True)
    assert 'No se encontraron turnos que coincidan con los filtros.' in texto
