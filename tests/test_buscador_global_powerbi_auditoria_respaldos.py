"""Pruebas del "recorrido completo del aplicativo" pedido por Tomás (19/09/2026, verbatim):
"haz que los módulos que aun no están en el botón Buscar en Arkiv, no carguen, recuerda, este
botón debe funcionar de manera transversal siempre para que todo cambio se pueda buscar aquí,
adicional, incluye los tableros o presentaciones de Power Bi y todos los cambios en el sistema de
Respaldo, en el Backup de la DB". Es decir: ningún módulo del aplicativo debe quedar afuera del
buscador global — se agregan las 3 categorías que faltaban en /buscar/api (ver
buscar_global_api() en app.py): Indicadores / Power BI, Auditoría y Logs + Log de Correos
Enviados, y Respaldos de Base de Datos.

Puntos clave que estas pruebas verifican:
  1) Indicadores / Power BI replica EXACTAMENTE la regla de listar_powerbi()/ver_powerbi(): se ve
     con el permiso extra 'reportes' O si el rol propio está en 'roles_permitidos' del tablero, y
     un tablero bloqueado (activo=False) solo lo ve un admin.
  2) Auditoría y Logs / Log de Correos Enviados replica EXACTAMENTE la regla de
     auditoria_o_extra_required: admin/agente por rol, o el permiso extra 'auditoria'.
  3) Respaldos de Base de Datos solo lo ve la cuenta super-admin LITERAL 'admin' (igual que
     superadmin_required en las rutas reales de /admin/respaldos) — ni siquiera otro admin.
  4) "Todos los cambios en el sistema de Respaldo" quedan cubiertos SIN código adicional: cada
     acción de Respaldos (generar/eliminar/cambiar frecuencia) ya se registra como una fila más
     en 'logs' vía registrar_log(), así que aparece en la categoría "Auditoría y Logs".
"""
import json
import os


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


def _crear_tablero_powerbi(app, titulo='Tablero de Prueba', roles_permitidos='admin', activo=True,
                            categoria='General', embed_url='https://app.powerbi.com/view?r=xyz'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = (
        "INSERT INTO reportes_powerbi (titulo, descripcion, categoria, embed_url, roles_permitidos, activo) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
        if db_type == 'postgres' else
        "INSERT INTO reportes_powerbi (titulo, descripcion, categoria, embed_url, roles_permitidos, activo) VALUES (?, ?, ?, ?, ?, ?)"
    )
    cur.execute(q, (titulo, 'Descripción de prueba', categoria, embed_url, roles_permitidos, activo))
    tablero_id = cur.fetchone()[0] if db_type == 'postgres' else cur.lastrowid
    conn.commit()
    conn.close()
    return tablero_id


def _crear_log(app, usuario='admin', accion='Acción de prueba', detalles='Detalle de prueba',
                fecha='2026-09-19 10:00:00'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (%s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)")
    cur.execute(q, (usuario, accion, detalles, fecha))
    conn.commit()
    conn.close()


def _crear_correo_log(app, destinatario='alguien@preventivaips.com.co', asunto='Asunto de prueba',
                       tipo='notificacion', estado='enviado', fecha='2026-09-19 10:00:00'):
    conn, db_type = app.get_db()
    cur = conn.cursor()
    q = ("INSERT INTO correos_log (fecha, destinatario, asunto, tipo, estado) VALUES (%s, %s, %s, %s, %s)"
         if db_type == 'postgres' else
         "INSERT INTO correos_log (fecha, destinatario, asunto, tipo, estado) VALUES (?, ?, ?, ?, ?)")
    cur.execute(q, (fecha, destinatario, asunto, tipo, estado))
    conn.commit()
    conn.close()


def _crear_archivo_respaldo(directorio, nombre, contenido=None):
    os.makedirs(directorio, exist_ok=True)
    ruta = os.path.join(directorio, nombre)
    with open(ruta, 'w', encoding='utf-8') as f:
        json.dump(contenido or {'usuarios': []}, f)
    return ruta


# --- Indicadores / Power BI --------------------------------------------------------------

def test_estandar_sin_permiso_ni_rol_permitido_no_ve_el_tablero(client, app, crear_usuario):
    _crear_tablero_powerbi(app, titulo='Ventas Trimestrales', roles_permitidos='admin')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    data = client.get('/buscar/api?q=ventas trimestrales').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' not in categorias


def test_estandar_con_permiso_extra_reportes_ve_cualquier_tablero_activo(client, app, crear_usuario):
    _crear_tablero_powerbi(app, titulo='Ventas Trimestrales', roles_permitidos='admin')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['reportes'])

    data = client.get('/buscar/api?q=ventas trimestrales').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' in categorias


def test_estandar_sin_permiso_extra_ve_tablero_cuyo_rol_esta_permitido(client, app, crear_usuario):
    _crear_tablero_powerbi(app, titulo='Rotación de Personal', roles_permitidos='estandar,agente')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    data = client.get('/buscar/api?q=rotacion de personal').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' in categorias


def test_tablero_bloqueado_no_aparece_ni_con_el_permiso_extra_si_no_es_admin(client, app, crear_usuario):
    _crear_tablero_powerbi(app, titulo='Tablero Bloqueado', roles_permitidos='admin', activo=False)
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['reportes'])

    data = client.get('/buscar/api?q=tablero bloqueado').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' not in categorias


