"""Pruebas de los scripts de respaldo externo (scripts/respaldo_db_externo.py y
scripts/respaldo_cloudinary_externo.py). Estos scripts NO corren dentro de la app de Flask —
están pensados para un job programado de GitHub Actions (ver
.github/workflows/respaldo-externo.yml) — así que aquí se prueban de forma aislada, sin
necesidad de una base de datos ni de credenciales reales de S3/Cloudinary: se inyectan
dobles (fakes) donde el script real hablaría con pg_dump, boto3 o la Admin API de Cloudinary.
"""
from datetime import datetime, timezone

import pytest

from scripts import respaldo_cloudinary_externo as rc
from scripts import respaldo_db_externo as rd


# ─────────────────────────── respaldo_db_externo.py ───────────────────────────

def test_variables_faltantes_detecta_todo_lo_que_falta():
    assert set(rd.variables_faltantes({})) == {
        'DATABASE_URL', 'RESPALDO_S3_BUCKET', 'RESPALDO_S3_ACCESS_KEY_ID', 'RESPALDO_S3_SECRET_ACCESS_KEY',
    }


def test_variables_faltantes_vacio_cuando_todo_esta_configurado():
    config = {
        'database_url': 'postgresql://u:p@host/db',
        'bucket': 'mi-bucket',
        'access_key': 'AKIA...',
        'secret_key': 'secreto',
    }
    assert rd.variables_faltantes(config) == []


def test_nombre_archivo_respaldo_tiene_el_formato_esperado():
    momento = datetime(2026, 9, 14, 3, 0, 0, tzinfo=timezone.utc)
    assert rd.nombre_archivo_respaldo(momento) == 'arkiv_db_2026-09-14_030000.dump'


def test_clave_remota_junta_prefijo_y_nombre():
    config = {'prefijo': 'arkiv/db'}
    assert rd.clave_remota(config, 'arkiv_db_x.dump') == 'arkiv/db/arkiv_db_x.dump'


class _RunnerFalso:
    """Simula subprocess.run para pg_dump: 'escribe' el archivo de salida (como haría pg_dump
    de verdad con -f) y devuelve el returncode configurado."""

    def __init__(self, returncode=0, stderr='', contenido=b'contenido-falso-del-dump'):
        self.returncode = returncode
        self.stderr = stderr
        self.contenido = contenido
        self.llamados = []

    def __call__(self, comando, capture_output=True, text=True):
        self.llamados.append(comando)
        ruta_destino = comando[comando.index('-f') + 1]
        if self.returncode == 0:
            with open(ruta_destino, 'wb') as f:
                f.write(self.contenido)
        return self


def test_generar_dump_exitoso_escribe_el_archivo(tmp_path):
    runner = _RunnerFalso(returncode=0)
    destino = tmp_path / 'salida.dump'

    ruta = rd.generar_dump('postgresql://u:p@host/db', str(destino), runner=runner)

    assert ruta == str(destino)
    assert destino.read_bytes() == b'contenido-falso-del-dump'
    # La URL de conexión se pasa a pg_dump tal cual, no se filtra ni se registra en texto plano
    # en ningún otro lado que no sea el propio comando ejecutado.
    assert 'postgresql://u:p@host/db' in runner.llamados[0]


def test_generar_dump_fallido_lanza_con_el_stderr(tmp_path):
    runner = _RunnerFalso(returncode=1, stderr='pg_dump: error: connection refused')
    destino = tmp_path / 'salida.dump'

    with pytest.raises(RuntimeError, match='connection refused'):
        rd.generar_dump('postgresql://u:p@host/db', str(destino), runner=runner)


class _S3Falso:
    def __init__(self):
        self.subidos = []

    def upload_file(self, ruta_local, bucket, clave):
        self.subidos.append((ruta_local, bucket, clave))

    def get_object(self, Bucket, Key):
        raise KeyError('no existe en este fake')

    def put_object(self, **kwargs):
        self.subidos.append(kwargs)


