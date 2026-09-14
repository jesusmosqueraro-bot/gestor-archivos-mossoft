#!/usr/bin/env python3
"""📦 Respaldo externo (espejo) de los archivos de Cloudinary hacia el mismo almacenamiento
S3-compatible que usa respaldo_db_externo.py (ver ese archivo para la explicación de por qué
S3-compatible sirve tanto para AWS S3 como para Backblaze B2).

Por qué hace falta: Cloudinary es hoy la ÚNICA copia de todos los archivos que la gente sube a
Arkiv (fotos y videos del Fondo de Login, adjuntos de tickets y del chat, firmas digitalizadas,
actas). Si esa cuenta de Cloudinary se pierde, se borra por error, o hay un problema de
facturación, esos archivos desaparecen sin que exista ninguna copia en otro lado. Este script
cierra ese hueco copiando cada recurso (imagen/video/archivo) a un bucket aparte.

Mantiene un manifiesto (_manifest.json, guardado dentro del propio bucket) con la versión de
cada recurso ya respaldado, para NO volver a descargar/subir en cada corrida lo que ya está al
día — con una cuenta de Cloudinary grande (sobre todo por los videos), volver a bajar todo cada
vez sería lento y caro en transferencia. Solo se descarga/sube lo nuevo o lo que cambió de
versión desde la corrida anterior.

Pensado para correr como un job PROGRAMADO de GitHub Actions (ver
.github/workflows/respaldo-externo.yml), NO dentro de la app de Flask en Render — copiar
archivos grandes no debe competir por recursos con el tráfico real de la app.

Variables de entorno requeridas (además de las de respaldo_db_externo.py: RESPALDO_S3_BUCKET,
RESPALDO_S3_ACCESS_KEY_ID, RESPALDO_S3_SECRET_ACCESS_KEY):
  CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET   (las mismas que ya usa Arkiv)
Opcionales:
  RESPALDO_S3_ENDPOINT_URL, RESPALDO_S3_REGION   (igual que en respaldo_db_externo.py)
  RESPALDO_S3_PREFIJO_CLOUDINARY                 Carpeta dentro del bucket (default 'arkiv/cloudinary').
"""
import io
import json
import os
import sys

import boto3
import cloudinary
import cloudinary.api
import requests

TIPOS_DE_RECURSO = ('image', 'video', 'raw')


def _configuracion_desde_entorno():
    return {
        'bucket': os.environ.get('RESPALDO_S3_BUCKET'),
        'access_key': os.environ.get('RESPALDO_S3_ACCESS_KEY_ID'),
        'secret_key': os.environ.get('RESPALDO_S3_SECRET_ACCESS_KEY'),
        'endpoint_url': os.environ.get('RESPALDO_S3_ENDPOINT_URL') or None,
        'region': os.environ.get('RESPALDO_S3_REGION', 'us-east-1'),
        'prefijo': (os.environ.get('RESPALDO_S3_PREFIJO_CLOUDINARY', 'arkiv/cloudinary') or 'arkiv/cloudinary').strip('/'),
        'cloudinary_cloud_name': os.environ.get('CLOUDINARY_CLOUD_NAME'),
        'cloudinary_api_key': os.environ.get('CLOUDINARY_API_KEY'),
        'cloudinary_api_secret': os.environ.get('CLOUDINARY_API_SECRET'),
    }


def variables_faltantes(config):
    requeridas = {
        'RESPALDO_S3_BUCKET': config.get('bucket'),
        'RESPALDO_S3_ACCESS_KEY_ID': config.get('access_key'),
        'RESPALDO_S3_SECRET_ACCESS_KEY': config.get('secret_key'),
        'CLOUDINARY_CLOUD_NAME': config.get('cloudinary_cloud_name'),
        'CLOUDINARY_API_KEY': config.get('cloudinary_api_key'),
        'CLOUDINARY_API_SECRET': config.get('cloudinary_api_secret'),
    }
    return [nombre for nombre, valor in requeridas.items() if not valor]


def clave_manifiesto(config):
    return f"{config['prefijo']}/_manifest.json"


def clave_recurso(config, resource_type, public_id, extension):
    return f"{config['prefijo']}/{resource_type}/{public_id}{extension}"


def clave_manifiesto_recurso(resource_type, public_id):
    """Clave interna dentro del diccionario del manifiesto (no confundir con clave_manifiesto,
    que es la ruta del ARCHIVO del manifiesto en el bucket)."""
    return f"{resource_type}/{public_id}"


def extension_de_recurso(recurso):
    formato = recurso.get('format')
    return f".{formato}" if formato else ''


