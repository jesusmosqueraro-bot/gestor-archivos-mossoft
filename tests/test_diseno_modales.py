"""Pruebas de /admin/diseno (personalización de colores de los modales, pedido por Tomás,
12/09/2026: "un modal de diseño para poder modificar a gusto los colores de los modales").

Cubre: que solo la cuenta super-admin ('admin') puede ver/guardar/restablecer los colores, que
guardar valida cada campo como '#rrggbb' (cayendo al valor por defecto si no lo es), que lo
guardado se refleja de inmediato en cualquier página (vía el context_processor
_inyectar_colores_modal + partials/colores_modal_personalizados.html), y que restablecer vuelve
exactamente a los valores de fábrica.

También cubre el logo institucional y la marca de agua de las actas (pedido de Tomás,
19/09/2026: "habilita ... una opción para cambiar el icono de preventiva cuando se desee o
cuando se cambie de Sociedad, y ... la opción de cambiar la marca de agua a las imágenes",
aclarado con AskUserQuestion a "en todo el sistema" para el logo y "la de las actas en PDF"
para la marca de agua). Mismo nivel de acceso que los colores (@superadmin_required) y mismo
patrón de subida a Cloudinary que _subir_icono_tipo_activo (ver test_tipos_activo_icono_y_
alta_rapida.py y test_firma_digital.py para el mismo mecanismo ya probado en otros lados).
"""
import io
import json

import cloudinary.uploader


def _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/logo_x.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def test_ver_diseno_modales_solo_superadmin(admin_session, app):
    """La cuenta super-admin 'admin' (sembrada por init_db()) sí puede ver la pantalla."""
    resp = admin_session.get('/admin/diseno')
    assert resp.status_code == 200
    texto = resp.data.decode('utf-8')
    assert 'Diseño de Modales' in texto
    assert 'name="acentos__azul_primario"' in texto
    assert 'name="oscuro__fondo"' in texto
    assert 'name="claro__texto_secundario"' in texto
    assert 'name="descanso__borde"' in texto


def test_ver_diseno_modales_admin_comun_no_puede(client, app, crear_usuario):
    """Un usuario con rol 'admin' pero que NO es la cuenta literal 'admin' (super-admin) es
    redirigido — mismo nivel de acceso que Respaldos/Gestor de BD (@superadmin_required)."""
    usuario = crear_usuario(rol='admin')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'admin'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    resp = client.get('/admin/diseno')
    assert resp.status_code == 302
    assert '/admin/diseno' not in resp.headers.get('Location', '')


def test_ver_diseno_modales_estandar_no_puede(sesion_usuario):
    resp = sesion_usuario.get('/admin/diseno')
    assert resp.status_code == 302


def test_ver_diseno_modales_requiere_login(client):
    resp = client.get('/admin/diseno')
    assert resp.status_code == 302


def test_valores_por_defecto_coinciden_con_los_colores_originales(app):
    """Antes de que cualquier admin toque /admin/diseno, _colores_modal_actuales() debe devolver
    exactamente COLORES_MODAL_POR_DEFECTO (los colores que los modales ya tenían) — es lo que
    garantiza que desplegar este feature no cambia nada visualmente todavía."""
    assert app._colores_modal_actuales() == app.COLORES_MODAL_POR_DEFECTO


def test_guardar_colores_modal_persiste_y_se_refleja_en_cualquier_pagina(admin_session, app):
    form = {}
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        for clave in valores:
            form[f'{grupo}__{clave}'] = '#ff00aa' if (grupo, clave) == ('acentos', 'azul_primario') else valores[clave]

    resp = admin_session.post('/admin/diseno/guardar', data=form, follow_redirects=True)
    assert resp.status_code == 200

    actuales = app._colores_modal_actuales()
    assert actuales['acentos']['azul_primario'] == '#ff00aa'
    # el resto de campos no tocados por esta prueba deben seguir en su valor por defecto
    assert actuales['oscuro']['fondo'] == app.COLORES_MODAL_POR_DEFECTO['oscuro']['fondo']

    # Se refleja en CUALQUIER plantilla renderizada (context_processor + partial), no solo en
    # /admin/diseno: /bienvenida es una buena prueba porque no pasa 'colores_modal' explícito.
    pagina = admin_session.get('/bienvenida')
    assert '--marca-azul-primario: #ff00aa;' in pagina.data.decode('utf-8')