def test_subir_a_s3_usa_bucket_y_clave_correctos(tmp_path):
    archivo = tmp_path / 'arkiv_db_2026-09-14_030000.dump'
    archivo.write_bytes(b'x')
    s3 = _S3Falso()
    config = {'bucket': 'mi-bucket', 'prefijo': 'arkiv/db'}

    clave = rd.subir_a_s3(s3, config, str(archivo), 'arkiv_db_2026-09-14_030000.dump')

    assert clave == 'arkiv/db/arkiv_db_2026-09-14_030000.dump'
    assert s3.subidos == [(str(archivo), 'mi-bucket', 'arkiv/db/arkiv_db_2026-09-14_030000.dump')]


def test_main_termina_con_error_si_faltan_variables(monkeypatch):
    for var in ('DATABASE_URL', 'RESPALDO_S3_BUCKET', 'RESPALDO_S3_ACCESS_KEY_ID', 'RESPALDO_S3_SECRET_ACCESS_KEY'):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        rd.main()
    assert exc_info.value.code == 1


# ─────────────────────────── respaldo_cloudinary_externo.py ───────────────────────────

def test_variables_faltantes_cloudinary_detecta_todo_lo_que_falta():
    faltantes = set(rc.variables_faltantes({}))
    assert 'RESPALDO_S3_BUCKET' in faltantes
    assert 'CLOUDINARY_CLOUD_NAME' in faltantes
    assert 'CLOUDINARY_API_KEY' in faltantes
    assert 'CLOUDINARY_API_SECRET' in faltantes


def test_extension_de_recurso_con_formato():
    assert rc.extension_de_recurso({'format': 'png'}) == '.png'


def test_extension_de_recurso_sin_formato():
    assert rc.extension_de_recurso({}) == ''


def test_clave_recurso_y_manifiesto():
    config = {'prefijo': 'arkiv/cloudinary'}
    assert rc.clave_recurso(config, 'image', 'fondo_login/abc123', '.jpg') == 'arkiv/cloudinary/image/fondo_login/abc123.jpg'
    assert rc.clave_manifiesto(config) == 'arkiv/cloudinary/_manifest.json'
    assert rc.clave_manifiesto_recurso('image', 'fondo_login/abc123') == 'image/fondo_login/abc123'


def test_debe_respaldarse_recurso_nuevo():
    assert rc.debe_respaldarse({}, 'image', {'public_id': 'x', 'version': 7}) is True


def test_debe_respaldarse_version_sin_cambios_se_omite():
    manifiesto = {'image/x': 7}
    assert rc.debe_respaldarse(manifiesto, 'image', {'public_id': 'x', 'version': 7}) is False


def test_debe_respaldarse_version_distinta_se_vuelve_a_respaldar():
    manifiesto = {'image/x': 6}
    assert rc.debe_respaldarse(manifiesto, 'image', {'public_id': 'x', 'version': 7}) is True


class _ApiCloudinaryFalsa:
    """Simula cloudinary.api.resources(...) con paginación de dos páginas, para probar que
    listar_recursos_cloudinary recorre TODO el resultado y no solo la primera página."""

    def __init__(self, paginas):
        self.paginas = paginas
        self.llamados = []

    def resources(self, **kwargs):
        self.llamados.append(kwargs)
        cursor = kwargs.get('next_cursor')
        indice = 0 if cursor is None else int(cursor)
        return self.paginas[indice]


def test_listar_recursos_cloudinary_recorre_todas_las_paginas():
    api = _ApiCloudinaryFalsa(paginas=[
        {'resources': [{'public_id': 'a'}], 'next_cursor': '1'},
        {'resources': [{'public_id': 'b'}]},
    ])

    recursos = list(rc.listar_recursos_cloudinary('image', api=api))

    assert [r['public_id'] for r in recursos] == ['a', 'b']
    assert api.llamados[0]['resource_type'] == 'image'
    assert 'next_cursor' not in api.llamados[0]
    assert api.llamados[1]['next_cursor'] == '1'


class _RespuestaDescargaFalsa:
    def __init__(self, contenido=b'bytes-del-archivo'):
        self.content = contenido

    def raise_for_status(self):
        pass


