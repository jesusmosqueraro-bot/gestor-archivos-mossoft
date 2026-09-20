"""Pruebas del módulo "Cuadro de Turnos Hospitalarios y Administrativos" (pedido por Tomás,
20/09/2026): programación semanal de turnos, con matriz colaborador x día, publicación con
notificación por correo + WhatsApp, cierre de cuadros, y un catálogo administrable de tipos de
turno. Ver la sección "🗓️ CUADRO DE TURNOS..." en app.py para el diseño completo.

Puntos clave que estas pruebas verifican (siguiendo la revisión de 7 puntos que hizo Tomás sobre
su propia propuesta inicial):
  1) Esquema: las 4 tablas nuevas existen y tipos_turno viene sembrado con las jornadas típicas.
  2) Control de acceso: turnos_o_extra_required (rol operativo O permiso extra 'turnos') para el
     cuadro y la asignación; admin_required estricto para el catálogo de tipos; el endpoint
     compartido de búsqueda de usuarios se abre también con el permiso extra 'turnos' (pedido
     explícito: "que los usuarios se puedan buscar por numero de documento y/o nombre").
  3) Asignación: validaciones, resolución de colaborador_usuario -> id real (nunca expone el id
     numérico al frontend), turno inexistente/tipo inexistente.
  4) Conflictos de horario: SOLO avisan (no bloquean) — turnos consecutivos sin solape no avisan;
     un solape real sí, y se puede confirmar de todas formas con forzar=1.
  5) Turnos que cruzan la medianoche: _calcular_inicio_fin_real calcula fin_real al día siguiente.
  6) Cancelación: es baja lógica (estado='cancelado'), no borra la fila ni afecta el historial.
  7) Publicación: crea/reutiliza un cuadro, adopta los turnos sueltos del rango, y notifica SOLO
     los turnos sin ningún intento previo (no reenvía spam si se vuelve a publicar).
  8) Cierre de cuadro: solo procede si el cuadro está 'publicado'.
  9) Catálogo de Tipos de Turno: alta con cálculo automático de duración (incluyendo turnos que
     cruzan medianoche), código único, y baja lógica ('inactivo', no se borra).
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    (tid,) = cur.fetchone()
    conn.close()
    return tid


def _fila_turno(app, turno_id):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, cuadro_id, area, rol_profesional FROM turnos_asignados WHERE id = ?", (turno_id,))
    fila = cur.fetchone()
    conn.close()
    return fila


def _esperar_hasta(condicion, timeout=2.0, intervalo=0.02):
    """/turnos/publicar_semana dispara la notificación en threading.Thread (para no bloquear la
    respuesta HTTP mientras se envían correos/WhatsApp) — NO se debe reemplazar threading.Thread
    globalmente para 'volverlo síncrono' en las pruebas: threading.Timer (usado internamente por
    Flask-Limiter para expirar su almacenamiento en memoria) hereda de threading.Thread y se
    rompe si se sustituye esa clase a nivel de módulo (produce
    'AssertionError: Thread.__init__() not called' en pruebas totalmente ajenas a Turnos). En vez
    de eso, se espera activamente (con límite de tiempo) a que el hilo real termine de escribir en
    la base de datos, igual que cualquier prueba de una tarea asíncrona real."""
    import time
    limite = time.time() + timeout
    while time.time() < limite:
        if condicion():
            return True
        time.sleep(intervalo)
    return condicion()


def _mock_notificar_turno(monkeypatch, app):
    """Reemplaza notificar_turno() por una versión igual de rápida (sin red) pero que sigue
    dejando un rastro real en notificaciones_turnos, para poder probar la semántica de
    'no reenviar spam' (NOT EXISTS ... notificaciones_turnos) tal como la usa
    /turnos/publicar_semana, sin depender de la red ni de las credenciales de WhatsApp."""
    llamadas = []

    def _fake(turno_id, tipo_evento='CREACION'):
        conn, db_type = app.get_db()
        cur = conn.cursor()
        cur.execute("SELECT usuario_id FROM turnos_asignados WHERE id = ?", (turno_id,))
        fila = cur.fetchone()
        if fila:
            cur.execute(
                "INSERT INTO notificaciones_turnos (turno_id, usuario_id, canal, tipo_evento, estado, creado_en) VALUES (?,?,?,?,?,?)",
                (turno_id, fila[0], 'EMAIL', tipo_evento, 'enviado', app.obtener_fecha_actual()),
            )
            conn.commit()
        conn.close()
        llamadas.append(turno_id)

    monkeypatch.setattr(app, 'notificar_turno', _fake)
    return llamadas


def _total_notificaciones(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notificaciones_turnos")
    (n,) = cur.fetchone()
    conn.close()
    return n


# ---------------------------------------------------------------------------
# 1) Esquema
# ---------------------------------------------------------------------------

def test_las_tablas_de_turnos_existen(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    for tabla in ('tipos_turno', 'cuadros_turnos', 'turnos_asignados', 'notificaciones_turnos'):
        cur.execute(f"SELECT COUNT(*) FROM {tabla}")  # no debe reventar
    conn.close()


def test_tipos_turno_viene_sembrado_con_las_jornadas_tipicas(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT codigo FROM tipos_turno ORDER BY orden ASC")
    codigos = [f[0] for f in cur.fetchall()]
    conn.close()
    assert set(codigos) == {'M6_12', 'T12_18', 'N18_6', 'DIA_12', 'ADMIN_8_17', 'DESCANSO'}


# ---------------------------------------------------------------------------
# 2) Control de acceso
# ---------------------------------------------------------------------------

def test_anonimo_no_entra_al_cuadro(client):
    r = client.get('/turnos/cuadro', follow_redirects=False)
    assert r.status_code == 302


def test_estandar_sin_permiso_extra_sigue_bloqueado_del_cuadro(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')
    assert client.get('/turnos/cuadro').status_code in (302, 403)


def test_estandar_con_el_permiso_extra_turnos_entra_al_cuadro(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['turnos'])
    assert client.get('/turnos/cuadro').status_code == 200


def test_el_permiso_extra_turnos_es_puntual_no_abre_tipos_de_turno(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['turnos'])
    assert client.get('/turnos/tipos').status_code in (302, 403)


def test_agente_entra_al_cuadro_sin_necesitar_el_permiso_extra(client, app, crear_usuario):
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    assert client.get('/turnos/cuadro').status_code == 200


def test_turnos_tipos_es_exclusivo_de_admin_ni_agente_entra(client, app, crear_usuario):
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    assert client.get('/turnos/tipos').status_code in (302, 403)


def test_admin_entra_al_catalogo_de_tipos(admin_session):
    assert admin_session.get('/turnos/tipos').status_code == 200


def test_buscador_compartido_de_usuarios_se_abre_con_el_permiso_extra_turnos(client, app, crear_usuario):
    """El pedido explícito de Tomás ("que los usuarios se puedan buscar por numero de documento
    y/o nombre" en el selector de colaborador) reutiliza /usuarios/buscar y /usuarios/buscar_cedula
    — ver inventario_o_boveda_o_extra_required, ahora extendido con 'turnos'."""
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['turnos'])
    assert client.get('/usuarios/buscar_cedula?cedula=123').status_code == 200
    assert client.get('/usuarios/buscar?q=ab').status_code == 200


def test_buscador_compartido_sigue_bloqueado_sin_ningun_permiso_de_los_tres(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=[])
    assert client.get('/usuarios/buscar_cedula?cedula=123').status_code in (302, 403)


# ---------------------------------------------------------------------------
# 3) Asignación de turnos
# ---------------------------------------------------------------------------

def test_asignar_turno_exitoso(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_asignar', correo='colab_asignar@preventivaips.com.co', telefono='3001112233', cedula='1001')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO', 'observaciones': 'Cubre incapacidad',
    })

    data = r.get_json()
    assert data['ok'] is True
    fila = _fila_turno(app, data['turno_id'])
    assert fila == ('activo', None, area, 'MEDICO')


def test_asignar_turno_sin_colaborador_valido_no_expone_el_id_ni_crea_nada(admin_session, app):
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': 'no_existe_este_usuario', 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.status_code == 400
    assert 'No se encontró ese colaborador' in r.get_json()['errores'][0]


def test_asignar_turno_valida_todos_los_campos_obligatorios(admin_session):
    r = admin_session.post('/turnos/asignar', data={})
    assert r.status_code == 400
    errores = r.get_json()['errores']
    assert len(errores) >= 5


def test_asignar_turno_con_tipo_de_turno_inexistente(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_tipo_malo')
    area, sede = _crear_area_y_sede(app)

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': '999999',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.status_code == 400
    assert 'ya no existe' in r.get_json()['errores'][0]


def test_asignar_turno_rechaza_rol_profesional_invalido(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_rol_malo')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'INVENTADO',
    })

    assert r.status_code == 400


def test_editar_turno_existente_no_cambia_el_colaborador_solo_los_demas_campos(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_editar')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']

    r = admin_session.post('/turnos/asignar', data={
        'turno_id': str(turno_id), 'colaborador_usuario': colaborador, 'fecha': '2026-09-21',
        'tipo_turno_id': str(tipo_id), 'area': area, 'sede': sede, 'rol_profesional': 'ENFERMERO_JEFE',
        'observaciones': 'Cambio de rol',
    })

    assert r.get_json()['ok'] is True
    fila = _fila_turno(app, turno_id)
    assert fila[3] == 'ENFERMERO_JEFE'


# ---------------------------------------------------------------------------
# 4) Conflictos de horario: avisan, no bloquean (revisión explícita de Tomás sobre su propuesta)
# ---------------------------------------------------------------------------

def test_turnos_consecutivos_sin_solape_no_generan_conflicto(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_consecutivo')
    area, sede = _crear_area_y_sede(app)
    tipo_manana = _tipo_id(app, 'M6_12')   # 06:00-12:00
    tipo_tarde = _tipo_id(app, 'T12_18')   # 12:00-18:00 (empieza justo cuando termina el anterior)

    r1 = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_manana),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    r2 = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_tarde),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r1.get_json()['ok'] is True
    assert r2.get_json()['ok'] is True


def test_solape_real_de_horario_avisa_pero_no_bloquea_y_se_puede_forzar(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_solape')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r_sin_forzar = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    data = r_sin_forzar.get_json()
    assert data['ok'] is False
    assert data['conflicto'] is True
    assert len(data['turnos_conflicto']) == 1

    r_forzado = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO', 'forzar': '1',
    })
    assert r_forzado.get_json()['ok'] is True


def test_un_turno_cancelado_no_cuenta_para_el_conflicto(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_cancelado_conflicto')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    primero = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']
    admin_session.post(f'/turnos/asignados/{primero}/eliminar')

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    assert r.get_json()['ok'] is True


# ---------------------------------------------------------------------------
# 5) Turnos que cruzan la medianoche (revisión explícita de Tomás: "manejar turnos nocturnos con
#    timestamps reales, no solo con el campo de fecha")
# ---------------------------------------------------------------------------

def test_calcular_inicio_fin_real_turno_nocturno_cruza_medianoche(app):
    inicio, fin = app._calcular_inicio_fin_real('2026-09-21', '18:00', '06:00')
    assert inicio == '2026-09-21 18:00:00'
    assert fin == '2026-09-22 06:00:00'


def test_calcular_inicio_fin_real_turno_normal_mismo_dia(app):
    inicio, fin = app._calcular_inicio_fin_real('2026-09-21', '06:00', '12:00')
    assert inicio == '2026-09-21 06:00:00'
    assert fin == '2026-09-21 12:00:00'


def test_turno_nocturno_conflicto_con_el_dia_siguiente(admin_session, app, crear_usuario):
    """Un colaborador con turno Noche (18:00-06:00) el día 21 no puede tener, sin aviso, otro
    turno que empiece antes de las 06:00 del día 22 (fin_real real es 2026-09-22 06:00:00)."""
    colaborador = crear_usuario(usuario='colab_nocturno')
    area, sede = _crear_area_y_sede(app)
    tipo_noche = _tipo_id(app, 'N18_6')
    tipo_manana = _tipo_id(app, 'M6_12')

    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_noche),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    # Turno "mañana" del día 22 empieza justo cuando termina la noche del 21 (06:00) -> sin solape.
    r_sin_solape = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-22', 'tipo_turno_id': str(tipo_manana),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    assert r_sin_solape.get_json()['ok'] is True


# ---------------------------------------------------------------------------
# 6) Cancelación = baja lógica
# ---------------------------------------------------------------------------

def test_cancelar_turno_no_borra_la_fila_solo_cambia_el_estado(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_baja_logica')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']

    r = admin_session.post(f'/turnos/asignados/{turno_id}/eliminar')

    assert r.get_json()['ok'] is True
    fila = _fila_turno(app, turno_id)
    assert fila is not None
    assert fila[0] == 'cancelado'


def test_turno_cancelado_no_aparece_en_el_listado_de_la_semana(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_no_en_listado')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']
    admin_session.post(f'/turnos/asignados/{turno_id}/eliminar')

    listado_ids = [r['id'] for r in app._datos_turnos('2026-09-21', '2026-09-21')]
    assert turno_id not in listado_ids


# ---------------------------------------------------------------------------
# 7) Publicación: crea/reutiliza cuadro, adopta turnos sueltos, notifica solo una vez por turno
# ---------------------------------------------------------------------------

def test_publicar_semana_crea_el_cuadro_y_lo_marca_publicado(admin_session, app, crear_usuario, monkeypatch):
    _mock_notificar_turno(monkeypatch, app)
    colaborador = crear_usuario(usuario='colab_publicar')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27')
    data = r.get_json()

    # 'notificando' se calcula de forma síncrona (antes de disparar el hilo), así que no depende
    # de que el hilo de aviso ya haya terminado.
    assert data['ok'] is True
    assert data['notificando'] == 1
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM cuadros_turnos WHERE id = ?", (data['cuadro_id'],))
    (estado,) = cur.fetchone()
    conn.close()
    assert estado == 'publicado'
    # Se espera a que el hilo de aviso termine antes de que la prueba acabe: si sigue vivo cuando
    # la prueba SIGUIENTE borra/recrea la base sqlite (fixture autouse _base_de_datos_limpia),
    # revienta con "attempt to write a readonly database" en un hilo que nadie está esperando.
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 1)


def test_publicar_de_nuevo_no_reenvia_a_turnos_ya_notificados(admin_session, app, crear_usuario, monkeypatch):
    _mock_notificar_turno(monkeypatch, app)
    colaborador = crear_usuario(usuario='colab_no_reenvio')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    primera = admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27').get_json()
    assert primera['notificando'] == 1
    # El envío real ocurre en threading.Thread (para no bloquear la respuesta) — se espera a que
    # termine de escribir su fila en notificaciones_turnos antes de publicar de nuevo, en vez de
    # asumir que ya terminó (ver _esperar_hasta).
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 1)

    segunda = admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27').get_json()

    assert segunda['ok'] is True
    assert segunda['notificando'] == 0


def test_un_turno_agregado_despues_de_publicar_si_se_notifica_en_la_siguiente_publicacion(admin_session, app, crear_usuario, monkeypatch):
    _mock_notificar_turno(monkeypatch, app)
    colaborador = crear_usuario(usuario='colab_turno_nuevo')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27')
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 1)

    # Se agrega un turno nuevo dentro de la misma semana, después de la primera publicación.
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-22', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    segunda = admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27').get_json()

    assert segunda['notificando'] == 1
    # Espera a que el segundo hilo también termine antes de que la prueba acabe (mismo motivo).
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 2)


def test_publicar_respeta_el_filtro_de_sede_area_al_adoptar_turnos(admin_session, app, crear_usuario, monkeypatch):
    _mock_notificar_turno(monkeypatch, app)
    colaborador = crear_usuario(usuario='colab_filtro_publicar')
    area_a, sede_a = _crear_area_y_sede(app, area='Urgencias', sede='SedePrincipal')
    area_b, sede_b = _crear_area_y_sede(app, area='ConsultaExterna', sede='SedeNorte')
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area_a, 'sede': sede_a, 'rol_profesional': 'MEDICO',
    })
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area_b, 'sede': sede_b, 'rol_profesional': 'MEDICO', 'forzar': '1',
    })

    r = admin_session.post(f'/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27&sede={sede_a}&area={area_a}')

    assert r.get_json()['notificando'] == 1
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 1)


# ---------------------------------------------------------------------------
# 8) Cierre de cuadro
# ---------------------------------------------------------------------------

def test_no_se_puede_cerrar_un_cuadro_que_sigue_en_borrador(admin_session, app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO cuadros_turnos (nombre, periodo_inicio, periodo_fin, creado_por, fecha_creacion) VALUES ('Semana X', '2026-09-21', '2026-09-27', 'admin', '2026-09-20 00:00:00')")
    cuadro_id = cur.lastrowid
    conn.commit()
    conn.close()

    r = admin_session.post(f'/turnos/cuadros/{cuadro_id}/cerrar')

    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_cerrar_un_cuadro_publicado(admin_session, app, crear_usuario, monkeypatch):
    _mock_notificar_turno(monkeypatch, app)
    colaborador = crear_usuario(usuario='colab_cerrar_cuadro')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    cuadro_id = admin_session.post('/turnos/publicar_semana?desde=2026-09-21&hasta=2026-09-27').get_json()['cuadro_id']
    assert _esperar_hasta(lambda: _total_notificaciones(app) >= 1)

    r = admin_session.post(f'/turnos/cuadros/{cuadro_id}/cerrar')

    assert r.get_json()['ok'] is True
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, cerrado_por FROM cuadros_turnos WHERE id = ?", (cuadro_id,))
    estado, cerrado_por = cur.fetchone()
    conn.close()
    assert estado == 'cerrado'
    assert cerrado_por == 'admin'


# ---------------------------------------------------------------------------
# 9) Notificaciones: correo funciona ya, WhatsApp queda registrado como pendiente sin credenciales
# ---------------------------------------------------------------------------

def test_notificar_turno_registra_email_enviado_y_whatsapp_sin_configurar(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_notificar', correo='colab_notificar@preventivaips.com.co', telefono='3005556677')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']

    app.notificar_turno(turno_id, 'CREACION')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT canal, estado, error FROM notificaciones_turnos WHERE turno_id = ?", (turno_id,))
    filas = {c: (e, err) for c, e, err in cur.fetchall()}
    conn.close()
    assert filas['EMAIL'][0] == 'enviado'
    assert filas['WHATSAPP'][0] == 'error'
    assert 'no está configurado' in filas['WHATSAPP'][1]


def test_notificar_turno_sin_correo_registrado_marca_error_en_email(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_sin_correo')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET correo = '' WHERE usuario = ?", (colaborador,))
    conn.commit()
    conn.close()
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']

    app.notificar_turno(turno_id, 'CREACION')

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado, error FROM notificaciones_turnos WHERE turno_id = ? AND canal = 'EMAIL'", (turno_id,))
    estado, error = cur.fetchone()
    conn.close()
    assert estado == 'error'
    assert 'no tiene correo registrado' in error


def test_whatsapp_turno_configurado_es_false_sin_variables_de_entorno(app, monkeypatch):
    monkeypatch.setattr(app, 'WHATSAPP_CLOUD_API_TOKEN', None)
    monkeypatch.setattr(app, 'WHATSAPP_CLOUD_API_PHONE_ID', None)
    assert app._whatsapp_turno_configurado() is False


# ---------------------------------------------------------------------------
# 10) Catálogo de Tipos de Turno (admin_required estricto)
# ---------------------------------------------------------------------------

def test_crear_tipo_de_turno_calcula_la_duracion_automaticamente(admin_session, app):
    r = admin_session.post('/turnos/tipos', data={
        'codigo': 'TARDE_14_22', 'nombre': 'Tarde 14 a 22', 'hora_inicio': '14:00', 'hora_fin': '22:00',
        'categoria': 'ASISTENCIAL', 'color_hex': '#f97316',
    }, follow_redirects=False)
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_horas, estado FROM tipos_turno WHERE codigo = 'TARDE_14_22'")
    duracion, estado = cur.fetchone()
    conn.close()
    assert float(duracion) == 8.0
    assert estado == 'activo'


def test_crear_tipo_de_turno_nocturno_calcula_bien_la_duracion_cruzando_medianoche(admin_session, app):
    admin_session.post('/turnos/tipos', data={
        'codigo': 'NOCHE_22_5', 'nombre': 'Noche larga', 'hora_inicio': '22:00', 'hora_fin': '05:00',
        'categoria': 'ASISTENCIAL',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT duracion_horas FROM tipos_turno WHERE codigo = 'NOCHE_22_5'")
    (duracion,) = cur.fetchone()
    conn.close()
    assert float(duracion) == 7.0


def test_crear_tipo_de_turno_con_codigo_repetido_no_crea_duplicado(admin_session, app):
    admin_session.post('/turnos/tipos', data={
        'codigo': 'M6_12', 'nombre': 'Otra mañana', 'hora_inicio': '06:00', 'hora_fin': '12:00',
    }, follow_redirects=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tipos_turno WHERE codigo = 'M6_12'")
    (n,) = cur.fetchone()
    conn.close()
    assert n == 1


def test_desactivar_tipo_de_turno_es_baja_logica(admin_session, app):
    tipo_id = _tipo_id(app, 'DESCANSO')

    r = admin_session.post(f'/turnos/tipos/{tipo_id}/eliminar', follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM tipos_turno WHERE id = ?", (tipo_id,))
    (estado,) = cur.fetchone()
    conn.close()
    assert estado == 'inactivo'


def test_desactivar_tipo_de_turno_no_afecta_turnos_ya_asignados_con_el(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_tipo_desactivado')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'DESCANSO')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'ADMINISTRATIVO',
    }).get_json()['turno_id']

    admin_session.post(f'/turnos/tipos/{tipo_id}/eliminar')

    fila = _fila_turno(app, turno_id)
    assert fila[0] == 'activo'


# ---------------------------------------------------------------------------
# 11) Exportaciones (respetan filtros, mismo patrón que Geolocalización)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('ruta,content_type_esperado', [
    ('/turnos/exportar_csv', 'text/csv'),
    ('/turnos/exportar_xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
    ('/turnos/exportar_pdf', 'application/pdf'),
])
def test_exportaciones_devuelven_el_content_type_correcto(admin_session, app, crear_usuario, ruta, content_type_esperado):
    colaborador = crear_usuario(usuario=f'colab_export_{ruta[-3:]}')
    area, sede = _crear_area_y_sede(app, area=f'Area{ruta[-3:]}', sede=f'Sede{ruta[-3:]}')
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.get(f'{ruta}?desde=2026-09-21&hasta=2026-09-27')

    assert r.status_code == 200
    assert content_type_esperado in r.headers['Content-Type']
    assert 'Arkiv_CuadroTurnos_' in r.headers['Content-Disposition']


# ---------------------------------------------------------------------------
# 12) La página del cuadro renderiza sin reventar con datos reales (matriz + listado + modal)
# ---------------------------------------------------------------------------

def test_pagina_del_cuadro_renderiza_con_un_turno_real_sin_reventar(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_render', nombre="María O'Higgins Pérez")
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO', 'observaciones': "Nota con 'comillas' y \"dobles\"",
    })

    r = admin_session.get('/turnos/cuadro?desde=2026-09-21')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'data-ayuda-modulo="turnos_cuadro"' in texto
    assert 'data-tabla-interactiva="turnos"' in texto


# ---------------------------------------------------------------------------
# 13) Horario personalizado (pedido de Tomás, 20/09/2026: "que se puedan crear horarios desde
#     cero para los turnos, poder crear horarios específicos") — ver
#     _resolver_tipo_turno_personalizado: encuentra-o-crea, idempotente, en el mismo catálogo
#     tipos_turno (es_personalizado=true), sin tocar turnos_asignados.tipo_turno_id (sigue
#     NOT NULL). Los personalizados quedan OCULTOS del desplegable normal.
# ---------------------------------------------------------------------------

def test_asignar_con_horario_personalizado_crea_un_tipo_libre_marcado_personalizado(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_libre_1')
    area, sede = _crear_area_y_sede(app)

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'horario_personalizado': '1',
        'hora_inicio_libre': '19:00', 'hora_fin_libre': '07:00', 'nombre_horario_libre': 'Turno especial',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.get_json()['ok'] is True
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT nombre, es_personalizado, hora_inicio, hora_fin FROM tipos_turno WHERE codigo = 'LIBRE-1900-0700'")
    nombre, es_personalizado, hora_inicio, hora_fin = cur.fetchone()
    conn.close()
    assert nombre == 'Turno especial'
    assert bool(es_personalizado) is True
    assert hora_inicio == '19:00' and hora_fin == '07:00'


def test_horario_personalizado_es_idempotente_reutiliza_el_mismo_tipo(admin_session, app, crear_usuario):
    colaborador_1 = crear_usuario(usuario='colab_libre_2a')
    colaborador_2 = crear_usuario(usuario='colab_libre_2b')
    area, sede = _crear_area_y_sede(app)

    r1 = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador_1, 'fecha': '2026-09-21', 'horario_personalizado': '1',
        'hora_inicio_libre': '10:00', 'hora_fin_libre': '16:00',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()
    r2 = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador_2, 'fecha': '2026-09-22', 'horario_personalizado': '1',
        'hora_inicio_libre': '10:00', 'hora_fin_libre': '16:00',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo_turno_id FROM turnos_asignados WHERE id IN (?, ?)", (r1['turno_id'], r2['turno_id']))
    ids_tipo = {f[0] for f in cur.fetchall()}
    cur.execute("SELECT COUNT(*) FROM tipos_turno WHERE codigo = 'LIBRE-1000-1600'")
    (total_filas,) = cur.fetchone()
    conn.close()
    assert len(ids_tipo) == 1  # ambos turnos reutilizan el MISMO tipo, no crean uno cada uno
    assert total_filas == 1


def test_horario_personalizado_con_horas_invalidas_es_rechazado(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_libre_3')
    area, sede = _crear_area_y_sede(app)

    r = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'horario_personalizado': '1',
        'hora_inicio_libre': 'no-es-hora', 'hora_fin_libre': '07:00',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.status_code == 400
    assert 'horario personalizado' in r.get_json()['errores'][0].lower()


def test_tipos_turno_personalizados_no_aparecen_en_el_catalogo_del_desplegable(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_libre_4')
    area, sede = _crear_area_y_sede(app)
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'horario_personalizado': '1',
        'hora_inicio_libre': '08:00', 'hora_fin_libre': '20:00',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    codigos_activos = {t['codigo'] for t in app._tipos_turno_activos()}
    assert 'LIBRE-0800-2000' not in codigos_activos


# ---------------------------------------------------------------------------
# 14) Asignación por grupo (pedido de Tomás, 20/09/2026: "modificar el horario de una persona o
#     varias personas o de todo el grupo") — /turnos/asignar_grupo. Solo CREA turnos nuevos;
#     misma filosofía de conflictos "avisa, no bloquea" que /turnos/asignar, pero por lote.
# ---------------------------------------------------------------------------

def test_asignar_grupo_crea_un_turno_para_cada_colaborador_marcado(admin_session, app, crear_usuario):
    c1 = crear_usuario(usuario='grupo_col_1')
    c2 = crear_usuario(usuario='grupo_col_2')
    c3 = crear_usuario(usuario='grupo_col_3')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar_grupo', data={
        'colaboradores_usuario': [c1, c2, c3], 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    data = r.get_json()
    assert data['ok'] is True
    assert data['total'] == 3
    assert data['no_encontrados'] == []
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM turnos_asignados WHERE fecha = '2026-09-21' AND estado = 'activo'")
    (total,) = cur.fetchone()
    conn.close()
    assert total == 3


def test_asignar_grupo_reporta_pero_no_revienta_por_colaboradores_inexistentes(admin_session, app, crear_usuario):
    c1 = crear_usuario(usuario='grupo_col_existe')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar_grupo', data={
        'colaboradores_usuario': [c1, 'usuario_que_no_existe'], 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    data = r.get_json()
    assert data['ok'] is True
    assert data['total'] == 1
    assert data['no_encontrados'] == ['usuario_que_no_existe']


def test_asignar_grupo_avisa_conflicto_por_colaborador_y_se_puede_forzar_el_lote(admin_session, app, crear_usuario):
    c1 = crear_usuario(usuario='grupo_col_conflicto_1')
    c2 = crear_usuario(usuario='grupo_col_conflicto_2')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    # c1 ya tiene un turno ese día -> al asignarle el grupo de nuevo, debe generar conflicto SOLO
    # para c1, no para c2.
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': c1, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r_sin_forzar = admin_session.post('/turnos/asignar_grupo', data={
        'colaboradores_usuario': [c1, c2], 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })
    data = r_sin_forzar.get_json()
    assert data['ok'] is False
    assert data['conflicto'] is True
    assert list(data['conflictos_por_colaborador'].keys()) == [c1]

    r_forzado = admin_session.post('/turnos/asignar_grupo', data={
        'colaboradores_usuario': [c1, c2], 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO', 'forzar': '1',
    })
    assert r_forzado.get_json()['ok'] is True
    assert r_forzado.get_json()['total'] == 2


def test_asignar_grupo_sin_colaboradores_es_rechazado(admin_session, app):
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')

    r = admin_session.post('/turnos/asignar_grupo', data={
        'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id), 'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.status_code == 400


def test_asignar_grupo_admite_horario_personalizado_igual_que_el_individual(admin_session, app, crear_usuario):
    c1 = crear_usuario(usuario='grupo_col_libre_1')
    c2 = crear_usuario(usuario='grupo_col_libre_2')
    area, sede = _crear_area_y_sede(app)

    r = admin_session.post('/turnos/asignar_grupo', data={
        'colaboradores_usuario': [c1, c2], 'fecha': '2026-09-21', 'horario_personalizado': '1',
        'hora_inicio_libre': '09:00', 'hora_fin_libre': '17:00',
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    assert r.get_json()['ok'] is True
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tipos_turno WHERE codigo = 'LIBRE-0900-1700'")
    (total_tipos,) = cur.fetchone()
    conn.close()
    assert total_tipos == 1  # un solo tipo creado, reutilizado para los dos colaboradores del grupo


# ---------------------------------------------------------------------------
# 15) Favoritos de colaborador (personal de quien los marca, ordenan arriba de la matriz)
# ---------------------------------------------------------------------------

def test_alternar_favorito_colaborador_marca_y_desmarca(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_favorito_1')

    r1 = admin_session.post(f'/turnos/favoritos/{colaborador}/alternar')
    assert r1.get_json() == {'ok': True, 'favorito': True}

    r2 = admin_session.post(f'/turnos/favoritos/{colaborador}/alternar')
    assert r2.get_json() == {'ok': True, 'favorito': False}


def test_favorito_es_personal_de_quien_lo_marca_no_afecta_a_otro_admin(admin_session, app, client, crear_usuario):
    colaborador = crear_usuario(usuario='colab_favorito_2')
    otro_admin = crear_usuario(usuario='otro_admin_favoritos', rol='admin')
    admin_session.post(f'/turnos/favoritos/{colaborador}/alternar')

    assert colaborador in app._favoritos_colaboradores_de('admin')
    assert colaborador not in app._favoritos_colaboradores_de(otro_admin)


def test_colaborador_favorito_aparece_primero_en_la_matriz(admin_session, app, crear_usuario):
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    zzz = crear_usuario(usuario='colab_zzz_no_favorito', nombre='Zzz Ultimo Alfabetico')
    aaa = crear_usuario(usuario='colab_aaa_favorito', nombre='Aaa Primero Alfabetico')
    for c in (zzz, aaa):
        admin_session.post('/turnos/asignar', data={
            'colaborador_usuario': c, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
            'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
        })
    # 'zzz' iría de últimas alfabéticamente, pero al marcarla favorita debe subir primero.
    admin_session.post(f'/turnos/favoritos/{zzz}/alternar')

    r = admin_session.get('/turnos/cuadro?desde=2026-09-21')
    texto = r.get_data(as_text=True)
    assert texto.index('Zzz Ultimo Alfabetico') < texto.index('Aaa Primero Alfabetico')


# ---------------------------------------------------------------------------
# 16) Vistas favoritas (combinación de Sede/Área/Rol guardada con nombre; una puede ser la
#     predeterminada que se precarga sola al entrar sin filtros en la URL)
# ---------------------------------------------------------------------------

def test_guardar_vista_favorita_y_marcarla_predeterminada(admin_session, app):
    area, sede = _crear_area_y_sede(app)

    r = admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Mi vista', 'area': area, 'sede': sede, 'es_default': '1'})
    data = r.get_json()
    assert data['ok'] is True

    vistas = app._vistas_favoritas_de('admin')
    assert len(vistas) == 1
    assert vistas[0]['nombre'] == 'Mi vista'
    assert vistas[0]['es_default'] is True
    assert app._vista_favorita_default('admin') == {'area': area, 'sede': sede, 'rol': ''}


def test_guardar_vista_sin_nombre_es_rechazado(admin_session):
    r = admin_session.post('/turnos/vistas/guardar', data={'nombre': '', 'area': 'X'})
    assert r.status_code == 400
    assert r.get_json()['ok'] is False


def test_solo_una_vista_puede_ser_predeterminada_a_la_vez(admin_session, app):
    id1 = admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Vista 1', 'es_default': '1'}).get_json()['vista_id']
    id2 = admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Vista 2', 'es_default': '1'}).get_json()['vista_id']

    vistas = {v['id']: v['es_default'] for v in app._vistas_favoritas_de('admin')}
    assert vistas[id1] is False
    assert vistas[id2] is True

    admin_session.post(f'/turnos/vistas/{id1}/predeterminar')
    vistas = {v['id']: v['es_default'] for v in app._vistas_favoritas_de('admin')}
    assert vistas[id1] is True
    assert vistas[id2] is False


def test_predeterminar_una_vista_ajena_falla(admin_session, app, crear_usuario):
    otro = crear_usuario(usuario='dueno_de_la_vista', rol='admin')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO turnos_vistas_favoritas (usuario, nombre, es_default, creado_en) VALUES (?, ?, 0, ?)", (otro, 'Vista ajena', app.obtener_fecha_actual()))
    vista_id = cur.lastrowid
    conn.commit()
    conn.close()

    r = admin_session.post(f'/turnos/vistas/{vista_id}/predeterminar')
    assert r.status_code == 404


def test_eliminar_vista_favorita_ajena_falla_y_no_borra_nada(admin_session, app, crear_usuario):
    otro = crear_usuario(usuario='dueno_de_la_vista_2', rol='admin')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO turnos_vistas_favoritas (usuario, nombre, es_default, creado_en) VALUES (?, ?, 0, ?)", (otro, 'Vista ajena 2', app.obtener_fecha_actual()))
    vista_id = cur.lastrowid
    conn.commit()
    conn.close()

    r = admin_session.post(f'/turnos/vistas/{vista_id}/eliminar')

    assert r.status_code == 404
    assert len(app._vistas_favoritas_de(otro)) == 1


def test_eliminar_vista_propia_funciona(admin_session, app):
    vista_id = admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Para borrar'}).get_json()['vista_id']

    r = admin_session.post(f'/turnos/vistas/{vista_id}/eliminar')

    assert r.get_json()['ok'] is True
    assert app._vistas_favoritas_de('admin') == []


def test_vista_predeterminada_se_precarga_sola_sin_filtros_en_la_url(admin_session, app):
    area, sede = _crear_area_y_sede(app, area='AreaDefault', sede='SedeDefault')
    admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Default', 'area': area, 'sede': sede, 'es_default': '1'})

    r = admin_session.get('/turnos/cuadro')

    assert r.status_code == 200
    # Si la vista default se aplicó, el <select> de Sede debe traer esa Sede ya seleccionada.
    texto = r.get_data(as_text=True)
    assert f'value="{sede}" selected' in texto


def test_vista_predeterminada_no_se_aplica_si_la_url_ya_trae_filtros_explicitos(admin_session, app):
    area, sede = _crear_area_y_sede(app, area='AreaDefault2', sede='SedeDefault2')
    admin_session.post('/turnos/vistas/guardar', data={'nombre': 'Default2', 'area': area, 'sede': sede, 'es_default': '1'})

    # El propio usuario limpia filtros a mano (sede='' explícito en la URL) -> debe respetarse,
    # NO debe volver a imponerse la vista default por encima de una elección explícita.
    r = admin_session.get('/turnos/cuadro?sede=&area=&rol=')

    texto = r.get_data(as_text=True)
    assert f'value="{sede}" selected' not in texto


# ---------------------------------------------------------------------------
# 17) Horas del Mes (pedido de Tomás, 20/09/2026: horas trabajadas/programadas + "horas a favor"
#     contra la meta mensual configurable por colaborador, usuarios.meta_horas_mensual)
# ---------------------------------------------------------------------------

def test_horas_mes_calcula_transcurridas_total_y_diferencia_con_meta(admin_session, app, crear_usuario):
    """Evita fijar/mockear 'hoy' (datetime.now se usa en varios sitios más de la petición —
    sesión, CSRF, auditoría— y sustituirlo globalmente es frágil); en cambio usa un turno
    fechado HOY de verdad, que siempre cae en 'horas_transcurridas' (fecha <= hoy) sin importar
    qué día sea al correr la prueba."""
    from datetime import datetime as _dt
    hoy = _dt.now(app.ZONA_HORARIA_COLOMBIA).date()
    colaborador = crear_usuario(usuario='colab_horas_mes_1')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET meta_horas_mensual = 4 WHERE usuario = ?", (colaborador,))
    conn.commit()
    conn.close()
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')  # 6 horas (06:00-12:00)
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': hoy.strftime('%Y-%m-%d'), 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.get(f'/turnos/horas_mes?mes={hoy.strftime("%Y-%m")}')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'Persona de Prueba' in texto
    assert '6.0 h' in texto  # horas_transcurridas = total, horas_programadas = 0
    assert '+2.0 h a favor' in texto  # 6h asignadas - 4h de meta = 2h a favor


def test_horas_mes_sin_meta_configurada_la_diferencia_es_none(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_horas_mes_sin_meta')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.get('/turnos/horas_mes?mes=2026-09')

    assert r.status_code == 200
    assert 'Sin meta definida' in r.get_data(as_text=True)


def test_horas_mes_respeta_el_filtro_de_area(admin_session, app, crear_usuario):
    c1 = crear_usuario(usuario='colab_horas_mes_area_a', nombre='Colaborador Area A')
    c2 = crear_usuario(usuario='colab_horas_mes_area_b', nombre='Colaborador Area B')
    area_a, sede_a = _crear_area_y_sede(app, area='HorasMesAreaA', sede='HorasMesSedeA')
    area_b, sede_b = _crear_area_y_sede(app, area='HorasMesAreaB', sede='HorasMesSedeB')
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': c1, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area_a, 'sede': sede_a, 'rol_profesional': 'MEDICO',
    })
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': c2, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area_b, 'sede': sede_b, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.get(f'/turnos/horas_mes?mes=2026-09&area={area_a}')

    texto = r.get_data(as_text=True)
    assert 'Colaborador Area A' in texto
    assert 'Colaborador Area B' not in texto


def test_horas_mes_turno_cancelado_no_cuenta(admin_session, app, crear_usuario):
    colaborador = crear_usuario(usuario='colab_horas_mes_cancelado', nombre='Colaborador Cancelado Horas')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    turno_id = admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    }).get_json()['turno_id']
    admin_session.post(f'/turnos/asignados/{turno_id}/eliminar')

    r = admin_session.get('/turnos/horas_mes?mes=2026-09')

    assert 'Colaborador Cancelado Horas' not in r.get_data(as_text=True)


def test_pagina_horas_del_mes_renderiza_sin_reventar(admin_session, app):
    r = admin_session.get('/turnos/horas_mes')
    assert r.status_code == 200
    assert 'data-ayuda-modulo="turnos_horas_mes"' in r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 18) Marca de agua institucional en la exportación a PDF (pedido de Tomás, 20/09/2026: "que este
#     documento también exporte la marca de agua") — reutiliza _pdf_decoracion_pagina_acta, el
#     mismo mecanismo ya usado por las actas de Inventario.
# ---------------------------------------------------------------------------

def test_exportar_pdf_de_turnos_aplica_la_decoracion_de_marca_de_agua(admin_session, app, crear_usuario, monkeypatch):
    llamadas = {'n': 0}
    original = app._pdf_decoracion_pagina_acta

    def _envoltorio(*args, **kwargs):
        llamadas['n'] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(app, '_pdf_decoracion_pagina_acta', _envoltorio)
    colaborador = crear_usuario(usuario='colab_pdf_marca_agua')
    area, sede = _crear_area_y_sede(app)
    tipo_id = _tipo_id(app, 'M6_12')
    admin_session.post('/turnos/asignar', data={
        'colaborador_usuario': colaborador, 'fecha': '2026-09-21', 'tipo_turno_id': str(tipo_id),
        'area': area, 'sede': sede, 'rol_profesional': 'MEDICO',
    })

    r = admin_session.get('/turnos/exportar_pdf?desde=2026-09-21&hasta=2026-09-27')

    assert r.status_code == 200
    assert llamadas['n'] >= 1


# ---------------------------------------------------------------------------
# 19) Meta de horas mensuales configurable por colaborador (Gestión de Usuarios → Editar/Crear)
# ---------------------------------------------------------------------------

def test_editar_usuario_guarda_la_meta_de_horas_mensuales(admin_session, app, crear_usuario):
    colaborador_usuario = crear_usuario(usuario='colab_meta_1')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (colaborador_usuario,))
    (usuario_id,) = cur.fetchone()
    conn.close()

    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{colaborador_usuario}@preventivaips.com.co', 'rol': 'estandar', 'meta_horas_mensual': '160',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT meta_horas_mensual FROM usuarios WHERE id = ?", (usuario_id,))
    (meta,) = cur.fetchone()
    conn.close()
    assert float(meta) == 160.0


def test_editar_usuario_meta_invalida_se_descarta_y_conserva_la_anterior(admin_session, app, crear_usuario):
    colaborador_usuario = crear_usuario(usuario='colab_meta_2')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (colaborador_usuario,))
    (usuario_id,) = cur.fetchone()
    cur.execute("UPDATE usuarios SET meta_horas_mensual = 100 WHERE id = ?", (usuario_id,))
    conn.commit()
    conn.close()

    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{colaborador_usuario}@preventivaips.com.co', 'rol': 'estandar', 'meta_horas_mensual': 'no-es-un-numero',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT meta_horas_mensual FROM usuarios WHERE id = ?", (usuario_id,))
    (meta,) = cur.fetchone()
    conn.close()
    assert float(meta) == 100.0


def test_editar_usuario_meta_en_blanco_limpia_la_meta(admin_session, app, crear_usuario):
    colaborador_usuario = crear_usuario(usuario='colab_meta_3')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (colaborador_usuario,))
    (usuario_id,) = cur.fetchone()
    cur.execute("UPDATE usuarios SET meta_horas_mensual = 100 WHERE id = ?", (usuario_id,))
    conn.commit()
    conn.close()

    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{colaborador_usuario}@preventivaips.com.co', 'rol': 'estandar', 'meta_horas_mensual': '',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT meta_horas_mensual FROM usuarios WHERE id = ?", (usuario_id,))
    (meta,) = cur.fetchone()
    conn.close()
    assert meta is None


def test_crear_usuario_con_meta_de_horas_mensuales_desde_el_alta(admin_session, app):
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Carla', 'primer_apellido': 'Meta', 'email': 'carla.meta@preventivaips.com.co',
        'password': 'ClaveSegura123', 'especialidad': 'Auxiliar', 'rol': 'estandar', 'meta_horas_mensual': '176',
    }, follow_redirects=False)

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT meta_horas_mensual FROM usuarios WHERE correo = 'carla.meta@preventivaips.com.co'")
    fila = cur.fetchone()
    conn.close()
    assert fila is not None
    assert float(fila[0]) == 176.0
