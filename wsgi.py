# 🩹 Este archivo existe SOLO para parchear gevent (monkey.patch_all()) ANTES de que se
# importe cualquier otra cosa. Gunicorn (ver Procfile) ahora apunta a "wsgi:app" en vez de
# "app:app" para que este parcheo temprano ocurra primero, y no después.
#
# 🐛 Bug real que esto corrige (encontrado el 05/09/2026 revisando los Logs de Render tras
# activar line-buffering): con "gunicorn app:app --worker-class geventwebsocket...", Gunicorn
# importaba primero el módulo "app" — y con él, sqlite3/urllib3/ssl/cloudinary, etc. — y RECIÉN
# DESPUÉS el worker de gevent llamaba a monkey.patch_all() (esto es justo lo que avisa
# "MonkeyPatchWarning: Monkey-patching ssl after ssl has already been imported" en los logs de
# arranque). Como urllib3 ya había guardado una referencia a la clase ssl.SSLContext ORIGINAL
# (sin parchear) antes de que gevent la reemplazara, cualquier conexión HTTPS nueva que usara
# urllib3 (como el propio SDK de Cloudinary) terminaba en un RecursionError infinito al fijar
# context.minimum_version dentro de create_urllib3_context(). Ese RecursionError — no un
# problema de Cloudinary en sí, ni del tamaño/formato de la imagen — era el error real detrás
# de "No se pudo subir el archivo. Intenta de nuevo." al adjuntar algo en el chat (y podía
# afectar, en teoría, cualquier otra subida a Cloudinary hecha con una conexión nueva).
#
# Parcheando aquí, en la primera línea de lo primero que Gunicorn importa, se evita esa mezcla:
# para cuando "from app import app" se ejecuta (la línea de abajo), ssl/socket ya están
# parcheados, así que todo lo que "app.py" importe después (cloudinary, urllib3, etc.) ve
# desde el principio la versión ya parcheada.
from gevent import monkey
monkey.patch_all()

from app import app  # noqa: E402,F401 (import intencionalmente después del monkey-patch)
