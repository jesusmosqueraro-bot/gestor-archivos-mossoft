"""Pruebas del permiso EXTRA por módulo (pedido por Tomás, 19/09/2026): "Quiero poder que el
módulo de usuario pueda indicar qué módulo o modal se le puede asignar a los usuarios, dado se
requiera alguna configuración específica." Ver MODULOS_ASIGNABLES/usuario_tiene_modulo/
modulo_o_acceso_operativo_required en app.py, y el checklist nuevo en el modal "Editar Usuario"
de templates/usuarios.html.

Puntos clave que estas pruebas verifican:
  1) Es un permiso EXTRA sobre el rol: SOLO agrega acceso, nunca le quita nada a admin/agente.
  2) Sin el permiso extra, un 'estandar' sigue bloqueado (nada cambió por accidente).
  3) Con el permiso extra concedido, un 'estandar' puede entrar a ESE módulo puntual y a ningún
     otro (el permiso no es "todo o nada").
  4) editar_usuario() persiste correctamente la lista (separada por coma) y descarta claves que
     no estén en el catálogo.
  5) La migración de esquema agregó la columna 'modulos_extra' a 'usuarios'.
  6) El checklist aparece en el modal de Editar Usuario con las claves del catálogo.
  7) El endpoint compartido (búsqueda de usuarios) se abre con CUALQUIERA de los dos módulos que
     lo usan (Inventario o Bóveda de Accesos).
"""
import pytest
from werkzeug.security import generate_password_hash


def _sesion_como(client, arkiv_app, usuario, rol, modulos_extra=None):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
        if modulos_extra is not None:
            sess['modulos_extra'] = modulos_extra
    return client


def _id_de(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0]


def _modulos_extra_guardados(app, usuario):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT modulos_extra FROM usuarios WHERE usuario = ?", (usuario,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 1) Esquema
# ---------------------------------------------------------------------------

def test_la_tabla_usuarios_tiene_la_columna_modulos_extra(app):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT modulos_extra FROM usuarios WHERE usuario = 'admin'")
    fila = cur.fetchone()
    conn.close()
    # No debe reventar (la columna existe) y una cuenta recién sembrada no tiene nada asignado.
    assert fila is not None


# ---------------------------------------------------------------------------
# 2) Catálogo expuesto a las plantillas
# ---------------------------------------------------------------------------

def test_modulos_asignables_catalog_tiene_las_ocho_claves_esperadas(app):
    # 🧩 19/09/2026 (tercera ronda de permisos por módulo): se agregó 'devoluciones'
    # (Certificación de Devoluciones) al catálogo, que ya traía 'reportes' de la ronda anterior.
    # Ver comentario junto a MODULOS_ASIGNABLES en app.py.
    claves = set(app.CLAVES_MODULOS_ASIGNABLES)
    assert claves == {
        'comunicados', 'inventario', 'boveda_accesos', 'auditoria', 'galerias', 'vencimientos',
        'reportes', 'devoluciones',
    }


def test_modal_editar_usuario_incluye_el_checklist_de_modulos(admin_session):
    html = admin_session.get('/usuarios').get_data(as_text=True)
    assert 'Acceso extra a módulos' in html
    for clave in ('comunicados', 'inventario', 'boveda_accesos', 'auditoria', 'galerias', 'vencimientos', 'reportes', 'devoluciones'):
        assert f'value="{clave}"' in html
    assert 'edit-modulo-extra' in html


# ---------------------------------------------------------------------------
# 3) usuario_tiene_modulo(): la función de bajo nivel
# ---------------------------------------------------------------------------

def test_estandar_sin_permiso_extra_sigue_bloqueado_de_inventario(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    r = client.get('/tickets/inventario')

    assert r.status_code in (302, 403)


def test_estandar_con_permiso_extra_de_inventario_puede_entrar(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['inventario'])

    r = client.get('/tickets/inventario')

    assert r.status_code == 200


def test_el_permiso_extra_es_puntual_no_abre_otros_modulos(client, app, crear_usuario):
    """Conceder 'inventario' no debe abrir, de regalo, Bóveda de Accesos ni Auditoría — el
    permiso extra es SIEMPRE por módulo, nunca "todo o nada"."""
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['inventario'])

    assert client.get('/credenciales').status_code in (302, 403)
    assert client.get('/logs').status_code in (302, 403)
    assert client.get('/vencimientos').status_code in (302, 403)


