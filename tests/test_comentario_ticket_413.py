"""🐛 Hallazgo reportado por Tomás (07/09/2026, con captura del error): al pegar una imagen
directamente en el editor de texto enriquecido de un comentario de ticket, Quill la mete en el
propio campo 'mensaje' como una línea de texto codificada en base64 — un campo de formulario
normal, no un archivo — y eso dispara un 413 "Request Entity Too Large" crudo de Werkzeug
(MAX_FORM_MEMORY_SIZE, ~500 KB) en vez de un aviso entendible. El bloqueo real vive del lado del
cliente (ver editor-enriquecido.js, que ya no deja pegar imágenes en el editor); esta prueba
cubre la red de seguridad del lado del servidor (_manejar_archivo_demasiado_grande en app.py)
para que, si de todas formas llega un campo de formulario demasiado pesado, la persona reciba un
redirect con un aviso en español en vez de la página de error en inglés de Werkzeug."""

from tests.test_tickets import _crear_ticket


def test_mensaje_demasiado_pesado_no_revienta_con_413_crudo(sesion_usuario, app):
    _crear_ticket(sesion_usuario, titulo="Ticket para probar el 413")
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets WHERE titulo = ?", ("Ticket para probar el 413",))
    ticket_id = cur.fetchone()[0]
    conn.close()

    # Simula lo que Quill produciría al pegar una captura de pantalla: una sola línea de texto
    # (base64) muchísimo más pesada que MAX_FORM_MEMORY_SIZE (500 KB) dentro del campo 'mensaje'.
    mensaje_gigante = "<p><img src=\"data:image/png;base64," + ("A" * (2 * 1024 * 1024)) + "\"></p>"

    r = sesion_usuario.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': mensaje_gigante}, follow_redirects=False)

    # No debe ser el 413 crudo de Werkzeug: el manejador global lo convierte en un redirect
    # (mismo patrón que _manejar_csrf_invalido) con un aviso amigable vía flash().
    assert r.status_code in (302, 303)


def test_mensaje_demasiado_pesado_muestra_aviso_amigable(sesion_usuario, app):
    _crear_ticket(sesion_usuario, titulo="Ticket para probar el aviso 413")
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM tickets WHERE titulo = ?", ("Ticket para probar el aviso 413",))
    ticket_id = cur.fetchone()[0]
    conn.close()

    mensaje_gigante = "<p><img src=\"data:image/png;base64," + ("A" * (2 * 1024 * 1024)) + "\"></p>"
    sesion_usuario.post(f'/tickets/{ticket_id}/comentar', data={'mensaje': mensaje_gigante}, follow_redirects=False,
                         headers={'Referer': f'/tickets/{ticket_id}'})

    r = sesion_usuario.get(f'/tickets/{ticket_id}')
    assert 'demasiado pesado' in r.get_data(as_text=True)
