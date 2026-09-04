"""Pruebas del atajo de teclado Esc (static/js/atajos_teclado.js): cierra modales abiertos y,
si no hay ninguno, navega a la página anterior del historial. El script debe incluirse en
todas las páginas de un módulo ya autenticado, pero NUNCA en login/recuperación/cambio de
clave obligatorio — ahí Esc no debe poder sacar a nadie del flujo de autenticación a medias."""


def test_bienvenida_incluye_el_atajo_de_esc(admin_session):
    texto = admin_session.get('/bienvenida').get_data(as_text=True)
    assert '/static/js/atajos_teclado.js' in texto


def test_inventario_incluye_el_atajo_de_esc(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert '/static/js/atajos_teclado.js' in texto


def test_gestor_de_archivos_incluye_el_atajo_de_esc(admin_session):
    texto = admin_session.get('/gestor').get_data(as_text=True)
    assert '/static/js/atajos_teclado.js' in texto


def test_login_no_incluye_el_atajo_de_esc(client):
    texto = client.get('/login').get_data(as_text=True)
    assert '/static/js/atajos_teclado.js' not in texto


def test_recuperar_clave_no_incluye_el_atajo_de_esc(client):
    texto = client.get('/recuperar').get_data(as_text=True)
    assert '/static/js/atajos_teclado.js' not in texto


def test_el_script_cierra_cualquier_modal_con_id_modal_y_navega_atras_si_no_hay_ninguno():
    """El comportamiento en el navegador no se puede probar con pytest (no hay DOM real), pero
    sí se puede verificar que el archivo implementa las tres reglas documentadas: cerrar
    modales abiertos por convención de id, no interrumpir un campo de texto a medio escribir
    en el primer Esc, y navegar atrás con el historial del navegador en cualquier otro caso."""
    contenido = open('static/js/atajos_teclado.js', encoding='utf-8').read()
    assert "evento.key !== 'Escape'" in contenido
    assert '[id^="modal-"]:not(.hidden)' in contenido
    assert 'elementoActivo.blur()' in contenido
    assert 'window.history.back()' in contenido