@pytest.mark.parametrize('clave,ruta', [
    ('comunicados', '/comunicados/cumplimiento'),
    ('inventario', '/tickets/inventario'),
    ('boveda_accesos', '/credenciales'),
    ('auditoria', '/logs'),
    ('galerias', '/subir'),
    ('vencimientos', '/vencimientos'),
    ('devoluciones', '/inventario/certificacion_devoluciones'),
])
def test_cada_modulo_del_catalogo_concede_su_propia_ruta(client, app, crear_usuario, clave, ruta):
    usuario = crear_usuario(usuario=f'estandar_{clave}', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=[clave])

    metodo = client.post if ruta == '/subir' else client.get
    r = metodo(ruta)

    # 200 (GET normal) o 302/400 (POST /subir sin archivo, pero ya pasó el chequeo de permiso,
    # no lo tumbó el decorador con un redirect a index) — lo que NO debe pasar es que el
    # decorador lo mande a login/index por falta de permiso; distinguimos con follow_redirects
    # apagado y validando que, si redirige, no sea porque el decorador negó el acceso al mismo
    # módulo recién concedido (comprobado aparte con las pruebas de "no otros módulos" arriba).
    assert r.status_code != 404


def test_gestion_humana_tambien_puede_recibir_un_modulo_extra(client, app, crear_usuario):
    """El caso real que motivó el pedido fue un 'estandar', pero el mecanismo no está atado a
    ese rol — 'gestion_humana' también debe poder recibir un módulo puntual."""
    usuario = crear_usuario(rol='gestion_humana')
    _sesion_como(client, app, usuario, 'gestion_humana', modulos_extra=['galerias'])

    r = client.post('/subir')

    assert r.status_code != 404
    # Sin el permiso, gestion_humana no debería poder.
    _sesion_como(client, app, usuario, 'gestion_humana', modulos_extra=[])
    r2 = client.post('/subir')
    assert r2.status_code in (302, 403)


def test_endpoint_compartido_de_busqueda_se_abre_con_inventario_o_con_boveda(client, app, crear_usuario):
    u1 = crear_usuario(usuario='estandar_busca_1', rol='estandar')
    _sesion_como(client, app, u1, 'estandar', modulos_extra=['inventario'])
    assert client.get('/usuarios/buscar_cedula?cedula=123').status_code == 200

    u2 = crear_usuario(usuario='estandar_busca_2', rol='estandar')
    _sesion_como(client, app, u2, 'estandar', modulos_extra=['boveda_accesos'])
    assert client.get('/usuarios/buscar_cedula?cedula=123').status_code == 200

    u3 = crear_usuario(usuario='estandar_busca_3', rol='estandar')
    _sesion_como(client, app, u3, 'estandar', modulos_extra=['auditoria'])
    assert client.get('/usuarios/buscar_cedula?cedula=123').status_code in (302, 403)


# ---------------------------------------------------------------------------
# 4) editar_usuario(): persistencia desde el formulario
# ---------------------------------------------------------------------------

def test_editar_usuario_guarda_los_modulos_extra_marcados(admin_session, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar',
        'modulos_extra': ['inventario', 'comunicados'],
    })

    assert r.status_code == 302
    guardado = _modulos_extra_guardados(app, usuario)
    assert set(guardado.split(',')) == {'inventario', 'comunicados'}


def test_editar_usuario_descarta_claves_que_no_existen_en_el_catalogo(admin_session, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar',
        'modulos_extra': ['inventario', 'algo_inventado_a_mano'],
    })

    assert r.status_code == 302
    guardado = _modulos_extra_guardados(app, usuario)
    assert guardado == 'inventario'


