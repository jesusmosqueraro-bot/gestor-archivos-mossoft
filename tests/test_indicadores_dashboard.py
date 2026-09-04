"""Pruebas de las mejoras a los tableros de indicadores (Indicadores de Soporte TI y Tablero
Ejecutivo): tiempo promedio de resolución, comparativo de solicitudes vs. la quincena anterior,
el nuevo gráfico "Por tipo", y los nuevos renglones de Vencimiento de Documentos y Certificación
de Devoluciones en el Tablero Ejecutivo.

Se creó junto con el rediseño visual de ambos tableros con la paleta de marca de Preventiva
Salud IPS (Azul Real #1A4B9C, Cyan #00A3DA, Naranja Acento #E67E00)."""
from datetime import timedelta


def _fecha(app, hace_horas=0):
    return (app.datetime.now(app.ZONA_HORARIA_COLOMBIA) - timedelta(hours=hace_horas)).strftime('%Y-%m-%d %H:%M:%S')


def _crear_ticket(app, estado='Abierto', fecha_creacion=None, sla_resolucion_cumplida=None, creado_por='admin'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    fecha_creacion = fecha_creacion or _fecha(app)
    q = ("INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, "
         "fecha_creacion, fecha_actualizacion, sla_resolucion_cumplida) VALUES (%s, %s, 'Incidente', 'Hardware', 'Media', %s, %s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, "
         "fecha_creacion, fecha_actualizacion, sla_resolucion_cumplida) VALUES (?, ?, 'Incidente', 'Hardware', 'Media', ?, ?, ?, ?, ?, ?)")
    cur.execute(q, ('Ticket de prueba', 'Descripción', estado, creado_por, creado_por, fecha_creacion, fecha_creacion, sla_resolucion_cumplida))
    conn.commit()
    conn.close()


def _crear_documento_empleado(app, usuario='admin', fecha_vencimiento='2020-01-01'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO documentos_empleado (usuario, tipo_documento, titulo, fecha_vencimiento, estado, creado_por, fecha_creacion) VALUES (%s, 'Cédula', 'Cédula de ciudadanía', %s, 'activo', 'admin', %s)"
         if db_type == 'postgres' else
         "INSERT INTO documentos_empleado (usuario, tipo_documento, titulo, fecha_vencimiento, estado, creado_por, fecha_creacion) VALUES (?, 'Cédula', 'Cédula de ciudadanía', ?, 'activo', 'admin', ?)")
    cur.execute(q, (usuario, fecha_vencimiento, '2026-01-01 09:00:00'))
    conn.commit()
    conn.close()


def _crear_activo(app, nombre='30099'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) VALUES (%s, 'Portátil', 'Disponible', %s, 'admin') RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, fecha_creacion, creado_por) VALUES (?, 'Portátil', 'Disponible', ?, 'admin')")
    cur.execute(q, (nombre, '2026-01-01 09:00:00'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def _crear_devolucion(app, activo_id, fecha, colaborador='Persona de Prueba'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones) VALUES (%s, %s, 'admin', %s, '')"
         if db_type == 'postgres' else
         "INSERT INTO inventario_devoluciones (activo_id, colaborador, confirmado_por, fecha, observaciones) VALUES (?, ?, 'admin', ?, '')")
    cur.execute(q, (activo_id, colaborador, fecha))
    conn.commit()
    conn.close()


# --- _formatear_duracion_horas ---

def test_formatear_duracion_horas_menos_de_un_dia(app):
    assert app._formatear_duracion_horas(3.5) == '3.5 h'


def test_formatear_duracion_horas_uno_o_mas_dias(app):
    assert app._formatear_duracion_horas(30) == '1d 6h'


def test_formatear_duracion_horas_none_si_no_hay_dato(app):
    assert app._formatear_duracion_horas(None) is None


# --- Tiempo promedio de resolución ---

def test_tiempo_promedio_resolucion_se_calcula_con_ticket_resuelto(app):
    fecha_creacion = _fecha(app, hace_horas=10)
    fecha_resuelto = _fecha(app, hace_horas=0)
    _crear_ticket(app, estado='Resuelto', fecha_creacion=fecha_creacion, sla_resolucion_cumplida=fecha_resuelto)

    ind = app._calcular_indicadores_tickets()

    assert ind['tiempo_promedio_resolucion_horas'] == 10.0
    assert ind['tiempo_promedio_resolucion_texto'] == '10.0 h'


def test_tiempo_promedio_resolucion_none_sin_tickets_resueltos(app):
    _crear_ticket(app, estado='Abierto')

    ind = app._calcular_indicadores_tickets()

    assert ind['tiempo_promedio_resolucion_horas'] is None
    assert ind['tiempo_promedio_resolucion_texto'] is None


# --- Comparativo vs. la quincena (14 días) anterior ---

def test_comparativo_periodo_anterior_variacion_positiva(app):
    # 1 solicitud hace 20 días (quincena anterior) y 2 solicitudes hoy (quincena actual).
    _crear_ticket(app, fecha_creacion=_fecha(app, hace_horas=20 * 24))
    _crear_ticket(app, fecha_creacion=_fecha(app, hace_horas=0))
    _crear_ticket(app, fecha_creacion=_fecha(app, hace_horas=1))

    ind = app._calcular_indicadores_tickets()

    assert ind['conteo_periodo_anterior'] == 1
    assert ind['conteo_periodo_actual'] == 2
    assert ind['variacion_pct_tendencia'] == 100.0


def test_comparativo_periodo_anterior_sin_datos_previos_no_calcula_variacion(app):
    _crear_ticket(app, fecha_creacion=_fecha(app, hace_horas=0))

    ind = app._calcular_indicadores_tickets()

    assert ind['conteo_periodo_anterior'] == 0
    assert ind['variacion_pct_tendencia'] is None


# --- Página de Indicadores de Soporte TI: nuevos KPIs y gráfico "Por tipo" ---

def test_indicadores_tickets_muestra_tiempo_de_resolucion_y_tendencia(admin_session):
    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)
    assert 'Tiempo prom. de resolución' in texto
    assert 'quincena anterior' in texto
    assert 'chart-tipo' in texto


