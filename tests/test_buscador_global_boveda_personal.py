"""Pruebas de cobertura del buscador global ("Buscar en Arkiv") sobre la Bóveda de Credenciales.

Hasta ahora /buscar/api tenía dos problemas aquí (reportados por Tomás, 12/09/2026 — "quiero
que se adicione de manera transversal el boton Buscar en Arkiv, que busque todo, los ultimos
dos modulos, no los incluye aun en la sus busquedas"):

1. "Mi Bóveda Personal" (accesible para CUALQUIER rol, incluido 'estandar') no aparecía en
   ninguna búsqueda — el bloque de credenciales del buscador estaba envuelto por completo en
   `if es_soporte:`.
2. La consulta de "Bóveda de Accesos" (la institucional, solo admin/agente) no filtraba por
   'visibilidad': un ítem 'personal' de CUALQUIER usuario se colaba ahí, exponiendo su
   título/área/notas a cualquier admin/agente que buscara, bajo la categoría equivocada y con
   un enlace a /credenciales donde ese ítem ni siquiera aparece listado.

Estas pruebas cubren ambos arreglos: que Mi Bóveda Personal ahora aparezca (solo con lo propio),
que la Bóveda de Accesos institucional siga encontrando los ítems 'equipo' de siempre, y que ya
no se filtre ningún ítem 'personal' ajeno hacia esa categoría."""


def _crear_credencial(app, titulo, propietario, visibilidad, usuario_acceso='', area='', notas=''):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (%s, '', %s, %s, %s, %s, '2026-01-01', 'activo', '', 'credencial', %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, etiquetas, tipo_item, contenido_seguro, propietario, visibilidad) "
         "VALUES (?, '', ?, ?, ?, ?, '2026-01-01', 'activo', '', 'credencial', ?, ?, ?)")
    pass_cifrada = app.encriptar_texto('ClaveDePrueba1')
    contenido_cifrado = app.encriptar_texto('')
    cur.execute(q, (titulo, usuario_acceso, pass_cifrada, area, notas, contenido_cifrado, propietario, visibilidad))
    conn.commit()
    conn.close()


# --- Mi Bóveda Personal ---

def test_buscador_global_encuentra_item_de_mi_boveda_personal(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    _crear_credencial(app, titulo='Correo Personal Gmail', propietario=propietario, visibilidad='personal')

    data = sesion_usuario.get('/buscar/api?q=correo personal').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Mi Bóveda Personal' in categorias


def test_buscador_global_mi_boveda_personal_enlaza_a_mi_boveda(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    _crear_credencial(app, titulo='Banco Personal', propietario=propietario, visibilidad='personal')

    data = sesion_usuario.get('/buscar/api?q=banco personal').get_json()

    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Mi Bóveda Personal')
    assert resultado['url'] == '/mi_boveda'


def test_buscador_global_encuentra_item_personal_por_usuario_de_acceso(sesion_usuario, app):
    with sesion_usuario.session_transaction() as sess:
        propietario = sess['username']
    _crear_credencial(app, titulo='Netflix', propietario=propietario, visibilidad='personal', usuario_acceso='cliente_netflix_2026')

    data = sesion_usuario.get('/buscar/api?q=cliente_netflix_2026').get_json()

    titulos = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Mi Bóveda Personal']
    assert 'Netflix' in titulos


def test_buscador_global_no_filtra_item_personal_de_otro_usuario_hacia_mi_boveda(sesion_usuario, app, crear_usuario):
    otro = crear_usuario(rol='estandar')
    _crear_credencial(app, titulo='Correo del Compañero', propietario=otro, visibilidad='personal')

    data = sesion_usuario.get('/buscar/api?q=correo del compañero').get_json()

    titulos_personales = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Mi Bóveda Personal']
    assert 'Correo del Compañero' not in titulos_personales


def test_admin_puede_buscar_su_propia_boveda_personal(admin_session, app):
    _crear_credencial(app, titulo='Clave Personal del Admin', propietario='admin', visibilidad='personal')

    data = admin_session.get('/buscar/api?q=clave personal del admin').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Mi Bóveda Personal' in categorias


# --- Bóveda de Accesos (institucional) ---

def test_buscador_global_sigue_encontrando_item_institucional_en_boveda_de_accesos(admin_session, app):
    _crear_credencial(app, titulo='VPN Corporativa', propietario='admin', visibilidad='equipo', area='Sistemas')

    data = admin_session.get('/buscar/api?q=vpn corporativa').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Bóveda de Accesos' in categorias


def test_buscador_global_ya_no_filtra_item_personal_ajeno_hacia_boveda_de_accesos(admin_session, app, crear_usuario):
    otro = crear_usuario(rol='estandar')
    _crear_credencial(app, titulo='Streaming Personal de Otro', propietario=otro, visibilidad='personal', area='Personal')

    data = admin_session.get('/buscar/api?q=streaming personal de otro').get_json()

    titulos_institucionales = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Bóveda de Accesos']
    assert 'Streaming Personal de Otro' not in titulos_institucionales
    # Tampoco debe colarse en Mi Bóveda Personal del admin — no es suyo.
    titulos_personales = [r['titulo'] for r in data['resultados'] if r['categoria'] == 'Mi Bóveda Personal']
    assert 'Streaming Personal de Otro' not in titulos_personales


def test_estandar_no_ve_boveda_de_accesos_institucional_en_el_buscador_global(sesion_usuario, app):
    _crear_credencial(app, titulo='VPN Corporativa Dos', propietario='admin', visibilidad='equipo', area='Sistemas')

    data = sesion_usuario.get('/buscar/api?q=vpn corporativa dos').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Bóveda de Accesos' not in categorias