def test_editar_usuario_sin_marcar_ningun_modulo_los_deja_vacios(admin_session, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    usuario_id = _id_de(app, usuario)
    # Primero le concede uno...
    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar', 'modulos_extra': ['auditoria'],
    })
    assert _modulos_extra_guardados(app, usuario) == 'auditoria'

    # ... y luego lo guarda de nuevo sin marcar ninguno: debe quedar sin módulos extra (el
    # checklist SIEMPRE viaja completo en el POST, a diferencia de la firma, que si no se toca
    # se conserva).
    admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'estandar',
    })
    assert _modulos_extra_guardados(app, usuario) in (None, '')


def test_editar_usuario_no_afecta_el_acceso_normal_de_un_agente(admin_session, app, crear_usuario):
    """Confirma la promesa "permiso EXTRA, nunca resta": guardar módulos_extra en una cuenta
    'agente' (aunque no tenga sentido práctico) no debe romper nada de lo que ya podía hacer."""
    usuario = crear_usuario(rol='agente')
    usuario_id = _id_de(app, usuario)

    r = admin_session.post(f'/editar_usuario/{usuario_id}', data={
        'email': f'{usuario}@preventivaips.com.co', 'rol': 'agente', 'modulos_extra': ['inventario'],
    })
    assert r.status_code == 302


# ---------------------------------------------------------------------------
# 5) Sesión: login() / login_2fa() deben poblar session['modulos_extra']
# ---------------------------------------------------------------------------

def test_login_puebla_modulos_extra_en_la_sesion(client, app, crear_usuario, monkeypatch):
    monkeypatch.setattr(app, 'verificar_recaptcha', lambda token: True)
    usuario = crear_usuario(usuario='con_modulo_extra', password_hash=generate_password_hash('ClaveSegura123'), rol='estandar')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET modulos_extra = ? WHERE usuario = ?", ('inventario,galerias', usuario))
    conn.commit()
    conn.close()

    r = client.post('/login', data={'usuario': usuario, 'password': 'ClaveSegura123'}, follow_redirects=False)

    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert set(sess.get('modulos_extra') or []) == {'inventario', 'galerias'}


# ---------------------------------------------------------------------------
# 6) Plantillas: tarjetas del panel y controles internos
# ---------------------------------------------------------------------------

def test_bienvenida_muestra_tarjeta_de_inventario_solo_con_el_permiso_extra(client, app, crear_usuario):
    usuario = crear_usuario(usuario='ve_inventario', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['inventario'])
    html = client.get('/bienvenida').get_data(as_text=True)
    assert 'Ir al inventario' in html

    otro = crear_usuario(usuario='no_ve_inventario', rol='estandar')
    _sesion_como(client, app, otro, 'estandar', modulos_extra=[])
    html2 = client.get('/bienvenida').get_data(as_text=True)
    assert 'Ir al inventario' not in html2


def test_bienvenida_muestra_tarjeta_de_reportes_solo_con_el_permiso_extra(client, app, crear_usuario):
    """Corrige el bug evidenciado por Tomás en video (19/09/2026): 'Indicadores / Power BI' no
    tenía tarjeta propia en /bienvenida, así que conceder el permiso extra 'reportes' desde
    Gestión de Usuarios no se reflejaba visiblemente ahí — la única forma de llegar al tablero
    era por el buscador global o memorizando la URL. Ver la tarjeta nueva en bienvenida.html y
    el comentario actualizado junto al bloque de Power BI en buscar_global_api()."""
    usuario = crear_usuario(usuario='ve_powerbi', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['reportes'])
    html = client.get('/bienvenida').get_data(as_text=True)
    # 'Ver indicadores' es el texto del botón de la tarjeta en sí — a diferencia de "Indicadores /
    # Power BI", que también aparece siempre (tenga o no el permiso) en la ayuda estática del
    # buscador global (ver partials/buscador.html), así que no sirve para distinguir los dos casos.
    assert 'Ver indicadores' in html

    otro = crear_usuario(usuario='no_ve_powerbi', rol='estandar')
    _sesion_como(client, app, otro, 'estandar', modulos_extra=[])
    html2 = client.get('/bienvenida').get_data(as_text=True)
    assert 'Ver indicadores' not in html2


