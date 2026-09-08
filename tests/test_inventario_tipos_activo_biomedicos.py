"""Pedido por Tomás: sumar al catálogo de Tipos de activo de Inventario una lista completa de
dispositivos biomédicos (analizador hematológico, desfibrilador, ventilador mecánico, etc.),
adicional a los 8 tipos genéricos que ya traía Arkiv (Computador, Portátil, Impresora...).

La siembra corre en init_db() en cada arranque (ver 'tipos_biomedicos_a_sincronizar'), pero de
forma idempotente: solo agrega un tipo si su 'key' todavía no existe en la base — así es segura
de correr una y otra vez, incluso sobre una base de datos ya en producción con tipos propios."""


def test_catalogo_incluye_dispositivos_biomedicos(admin_session, app):
    """Los 8 tipos originales y una muestra de los nuevos dispositivos biomédicos deben
    convivir en el mismo catálogo, todos activos."""
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, etiqueta, icono, estado FROM tipos_activo_catalogo WHERE key IN "
                "('DESKTOP', 'HEMATOLOGY_ANALYZER', 'DEFIBRILLATOR', 'VENTILATOR', 'ULTASONIC_CLEANER')")
    filas = {r[0]: {'etiqueta': r[1], 'icono': r[2], 'estado': r[3]} for r in cur.fetchall()}
    conn.close()

    assert filas['DESKTOP']['etiqueta'] == 'Computador de Escritorio'  # el catálogo original sigue intacto

    assert filas['HEMATOLOGY_ANALYZER']['etiqueta'] == 'Analizador Hematológico'
    assert filas['HEMATOLOGY_ANALYZER']['icono'] == 'vial-virus'

    assert filas['DEFIBRILLATOR']['etiqueta'] == 'Desfibrilador / DEA'
    assert filas['VENTILATOR']['etiqueta'] == 'Ventilador Mecánico (UCI / Transporte)'
    assert filas['ULTASONIC_CLEANER']['etiqueta'] == 'Lavadora Ultrasónica'

    for tipo in filas.values():
        assert (tipo['estado'] or 'activo') == 'activo'


def test_sincronizacion_de_tipos_biomedicos_es_idempotente(app):
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
    cur.execute("SELECT COUNT(*) FROM tipos_activo_catalogo WHERE key = 'VENTILATOR'")
    duplicados_ventilador = cur.fetchone()[0]
    conn.close()

    assert total_despues == total_antes
    assert duplicados_ventilador == 1


def test_modal_de_tipos_de_activo_incluye_los_dispositivos_biomedicos(admin_session, app):
    """El modal 'Tipos de activo' de /tickets/inventario debe listar los nuevos tipos, y el
    selector de íconos debe incluir los íconos de FontAwesome que usan (para poder elegirlos
    también al crear un tipo nuevo a mano)."""
    html = admin_session.get('/tickets/inventario').get_data(as_text=True)

    assert 'Analizador Hematológico' in html
    assert 'Ventilador Mecánico (UCI / Transporte)' in html
    assert 'value="vial-virus"' in html  # selector de íconos del formulario "Agregar tipo"
    assert 'value="lungs"' in html


def test_se_puede_crear_un_activo_con_un_tipo_biomedico(admin_session, app):
    """Prueba de humo: un tipo biomédico del catálogo debe poder usarse igual que cualquier
    otro al registrar un activo nuevo en Inventario."""
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': 'BIOMED-001', 'tipo_activo': 'Desfibrilador / DEA', 'estado': 'Disponible'
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tipo_activo FROM activos_inventario WHERE nombre = ?", ('BIOMED-001',))
    fila = cur.fetchone()
    conn.close()
    assert fila[0] == 'Desfibrilador / DEA'