# --- Tablero Ejecutivo: nuevos renglones de Vencimiento de Documentos y Devoluciones ---

def test_tablero_ejecutivo_muestra_documentos_vencidos(admin_session, app):
    _crear_documento_empleado(app, fecha_vencimiento='2020-01-01')  # muy en el pasado: vencido

    texto = admin_session.get('/tablero-ejecutivo').get_data(as_text=True)

    assert 'Vencimiento de Documentos' in texto
    assert '1 vencidos' in texto


def test_tablero_ejecutivo_muestra_devoluciones_certificadas_del_mes(admin_session, app):
    activo_id = _crear_activo(app)
    fecha_este_mes = app.datetime.now(app.ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-15 10:00:00')
    _crear_devolucion(app, activo_id, fecha_este_mes)

    texto = admin_session.get('/tablero-ejecutivo').get_data(as_text=True)

    assert 'Certificación de Devoluciones' in texto
    assert '1 certificadas este mes' in texto


def test_tablero_ejecutivo_muestra_tiempo_de_resolucion_y_tendencia(admin_session, app):
    fecha_creacion = _fecha(app, hace_horas=5)
    _crear_ticket(app, estado='Resuelto', fecha_creacion=fecha_creacion, sla_resolucion_cumplida=_fecha(app))

    texto = admin_session.get('/tablero-ejecutivo').get_data(as_text=True)

    assert 'Tiempo prom. de resolución' in texto
    assert 'quincena anterior' in texto


# --- Exportaciones: que no se rompan con los nuevos colores de marca y el gráfico "Por tipo" ---

def test_exportar_indicadores_pdf_no_falla_con_los_nuevos_graficos(admin_session, app):
    fecha_creacion = _fecha(app, hace_horas=5)
    _crear_ticket(app, estado='Resuelto', fecha_creacion=fecha_creacion, sla_resolucion_cumplida=_fecha(app))
    _crear_ticket(app, estado='Abierto')

    resp = admin_session.get('/tickets/indicadores/exportar_pdf')

    assert resp.status_code == 200
    assert resp.headers['Content-Type'] == 'application/pdf'


def test_exportar_indicadores_xlsx_no_falla_con_los_nuevos_graficos(admin_session, app):
    fecha_creacion = _fecha(app, hace_horas=5)
    _crear_ticket(app, estado='Resuelto', fecha_creacion=fecha_creacion, sla_resolucion_cumplida=_fecha(app))
    _crear_ticket(app, estado='Abierto')

    resp = admin_session.get('/tickets/indicadores/exportar_xlsx')

    assert resp.status_code == 200
    assert 'spreadsheetml' in resp.headers['Content-Type']


# --- Filtro por rango de fechas, por mes y por analista (Task #128/#129) ---

def _fecha_dia(app, hace_dias):
    return (app.datetime.now(app.ZONA_HORARIA_COLOMBIA) - timedelta(days=hace_dias)).strftime('%Y-%m-%d %H:%M:%S')


def test_filtro_por_rango_de_fechas_excluye_tickets_fuera_del_rango(app):
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 40))  # fuera del rango
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 3))   # dentro del rango

    hoy = app.datetime.now(app.ZONA_HORARIA_COLOMBIA)
    fecha_inicio = (hoy - timedelta(days=10)).strftime('%Y-%m-%d')
    fecha_fin = hoy.strftime('%Y-%m-%d')
    ind = app._calcular_indicadores_tickets(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)

    assert ind['total'] == 1
    assert ind['titulo_comparativo_periodo'] == 'período anterior'