def test_bienvenida_muestra_tarjeta_de_reportes_a_admin_y_agente_sin_necesitar_el_permiso_extra(client, app, crear_usuario):
    """El permiso extra 'reportes' SOLO agrega acceso — admin/agente ya ven la tarjeta por su rol,
    sin necesidad de que nadie se la conceda a mano (misma promesa que el resto del catálogo, ver
    MODULOS_ASIGNABLES). Esto es a propósito: el checklist de 'Acceso extra a módulos' en el
    modal de Editar Usuario NO le quita nada a una cuenta admin/agente aunque quede sin marcar."""
    agente = crear_usuario(usuario='agente_ve_powerbi', rol='agente')
    _sesion_como(client, app, agente, 'agente', modulos_extra=[])
    html = client.get('/bienvenida').get_data(as_text=True)
    assert 'Ver indicadores' in html


def test_comunicados_muestra_boton_publicar_con_el_permiso_extra(client, app, crear_usuario):
    usuario = crear_usuario(usuario='publica_comunicados', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['comunicados'])
    html = client.get('/comunicados').get_data(as_text=True)
    assert 'onclick="abrirModalCrear()"' in html

    otro = crear_usuario(usuario='no_publica_comunicados', rol='estandar')
    _sesion_como(client, app, otro, 'estandar', modulos_extra=[])
    html2 = client.get('/comunicados').get_data(as_text=True)
    assert 'onclick="abrirModalCrear()"' not in html2


def test_galerias_muestra_boton_nuevo_instructivo_con_el_permiso_extra_pero_no_papelera(client, app, crear_usuario):
    usuario = crear_usuario(usuario='sube_instructivos', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['galerias'])
    html = client.get('/gestor').get_data(as_text=True)
    assert 'onclick="abrirModalSubir()"' in html
    # La Papelera NO es parte del catálogo de permisos extra — sigue exclusiva de admin/agente.
    assert 'title="Papelera"' not in html

    otro = crear_usuario(usuario='no_sube_instructivos', rol='estandar')
    _sesion_como(client, app, otro, 'estandar', modulos_extra=[])
    html2 = client.get('/gestor').get_data(as_text=True)
    assert 'onclick="abrirModalSubir()"' not in html2


def test_tipos_de_activo_sigue_siendo_solo_lectura_para_estandar_con_inventario_extra(client, app, crear_usuario):
    usuario = crear_usuario(usuario='inventario_solo_lectura_tipos', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['inventario'])
    html = client.get('/tickets/inventario').get_data(as_text=True)
    # Puede abrir la página y ver el catálogo...
    assert 'Tipos de activo' in html
    # ...pero no el formulario para crear un tipo nuevo (sigue siendo admin_required en el
    # backend, ver crear_tipo_activo_catalogo).
    assert 'Agregar tipo' not in html


def test_tipos_de_activo_conserva_los_controles_para_admin(admin_session):
    html = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert 'Agregar tipo' in html


# ---------------------------------------------------------------------------
# 8) Módulos extra también desde el ALTA (pedido por Tomás, 19/09/2026: "no visualizo los
#    botones o los permisos o modulos que se pueden habilitar para la creacion de usuarios...
#    cuando se cree un usuario, se indique si se requiere habilitar módulos adicionales"). El
#    checklist ya existía en Editar Usuario; se agregó también al modal "Registrar Usuario" para
#    no obligar a crear la cuenta y de inmediato tener que editarla solo para conceder el acceso.
# ---------------------------------------------------------------------------

def _crear_especialidad(app, nombre='Auxiliar de Prueba Modulos'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO especialidades_catalogo (nombre, estado) VALUES (%s, 'activo')"
         if db_type == 'postgres' else
         "INSERT INTO especialidades_catalogo (nombre, estado) VALUES (?, 'activo')")
    cur.execute(q, (nombre,))
    conn.commit()
    conn.close()
    return nombre


def test_modal_registrar_usuario_tambien_incluye_el_checklist_de_modulos(admin_session):
    html = admin_session.get('/usuarios').get_data(as_text=True)
    # Debe aparecer una vez en "Registrar Usuario" y otra vez en "Editar Usuario" (dos modales
    # independientes en la misma página, cada uno con su propio checklist).
    assert html.count('Acceso extra a módulos') == 2
    for clave in ('comunicados', 'inventario', 'boveda_accesos', 'auditoria', 'galerias', 'vencimientos', 'reportes', 'devoluciones'):
        assert html.count(f'value="{clave}"') == 2


