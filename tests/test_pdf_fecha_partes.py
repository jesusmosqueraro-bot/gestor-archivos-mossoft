"""Pruebas de _pdf_fecha_partes: separa la fecha guardada de un acta en (dd, mm, aaaa) para la
casilla 'FECHA | DD | MM | AAAA' del PDF (formato en papel de Preventiva IPS).

Bug reportado por Tomás (08/09/2026, con capturas comparando dos actas): algunas actas mostraban
la fecha completa metida en la casilla AAAA, con DD y MM vacíos. Causa: la función solo probaba
el formato 'AAAA-MM-DD HH:MM:SS' de obtener_fecha_actual(), pero (a) el correo automático de
asignación (_enviar_formulario_asignacion_por_correo) armaba su propia fecha SIN hora
('AAAA-MM-DD'), y (b) las actas más antiguas, de antes de la corrección de DateStyle en Postgres,
quedaron guardadas con el formato previo ('DD/MM/AAAA hh:mm AM/PM')."""


def test_fecha_con_hora_formato_actual_se_separa_correctamente(app):
    dd, mm, aaaa = app._pdf_fecha_partes('2026-09-07 17:51:00')
    assert (dd, mm, aaaa) == ('07', '09', '2026')


def test_fecha_sin_hora_tambien_se_separa_correctamente(app):
    """Este era el caso que reventaba: el correo automático de asignación arma la fecha sin
    componente de hora ('AAAA-MM-DD')."""
    dd, mm, aaaa = app._pdf_fecha_partes('2026-09-07')
    assert (dd, mm, aaaa) == ('07', '09', '2026')


def test_fecha_en_formato_historico_dd_mm_aaaa_se_separa_correctamente(app):
    """Formato usado antes de la corrección de DateStyle en Postgres (ver obtener_fecha_actual)."""
    dd, mm, aaaa = app._pdf_fecha_partes('07/09/2026 05:51 PM')
    assert (dd, mm, aaaa) == ('07', '09', '2026')


def test_fecha_vacia_no_revienta(app):
    dd, mm, aaaa = app._pdf_fecha_partes('')
    assert (dd, mm, aaaa) == ('', '', '-')
    dd, mm, aaaa = app._pdf_fecha_partes(None)
    assert (dd, mm, aaaa) == ('', '', '-')


def test_fecha_en_formato_desconocido_no_revienta_y_muestra_el_texto_tal_cual(app):
    """Si algún día apareciera un formato no contemplado, el PDF debe seguir generándose (con la
    fecha completa visible en la casilla AAAA) en vez de lanzar una excepción."""
    dd, mm, aaaa = app._pdf_fecha_partes('texto-no-es-una-fecha')
    assert dd == ''
    assert mm == ''
    assert aaaa == 'texto-no-es-una-fecha'
