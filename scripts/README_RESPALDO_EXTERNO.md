# Respaldo externo de Arkiv (base de datos + Cloudinary)

Qué es esto: una copia de seguridad de la base de datos (Neon) y de todos los archivos subidos
a Arkiv (Cloudinary), guardada en un bucket S3-compatible totalmente aparte — independiente de
Render, Neon y Cloudinary a la vez. Corre sola, en GitHub Actions, sin tocar la app en
producción. Ver `.github/workflows/respaldo-externo.yml` para el detalle técnico.

Esta guía es para quien tenga acceso al repositorio de GitHub y a la cuenta de almacenamiento
(Tomás, o quien administre esas cuentas) — Claude no puede crear la cuenta ni cargar los
secrets por ustedes, porque eso implica credenciales/pagos que solo el dueño de la cuenta debe
manejar.

## 1. Elegir dónde va el bucket

Recomendado: **Backblaze B2** — más barato para este volumen (primeros 10 GB gratis, luego
~$6/TB/mes), y habla el mismo protocolo S3 que usan los scripts (no hay que cambiar código). Si
ya tienen o prefieren usar **AWS S3**, funciona exactamente igual, solo cambia qué secrets se
llenan (ver abajo).

### Opción A: Backblaze B2
1. Crear cuenta en https://www.backblaze.com/sign-up/cloud-storage (el nivel gratis de 10 GB no
   pide tarjeta).
2. Crear un bucket **privado** (no público) — por ejemplo `arkiv-respaldos`.
3. Ir a "App Keys" → "Add a New Application Key", restringida a ese bucket, con permiso de
   lectura y escritura.
4. Anotar: `keyID` (→ `RESPALDO_S3_ACCESS_KEY_ID`), `applicationKey` (→
   `RESPALDO_S3_SECRET_ACCESS_KEY`), y el endpoint S3 que Backblaze muestra en los detalles del
   bucket (algo como `https://s3.us-west-004.backblazeb2.com` → `RESPALDO_S3_ENDPOINT_URL`).

### Opción B: AWS S3
1. Crear un bucket privado en S3 (bloqueando todo acceso público).
2. Crear un usuario de IAM con una política que solo permita `s3:PutObject`, `s3:GetObject` y
   `s3:ListBucket` sobre ESE bucket (no permisos de administrador).
3. Generar sus Access Key / Secret Key.
4. `RESPALDO_S3_ENDPOINT_URL` se deja VACÍO (no se configura ese secret) — boto3 ya sabe hablar
   con S3 directamente. `RESPALDO_S3_REGION` = la región del bucket (ej. `us-east-1`).

## 2. Configurar el ciclo de vida (retención) del bucket

Para que los respaldos viejos se borren solos en vez de acumularse para siempre: en el panel del
bucket (Backblaze: "Lifecycle Settings"; AWS S3: "Management → Lifecycle rules"), agregar una
regla que expire/borre objetos después de, por ejemplo, 90 días. Así el propio proveedor de
almacenamiento se encarga del borrado — los scripts nunca borran nada por su cuenta.

## 3. Agregar los secrets en GitHub

En el repositorio → **Settings → Secrets and variables → Actions → New repository secret**,
agregar uno por uno (los nombres deben ser EXACTOS):

| Secret | Valor |
|---|---|
| `DATABASE_URL` | La misma cadena de conexión de Postgres que ya usa Render (Neon) |
| `RESPALDO_S3_BUCKET` | El nombre del bucket creado arriba |
| `RESPALDO_S3_ACCESS_KEY_ID` | La access key del paso 1 |
| `RESPALDO_S3_SECRET_ACCESS_KEY` | La secret key del paso 1 |
| `RESPALDO_S3_ENDPOINT_URL` | Solo si usan Backblaze B2 (dejar sin crear este secret si es AWS S3) |
| `RESPALDO_S3_REGION` | Opcional; si no se configura, se usa `us-east-1` |
| `CLOUDINARY_CLOUD_NAME` | El mismo que ya está configurado en Render |
| `CLOUDINARY_API_KEY` | El mismo que ya está configurado en Render |
| `CLOUDINARY_API_SECRET` | El mismo que ya está configurado en Render |

Los valores de `CLOUDINARY_*` y `DATABASE_URL` ya existen como variables de entorno en Render
(Dashboard del servicio → Environment) — es cuestión de copiarlos de ahí a GitHub, no hace falta
generar nada nuevo para esos tres.

## 4. Probar que funciona

Una vez agregados los secrets: en GitHub → pestaña **Actions** → "Respaldo externo (DB +
Cloudinary)" → **Run workflow** (botón a la derecha) para dispararlo manualmente sin esperar al
horario programado. Revisar que ambos jobs (`respaldo-base-de-datos` y `respaldo-cloudinary`)
terminen en verde, y confirmar en el panel de Backblaze/AWS que aparecieron los archivos nuevos
dentro del bucket (carpetas `arkiv/db/` y `arkiv/cloudinary/`).

## 5. Horario ya configurado

- Base de datos: todos los días a la 1:00 a.m. hora Colombia (bajo tráfico, respaldo rápido).
- Cloudinary: una vez por semana, domingos a la 1:30 a.m. hora Colombia (puede tardar más si hay
  muchos archivos — no tiene sentido correrlo a diario, y el manifiesto interno hace que cada
  corrida solo transfiera lo nuevo o lo que cambió desde la última vez).

Ambos también se pueden disparar manualmente cuando se quiera (botón "Run workflow"), por
ejemplo antes de hacer el simulacro de restauración pendiente.

## 6. Cómo restaurar en un simulacro (o en una emergencia real)

Ver el bloque "CÓMO RESTAURAR" al final de `scripts/respaldo_db_externo.py` — en resumen:
descargar el `.dump` más reciente del bucket y correr `pg_restore` contra una base de datos de
prueba (NUNCA directo contra producción) para confirmar que el respaldo sirve de verdad. Los
archivos de Cloudinary respaldados quedan simplemente como objetos normales dentro del bucket,
organizados por tipo (`image/`, `video/`, `raw/`) y `public_id` — se pueden descargar y volver a
subir a Cloudinary con la Admin API si hiciera falta reconstruir la cuenta desde cero.