def test_respaldar_recurso_descarga_y_sube_al_bucket():
    s3 = _S3Falso()
    config = {'bucket': 'mi-bucket', 'prefijo': 'arkiv/cloudinary'}
    recurso = {'public_id': 'firmas/juan', 'secure_url': 'https://res.cloudinary.com/x/raw/upload/firmas/juan.png', 'format': 'png'}
    descargas = []

    def descargar_falso(url, timeout=60):
        descargas.append((url, timeout))
        return _RespuestaDescargaFalsa()

    # upload_fileobj no está en _S3Falso todavía — se agrega aquí para esta prueba puntual.
    subidos_fileobj = []
    s3.upload_fileobj = lambda fileobj, bucket, clave: subidos_fileobj.append((fileobj.read(), bucket, clave))

    clave = rc.respaldar_recurso(s3, config, 'image', recurso, descargar=descargar_falso)

    assert clave == 'arkiv/cloudinary/image/firmas/juan.png'
    assert descargas == [('https://res.cloudinary.com/x/raw/upload/firmas/juan.png', 60)]
    assert subidos_fileobj == [(b'bytes-del-archivo', 'mi-bucket', 'arkiv/cloudinary/image/firmas/juan.png')]


def test_main_cloudinary_termina_con_error_si_faltan_variables(monkeypatch):
    for var in ('RESPALDO_S3_BUCKET', 'RESPALDO_S3_ACCESS_KEY_ID', 'RESPALDO_S3_SECRET_ACCESS_KEY',
                'CLOUDINARY_CLOUD_NAME', 'CLOUDINARY_API_KEY', 'CLOUDINARY_API_SECRET'):
        monkeypatch.delenv(var, raising=False)

    with pytest.raises(SystemExit) as exc_info:
        rc.main()
    assert exc_info.value.code == 1


def test_main_cloudinary_respalda_lo_nuevo_y_omite_lo_ya_respaldado(monkeypatch):
    """Prueba de integración con todo lo externo (S3, Cloudinary) reemplazado por dobles: dos
    recursos ya en el manifiesto con su versión vigente (se omiten) y uno nuevo (se respalda)."""
    monkeypatch.setenv('RESPALDO_S3_BUCKET', 'mi-bucket')
    monkeypatch.setenv('RESPALDO_S3_ACCESS_KEY_ID', 'clave')
    monkeypatch.setenv('RESPALDO_S3_SECRET_ACCESS_KEY', 'secreto')
    monkeypatch.setenv('CLOUDINARY_CLOUD_NAME', 'demo')
    monkeypatch.setenv('CLOUDINARY_API_KEY', 'k')
    monkeypatch.setenv('CLOUDINARY_API_SECRET', 's')

    manifiesto_previo = {'image/ya_respaldado': 3}
    s3 = _S3Falso()
    subidos_fileobj = []
    s3.upload_fileobj = lambda fileobj, bucket, clave: subidos_fileobj.append((bucket, clave))
    import json as _json
    s3.get_object = lambda Bucket, Key: {'Body': type('B', (), {'read': lambda self: _json.dumps(manifiesto_previo).encode()})()}
    guardados = []
    s3.put_object = lambda **kwargs: guardados.append(kwargs)

    monkeypatch.setattr(rc, 'cliente_s3', lambda config: s3)
    monkeypatch.setattr(rc.cloudinary, 'config', lambda **kwargs: None)

    recursos_por_tipo = {
        'image': [
            {'public_id': 'ya_respaldado', 'version': 3, 'secure_url': 'https://x/ya.png', 'format': 'png'},
            {'public_id': 'nuevo', 'version': 1, 'secure_url': 'https://x/nuevo.png', 'format': 'png'},
        ],
        'video': [],
        'raw': [],
    }

    def listar_falso(resource_type, api=None):
        return iter(recursos_por_tipo[resource_type])

    monkeypatch.setattr(rc, 'listar_recursos_cloudinary', listar_falso)
    monkeypatch.setattr(rc, 'respaldar_recurso', lambda s3_, config, resource_type, recurso, descargar=None: f"arkiv/cloudinary/{resource_type}/{recurso['public_id']}.png")

    rc.main()

    # El manifiesto guardado al final debe conservar el que ya estaba Y agregar el nuevo.
    manifiesto_final = _json.loads(guardados[-1]['Body'])
    assert manifiesto_final == {'image/ya_respaldado': 3, 'image/nuevo': 1}
