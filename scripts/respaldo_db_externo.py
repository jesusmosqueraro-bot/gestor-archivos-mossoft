#!/usr/bin/env python3
"""📦 Respaldo externo de la base de datos (Postgres/Neon) hacia almacenamiento S3-compatible
(AWS S3 o Backblaze B2 — ambos hablan el mismo protocolo S3 vía boto3, así que este mismo script
sirve para cualquiera de los dos sin cambiar una línea, solo configurando las variables de
entorno de abajo).

Pensado para correr como un job PROGRAMADO de GitHub Actions (ver
.github/workflows/respaldo-externo.yml), NO dentro de la app de Flask en Render — así el
respaldo no depende de que Render esté disponible ni compite por recursos con el tráfico real,
y sigue funcionando aunque Render, Neon o Cloudinary tengan un problema al mismo tiempo.

Por qué esto además del respaldo que ya genera la propia app (ver "MÓDULO DE RESPALDOS DE BASE
DE DATOS" en app.py): ese respaldo vuelca en JSON solo los DATOS de una lista fija de tablas
(TABLAS_RESPALDO) y no incluye el ESQUEMA, así que no se puede restaurar con una herramienta
estándar de Postgres — hay que escribir un importador a mano. Este script usa `pg_dump` en
formato 'custom' (-Fc): un volcado binario comprimido que incluye esquema + datos y se restaura
directo con `pg_restore`, la forma estándar y más confiable de recuperar una base de Postgres
completa. Ver el bloque "CÓMO RESTAURAR" al final de este archivo.

Variables de entorno requeridas:
  DATABASE_URL                    Cadena de conexión de Postgres (la misma que usa Render/Neon).
  RESPALDO_S3_BUCKET              Nombre del bucket destino.
  RESPALDO_S3_ACCESS_KEY_ID       Access key del bucket.
  RESPALDO_S3_SECRET_ACCESS_KEY   Secret key del bucket.
Opcionales:
  RESPALDO_S3_ENDPOINT_URL        Endpoint S3-compatible (ej. Backblaze B2:
                                   https://s3.<region>.backblazeb2.com). Vacío/ausente = AWS S3.
  RESPALDO_S3_REGION              Región (default 'us-east-1'; Backblaze la ignora en la
                                   práctica pero boto3 exige que se le pase algo).
  RESPALDO_S3_PREFIJO_DB          Prefijo/carpeta dentro del bucket (default 'arkiv/db').

La retención (cuánto tiempo se guardan los respaldos viejos) se configura como una regla de
"lifecycle" en el bucket mismo (ver instrucciones en el README de este directorio) — más simple
y más seguro que si este script tuviera que borrar objetos por su cuenta.
"""
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

import boto3


def _configuracion_desde_entorno():
    """Junta toda la configuración leída de variables de entorno en un solo dict, para que el
    resto del script (y las pruebas) no dependan de leer os.environ directamente en cada punto."""
    return {
        'database_url': os.environ.get('DATABASE_URL'),
        'bucket': os.environ.get('RESPALDO_S3_BUCKET'),
        'access_key': os.environ.get('RESPALDO_S3_ACCESS_KEY_ID'),
        'secret_key': os.environ.get('RESPALDO_S3_SECRET_ACCESS_KEY'),
        'endpoint_url': os.environ.get('RESPALDO_S3_ENDPOINT_URL') or None,
        'region': os.environ.get('RESPALDO_S3_REGION', 'us-east-1'),
        'prefijo': (os.environ.get('RESPALDO_S3_PREFIJO_DB', 'arkiv/db') or 'arkiv/db').strip('/'),
    }