def test_guardar_colores_modal_rechaza_valores_invalidos(admin_session, app):
    """Un color inválido (no '#rrggbb') en un campo cae a su valor por defecto, sin tumbar el
    guardado del resto de campos ni dejar basura en la BD."""
    form = {}
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        for clave in valores:
            form[f'{grupo}__{clave}'] = valores[clave]
    form['claro__fondo'] = 'javascript:alert(1)'  # intento de valor inválido/malicioso

    admin_session.post('/admin/diseno/guardar', data=form, follow_redirects=True)

    actuales = app._colores_modal_actuales()
    assert actuales['claro']['fondo'] == app.COLORES_MODAL_POR_DEFECTO['claro']['fondo']


def test_guardar_colores_modal_con_formulario_incompleto_completa_con_defectos(admin_session, app):
    """Si el formulario llega sin todos los 16 campos (ej. un POST manual recortado), el JSON
    guardado de todas formas queda completo — cada campo faltante cae a su valor por defecto."""
    admin_session.post('/admin/diseno/guardar', data={'acentos__cian': '#00ff00'}, follow_redirects=True)

    actuales = app._colores_modal_actuales()
    assert actuales['acentos']['cian'] == '#00ff00'
    assert actuales['descanso']['texto'] == app.COLORES_MODAL_POR_DEFECTO['descanso']['texto']
    guardado = json.loads(app._config_app_valor(app.CLAVE_COLORES_MODAL))
    for grupo, valores in app.COLORES_MODAL_POR_DEFECTO.items():
        assert set(guardado[grupo].keys()) == set(valores.keys())


def test_restablecer_diseno_modales_vuelve_a_los_valores_de_fabrica(admin_session, app):
    admin_session.post('/admin/diseno/guardar', data={'acentos__naranja': '#123456'}, follow_redirects=True)
    assert app._colores_modal_actuales()['acentos']['naranja'] == '#123456'

    admin_session.post('/admin/diseno/restablecer', follow_redirects=True)
    assert app._colores_modal_actuales() == app.COLORES_MODAL_POR_DEFECTO


# ---------------------------------------------------------------------------
# Logo institucional y marca de agua de las actas (pedido de Tomás, 19/09/2026)
# ---------------------------------------------------------------------------

def test_sin_personalizar_no_hay_logo_ni_marca_agua_propios(app):
    """Antes de que cualquier admin toque /admin/diseno, ninguno de los dos está personalizado —
    el sistema sigue mostrando el logo de fábrica de Preventiva Salud IPS en todas partes."""
    assert app._logo_institucional_url_actual() is None
    assert app._marca_agua_actas_url_actual() is None


def test_pagina_de_diseno_modales_muestra_las_secciones_de_logo_y_marca_de_agua(admin_session):
    texto = admin_session.get('/admin/diseno').get_data(as_text=True)
    assert 'Logo institucional' in texto
    assert 'Marca de agua' in texto
    assert 'name="logo_archivo"' in texto
    assert 'name="marca_agua_archivo"' in texto


def test_guardar_logo_institucional_solo_superadmin(client, app, crear_usuario):
    """Mismo nivel de acceso que guardar los colores (@superadmin_required): un admin común no
    puede cambiar el logo institucional de toda la plataforma."""
    usuario = crear_usuario(rol='admin')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'admin'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    resp = client.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'logo.png'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    assert '/admin/diseno' not in resp.headers.get('Location', '')
    assert app._logo_institucional_url_actual() is None


def test_guardar_logo_institucional_sube_a_cloudinary_y_se_refleja_en_todo_el_sistema(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/logo_nuevo.png')

    resp = admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'logo.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    assert app._logo_institucional_url_actual() == 'https://res.cloudinary.com/demo/image/upload/logo_nuevo.png'
    # Sin marca de agua propia de las actas, reutiliza el nuevo logo (ver
    # test_marca_agua_actas_reutiliza_el_logo_institucional_personalizado).
    assert app._marca_agua_actas_fuente_pdf() == 'https://res.cloudinary.com/demo/image/upload/logo_nuevo.png'

    # Se refleja de inmediato en cualquier plantilla que use logo_institucional_url (barra de
    # navegación, vía el context_processor _inyectar_colores_modal) — /bienvenida no lo pide
    # explícito, igual que la prueba equivalente de colores.
    pagina = admin_session.get('/bienvenida').get_data(as_text=True)
    assert 'https://res.cloudinary.com/demo/image/upload/logo_nuevo.png' in pagina

    # Y en /login (sin sesión activa) — se usa un cliente nuevo sin cookies porque
    # admin_session ya está autenticado y /login lo redirigiría a /bienvenida.
    cliente_anonimo = app.app.test_client()
    login_pagina = cliente_anonimo.get('/login').get_data(as_text=True)
    assert 'https://res.cloudinary.com/demo/image/upload/logo_nuevo.png' in login_pagina


def test_guardar_logo_institucional_rechaza_formato_invalido(admin_session, app):
    resp = admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'no es una imagen'), 'archivo.exe'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert app._logo_institucional_url_actual() is None