def debe_respaldarse(manifiesto, resource_type, recurso):
    """True si este recurso es nuevo o cambió de versión desde el último respaldo — o sea, si
    hay que (re)descargarlo y subirlo. False si el manifiesto ya tiene registrada exactamente
    esta versión (nada que hacer)."""
    clave = clave_manifiesto_recurso(resource_type, recurso['public_id'])
    return manifiesto.get(clave) != recurso.get('version')


def cliente_s3(config):
    return boto3.client(
        's3',
        endpoint_url=config['endpoint_url'],
        aws_access_key_id=config['access_key'],
        aws_secret_access_key=config['secret_key'],
        region_name=config['region'],
    )


def leer_manifiesto(s3, config):
    """Lee el manifiesto guardado en el bucket. {} si todavía no existe (primera corrida) o si
    el archivo quedó corrupto — nunca revienta el respaldo por esto (peor caso: se vuelve a
    respaldar algo que ya estaba al día)."""
    try:
        obj = s3.get_object(Bucket=config['bucket'], Key=clave_manifiesto(config))
        return json.loads(obj['Body'].read())
    except Exception:
        return {}


def guardar_manifiesto(s3, config, manifiesto):
    s3.put_object(
        Bucket=config['bucket'],
        Key=clave_manifiesto(config),
        Body=json.dumps(manifiesto).encode('utf-8'),
        ContentType='application/json',
    )


def listar_recursos_cloudinary(resource_type, api=cloudinary.api):
    """Recorre TODOS los recursos de un resource_type dado, paginando con next_cursor hasta
    agotarlos. 'api' es inyectable para las pruebas."""
    cursor = None
    while True:
        parametros = {'resource_type': resource_type, 'type': 'upload', 'max_results': 500}
        if cursor:
            parametros['next_cursor'] = cursor
        respuesta = api.resources(**parametros)
        for recurso in respuesta.get('resources', []):
            yield recurso
        cursor = respuesta.get('next_cursor')
        if not cursor:
            break


def respaldar_recurso(s3, config, resource_type, recurso, descargar=requests.get):
    """Descarga un recurso desde su secure_url y lo sube al bucket. 'descargar' es inyectable
    para las pruebas (evita golpear la red real)."""
    respuesta = descargar(recurso['secure_url'], timeout=60)
    respuesta.raise_for_status()
    clave = clave_recurso(config, resource_type, recurso['public_id'], extension_de_recurso(recurso))
    s3.upload_fileobj(io.BytesIO(respuesta.content), config['bucket'], clave)
    return clave


def main():
    config = _configuracion_desde_entorno()
    faltantes = variables_faltantes(config)
    if faltantes:
        print(f"❌ Faltan variables de entorno: {', '.join(faltantes)}")
        sys.exit(1)

    cloudinary.config(
        cloud_name=config['cloudinary_cloud_name'],
        api_key=config['cloudinary_api_key'],
        api_secret=config['cloudinary_api_secret'],
    )
    s3 = cliente_s3(config)
    manifiesto = leer_manifiesto(s3, config)

    copiados = omitidos = fallidos = 0
    for resource_type in TIPOS_DE_RECURSO:
        for recurso in listar_recursos_cloudinary(resource_type):
            if not debe_respaldarse(manifiesto, resource_type, recurso):
                omitidos += 1
                continue
            try:
                clave = respaldar_recurso(s3, config, resource_type, recurso)
                manifiesto[clave_manifiesto_recurso(resource_type, recurso['public_id'])] = recurso.get('version')
                copiados += 1
                print(f"✅ {recurso['public_id']} → {clave}")
            except Exception as e:
                # Diagnóstico temporal: access_mode/type/created_at no son sensibles (no son
                # credenciales ni URLs) y ayudan a distinguir la causa más probable de un 404 al
                # descargar secure_url — un recurso con access_mode="authenticated" (entrega
                # restringida, necesita URL firmada) o type distinto de "upload" (no debería pasar
                # por el filtro de listar_recursos_cloudinary, pero se confirma aquí igual).
                print(
                    f"⚠️ Error respaldando '{recurso['public_id']}' ({resource_type}): {e} "
                    f"[access_mode={recurso.get('access_mode')!r} type={recurso.get('type')!r} "
                    f"created_at={recurso.get('created_at')!r}]"
                )
                fallidos += 1

    guardar_manifiesto(s3, config, manifiesto)
    print(f"\nResumen: {copiados} copiados, {omitidos} sin cambios, {fallidos} con error")
    if fallidos:
        sys.exit(1)


if __name__ == '__main__':
    main()