def variables_faltantes(config):
    """Devuelve la lista de nombres de variables obligatorias que no llegaron configuradas.
    Lista vacía = todo lo necesario está presente. Separado de _validar_configuracion para que
    se pueda probar sin que el proceso termine con sys.exit."""
    requeridas = {
        'DATABASE_URL': config.get('database_url'),
        'RESPALDO_S3_BUCKET': config.get('bucket'),
        'RESPALDO_S3_ACCESS_KEY_ID': config.get('access_key'),
        'RESPALDO_S3_SECRET_ACCESS_KEY': config.get('secret_key'),
    }
    return [nombre for nombre, valor in requeridas.items() if not valor]


def nombre_archivo_respaldo(momento=None):
    """Nombre del archivo de respaldo para un momento dado (UTC). Función aparte para poder
    probar el formato sin depender de datetime.now() real."""
    momento = momento or datetime.now(timezone.utc)
    return f"arkiv_db_{momento.strftime('%Y-%m-%d_%H%M%S')}.dump"


def clave_remota(config, nombre_archivo):
    """Ruta completa (prefijo + nombre) que tendrá el objeto dentro del bucket."""
    return f"{config['prefijo']}/{nombre_archivo}"


def generar_dump(database_url, ruta_destino, runner=subprocess.run):
    """Corre pg_dump en formato 'custom' (-Fc) contra database_url, guardando el resultado en
    ruta_destino. --no-owner/--no-privileges: el dump queda restaurable en cualquier instancia
    de Postgres, sin pelearse con roles que no existan ahí (p. ej. restaurar el respaldo de Neon
    en una instancia local para probar). 'runner' es inyectable para las pruebas."""
    comando = [
        'pg_dump', database_url,
        '-Fc',
        '--no-owner',
        '--no-privileges',
        '-f', ruta_destino,
    ]
    resultado = runner(comando, capture_output=True, text=True)
    if resultado.returncode != 0:
        raise RuntimeError(f"pg_dump falló (código {resultado.returncode}): {resultado.stderr}")
    return ruta_destino


def cliente_s3(config):
    return boto3.client(
        's3',
        endpoint_url=config['endpoint_url'],
        aws_access_key_id=config['access_key'],
        aws_secret_access_key=config['secret_key'],
        region_name=config['region'],
    )


def subir_a_s3(s3, config, ruta_local, nombre_archivo):
    clave = clave_remota(config, nombre_archivo)
    s3.upload_file(ruta_local, config['bucket'], clave)
    return clave


def main():
    config = _configuracion_desde_entorno()
    faltantes = variables_faltantes(config)
    if faltantes:
        print(f"❌ Faltan variables de entorno: {', '.join(faltantes)}")
        sys.exit(1)

    nombre_archivo = nombre_archivo_respaldo()
    with tempfile.TemporaryDirectory() as tmp:
        ruta_local = os.path.join(tmp, nombre_archivo)
        try:
            generar_dump(config['database_url'], ruta_local)
        except Exception as e:
            print(f"❌ {e}")
            sys.exit(1)
        tamano = os.path.getsize(ruta_local)
        print(f"✅ pg_dump generado: {nombre_archivo} ({tamano:,} bytes)")

        try:
            s3 = cliente_s3(config)
            clave = subir_a_s3(s3, config, ruta_local, nombre_archivo)
        except Exception as e:
            print(f"❌ Error subiendo el respaldo al bucket: {e}")
            sys.exit(1)
        print(f"✅ Subido a s3://{config['bucket']}/{clave}")


if __name__ == '__main__':
    main()


# ───────────────────────────── CÓMO RESTAURAR ─────────────────────────────
# 1. Descargar el .dump del bucket (consola de AWS/Backblaze, o `aws s3 cp` / `b2 file download`).
# 2. Contra una base de datos Postgres VACÍA (nunca contra producción directamente — restaurar
#    primero en una instancia de prueba, ver el "simulacro de restauración" pendiente):
#      pg_restore --no-owner --no-privileges -d "<DATABASE_URL_DESTINO>" arkiv_db_XXXX.dump
# 3. Verificar que la app arranca y los datos se ven correctos antes de considerar el simulacro
#    exitoso.