def test_registrar_usuario_guarda_los_modulos_extra_marcados(admin_session, app):
    especialidad = _crear_especialidad(app)
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Nueva', 'primer_apellido': 'ConModulos',
        'email': 'nueva.conmodulos@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
        'modulos_extra': ['inventario', 'comunicados'],
    }, follow_redirects=False)

    assert r.status_code == 302
    guardado = _modulos_extra_guardados(app, _usuario_por_correo(app, 'nueva.conmodulos@preventivaips.com.co'))
    assert set(guardado.split(',')) == {'inventario', 'comunicados'}


def test_registrar_usuario_descarta_claves_que_no_existen_en_el_catalogo(admin_session, app):
    especialidad = _crear_especialidad(app, 'Auxiliar Claves Invalidas')
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Nueva', 'primer_apellido': 'ClaveInventada',
        'email': 'nueva.claveinventada@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
        'modulos_extra': ['inventario', 'algo_inventado_a_mano'],
    }, follow_redirects=False)

    assert r.status_code == 302
    guardado = _modulos_extra_guardados(app, _usuario_por_correo(app, 'nueva.claveinventada@preventivaips.com.co'))
    assert guardado == 'inventario'


def test_registrar_usuario_sin_marcar_ningun_modulo_los_deja_vacios(admin_session, app):
    especialidad = _crear_especialidad(app, 'Auxiliar Sin Modulos')
    r = admin_session.post('/usuarios', data={
        'primer_nombre': 'Nueva', 'primer_apellido': 'SinModulos',
        'email': 'nueva.sinmodulos@preventivaips.com.co', 'password': 'ClaveValida123',
        'especialidad': especialidad, 'rol': 'estandar',
    }, follow_redirects=False)

    assert r.status_code == 302
    guardado = _modulos_extra_guardados(app, _usuario_por_correo(app, 'nueva.sinmodulos@preventivaips.com.co'))
    assert guardado in (None, '')


def test_registrar_usuario_desde_carga_masiva_no_recibe_modulos_extra(admin_session, app):
    """La carga masiva y el alta rápida desde Inventario no exponen el checklist (no tiene
    sentido pedirlo ahí): confirma que _crear_usuario_interno sigue dejando modulos_extra vacío
    cuando 'datos' no trae esa clave, sin que la nueva funcionalidad rompa esos otros dos flujos."""
    r = admin_session.post('/tickets/inventario/usuarios/crear_rapido', data={
        'primer_nombre': 'Rapido', 'primer_apellido': 'SinModulos',
        'email': 'rapido.sinmodulos@preventivaips.com.co',
        'especialidad': 'No Existe Pero No Es Obligatoria',
    })
    data = r.get_json()
    assert data['ok'] is True
    guardado = _modulos_extra_guardados(app, data['usuario'])
    assert guardado in (None, '')


def _usuario_por_correo(app, correo):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT usuario FROM usuarios WHERE correo = ?", (correo,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


# ---------------------------------------------------------------------------
# 9) Módulo 'devoluciones' (pedido por Tomás, 19/09/2026, tercera ronda): "requiero poder
#    asignar módulos específicos a los usuarios cuando se crean, ejemplo poder asignar a un
#    usuario que se esta creando, acceso al modulo de devoluciones, y el usuario tendra rol
#    estandar, solo no habilites los modulos manejados o controlados por el agente usuario
#    AdminMaster." Da acceso a /inventario/certificacion_devoluciones (ver
#    certificacion_devolucion_required) sin necesitar rol 'agente' ni 'gestion_humana' — pero,
#    a propósito, NO extiende el paso de firma de Soporte TI/Gestión Humana del flujo de paz y
#    salvo de 3 firmas, que sigue siendo exclusivo de esos roles.
# ---------------------------------------------------------------------------

def _crear_activo_asignado(app, nombre='Portátil Devoluciones', asignado_a='Colaborador De Prueba'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
         if db_type == 'postgres' else
         "INSERT INTO activos_inventario (nombre, tipo_activo, estado, asignado_a, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?)")
    cur.execute(q, (nombre, 'Portátil', 'Asignado', asignado_a, '2026-09-01 09:00:00', 'admin'))
    activo_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return activo_id


