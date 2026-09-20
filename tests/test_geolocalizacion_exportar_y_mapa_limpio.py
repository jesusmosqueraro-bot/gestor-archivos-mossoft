"""Pedido de Tomás (20/09/2026): "Exportar a csv o Excel y a PDF, que el mapa se limpie y que
solo muestre las ubicaciones actuales [...] debe seguir existiendo el registro, pero no debe
cargar el mapa las conexiones anteriores." Se resolvió con AskUserQuestion que la exportación es
sobre la tabla de /admin/geolocalizacion (usuario, IP, lat/lon, fecha, sede).

Estas pruebas cubren:
- Las 3 rutas nuevas de exportación (CSV/Excel/PDF), su control de acceso, y que respetan el
  filtro de usuario/fecha ya existente en la página.
- Que el HTML servido sigue incluyendo el registro COMPLETO en REGISTROS (la limpieza del mapa
  ocurre solo en el JS del navegador, filtrando a un marcador por usuario -- ver
  admin_geolocalizacion.html -- nunca en el backend ni en la base de datos), y que el filtrado a
  "solo el más reciente por usuario" está presente en ese script.
"""
import io
import openpyxl
from werkzeug.security import generate_password_hash


def _forzar_recaptcha_ok(monkeypatch, app):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)


def _login_con_coordenadas(app, usuario, lat, lng):
    app.app.test_client().post('/login', data={
        'usuario': usuario, 'password': 'ClaveSegura123', 'latitud': str(lat), 'longitud': str(lng),
    })


def test_exportar_csv_requiere_sesion_iniciada(client):
    r = client.get('/admin/geolocalizacion/exportar_csv', follow_redirects=False)
    assert r.status_code == 302
    assert '/login' in r.headers.get('Location', '')


def test_exportar_csv_requiere_rol_admin(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'estandar'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False

    r = client.get('/admin/geolocalizacion/exportar_csv', follow_redirects=False)

    assert r.status_code == 302
    assert 'geolocalizacion' not in r.headers.get('Location', '')


def test_exportar_csv_incluye_los_registros(admin_session, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    _login_con_coordenadas(app, usuario, 4.710989, -74.072092)

    r = admin_session.get('/admin/geolocalizacion/exportar_csv')

    assert r.status_code == 200
    assert 'text/csv' in r.headers['Content-Type']
    texto = r.get_data(as_text=True)
    assert usuario in texto
    assert '4.710989' in texto or '4,710989' in texto


def test_exportar_xlsx_respeta_el_filtro_de_usuario(admin_session, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario_a = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    usuario_b = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    _login_con_coordenadas(app, usuario_a, 4.710989, -74.072092)
    _login_con_coordenadas(app, usuario_b, 4.710989, -74.072092)

    r = admin_session.get(f'/admin/geolocalizacion/exportar_xlsx?usuario={usuario_a}')

    assert r.status_code == 200
    wb = openpyxl.load_workbook(io.BytesIO(r.data))
    ws = wb.active
    usuarios_en_hoja = [row[0].value for row in ws.iter_rows(min_row=2)]
    assert usuario_a in usuarios_en_hoja
    assert usuario_b not in usuarios_en_hoja


def test_exportar_pdf_devuelve_un_pdf_valido(admin_session, app, crear_usuario, monkeypatch):
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    _login_con_coordenadas(app, usuario, 4.710989, -74.072092)

    r = admin_session.get('/admin/geolocalizacion/exportar_pdf')

    assert r.status_code == 200
    assert r.headers['Content-Type'] == 'application/pdf'
    assert r.data[:4] == b'%PDF'


def test_exportar_pdf_no_falla_sin_ningun_registro(admin_session):
    r = admin_session.get('/admin/geolocalizacion/exportar_pdf')
    assert r.status_code == 200
    assert r.data[:4] == b'%PDF'


def test_pagina_incluye_los_enlaces_de_exportar(admin_session):
    texto = admin_session.get('/admin/geolocalizacion').get_data(as_text=True)
    assert 'geolocalizacion_exportar_csv' in texto or '/admin/geolocalizacion/exportar_csv' in texto
    assert 'geolocalizacion_exportar_xlsx' in texto or '/admin/geolocalizacion/exportar_xlsx' in texto
    assert 'geolocalizacion_exportar_pdf' in texto or '/admin/geolocalizacion/exportar_pdf' in texto


def test_registros_embebidos_siguen_completos_pese_a_la_limpieza_del_mapa(admin_session, app, crear_usuario, monkeypatch):
    """La limpieza del mapa (solo el marcador más reciente por usuario) ocurre en el JavaScript
    del navegador -- el backend sigue mandando el HISTORIAL COMPLETO en REGISTROS, tal como pidió
    Tomás ("debe seguir existiendo el registro"), para que la tabla de respaldo y las
    exportaciones de arriba no pierdan ningún dato histórico."""
    _forzar_recaptcha_ok(monkeypatch, app)
    usuario = crear_usuario(password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    _login_con_coordenadas(app, usuario, 4.0, -74.0)
    _login_con_coordenadas(app, usuario, 5.0, -75.0)
    _login_con_coordenadas(app, usuario, 6.0, -76.0)

    texto = admin_session.get('/admin/geolocalizacion').get_data(as_text=True)

    inicio = texto.index('const REGISTROS')
    fin = texto.index('const SEDES')
    bloque = texto[inicio:fin]
    assert bloque.count(usuario) == 3, "las 3 filas históricas del usuario deben seguir viajando al navegador"


def test_script_del_mapa_filtra_a_un_marcador_por_usuario(admin_session):
    """Confirma que el mecanismo de 'limpieza' vive en el JS del propio visor (no en el backend
    ni borrando nada de la base de datos): un Set que evita agregar más de un circleMarker por
    usuario, quedándose con el primero que aparece (el más reciente, porque REGISTROS ya viene
    ordenado DESC por id)."""
    texto = admin_session.get('/admin/geolocalizacion').get_data(as_text=True)
    assert 'usuariosYaEnMapa' in texto
    assert 'usuariosYaEnMapa.has(r.usuario)' in texto
    assert 'usuariosYaEnMapa.add(r.usuario)' in texto