def test_guardar_logo_institucional_rechaza_archivo_demasiado_grande(admin_session, app):
    contenido_enorme = b'\x89PNG\r\n\x1a\n' + (b'A' * (app.TAMANO_MAXIMO_IMAGEN_INSTITUCIONAL + 1))
    resp = admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(contenido_enorme), 'logo_enorme.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert app._logo_institucional_url_actual() is None


def test_guardar_logo_institucional_sin_archivo_no_hace_nada(admin_session, app):
    resp = admin_session.post('/admin/diseno/logo/guardar', data={}, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert app._logo_institucional_url_actual() is None


def test_restablecer_logo_institucional_vuelve_al_de_preventiva(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/logo_temporal.png')
    admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'logo.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert app._logo_institucional_url_actual() is not None

    resp = admin_session.post('/admin/diseno/logo/restablecer', follow_redirects=True)
    assert resp.status_code == 200
    assert app._logo_institucional_url_actual() is None


def test_guardar_marca_agua_actas_solo_superadmin(client, app, crear_usuario):
    usuario = crear_usuario(rol='admin')
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = 'admin'
        sess['instance_id'] = app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    resp = client.post('/admin/diseno/marca-agua/guardar', data={
        'marca_agua_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'marca.png'),
    }, content_type='multipart/form-data')
    assert resp.status_code == 302
    assert '/admin/diseno' not in resp.headers.get('Location', '')
    assert app._marca_agua_actas_url_actual() is None


def test_guardar_marca_agua_actas_sube_a_cloudinary_y_tiene_prioridad_sobre_el_logo(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/logo_base.png')
    admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'logo.png'),
    }, content_type='multipart/form-data')

    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png')
    resp = admin_session.post('/admin/diseno/marca-agua/guardar', data={
        'marca_agua_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'marca.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200

    assert app._marca_agua_actas_url_actual() == 'https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png'
    # La marca de agua propia de las actas gana sobre el logo institucional (ver
    # test_marca_agua_actas_propia_tiene_prioridad_sobre_el_logo), pero el logo institucional
    # (usado en la barra de navegación, login, etc.) no cambia por esto.
    assert app._marca_agua_actas_fuente_pdf() == 'https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png'
    assert app._logo_institucional_url_actual() == 'https://res.cloudinary.com/demo/image/upload/logo_base.png'


def test_guardar_marca_agua_actas_rechaza_formato_invalido(admin_session, app):
    resp = admin_session.post('/admin/diseno/marca-agua/guardar', data={
        'marca_agua_archivo': (io.BytesIO(b'no es una imagen'), 'archivo.exe'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert app._marca_agua_actas_url_actual() is None


def test_restablecer_marca_agua_actas_vuelve_a_reutilizar_el_logo_institucional(admin_session, app, monkeypatch):
    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/logo_base.png')
    admin_session.post('/admin/diseno/logo/guardar', data={
        'logo_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'logo.png'),
    }, content_type='multipart/form-data')

    _mock_cloudinary_upload(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/marca_agua_propia.png')
    admin_session.post('/admin/diseno/marca-agua/guardar', data={
        'marca_agua_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'marca.png'),
    }, content_type='multipart/form-data')
    assert app._marca_agua_actas_url_actual() is not None

    resp = admin_session.post('/admin/diseno/marca-agua/restablecer', follow_redirects=True)
    assert resp.status_code == 200
    assert app._marca_agua_actas_url_actual() is None
    # Al restablecerla, vuelve a reutilizar el logo institucional vigente (que sigue personalizado).
    assert app._marca_agua_actas_fuente_pdf() == 'https://res.cloudinary.com/demo/image/upload/logo_base.png'