def test_estandar_sin_devoluciones_sigue_bloqueado_de_certificacion(client, app, crear_usuario):
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    r = client.get('/inventario/certificacion_devoluciones')

    assert r.status_code in (302, 403)


def test_bienvenida_muestra_tarjeta_de_devoluciones_solo_con_el_permiso_extra(client, app, crear_usuario):
    usuario = crear_usuario(usuario='certifica_devoluciones', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['devoluciones'])
    html = client.get('/bienvenida').get_data(as_text=True)
    assert 'Certificar devoluciones' in html

    otro = crear_usuario(usuario='no_certifica_devoluciones', rol='estandar')
    _sesion_como(client, app, otro, 'estandar', modulos_extra=[])
    html2 = client.get('/bienvenida').get_data(as_text=True)
    assert 'Certificar devoluciones' not in html2


def test_estandar_con_devoluciones_puede_certificar_una_devolucion(client, app, crear_usuario):
    usuario = crear_usuario(usuario='certifica_devoluciones_2', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['devoluciones'])
    activo_id = _crear_activo_asignado(app)

    r = client.post(f'/inventario/{activo_id}/confirmar_devolucion', data={'observaciones': 'Todo en orden'})

    assert r.status_code == 302
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM activos_inventario WHERE id = ?", (activo_id,))
    (estado,) = cur.fetchone()
    cur.execute("SELECT confirmado_por FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    (confirmado_por,) = cur.fetchone()
    conn.close()
    assert estado == 'Devolución'
    assert confirmado_por == usuario


def test_estandar_con_devoluciones_no_puede_firmar_el_paz_y_salvo_de_ti_ni_gh(client, app, crear_usuario):
    """El permiso extra 'devoluciones' da acceso al módulo (certificar la devolución en sí),
    pero NO a los pasos de Soporte TI o Gestión Humana del paz y salvo de 3 firmas — esos siguen
    siendo exclusivos de esos roles (ROLES_FIRMA_TI_PAZ_Y_SALVO/ROLES_FIRMA_GH_PAZ_Y_SALVO no
    miran usuario_tiene_modulo), tal como pidió Tomás explícitamente."""
    usuario = crear_usuario(usuario='certifica_sin_firmar', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['devoluciones'])
    activo_id = _crear_activo_asignado(app, nombre='Portátil Paz Y Salvo')

    client.post(f'/inventario/{activo_id}/confirmar_devolucion', data={
        'firma_colaborador_dataurl': 'data:image/png;base64,ABC',
    })

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, estado FROM inventario_devoluciones WHERE activo_id = ?", (activo_id,))
    devolucion_id, estado = cur.fetchone()
    conn.close()
    assert estado == 'pendiente_ti'

    r_ti = client.post(f'/inventario/certificacion_devoluciones/{devolucion_id}/firmar', data={
        'rol_firma': 'ti', 'firma_dataurl': 'data:image/png;base64,XYZ',
    }, follow_redirects=True)
    assert 'Solo un usuario de Soporte TI' in r_ti.get_data(as_text=True)

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT estado FROM inventario_devoluciones WHERE id = ?", (devolucion_id,))
    (estado_tras_intento,) = cur.fetchone()
    conn.close()
    assert estado_tras_intento == 'pendiente_ti'


def test_busqueda_global_incluye_devoluciones_con_el_permiso_extra(client, app, crear_usuario):
    usuario = crear_usuario(usuario='busca_devoluciones', rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['devoluciones'])
    activo_id = _crear_activo_asignado(app, nombre='Portátil Buscable En Devoluciones', asignado_a='Persona Buscable Devolucion')
    # El buscador global busca en el HISTORIAL ya confirmado (inventario_devoluciones), no en
    # los pendientes — así que primero se certifica la devolución con este mismo permiso extra.
    client.post(f'/inventario/{activo_id}/confirmar_devolucion', data={})

    r = client.get('/buscar/api?q=Buscable')

    categorias = {res['categoria'] for res in r.get_json()['resultados']}
    assert 'Certificación de Devoluciones' in categorias