def test_admin_ve_tablero_bloqueado_en_el_buscador_global(admin_session, app):
    _crear_tablero_powerbi(app, titulo='Tablero Bloqueado Admin', roles_permitidos='admin', activo=False)

    data = admin_session.get('/buscar/api?q=tablero bloqueado admin').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' in categorias


def test_agente_ve_el_catalogo_completo_de_powerbi_por_rol_sin_permiso_extra(client, app, crear_usuario):
    _crear_tablero_powerbi(app, titulo='Indicadores de Soporte TI', roles_permitidos='admin')
    agente = crear_usuario(usuario='agente_powerbi', rol='agente')
    _sesion_como(client, app, agente, 'agente')

    data = client.get('/buscar/api?q=indicadores de soporte ti').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Indicadores / Power BI' in categorias


def test_buscador_global_powerbi_enlaza_al_visor_del_tablero(admin_session, app):
    tablero_id = _crear_tablero_powerbi(app, titulo='Tablero Con Enlace')

    data = admin_session.get('/buscar/api?q=tablero con enlace').get_json()

    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Indicadores / Power BI')
    assert resultado['url'] == f'/indicadores/powerbi/{tablero_id}'


# --- Auditoría y Logs / Log de Correos Enviados -------------------------------------------

def test_estandar_sin_permiso_extra_no_ve_auditoria_en_el_buscador(client, app, crear_usuario):
    _crear_log(app, accion='Usuario eliminado', detalles='Se eliminó la cuenta xyz')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    data = client.get('/buscar/api?q=usuario eliminado').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Auditoría y Logs' not in categorias


def test_estandar_con_permiso_extra_auditoria_ve_logs(client, app, crear_usuario):
    _crear_log(app, accion='Usuario eliminado', detalles='Se eliminó la cuenta xyz')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['auditoria'])

    data = client.get('/buscar/api?q=usuario eliminado').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Auditoría y Logs' in categorias


def test_agente_ve_logs_por_rol_sin_permiso_extra(client, app, crear_usuario):
    _crear_log(app, accion='Ticket cerrado', detalles='Se cerró el ticket 42')
    agente = crear_usuario(usuario='agente_logs', rol='agente')
    _sesion_como(client, app, agente, 'agente')

    data = client.get('/buscar/api?q=ticket cerrado').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Auditoría y Logs' in categorias


def test_buscador_global_logs_enlaza_a_ver_logs_filtrado(admin_session, app):
    _crear_log(app, accion='Contraseña restablecida', detalles='Restablecimiento manual')

    data = admin_session.get('/buscar/api?q=contrasena restablecida').get_json()

    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Auditoría y Logs')
    assert resultado['url'] == '/logs?q=Contrase%C3%B1a+restablecida'


