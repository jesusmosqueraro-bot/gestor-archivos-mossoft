"""Pruebas de la validación de contenido real de archivos subidos (magic bytes / firmas) —
hallazgo de auditoría de seguridad del 06/09/2026 (Tomás, con Gemini): antes, archivo_permitido
solo miraba la EXTENSIÓN del nombre del archivo (ALLOWED_EXTENSIONS), así que un ejecutable
renombrado a .pdf pasaba el filtro igual. Ahora, si se le pasa el archivo subido (FileStorage),
también revisa que su contenido real (los primeros bytes) sea compatible con esa extensión —
ver _firma_archivo_coincide y archivo_permitido en app.py."""
import io

import app as arkiv


def _file_storage(contenido: bytes, nombre: str):
    """Simula un archivo subido (lo que Flask/Werkzeug entrega en request.files) sin necesitar
    una petición HTTP completa — solo el nombre y el stream de bytes que archivo_permitido lee."""
    from werkzeug.datastructures import FileStorage
    return FileStorage(stream=io.BytesIO(contenido), filename=nombre)


def test_extension_no_permitida_se_rechaza_sin_importar_el_contenido():
    """Una .exe (extensión que ni siquiera está en la lista blanca) se rechaza de una, sin
    llegar a mirar el contenido — comportamiento que ya existía y no debe cambiar."""
    assert arkiv.archivo_permitido('virus.exe') is False


def test_sin_archivo_adjunto_pasa_solo_la_validacion_de_extension():
    """Si se llama sin el FileStorage (como en el código que solo necesita saber si la
    extensión es válida, antes de recibir el archivo), no se exige ninguna firma — mismo
    comportamiento de siempre para ese caso."""
    assert arkiv.archivo_permitido('foto.png') is True


def test_pdf_con_contenido_real_de_pdf_se_acepta():
    archivo = _file_storage(b'%PDF-1.4 contenido real de un pdf', 'informe.pdf')
    assert arkiv.archivo_permitido('informe.pdf', archivo) is True


def test_png_con_contenido_real_de_png_se_acepta():
    archivo = _file_storage(b'\x89PNG\r\n\x1a\ncontenido real de una imagen', 'foto.png')
    assert arkiv.archivo_permitido('foto.png', archivo) is True


def test_ejecutable_renombrado_a_pdf_se_rechaza():
    """El caso que motivó este arreglo: un .exe (firma 'MZ' de Windows) guardado con nombre
    informe.pdf. La extensión sola lo dejaría pasar; el contenido real lo delata."""
    archivo = _file_storage(b'MZ\x90\x00\x03\x00\x00\x00contenido de un ejecutable', 'informe.pdf')
    assert arkiv.archivo_permitido('informe.pdf', archivo) is False


def test_script_con_shebang_renombrado_a_imagen_se_rechaza():
    archivo = _file_storage(b'#!/bin/bash\nrm -rf /', 'foto.jpg')
    assert arkiv.archivo_permitido('foto.jpg', archivo) is False


def test_docx_con_contenido_falso_de_texto_plano_se_rechaza():
    """docx/xlsx/pptx son en el fondo un .zip (formato Office Open XML) — un archivo de texto
    plano guardado como .docx no trae la firma de zip (PK\\x03\\x04) y debe rechazarse."""
    archivo = _file_storage(b'esto no es un documento de Word de verdad', 'informe.docx')
    assert arkiv.archivo_permitido('informe.docx', archivo) is False


def test_docx_con_contenido_real_de_zip_se_acepta():
    archivo = _file_storage(b'PK\x03\x04contenido comprimido real', 'informe.docx')
    assert arkiv.archivo_permitido('informe.docx', archivo) is True


def test_txt_con_bytes_nulos_se_rechaza_por_parecer_binario():
    """El texto plano no tiene una firma fija, así que solo se rechaza si trae bytes nulos —
    indicio típico de que en realidad es contenido binario disfrazado de .txt."""
    archivo = _file_storage(b'contenido\x00binario\x00disfrazado', 'notas.txt')
    assert arkiv.archivo_permitido('notas.txt', archivo) is False


def test_txt_con_texto_normal_se_acepta():
    archivo = _file_storage('notas normales en español, con tildes: ñ á é'.encode('utf-8'), 'notas.txt')
    assert arkiv.archivo_permitido('notas.txt', archivo) is True


def test_la_validacion_de_contenido_no_deja_el_stream_desplazado():
    """archivo_permitido debe rebobinar el stream a donde estaba antes de leerlo — si no, el
    código que sube el archivo después (a Cloudinary) subiría el archivo sin sus primeros
    bytes."""
    archivo = _file_storage(b'%PDF-1.4 contenido real de un pdf', 'informe.pdf')
    assert arkiv.archivo_permitido('informe.pdf', archivo) is True
    assert archivo.stream.tell() == 0
    assert archivo.stream.read() == b'%PDF-1.4 contenido real de un pdf'
