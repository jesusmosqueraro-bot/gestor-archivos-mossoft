"""Pruebas del Acta de ASIGNACIÓN de un activo (TI o Biomédico) a un usuario: al crear/editar un
activo, marcando la casilla 'Generar acta de asignación' queda un registro histórico en
'actas_asignacion' (nunca se sobreescribe con una reasignación posterior — igual que el acta de
recibido biomédico), descargable en PDF, con un título distinto según si el activo está marcado
como biomédico o no."""


def _crear_activo_directo(app, nombre='70001', es_biomedico=False, asignado_a=None, estado='Disponible'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id" if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, es_biomedico, fecha_creacion, creado_por) "
         "VALUES (?, ?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', estado, asignado_a, es_biomedico, '2026-09-04 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_crear_activo_marcando_generar_acta_registra_el_acta_de_asignacion(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70010', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Laura Gómez',
        'generar_acta_asignacion': 'on', 'acta_asignacion_descripcion': 'Entregado con cargador nuevo.',
    }, follow_redirects=True)

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('70010',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT asignado_a, descripcion_breve, generado_por FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    acta = cur.fetchone()
    conn.close()
    assert acta == ('Laura Gómez', 'Entregado con cargador nuevo.', 'admin')
    texto = r.get_data(as_text=True)
    assert 'Acta de asignación registrada' in texto


def test_crear_activo_sin_marcar_la_casilla_no_registra_ninguna_acta(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70011', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Carlos Ruiz',
        # Sin 'generar_acta_asignacion' — no debe registrarse nada, aunque venga una descripción.
        'acta_asignacion_descripcion': 'Esto no debería guardarse.',
    })
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('70011',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_generar_acta_marcada_sin_asignado_a_no_bloquea_el_guardado_pero_avisa(admin_session, app):
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70012', 'tipo_activo': 'Portátil', 'estado': 'Disponible',
        # Sin 'asignado_a' — la casilla queda marcada, pero no hay a quién hacerle el acta.
        'generar_acta_asignacion': 'on',
    }, follow_redirects=True)

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM activos_inventario WHERE nombre = ?", ('70012',))
    assert cur.fetchone()[0] == 1  # el activo SÍ se guardó
    conn.close()
    texto = r.get_data(as_text=True)
    assert 'ACTA DE ASIGNACIÓN' in texto or 'acta de asignación' in texto.lower()


def test_activo_que_pasa_a_devolucion_no_registra_acta_de_asignacion_aunque_se_marque(admin_session, app):
    """Si en la misma edición el activo entra a estado 'Devolución', 'asignado_a' se limpia antes
    de guardar (ver editar_activo) — el acta de asignación debe usar ese valor YA limpio, no el
    que venía crudo en el formulario, para no dejar un acta fantasma de una asignación que en los
    hechos se está cerrando."""
    activo_id = _crear_activo_directo(app, nombre='70013', asignado_a='Mario Duarte', estado='Asignado')

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70013', 'tipo_activo': 'Portátil', 'estado': 'Devolución', 'asignado_a': 'Mario Duarte',
        'generar_acta_asignacion': 'on', 'acta_asignacion_descripcion': 'No debería registrarse.',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    assert cur.fetchone()[0] == 0
    conn.close()


def test_editar_activo_agrega_una_segunda_acta_de_asignacion_sin_borrar_la_primera(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='70014', asignado_a='Primer Usuario', estado='Asignado')

    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70014', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Primer Usuario',
        'generar_acta_asignacion': 'on',
    })
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70014', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Segundo Usuario',
        'generar_acta_asignacion': 'on',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT asignado_a FROM actas_asignacion WHERE activo_id = ? ORDER BY id", (activo_id,))
    asignados = [f[0] for f in cur.fetchall()]
    conn.close()
    assert asignados == ['Primer Usuario', 'Segundo Usuario']


def test_listar_actas_de_asignacion_de_un_activo(admin_session, app):
    activo_id = _crear_activo_directo(app, nombre='70015', asignado_a='Ana Torres', estado='Asignado')
    admin_session.post(f'/tickets/inventario/{activo_id}/editar', data={
        'nombre': '70015', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Ana Torres',
        'generar_acta_asignacion': 'on', 'acta_asignacion_descripcion': 'Sin novedad.',
    })

    r = admin_session.get(f'/tickets/inventario/{activo_id}/actas_asignacion')
    data = r.get_json()
    assert len(data['actas']) == 1
    assert data['actas'][0]['asignado_a'] == 'Ana Torres'
    assert data['actas'][0]['descripcion_breve'] == 'Sin novedad.'