def test_correos_log_requiere_el_mismo_permiso_que_logs(client, app, crear_usuario):
    _crear_correo_log(app, destinatario='colaborador@preventivaips.com.co', asunto='Bienvenido a Arkiv')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar')

    data = client.get('/buscar/api?q=bienvenido a arkiv').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Log de Correos Enviados' not in categorias


def test_estandar_con_permiso_extra_auditoria_ve_el_log_de_correos(client, app, crear_usuario):
    _crear_correo_log(app, destinatario='colaborador@preventivaips.com.co', asunto='Bienvenido a Arkiv')
    usuario = crear_usuario(rol='estandar')
    _sesion_como(client, app, usuario, 'estandar', modulos_extra=['auditoria'])

    data = client.get('/buscar/api?q=bienvenido a arkiv').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Log de Correos Enviados' in categorias


# --- Respaldos de Base de Datos -------------------------------------------------------------

def test_respaldo_no_aparece_para_un_admin_que_no_es_el_superadmin_literal(client, app, crear_usuario, monkeypatch, tmp_path):
    monkeypatch.setattr(app, 'RESPALDOS_DIR', str(tmp_path))
    _crear_archivo_respaldo(str(tmp_path), 'manual_2026-09-19_100000.json')
    otro_admin = crear_usuario(usuario='otro_admin', rol='admin')
    _sesion_como(client, app, otro_admin, 'admin')

    data = client.get('/buscar/api?q=manual_2026').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Respaldos de Base de Datos' not in categorias


def test_respaldo_visible_solo_para_la_cuenta_superadmin_literal(admin_session, app, monkeypatch, tmp_path):
    monkeypatch.setattr(app, 'RESPALDOS_DIR', str(tmp_path))
    _crear_archivo_respaldo(str(tmp_path), 'manual_2026-09-19_100000.json')

    data = admin_session.get('/buscar/api?q=manual_2026').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Respaldos de Base de Datos' in categorias


def test_respaldo_enlaza_a_la_pagina_de_respaldos(admin_session, app, monkeypatch, tmp_path):
    monkeypatch.setattr(app, 'RESPALDOS_DIR', str(tmp_path))
    _crear_archivo_respaldo(str(tmp_path), 'auto_2026-09-18_010000.json')

    data = admin_session.get('/buscar/api?q=auto_2026').get_json()

    resultado = next(r for r in data['resultados'] if r['categoria'] == 'Respaldos de Base de Datos')
    assert resultado['url'] == '/admin/respaldos'
    assert 'Automático' in resultado['subtitulo']


def test_sin_carpeta_de_respaldos_no_hay_error_ni_resultados(admin_session, app, monkeypatch, tmp_path):
    carpeta_inexistente = str(tmp_path / 'no_existe')
    monkeypatch.setattr(app, 'RESPALDOS_DIR', carpeta_inexistente)

    data = admin_session.get('/buscar/api?q=respaldo').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Respaldos de Base de Datos' not in categorias


def test_los_cambios_en_el_sistema_de_respaldo_quedan_cubiertos_por_auditoria_y_logs(admin_session, app):
    """Pedido explícito de Tomás: "todos los cambios en el sistema de Respaldo, en el Backup de
    la DB" deben poder buscarse. No hay una tabla de respaldos en la BD (ver
    test_respaldo_visible_solo_para_la_cuenta_superadmin_literal para el archivo en sí), pero
    cada ACCIÓN sobre Respaldos ya se registra como una fila más en 'logs' (ver generar_respaldo,
    eliminar_respaldo, configurar_respaldo_automatico en app.py) — así que ya es buscable hoy vía
    la categoría "Auditoría y Logs", sin necesitar código nuevo."""
    _crear_log(app, accion='Respaldo manual generado', detalles='manual_2026-09-19_100000.json')

    data = admin_session.get('/buscar/api?q=respaldo manual generado').get_json()

    categorias = [r['categoria'] for r in data['resultados']]
    assert 'Auditoría y Logs' in categorias
