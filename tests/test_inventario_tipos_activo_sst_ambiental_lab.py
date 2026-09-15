"""Pedido por Tomás (15/09/2026): sumar al catálogo de Tipos de activo de Inventario una lista de
insumos/material de SST, Ambiental y Laboratorio Clínico (EPP, botiquín, extintor, camilla de
rescate, puntos ecológicos, kit antiderrames, equipos y reactivos de laboratorio...), adicional a
los tipos genéricos y a los dispositivos biomédicos que ya traía Arkiv.

La siembra corre en init_db() en cada arranque (ver 'tipos_sst_ambiental_lab_a_sincronizar'), de
forma idempotente igual que los dispositivos biomédicos: solo agrega un tipo si su 'key' todavía
no existe en la base — segura de correr una y otra vez, incluso sobre una base de datos ya en
producción con tipos propios. 'Centrífuga' no se repite aquí porque ya existía en el catálogo
biomédico (key 'CENTRIFUGE')."""


def test_catalogo_incluye_insumos_sst_ambiental_laboratorio(admin_session, app):
    """Los tipos genéricos originales y una muestra de los nuevos de SST/Ambiental/Laboratorio
    deben convivir en el mismo catálogo, todos activos."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, etiqueta, icono, estado FROM tipos_activo_catalogo WHERE key IN "
                "('DESKTOP', 'SST_EPP', 'SST_BOTIQUIN', 'SST_EXTINTOR', 'SST_CAMILLA', "
                "'AMB_RESIDUOS', 'AMB_RECICLAJE', 'AMB_DERRAMES', 'AMB_PTAR', "
                "'LAB_EQUIPO', 'LAB_MUESTRAS', 'LAB_REACTIVOS', 'LAB_CADENA_FRIO')")
    filas = {r[0]: {'etiqueta': r[1], 'icono': r[2], 'estado': r[3]} for r in cur.fetchall()}
    conn.close()

    assert filas['DESKTOP']['etiqueta'] == 'Computador de Escritorio'  # el catálogo original sigue intacto

    assert filas['SST_EPP']['etiqueta'] == 'Elementos de Protección Personal (EPP)'
    assert filas['SST_EPP']['icono'] == 'hard-hat'
    assert filas['SST_BOTIQUIN']['etiqueta'] == 'Botiquín de Primeros Auxilios'
    assert filas['SST_EXTINTOR']['etiqueta'] == 'Extintor / Equipo Contra Incendios'
    assert filas['SST_CAMILLA']['etiqueta'] == 'Camilla de Rescate / Emergencias'

    assert filas['AMB_RESIDUOS']['etiqueta'] == 'Punto Ecológico / Residuos Peligrosos'
    assert filas['AMB_RECICLAJE']['icono'] == 'recycle'
    assert filas['AMB_DERRAMES']['etiqueta'] == 'Kit Antiderrames'
    assert filas['AMB_PTAR']['etiqueta'] == 'Gestión Ambiental / Agua (PTAR)'

    assert filas['LAB_EQUIPO']['etiqueta'] == 'Equipo de Laboratorio Clínico'
    assert filas['LAB_MUESTRAS']['icono'] == 'vial'
    assert filas['LAB_REACTIVOS']['etiqueta'] == 'Reactivos Químicos de Laboratorio'
    assert filas['LAB_CADENA_FRIO']['etiqueta'] == 'Nevera / Cadena de Frío (Laboratorio)'

    for tipo in filas.values():
        assert (tipo['estado'] or 'activo') == 'activo'


def test_centrifuga_no_queda_duplicada_entre_biomedicos_y_laboratorio(app):
    """'Centrífuga de Laboratorio' ya vivía en el catálogo biomédico (key CENTRIFUGE) antes de
    este cambio — no debe aparecer una segunda vez con una key nueva del bloque de laboratorio."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tipos_activo_catalogo WHERE etiqueta ILIKE %s" if db_type == 'postgres'
                else "SELECT COUNT(*) FROM tipos_activo_catalogo WHERE etiqueta LIKE ?", ('%Centrífuga%',))
    total_centrifugas = cur.fetchone()[0]
    conn.close()
    assert total_centrifugas == 1


def test_sincronizacion_de_tipos_sst_ambiental_lab_es_idempotente(app):
    """Correr init_db() de nuevo (como pasa en cada arranque de la app) no debe duplicar ningún
    tipo de activo ya sembrado."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tipos_activo_catalogo")
    total_antes = cur.fetchone()[0]
    conn.close()

    app.init_db()

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM tipos_activo_catalogo")
    total_despues = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM tipos_activo_catalogo WHERE key = 'SST_EPP'")
    duplicados_epp = cur.fetchone()[0]
    conn.close()

    assert total_despues == total_antes
    assert duplicados_epp == 1


def test_modal_de_tipos_de_activo_incluye_sst_ambiental_laboratorio(admin_session, app):
    """El modal 'Tipos de activo' de /tickets/inventario debe listar los nuevos tipos, y el
    selector de íconos debe incluir los íconos de FontAwesome que usan (para poder elegirlos
    también al crear un tipo nuevo a mano)."""
    html = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Elementos de Protección Personal (EPP)' in html
    assert 'Kit Antiderrames' in html
    assert 'Equipo de Laboratorio Clínico' in html
    assert 'value="hard-hat"' in html  # selector de íconos del formulario "Agregar tipo"
    assert 'value="biohazard"' in html
    assert 'value="flask-vial"' in html


def test_se_puede_crear_un_activo_con_un_tipo_de_sst(admin_session, app):
    """Prueba de humo: un tipo de SST/Ambiental/Laboratorio del catálogo debe poder usarse igual
    que cualquier otro al registrar un activo nuevo en Inventario."""
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': 'SST-001', 'tipo_activo': 'Extintor / Equipo Contra Incendios', 'estado': 'Disponible'
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo_activo FROM activos_inventario WHERE nombre = ?", ('SST-001',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Extintor / Equipo Contra Incendios'
