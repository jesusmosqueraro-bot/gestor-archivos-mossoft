"""Pruebas de la Auditoría de Bóveda Personal (pedido por Tomás): una ventana donde el
"Admin Master" — la cuenta LITERAL 'admin', no cualquier rol 'admin' — puede escribir el usuario
de cualquier persona y consultar/revelar lo que tenga guardado en su Bóveda Personal, para casos
de prioridad. Más restringida que el resto de la Bóveda Fase 3 (@superadmin_required, el mismo
candado del Gestor de Base de Datos y los Respaldos) y de solo lectura: no expone crear, editar
ni eliminar. Reutiliza el endpoint de revelar de Mi Bóveda Personal (/mi_boveda/<id>/revelar,
ver test_boveda_personal.py) sin cambios."""
import re

from tests.test_boveda_personal import _crear_entrada_personal


def _iniciar_sesion(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


def test_super_admin_puede_abrir_el_panel(admin_session):
    r = admin_session.get('/admin/boveda_personal')
    assert r.status_code == 200


def test_admin_comun_no_puede_abrir_el_panel(client, app, crear_usuario):
    """Aunque tenga rol 'admin', solo la cuenta LITERAL 'admin' entra aquí — a diferencia del
    resto de la Bóveda Fase 3, donde cualquier cuenta con rol 'admin' audita ítems personales."""
    otro_admin = crear_usuario(usuario='otro_admin', rol='admin')
    _iniciar_sesion(client, app, otro_admin, 'admin')

    r = client.get('/admin/boveda_personal')

    assert r.status_code == 302


def test_agente_no_puede_abrir_el_panel(client, app, crear_usuario):
    agente = crear_usuario(rol='agente')
    _iniciar_sesion(client, app, agente, 'agente')

    r = client.get('/admin/boveda_personal')

    assert r.status_code == 302


def test_lista_los_items_personales_del_usuario_buscado(admin_session, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    _crear_entrada_personal(app, usuario_a, servicio='Cuenta de Correo de A')

    r = admin_session.get(f'/admin/boveda_personal/{usuario_a}/items')

    assert r.status_code == 200
    data = r.get_json()
    assert data['usuario'] == usuario_a
    assert any(item['servicio'] == 'Cuenta de Correo de A' for item in data['items'])


def test_usuario_inexistente_devuelve_404(admin_session):
    r = admin_session.get('/admin/boveda_personal/usuario_que_no_existe/items')
    assert r.status_code == 404


def test_admin_comun_no_puede_consultar_items_de_otro(client, app, crear_usuario):
    otro_admin = crear_usuario(usuario='otro_admin2', rol='admin')
    usuario_a = crear_usuario(rol='estandar')
    _crear_entrada_personal(app, usuario_a)
    _iniciar_sesion(client, app, otro_admin, 'admin')

    r = client.get(f'/admin/boveda_personal/{usuario_a}/items')

    assert r.status_code == 302


def test_revelar_desde_el_panel_de_auditoria_sigue_funcionando(admin_session, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveDeAuditoria1')

    r = admin_session.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    assert r.status_code == 200
    assert r.get_json()['password'] == 'ClaveDeAuditoria1'


def test_revelar_de_otra_persona_queda_en_el_log_como_auditoria(admin_session, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, servicio='Entrada Auditada')

    admin_session.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accion FROM logs WHERE usuario = 'admin' AND detalles LIKE '%Entrada Auditada%' ORDER BY id DESC LIMIT 1")
    accion = cur.fetchone()[0]
    conn.close()
    assert accion == 'Auditoría de Bóveda Personal'


def test_revelar_de_su_propia_entrada_no_se_marca_como_auditoria(client, app, crear_usuario):
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, servicio='Entrada Propia')
    _iniciar_sesion(client, app, usuario_a, 'estandar')

    client.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT accion FROM logs WHERE usuario = ? AND detalles LIKE '%Entrada Propia%' ORDER BY id DESC LIMIT 1", (usuario_a,))
    accion = cur.fetchone()[0]
    conn.close()
    assert accion == 'Consulta en Mi Bóveda'


# 🐛 Mismo hallazgo que en test_boveda_personal.py (reportado por 'prueba_neon'): el fetch() de
# 'revelar' en admin_boveda_personal.html tampoco mandaba el encabezado X-CSRFToken, así que con
# la protección CSRF real activa en producción (desactivada aquí en el resto de la suite vía
# WTF_CSRF_ENABLED=False), "Ver clave"/"Copiar" en la ventana de auditoría del Admin Master
# también se habrían descartado en silencio. Se reactiva la protección a propósito para
# confirmarlo.

def test_revelar_desde_auditoria_funciona_con_csrf_real_y_encabezado(admin_session, app, crear_usuario, monkeypatch):
    monkeypatch.setitem(app.app.config, 'WTF_CSRF_ENABLED', True)
    usuario_a = crear_usuario(rol='estandar')
    reg_id = _crear_entrada_personal(app, usuario_a, password='ClaveAuditadaCsrf1')

    html = admin_session.get('/admin/boveda_personal').get_data(as_text=True)
    # Esta página no tiene formularios (es de solo lectura): el token vive en la constante JS
    # CSRF_TOKEN que alimenta el encabezado X-CSRFToken del fetch de revelar, no en un input.
    m = re.search(r'const CSRF_TOKEN = "([^"]+)"', html)
    assert m, "La página no expone CSRF_TOKEN — no se puede simular el fetch real de revelar."
    token = m.group(1)

    r = admin_session.post(f'/mi_boveda/{reg_id}/revelar', data={'accion': 'ver'},
                            headers={'X-CSRFToken': token})

    assert r.status_code == 200
    assert r.get_json()['password'] == 'ClaveAuditadaCsrf1'
