"""Pruebas de la aplicación del manual de marca de Preventiva Salud IPS en Arkiv (pedido por
Tomás, 12/09/2026): logo principal e tipografía Montserrat en /login (y ahora, global, en toda
la plataforma), y el color de fondo/tarjeta personalizado (paleta institucional) en el Muro de
Comunicados."""
import glob
import os


def test_montserrat_esta_enlazada_globalmente_en_todas_las_plantillas():
    """Pedido de Tomás, 12/09/2026: "Haz global la fuente Montserrat" — en vez de un
    templates/base.html (esta app no usa herencia de plantillas Jinja, cada .html es un
    documento completo), marca-institucional.css se enlaza al final del <head> de cada
    plantilla. Esta prueba evita que una plantilla nueva se quede afuera sin que nadie lo note."""
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    plantillas = sorted(glob.glob(os.path.join(raiz, 'templates', '*.html')))
    assert plantillas, "no se encontraron plantillas — revisar la ruta de búsqueda"
    sin_marca = []
    for ruta in plantillas:
        with open(ruta, encoding='utf-8') as f:
            contenido = f.read()
        if 'marca-institucional.css' not in contenido:
            sin_marca.append(os.path.basename(ruta))
    assert not sin_marca, f"Plantillas sin la tipografía institucional: {sin_marca}"


def test_bienvenida_incluye_la_hoja_de_marca_institucional(admin_session):
    """Chequeo end-to-end (no solo estático) de que una página distinta a /login también carga
    marca-institucional.css — confirma que el enlace realmente se sirve, no solo que el texto
    está en el archivo fuente."""
    r = admin_session.get('/bienvenida')

    assert r.status_code == 200
    assert 'marca-institucional.css' in r.get_data(as_text=True)


def test_login_muestra_el_logo_principal_de_preventiva_centrado(client):
    r = client.get('/login')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert '/static/img/logo_preventiva.png' in texto
    assert 'mx-auto' in texto  # el logo queda centrado, no solo presente en la página


def test_login_usa_la_tipografia_montserrat_del_manual_de_marca(client):
    r = client.get('/login')

    assert r.status_code == 200
    texto = r.get_data(as_text=True)
    assert 'Montserrat' in texto
    assert 'marca-institucional.css' in texto


def _crear_comunicado_via_formulario(admin_session, color=None):
    datos = {
        'titulo': 'Aviso con color de marca',
        'contenido': '<p>Contenido de prueba</p>',
        'nivel': 'info',
        'visibilidad': 'todos',
    }
    if color is not None:
        datos['color'] = color
    # El formulario real manda csrf_token; en pruebas CSRF queda deshabilitado (TESTING=True,
    # ver conftest.py), así que no hace falta generarlo aquí.
    return admin_session.post('/comunicados/crear', data=datos, follow_redirects=True)


def test_crear_comunicado_guarda_un_color_hex_valido_de_la_paleta_institucional(admin_session, app):
    _crear_comunicado_via_formulario(admin_session, color='#1654a5')

    texto = admin_session.get('/comunicados').get_data(as_text=True)
    assert '#1654a5' in texto


def test_crear_comunicado_descarta_un_color_invalido_y_no_revienta(admin_session, app):
    """Un valor manipulado (no hex de 6 dígitos) se descarta a favor de '' — la tarjeta debe
    seguir viéndose con su estilo por defecto, sin que el servidor truene ni guarde algo raro
    que después se inyecte como CSS en la plantilla."""
    r = _crear_comunicado_via_formulario(admin_session, color='javascript:alert(1)')

    assert r.status_code == 200
    conn, db_type = app.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT color FROM comunicados ORDER BY id DESC LIMIT 1")
    color_guardado = cursor.fetchone()[0]
    conn.close()
    assert color_guardado in (None, '')


def test_editar_comunicado_actualiza_el_color_de_la_tarjeta(admin_session, app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO comunicados (titulo, contenido, fecha, autor) VALUES (%s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO comunicados (titulo, contenido, fecha, autor) VALUES (?, ?, ?, ?)")
    cur.execute(q, ('Aviso a editar', '<p>Original</p>', '2026-09-12 09:00:00', 'admin'))
    com_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()

    admin_session.post(f'/comunicados/editar/{com_id}', data={
        'titulo': 'Aviso a editar',
        'contenido': '<p>Original</p>',
        'nivel': 'info',
        'visibilidad': 'todos',
        'color': '#ee7128',
    }, follow_redirects=True)

    texto = admin_session.get('/comunicados').get_data(as_text=True)
    assert '#ee7128' in texto