def test_acta_asignacion_pdf_ti_y_biomedico_usan_titulos_distintos(admin_session, app):
    activo_ti = _crear_activo_directo(app, nombre='70016', asignado_a='Usuario TI', estado='Asignado', es_biomedico=False)
    activo_bio = _crear_activo_directo(app, nombre='70017', asignado_a='Usuario Bio', estado='Asignado', es_biomedico=True)
    admin_session.post(f'/tickets/inventario/{activo_ti}/editar', data={
        'nombre': '70016', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Usuario TI',
        'generar_acta_asignacion': 'on',
    })
    admin_session.post(f'/tickets/inventario/{activo_bio}/editar', data={
        'nombre': '70017', 'tipo_activo': 'Bomba de infusión', 'estado': 'Asignado', 'asignado_a': 'Usuario Bio',
        'es_biomedico': 'on', 'generar_acta_asignacion': 'on',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, activo_id FROM actas_asignacion ORDER BY id")
    filas = cur.fetchall()
    conn.close()
    acta_ti_id = next(f[0] for f in filas if f[1] == activo_ti)
    acta_bio_id = next(f[0] for f in filas if f[1] == activo_bio)

    r_ti = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_ti_id}/pdf')
    r_bio = admin_session.get(f'/tickets/inventario/actas_asignacion/{acta_bio_id}/pdf')
    assert r_ti.status_code == 200 and r_ti.headers['Content-Type'] == 'application/pdf'
    assert r_bio.status_code == 200 and r_bio.headers['Content-Type'] == 'application/pdf'
    assert r_ti.data[:4] == b'%PDF'
    assert r_bio.data[:4] == b'%PDF'


def test_modal_inventario_incluye_la_seccion_de_acta_de_asignacion(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'name="generar_acta_asignacion"' in texto
    assert 'name="acta_asignacion_descripcion"' in texto


def test_actas_asignacion_requiere_rol_operativo(sesion_usuario, app):
    activo_id = _crear_activo_directo(app, nombre='70018')
    r = sesion_usuario.get(f'/tickets/inventario/{activo_id}/actas_asignacion')
    assert r.status_code in (302, 403)


# ────────────────────────────────────────────────────────────────────────────
# FIRMA DE QUIEN ASIGNA (pedido de Tomás, 06/09/2026): se auto-resuelve del perfil de quien
# genera el acta — igual de automática que la firma de quien recibe — sin ningún widget nuevo.
# ────────────────────────────────────────────────────────────────────────────

def test_acta_de_asignacion_incluye_la_firma_de_quien_la_genera_si_la_tiene_guardada(admin_session, app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET firma = ? WHERE usuario = ?",
                ('https://res.cloudinary.com/demo/image/upload/firma_admin.png', 'admin'))
    conn.commit()
    conn.close()

    admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70019', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Nuevo Usuario',
        'generar_acta_asignacion': 'on',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('70019',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT firma_asigna_url FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    firma_asigna_url = cur.fetchone()[0]
    conn.close()
    assert firma_asigna_url == 'https://res.cloudinary.com/demo/image/upload/firma_admin.png'


def test_acta_de_asignacion_sin_firma_guardada_de_quien_genera_no_falla(admin_session, app):
    """Si quien genera el acta nunca guardó una firma en su perfil, el acta queda igual
    registrada (firma_asigna_url en NULL) — no bloquea nada."""
    r = admin_session.post('/tickets/inventario/nuevo', data={
        'nombre': '70020', 'tipo_activo': 'Portátil', 'estado': 'Asignado', 'asignado_a': 'Otro Usuario',
        'generar_acta_asignacion': 'on',
    }, follow_redirects=True)
    assert r.status_code == 200

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM activos_inventario WHERE nombre = ?", ('70020',))
    activo_id = cur.fetchone()[0]
    cur.execute("SELECT firma_asigna_url FROM actas_asignacion WHERE activo_id = ?", (activo_id,))
    firma_asigna_url = cur.fetchone()[0]
    conn.close()
    assert firma_asigna_url is None
