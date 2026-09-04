"""Pruebas del tercer tema visual 'Descansar la vista' (sepia/tenue), agregado junto a los
temas claro y oscuro ya existentes. Cubre: que /perfil/tema acepte y persista 'descanso', que
el ciclo del botón flotante pase por los 3 estados en el orden correcto, y que las páginas
carguen la hoja de estilos correspondiente."""


def test_cambiar_tema_acepta_descanso_y_lo_persiste(admin_session, app):
    r = admin_session.post('/perfil/tema', data={'tema': 'descanso'}, follow_redirects=False)
    assert r.status_code == 302

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tema FROM usuarios WHERE usuario = 'admin'")
    tema_guardado = cur.fetchone()[0]
    conn.close()
    assert tema_guardado == 'descanso'


def test_cambiar_tema_con_valor_invalido_cae_a_oscuro(admin_session, app):
    admin_session.post('/perfil/tema', data={'tema': 'algo-raro'})

    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT tema FROM usuarios WHERE usuario = 'admin'")
    tema_guardado = cur.fetchone()[0]
    conn.close()
    assert tema_guardado == 'oscuro'


def test_pagina_con_tema_descanso_activo_marca_data_theme_descanso(admin_session):
    admin_session.post('/perfil/tema', data={'tema': 'descanso'})

    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)

    assert 'data-theme="descanso"' in texto
    assert '/static/css/tema-descanso.css' in texto


def test_ciclo_del_boton_de_tema_pasa_por_los_3_estados(admin_session):
    # claro -> el botón debe ofrecer pasar a 'oscuro'
    admin_session.post('/perfil/tema', data={'tema': 'claro'})
    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)
    assert 'name="tema" value="oscuro"' in texto

    # oscuro -> el botón debe ofrecer pasar a 'descanso'
    admin_session.post('/perfil/tema', data={'tema': 'oscuro'})
    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)
    assert 'name="tema" value="descanso"' in texto

    # descanso -> el botón debe ofrecer volver a 'claro'
    admin_session.post('/perfil/tema', data={'tema': 'descanso'})
    texto = admin_session.get('/tickets/indicadores').get_data(as_text=True)
    assert 'name="tema" value="claro"' in texto


def test_login_no_se_ve_afectado_por_el_tema_descanso():
    """login.html no debe tocarse por este cambio: no tiene selector de tema ni depende de
    session['tema']."""
    import os
    ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates', 'login.html')
    with open(ruta, encoding='utf-8') as f:
        contenido = f.read()
    assert 'tema-descanso.css' not in contenido
    assert 'perfil/tema' not in contenido