def test_sin_filtro_de_fecha_se_comporta_igual_que_antes(app):
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 40))
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 3))

    ind = app._calcular_indicadores_tickets()

    assert ind['total'] == 2
    assert ind['titulo_comparativo_periodo'] == 'quincena anterior'
    assert len(ind['dias_tendencia']) == 14


def test_filtro_por_agente_solo_cuenta_sus_tickets(app):
    _crear_ticket(app, creado_por='agente_uno')
    _crear_ticket(app, creado_por='agente_dos')
    _crear_ticket(app, creado_por='agente_dos')

    ind = app._calcular_indicadores_tickets(agente='agente_dos')

    assert ind['total'] == 2


def test_periodo_anterior_generalizado_cuenta_el_rango_inmediatamente_anterior(app):
    # Rango filtrado: últimos 5 días (3 tickets). Período anterior: los 5 días antes de eso (1 ticket).
    for i in range(3):
        _crear_ticket(app, fecha_creacion=_fecha_dia(app, i))
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 7))  # cae en el período anterior

    hoy = app.datetime.now(app.ZONA_HORARIA_COLOMBIA)
    fecha_inicio = (hoy - timedelta(days=4)).strftime('%Y-%m-%d')
    fecha_fin = hoy.strftime('%Y-%m-%d')
    ind = app._calcular_indicadores_tickets(fecha_inicio=fecha_inicio, fecha_fin=fecha_fin)

    assert ind['conteo_periodo_actual'] == 3
    assert ind['conteo_periodo_anterior'] == 1


def test_resolver_filtros_indicadores_prioriza_mes_sobre_fechas_manuales(client, admin_session):
    with client.session_transaction():
        pass
    resp = admin_session.get('/tickets/indicadores?mes=2026-02&fecha_inicio=2020-01-01&fecha_fin=2020-01-02')
    assert resp.status_code == 200
    texto = resp.get_data(as_text=True)
    # El combo de mes debe quedar seleccionado en el valor de 'mes', no en las fechas manuales.
    assert 'value="2026-02" selected' in texto


def test_pagina_indicadores_muestra_los_filtros_y_las_opciones_de_agente(admin_session, app):
    _crear_ticket(app, creado_por='agente_visible')

    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)

    assert 'name="fecha_inicio"' in texto
    assert 'name="fecha_fin"' in texto
    assert 'name="agente"' in texto
    assert 'agente_visible' in texto


def test_filtro_de_fecha_en_indicadores_acota_el_total_mostrado(admin_session, app):
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 40))
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 1))

    hoy = app.datetime.now(app.ZONA_HORARIA_COLOMBIA)
    fecha_inicio = (hoy - timedelta(days=5)).strftime('%Y-%m-%d')
    fecha_fin = hoy.strftime('%Y-%m-%d')
    texto = admin_session.get(f'/tickets/indicadores?fecha_inicio={fecha_inicio}&fecha_fin={fecha_fin}').get_data(as_text=True)

    assert '>1<' in texto  # Total Solicitudes = 1
    assert 'período anterior' in texto


def test_tablero_ejecutivo_refleja_el_mismo_filtro_de_fecha(admin_session, app):
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 40))
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 1))

    hoy = app.datetime.now(app.ZONA_HORARIA_COLOMBIA)
    fecha_inicio = (hoy - timedelta(days=5)).strftime('%Y-%m-%d')
    fecha_fin = hoy.strftime('%Y-%m-%d')
    texto = admin_session.get(f'/tablero-ejecutivo?fecha_inicio={fecha_inicio}&fecha_fin={fecha_fin}').get_data(as_text=True)

    assert 'período anterior' in texto


def test_exportaciones_de_indicadores_respetan_el_filtro_de_fecha(admin_session, app):
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 40))
    _crear_ticket(app, fecha_creacion=_fecha_dia(app, 1))

    hoy = app.datetime.now(app.ZONA_HORARIA_COLOMBIA)
    fecha_inicio = (hoy - timedelta(days=5)).strftime('%Y-%m-%d')
    fecha_fin = hoy.strftime('%Y-%m-%d')
    qs = f'fecha_inicio={fecha_inicio}&fecha_fin={fecha_fin}'

    csv_resp = admin_session.get(f'/tickets/indicadores/exportar_csv?{qs}')
    assert csv_resp.status_code == 200
    csv_texto = csv_resp.get_data(as_text=True)
    # Solo el ticket dentro del rango debe aparecer en el detalle del CSV.
    assert csv_texto.strip().count('\n') == 1  # encabezado + 1 fila

    pdf_resp = admin_session.get(f'/tickets/indicadores/exportar_pdf?{qs}')
    assert pdf_resp.status_code == 200

    xlsx_resp = admin_session.get(f'/tickets/indicadores/exportar_xlsx?{qs}')
    assert xlsx_resp.status_code == 200
