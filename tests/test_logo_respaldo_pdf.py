"""Prueba del respaldo del logo institucional en los PDF de actas (pedido de Tomás, 26/09/2026):
'Restaurar el logo institucional de Preventiva Salud IPS en el encabezado de los PDFs generados
... Asegurar que la ruta estática o renderizado en base64 cargue correctamente'.

Hipótesis de la causa reportada: una URL de Cloudinary vencida/caída guardada en
configuracion_app (de una personalización anterior desde /admin/diseno) hacía que
_cargar_imagen_reader_desde_fuente fallara en silencio y el PDF saliera SIN logo, sin ningún
aviso visible para el usuario. La corrección agrega un reintento automático con el archivo local
de fábrica (static/img/logo_preventiva.png) cuando la fuente configurada no se puede cargar.
"""


def test_logo_local_de_fabrica_carga_sin_configuracion_previa(app):
    """Sin ninguna personalización guardada en configuracion_app, la fuente del logo debe ser
    el archivo local de fábrica y debe cargar correctamente (esto ya funcionaba, pero confirma
    que la ruta estática en sí es válida)."""
    fuente = app._logo_institucional_fuente_pdf()
    assert fuente == app._RUTA_LOGO_PREVENTIVA
    lector = app._cargar_imagen_reader_desde_fuente(fuente)
    assert lector is not None


def test_url_de_cloudinary_caida_cae_de_vuelta_al_logo_local(app, monkeypatch):
    """Simula el escenario de producción: una URL de Cloudinary configurada que ya no responde
    (URL vencida/borrada). Antes, esto devolvía None (sin logo en el PDF, sin aviso). Ahora debe
    recuperar el logo local de fábrica en su lugar."""
    app._guardar_config_app(app.CLAVE_LOGO_INSTITUCIONAL, 'https://res.cloudinary.com/no-existe/imagen-vencida.png')

    def _get_que_falla(*a, **k):
        raise Exception("Simulated network failure: URL vencida")

    import requests
    monkeypatch.setattr(requests, 'get', _get_que_falla)

    fuente = app._logo_institucional_fuente_pdf()
    assert fuente.startswith('https://')
    lector = app._cargar_imagen_reader_desde_fuente(fuente)
    assert lector is not None, "Debe recuperar el logo local de fábrica en vez de quedar sin logo"


def test_marca_agua_tambien_cae_de_vuelta_al_logo_local(app, monkeypatch):
    """Mismo escenario que arriba, pero para la marca de agua (_marca_agua_logo_imagen_reader),
    que tenía su propia carga inline (no reutilizaba _cargar_imagen_reader_desde_fuente)."""
    app._guardar_config_app(app.CLAVE_LOGO_INSTITUCIONAL, 'https://res.cloudinary.com/no-existe/otra-vencida.png')
    app._MARCA_AGUA_LOGO_CACHE.clear()

    def _get_que_falla(*a, **k):
        raise Exception("Simulated network failure")

    import requests
    monkeypatch.setattr(requests, 'get', _get_que_falla)

    lector = app._marca_agua_logo_imagen_reader()
    assert lector is not None


def test_acta_de_asignacion_incluye_logo_pese_a_url_personalizada_caida(app, monkeypatch, admin_session):
    """Prueba de extremo a extremo: con una URL de logo personalizada rota guardada, el PDF del
    acta de asignación se debe seguir generando sin errores (y con logo real incrustado)."""
    app._guardar_config_app(app.CLAVE_LOGO_INSTITUCIONAL, 'https://res.cloudinary.com/no-existe/rota.png')

    def _get_que_falla(*a, **k):
        raise Exception("Simulated network failure")

    import requests
    monkeypatch.setattr(requests, 'get', _get_que_falla)

    campos = {
        'numero_acta': 1, 'fecha': '2026-09-26', 'responsable_asignacion': 'Admin',
        'asignado_a': 'Colaborador de Prueba', 'sede': 'Naranjal', 'area': 'Sistemas',
        'tipo_activo': 'Laptop', 'marca': 'Dell', 'modelo': 'Latitude', 'placa': '15011',
        'numero_serie': 'ABC123', 'proveedor': None, 'descripcion_breve': None,
        'firma_asigna_url': None, 'firma_url': None, 'es_biomedico': False, 'categoria_especial': None,
    }
    pdf_bytes = app._pdf_bytes_acta_asignacion(campos)
    assert pdf_bytes[:4] == b'%PDF'
    assert len(pdf_bytes) > 500
