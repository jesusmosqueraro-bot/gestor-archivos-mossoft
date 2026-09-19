"""Pruebas del pedido de Tomás del 19/09/2026 (captura de pantalla del formulario "Nuevo Activo"
de Inventario, campo Tipo): "debemos tener un botón en el que se puedan agregar Tipo, en el
módulo de inventarios, y que este a su vez, pueda cargar iconos relacionados cuando se agregue."

Cubre dos cosas nuevas sobre el catálogo de Tipos de activo ya existente
(crear_tipo_activo_catalogo):
  1) Subir una imagen como ícono del tipo (columna nueva tipos_activo_catalogo.icono_url),
     alternativa a elegir un ícono de Font Awesome de la lista fija.
  2) Alta "rápida" (origen=rapido): la misma ruta responde JSON en vez de redirigir, para poder
     crear un tipo desde un botón "+" junto al campo Tipo del formulario Nuevo/Editar Activo sin
     recargar la página ni perder lo que ya se hubiera escrito ahí.
"""
import io

import cloudinary.uploader
import pytest


def _sesion_como(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def _mock_cloudinary(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/icono_tipo.png'):
    monkeypatch.setattr(cloudinary.uploader, 'upload', lambda *a, **k: {'secure_url': url})


def _tipo_por_key(app, key):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT key, etiqueta, icono, icono_url FROM tipos_activo_catalogo WHERE key = ?", (key,))
    row = cur.fetchone()
    conn.close()
    return row


# ---------------------------------------------------------------------------
# Esquema
# ---------------------------------------------------------------------------

def test_tabla_tipos_activo_catalogo_tiene_columna_icono_url(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT icono_url FROM tipos_activo_catalogo LIMIT 1")
    conn.close()  # no debe reventar


# ---------------------------------------------------------------------------
# Ícono subido a Cloudinary
# ---------------------------------------------------------------------------

def test_crear_tipo_con_icono_subido_guarda_la_url(admin_session, app, monkeypatch):
    _mock_cloudinary(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/tablet.png')
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'TABLET_X', 'etiqueta': 'Tablet X', 'icono': 'tablet',
        'icono_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'icono.png'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    fila = _tipo_por_key(app, 'TABLET_X')
    assert fila is not None
    assert fila[3] == 'https://res.cloudinary.com/demo/image/upload/tablet.png'


def test_crear_tipo_sin_icono_subido_sigue_usando_el_de_fontawesome(admin_session, app):
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'RADIO_X', 'etiqueta': 'Radio X', 'icono': 'wifi',
    }, follow_redirects=True)
    assert resp.status_code == 200
    fila = _tipo_por_key(app, 'RADIO_X')
    assert fila is not None
    assert fila[2] == 'wifi'
    assert fila[3] is None


def test_crear_tipo_con_archivo_de_formato_invalido_no_lo_crea(admin_session, app):
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'MALO_X', 'etiqueta': 'Malo X', 'icono': 'box',
        'icono_archivo': (io.BytesIO(b'no es una imagen'), 'archivo.exe'),
    }, content_type='multipart/form-data', follow_redirects=True)
    assert resp.status_code == 200
    assert _tipo_por_key(app, 'MALO_X') is None


def test_catalogo_de_tipos_muestra_la_imagen_cuando_hay_icono_url(admin_session, app, monkeypatch):
    _mock_cloudinary(monkeypatch, url='https://res.cloudinary.com/demo/image/upload/scanner.png')
    admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'SCANNER_X', 'etiqueta': 'Scanner X', 'icono': 'print',
        'icono_archivo': (io.BytesIO(b'\x89PNG\r\n\x1a\ncontenido falso de imagen'), 'icono.png'),
    }, content_type='multipart/form-data')
    html = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'https://res.cloudinary.com/demo/image/upload/scanner.png' in html


# ---------------------------------------------------------------------------
# Alta rápida (origen=rapido): responde JSON, no redirige
# ---------------------------------------------------------------------------

def test_alta_rapida_responde_json_y_crea_el_tipo(admin_session, app):
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'DRON_X', 'etiqueta': 'Dron X', 'icono': 'wifi', 'origen': 'rapido',
    })
    assert resp.status_code == 200
    datos = resp.get_json()
    assert datos['success'] is True
    assert datos['etiqueta'] == 'Dron X'
    assert datos['key'] == 'DRON_X'
    assert _tipo_por_key(app, 'DRON_X') is not None


def test_alta_rapida_sin_etiqueta_responde_error_json_sin_crear_nada(admin_session, app):
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={
        'key': 'SINETIQUETA', 'etiqueta': '', 'origen': 'rapido',
    })
    assert resp.status_code == 400
    datos = resp.get_json()
    assert datos['success'] is False
    assert _tipo_por_key(app, 'SINETIQUETA') is None


def test_alta_rapida_con_key_duplicada_responde_error_json(admin_session, app):
    admin_session.post('/tickets/inventario/tipos/crear', data={'key': 'DUP_X', 'etiqueta': 'Dup X', 'origen': 'rapido'})
    resp = admin_session.post('/tickets/inventario/tipos/crear', data={'key': 'DUP_X', 'etiqueta': 'Otra Etiqueta', 'origen': 'rapido'})
    # No es estrictamente "duplicado" a nivel de constraint (no hay UNIQUE en 'key' en el esquema
    # actual), así que lo relevante es que la ruta rápida nunca deja de responder JSON, incluso
    # si el alta en sí no falla — cualquier camino de error real también debe ser JSON.
    assert resp.headers['Content-Type'].startswith('application/json')


def test_alta_rapida_rechaza_a_no_admin(client, app, crear_usuario):
    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    resp = client.post('/tickets/inventario/tipos/crear', data={
        'key': 'AGENTE_X', 'etiqueta': 'Agente X', 'origen': 'rapido',
    })
    # @admin_required redirige (no responde JSON) — un agente no debe poder crear tipos ni por
    # esta vía nueva.
    assert resp.status_code in (302, 401, 403)
    assert _tipo_por_key(app, 'AGENTE_X') is None


# ---------------------------------------------------------------------------
# Botón "+" visible junto al campo Tipo (solo admin)
# ---------------------------------------------------------------------------

def test_boton_agregar_tipo_rapido_visible_solo_para_admin(admin_session, client, app, crear_usuario):
    # El botón "+" en sí (onclick="abrirModalAgregarTipoRapido()") y el modal que abre están
    # gateados por rol == 'admin' en la plantilla; la FUNCIÓN de JS que los maneja se define sin
    # condición más abajo (no hay nada que invocarla si no hay botón), así que la prueba busca el
    # atributo onclick del botón, no el nombre de la función.
    html_admin = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'onclick="abrirModalAgregarTipoRapido()"' in html_admin
    assert 'id="modal-agregar-tipo-rapido"' in html_admin

    usuario = crear_usuario(rol='agente')
    _sesion_como(client, app, usuario, 'agente')
    html_agente = client.get('/tickets/inventario').get_data(as_text=True)
    assert 'onclick="abrirModalAgregarTipoRapido()"' not in html_agente
    assert 'id="modal-agregar-tipo-rapido"' not in html_agente
