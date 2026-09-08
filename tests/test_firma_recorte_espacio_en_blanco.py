"""Pruebas del recorte de espacio en blanco alrededor de una firma antes de incrustarla en un PDF
de acta (pedido de Tomás, 08/09/2026: 'las firmas se ven un poco orientadas hacia la
izquierda') — el canvas de firma digital siempre exporta un lienzo del mismo tamaño fijo, pero
el trazo casi nunca lo llena por completo, así que al incrustar la imagen tal cual (con un
ancho/alto fijo en el PDF) el trazo queda pegado a donde haya quedado dibujado dentro del lienzo
original en vez de centrado en su celda. _recortar_imagen_firma() recorta ese espacio en blanco
sobrante antes de que _pdf_elemento_firma() calcule el tamaño final preservando la proporción."""
import io

from PIL import Image, ImageDraw


def _png_con_trazo(tamano=(600, 200), caja_trazo=(20, 30, 100, 90), color_fondo=(255, 255, 255)):
    """Simula el PNG que exporta el canvas de firma: un lienzo grande, mayormente en blanco, con
    un trazo (rectángulo relleno, para tener bordes exactos y predecibles) solo en una porción
    pequeña — reproduce el caso real donde el trazo no llena el lienzo completo."""
    img = Image.new('RGB', tamano, color_fondo)
    draw = ImageDraw.Draw(img)
    draw.rectangle(caja_trazo, fill=(0, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return buf.getvalue()


def test_recorta_el_espacio_en_blanco_alrededor_del_trazo(app):
    datos = _png_con_trazo(tamano=(600, 200), caja_trazo=(20, 30, 100, 90))

    recortado = app._recortar_imagen_firma(datos)
    img = Image.open(io.BytesIO(recortado))

    assert img.size[0] < 600
    assert img.size[1] < 200


def test_el_recorte_queda_centrado_en_el_trazo_no_en_el_lienzo(app):
    """El trazo real está pegado a la esquina superior izquierda del lienzo (20,30)-(100,90) —
    tras recortar, el margen sobrante alrededor del trazo debe ser prácticamente simétrico (el
    mismo margen fijo en los 4 lados), no el desbalance original del lienzo de 600x200."""
    datos = _png_con_trazo(tamano=(600, 200), caja_trazo=(20, 30, 100, 90))

    recortado = app._recortar_imagen_firma(datos)
    img = Image.open(io.BytesIO(recortado))

    # Con margen=14 fijo en _recortar_imagen_firma: ancho ~ (100-20)+2*14=108, alto ~ (90-30)+2*14=88
    # (con clamping en los bordes si el margen se sale del lienzo, no es el caso aquí).
    assert 100 <= img.size[0] <= 116
    assert 80 <= img.size[1] <= 96


def test_lienzo_vacio_sin_trazo_devuelve_los_bytes_originales(app):
    img = Image.new('RGB', (600, 200), (255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    datos_vacio = buf.getvalue()

    resultado = app._recortar_imagen_firma(datos_vacio)

    assert resultado == datos_vacio


def test_imagen_invalida_no_revienta_y_devuelve_los_bytes_originales(app):
    datos_invalidos = b'esto no es un PNG ni un JPEG'

    resultado = app._recortar_imagen_firma(datos_invalidos)

    assert resultado == datos_invalidos


def test_recorta_correctamente_un_lienzo_con_fondo_transparente(app):
    """Si el canvas de firma exportó con fondo transparente (RGBA) en vez de blanco, el recorte
    debe seguir encontrando el trazo real y no confundir el canal alfa con contenido."""
    img = Image.new('RGBA', (600, 200), (255, 255, 255, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle((20, 30, 100, 90), fill=(0, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    datos = buf.getvalue()

    recortado = app._recortar_imagen_firma(datos)
    img2 = Image.open(io.BytesIO(recortado))

    assert img2.size[0] < 600
    assert img2.size[1] < 200


def test_pdf_elemento_firma_preserva_la_proporcion_de_una_firma_ancha(app, monkeypatch):
    """Una firma muy ancha y poco alta (proporción distinta al recuadro 6.5x3cm por defecto) no
    debe quedar deformada al incrustarse — _pdf_elemento_firma debe escalarla preservando su
    proporción real en vez de forzar el ancho/alto fijos."""
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm

    datos = _png_con_trazo(tamano=(600, 100), caja_trazo=(20, 20, 580, 80))

    class _RespuestaFalsa:
        def read(self):
            return datos

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(app.urllib.request, 'urlopen', lambda *a, **k: _RespuestaFalsa())

    elemento = app._pdf_elemento_firma('https://ejemplo.com/firma.png', getSampleStyleSheet())

    proporcion_imagen = elemento.drawWidth / elemento.drawHeight
    assert proporcion_imagen > 1.5  # sigue siendo claramente más ancha que alta, no cuadrada
