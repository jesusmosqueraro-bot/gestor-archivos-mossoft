import os
import uuid
import random
import sqlite3
import urllib.request
import urllib.parse
import json
import unicodedata
import re
import io
import csv
import threading
import base64
import hashlib
import hmac
import traceback
import time
import decimal
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify, stream_with_context, send_file
from werkzeug.security import generate_password_hash, check_password_hash

# flask_wtf seguro (protección CSRF real)
try:
    from flask_wtf import CSRFProtect
    from flask_wtf.csrf import CSRFError
except Exception:
    CSRFProtect = None
    CSRFError = Exception

# psycopg2 seguro para Render
try:
    import psycopg2
except Exception:
    psycopg2 = None

# cryptography para cifrado real de la bóveda de credenciales
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

import cloudinary
import cloudinary.uploader

# requests seguro
try:
    import requests
except Exception:
    requests = None

# bleach: limpia el HTML que produce el editor de texto enriquecido (Quill) antes de
# guardarlo, para que nadie pueda inyectar <script>, atributos onerror/onclick, etc. en la
# descripción de un ticket, un comentario o un comunicado. Si por algo no está instalado, se
# cae a texto plano (nunca se guarda HTML sin filtrar).
try:
    import bleach
    from bleach.css_sanitizer import CSSSanitizer
except Exception:
    bleach = None
    CSSSanitizer = None

app = Flask(__name__)
# 🔐 SECRET_KEY: nunca debe tener un valor real escrito en el código (quedaría expuesto en GitHub).
# Si no está seteada en las variables de entorno de Render, se genera una aleatoria en cada arranque.
# Esto no causa fricción extra: las sesiones ya se invalidan en cada reinicio por SERVER_INSTANCE_ID (ver abajo).
_SECRET_KEY_ENV = os.environ.get('SECRET_KEY')
if not _SECRET_KEY_ENV:
    print("⚠️ SECRET_KEY no configurada en variables de entorno de Render: se generó una aleatoria solo para esta instancia. Agrega SECRET_KEY en Render para persistirla.")
app.secret_key = _SECRET_KEY_ENV or base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8')

SERVER_INSTANCE_ID = str(uuid.uuid4())
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

# 🍪 Banderas explícitas de la cookie de sesión (antes quedaban en los valores por
# defecto de Flask). SECURE: el navegador nunca la envía por HTTP sin cifrar (Render
# solo sirve por HTTPS, así que no afecta nada). HTTPONLY: JavaScript en el navegador
# no puede leerla, ni siquiera vía un XSS. SAMESITE=Lax: no se envía en peticiones
# disparadas desde otros sitios, lo que además mitiga CSRF de rebote.
app.config['SESSION_COOKIE_SECURE'] = True
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'


@app.after_request
def _agregar_cabeceras_seguridad(response):
    # 🛡️ Cabeceras HTTP de seguridad estándar, ausentes hasta ahora. No cambian
    # el comportamiento visible de la app; reducen la superficie de ataque del
    # navegador (clickjacking, MIME-sniffing, fuga de referrer, etc.).
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Strict-Transport-Security'] = 'max-age=63072000; includeSubDomains'
    # CSP armada específicamente con los orígenes externos que la app realmente usa
    # hoy (Tailwind CDN, Font Awesome/cdnjs, Google Fonts, Cloudinary, reCAPTCHA).
    # 'unsafe-inline' se mantiene porque las plantillas usan scripts/estilos en línea
    # (onclick=, <script> por página); quitarlo requeriría reescribir todas las
    # plantillas a un esquema de nonces, algo que no se hizo en este cambio para no
    # arriesgar romper funcionalidad fuera de esta ronda de correcciones.
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://cdnjs.cloudflare.com "
        "https://www.google.com https://www.gstatic.com; "
        "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://fonts.googleapis.com; "
        "font-src 'self' data: https://fonts.gstatic.com https://cdnjs.cloudflare.com; "
        "img-src 'self' data: https://res.cloudinary.com; "
        "media-src 'self' https://res.cloudinary.com; "
        "connect-src 'self' https://www.google.com; "
        "frame-src https://www.google.com; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'self';"
    )
    return response

# 🛡️ Protección CSRF real vía Flask-WTF. Todas las plantillas con formularios POST ya
# incluyen (o se les agregó) el campo oculto csrf_token(); CSRFProtect valida ese token en
# cada POST/PUT/PATCH/DELETE y registra csrf_token() como global de Jinja automáticamente.
# Las dos únicas llamadas fetch() que no envían el token (incrementar_vista/descarga, meros
# contadores de vistas/descargas sin impacto sensible) quedan exentas explícitamente donde
# están definidas más abajo.
if CSRFProtect:
    csrf = CSRFProtect(app)

    @app.errorhandler(CSRFError)
    def _manejar_csrf_invalido(e):
        print(f"⚠️ CSRF inválido/expirado: {getattr(e, 'description', e)}")
        return redirect(request.referrer or url_for('index'))
else:
    # Si por alguna razón flask_wtf no está instalado, no tumbamos la app: se cae de vuelta
    # al placeholder inofensivo (sin protección CSRF real) en lugar de un 500 en cada página.
    print("⚠️ flask_wtf no está instalado: la protección CSRF real está desactivada. Agrega Flask-WTF a requirements.txt.")
    class _CsrfExemptDummy:
        def exempt(self, f):
            return f
    csrf = _CsrfExemptDummy()

    @app.context_processor
    def _inyectar_csrf_token_placeholder():
        return dict(csrf_token=lambda: '')

# 🇨🇴 ZONA HORARIA COLOMBIA CON FALLBACK SEGURO
try:
    ZONA_HORARIA_COLOMBIA = ZoneInfo("America/Bogota")
except Exception:
    ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

def obtener_fecha_actual():
    # ⚠️ Formato ISO 8601 (AAAA-MM-DD HH:MM:SS): Postgres lo interpreta correctamente
    # sin importar su configuración de DateStyle. El formato anterior "DD/MM/AAAA hh:mm AM/PM"
    # (ej: "21/08/2026 05:51 PM") fallaba con "date/time field value out of range" en Neon
    # cada vez que el día del mes era mayor a 12, porque Postgres lo interpretaba como MM/DD/AAAA.
    try:
        return datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def normalizar(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower().strip()

def _usuario_desde_nombre(texto):
    """Deja un nombre/apellido apto para nombre de usuario: sin tildes, minúsculas, solo
    letras y números (usa el mismo criterio de `normalizar` y además quita espacios/guiones,
    para apellidos compuestos como 'De la Cruz')."""
    return re.sub(r'[^a-z0-9]', '', normalizar(texto))

def _generar_username_unico(primer_nombre, primer_apellido, segundo_nombre='', segundo_apellido=''):
    """Genera un nombre de usuario a partir del nombre real de la persona, con la estructura
    pedida: primer nombre + primer apellido. Si ya existe, prueba estructuras alternativas
    (agregando la inicial del segundo apellido, la inicial del segundo nombre, o solo la
    inicial del primer nombre) y, como último recurso, agrega un número — hasta encontrar
    una que esté libre."""
    pn = _usuario_desde_nombre(primer_nombre)
    sn = _usuario_desde_nombre(segundo_nombre)
    pa = _usuario_desde_nombre(primer_apellido)
    sa = _usuario_desde_nombre(segundo_apellido)

    candidatos = []
    if pn and pa:
        candidatos.append(pn + pa)
        if sa:
            candidatos.append(pn + pa + sa[0])
        if sn:
            candidatos.append(pn + sn[0] + pa)
        candidatos.append(pn[0] + pa)

    vistos = set()
    candidatos_unicos = []
    for c in candidatos:
        if c and c not in vistos:
            vistos.add(c)
            candidatos_unicos.append(c)
    if not candidatos_unicos:
        candidatos_unicos = ['usuario']

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(%s)" if db_type == 'postgres' else "SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(?)"
        for candidato in candidatos_unicos:
            cursor.execute(q, (candidato,))
            if not cursor.fetchone():
                return candidato
        # Todas las estructuras anteriores ya existen: se agrega un número incremental a la
        # primera opción hasta encontrar una libre.
        base = candidatos_unicos[0]
        for n in range(2, 1000):
            candidato = f"{base}{n}"
            cursor.execute(q, (candidato,))
            if not cursor.fetchone():
                return candidato
    finally:
        conn.close()
    # Fallback extremo (no debería alcanzarse en la práctica).
    return f"{candidatos_unicos[0]}{int(datetime.now(ZONA_HORARIA_COLOMBIA).timestamp())}"

# 🔐 CIFRADO REAL DE LA BÓVEDA (Fernet / AES-128-CBC + HMAC)
# La clave SOLO debe vivir en la variable de entorno ENCRYPTION_KEY de Render.
# Genera una con: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
_ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY')
_fernet = None
if Fernet and _ENCRYPTION_KEY:
    try:
        _fernet = Fernet(_ENCRYPTION_KEY.encode('utf-8'))
    except Exception as _e:
        print(f"⚠️ ENCRYPTION_KEY inválida, revisa la variable de entorno: {_e}")
        _fernet = None

def _encriptar_xor_legacy(texto, clave):
    """Compatibilidad de solo-lectura con el cifrado XOR viejo, para poder migrar datos existentes."""
    bytes_texto = texto.encode('utf-8')
    return bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_texto)])

def desencriptar_texto_legacy_xor(texto_cifrado):
    """Descifra valores guardados con el XOR viejo (antes de Fernet). Solo para migración."""
    if not texto_cifrado:
        return ""
    try:
        clave = app.secret_key.encode('utf-8')
        bytes_cifrados = base64.b64decode(texto_cifrado.encode('utf-8'))
        descifrado = bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_cifrados)])
        return descifrado.decode('utf-8')
    except Exception:
        return ""

def encriptar_texto(texto):
    if not texto:
        return ""
    if not _fernet:
        # Sin ENCRYPTION_KEY configurada no ciframos en claro por error: mejor fallar visible.
        raise RuntimeError("ENCRYPTION_KEY no configurada en las variables de entorno de Render.")
    return _fernet.encrypt(texto.encode('utf-8')).decode('utf-8')

def _migrar_credencial_a_fernet(credencial_id, password_plano):
    """Re-guarda con Fernet (AES real) una credencial de la bóveda que todavía
    estaba cifrada con el XOR viejo. Migra de forma transparente, un registro
    a la vez, cada vez que alguien la lee — igual que ya se hace con los
    passwords de usuarios en texto plano."""
    if not _fernet or credencial_id is None:
        return
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        nueva_cifrada = encriptar_texto(password_plano)
        query = "UPDATE credenciales SET password_cifrada = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET password_cifrada = ? WHERE id = ?"
        cursor.execute(query, (nueva_cifrada, credencial_id))
        conn.commit()
        conn.close()
        print(f"🔐 Credencial ID {credencial_id} migrada de cifrado XOR (débil) a Fernet/AES.")
    except Exception as e:
        print(f"Error migrando credencial {credencial_id} a Fernet: {e}")

def desencriptar_texto(texto_cifrado, credencial_id=None):
    """Descifra un valor de la bóveda. Si se pasa credencial_id y el valor
    resulta estar todavía en el XOR viejo (no es un token Fernet válido),
    se re-cifra con Fernet y se re-guarda de una vez en la base de datos."""
    if not texto_cifrado:
        return ""
    if _fernet:
        try:
            return _fernet.decrypt(texto_cifrado.encode('utf-8')).decode('utf-8')
        except (InvalidToken, Exception):
            pass  # No es un token Fernet válido: puede ser un valor viejo cifrado con XOR. Seguimos abajo.
    # Sin ENCRYPTION_KEY configurada (o el valor no era un token Fernet válido): intentamos
    # el XOR viejo de todas formas, ya que ese cifrado no depende de _fernet en absoluto.
    # Antes esta rama solo se intentaba cuando _fernet SÍ existía, dejando sin poder leerse
    # cualquier valor viejo si ENCRYPTION_KEY no estaba configurada.
    legacy = desencriptar_texto_legacy_xor(texto_cifrado)
    if legacy:
        if _fernet:
            _migrar_credencial_a_fernet(credencial_id, legacy)
        return legacy
    return "⚠️ No se pudo descifrar (revisa ENCRYPTION_KEY)"


def _parsear_dias_rotacion(valor):
    """Convierte el campo de formulario 'rotacion_dias' (texto, puede venir vacío) a un entero
    positivo o None (sin política de rotación para esa credencial)."""
    try:
        dias = int(str(valor).strip())
        return dias if dias > 0 else None
    except (TypeError, ValueError):
        return None

# ☁️ CLOUDINARY
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

# 📦 EXTENSIONES PERMITIDAS (INCLUYE COMPRIMIDOS Y DOCUMENTOS DE OFFICE)
ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp',
    'pdf', 'txt', 'docx', 'xlsx', 'pptx',
    'mp4', 'mov', 'webm', 'avi',
    'zip', 'rar', '7z', 'tar', 'gz'
}
# 📦 LÍMITE DE TAMAÑO DE SUBIDA: 500 MB, con margen para videos de 4-10 minutos en buena
# calidad (un video de 4 min en 1080p suele pesar 100-300 MB según la compresión). Esto es
# el tope del lado de Flask/Render; el otro tope posible es el plan de Cloudinary (ver abajo).
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

# 📧 URL DE TU GOOGLE APPS SCRIPT OFICIAL (PUERTO 443 HTTPS - SIN BLOQUEOS DE RENDER)
GMAIL_SCRIPT_URL = os.environ.get('GMAIL_SCRIPT_URL', "https://script.google.com/macros/s/AKfycbwSBbdv-2xl5ND3LjXbDZaXBpzD-mQNNLlFn2H0ih8T7RZouOhF6uEZlxHONsJHxxjq/exec")

# 🔑 CLAVE SECRETA DE RECAPTCHA V2
# Nunca debe tener un valor real escrito en el código. Debe venir SIEMPRE de la variable
# de entorno RECAPTCHA_SECRET_KEY en Render (usa el valor que ya tenías funcionando).
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', '')
if not RECAPTCHA_SECRET_KEY:
    print("⚠️ RECAPTCHA_SECRET_KEY no configurada en variables de entorno de Render: el login fallará hasta que la agregues.")

DATABASE_URL = os.environ.get('DATABASE_URL')

@app.before_request
def validar_instancia_y_sesion():
    session.permanent = True
    if session.get('logged_in'):
        if session.get('instance_id') != SERVER_INSTANCE_ID:
            session.clear()
            return redirect(url_for('login', expirado='1'))

def get_db():
    if DATABASE_URL and psycopg2:
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(url)
        return conn, 'postgres'
    else:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        DB_NAME = os.path.join(BASE_DIR, "gestor.db")
        conn = sqlite3.connect(DB_NAME)
        return conn, 'sqlite'

def init_db():
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        if db_type == 'postgres':
            cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id SERIAL PRIMARY KEY, usuario VARCHAR(100) UNIQUE NOT NULL, password_hash VARCHAR(255) NOT NULL, correo VARCHAR(200) NOT NULL, rol VARCHAR(50) NOT NULL DEFAULT 'estandar', estado VARCHAR(20) NOT NULL DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id VARCHAR(50) PRIMARY KEY, titulo VARCHAR(200) NOT NULL, descripcion TEXT, fecha_subida VARCHAR(100), categoria VARCHAR(100) DEFAULT 'General', area VARCHAR(100) DEFAULT 'General', tipo VARCHAR(100) DEFAULT 'Instructivo', tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, estado VARCHAR(50) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id SERIAL PRIMARY KEY, galeria_id VARCHAR(50) REFERENCES galerias(id) ON DELETE CASCADE, filename TEXT, url_archivo TEXT NOT NULL DEFAULT '', nombre_original VARCHAR(255) NOT NULL DEFAULT '', estado VARCHAR(50) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY, usuario VARCHAR(100) NOT NULL, accion VARCHAR(100) NOT NULL, detalles TEXT, fecha VARCHAR(100) NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id SERIAL PRIMARY KEY, titulo VARCHAR(150) NOT NULL, url_acceso TEXT, usuario_acceso VARCHAR(150) NOT NULL, password_cifrada TEXT NOT NULL, area VARCHAR(100) DEFAULT 'General', notas TEXT, fecha_creacion VARCHAR(100) NOT NULL, estado VARCHAR(50) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id SERIAL PRIMARY KEY, titulo VARCHAR(200) NOT NULL, contenido TEXT NOT NULL, nivel VARCHAR(50) DEFAULT 'info', fijado INTEGER DEFAULT 0, imagen_url TEXT DEFAULT '', estado VARCHAR(50) DEFAULT 'activo', fecha VARCHAR(100) NOT NULL, autor VARCHAR(100) NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets (
                id SERIAL PRIMARY KEY, titulo VARCHAR(200) NOT NULL, descripcion TEXT NOT NULL, tipo VARCHAR(20) DEFAULT 'Incidente', categoria VARCHAR(50) DEFAULT 'Otro', prioridad VARCHAR(20) DEFAULT 'Media', estado VARCHAR(20) DEFAULT 'Abierto', creado_por VARCHAR(100) NOT NULL, asignado_a VARCHAR(100), fecha_creacion VARCHAR(100) NOT NULL, fecha_actualizacion VARCHAR(100) NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets_comentarios (
                id SERIAL PRIMARY KEY, ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE, autor VARCHAR(100) NOT NULL, mensaje TEXT NOT NULL, tipo VARCHAR(20) DEFAULT 'comentario', fecha VARCHAR(100) NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets_adjuntos (
                id SERIAL PRIMARY KEY, ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE, comentario_id INTEGER REFERENCES tickets_comentarios(id) ON DELETE CASCADE, url TEXT NOT NULL, nombre_original VARCHAR(255) NOT NULL, subido_por VARCHAR(100) NOT NULL, fecha VARCHAR(100) NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS conocimiento_articulos (
                id SERIAL PRIMARY KEY, titulo VARCHAR(200) NOT NULL, descripcion TEXT, url_documento TEXT NOT NULL, nombre_archivo VARCHAR(255) NOT NULL, vistas INTEGER DEFAULT 0, creado_por VARCHAR(100) NOT NULL, fecha_creacion VARCHAR(100) NOT NULL, estado VARCHAR(20) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS ticket_configuraciones (
                id SERIAL PRIMARY KEY, tipo VARCHAR(20) NOT NULL, nombre VARCHAR(150) NOT NULL, estado VARCHAR(20) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS activos_inventario (
                id SERIAL PRIMARY KEY, nombre VARCHAR(200) NOT NULL, tipo_activo VARCHAR(100) DEFAULT 'Otro', marca VARCHAR(100), modelo VARCHAR(100), numero_serie VARCHAR(150), estado VARCHAR(30) DEFAULT 'Disponible', asignado_a VARCHAR(100), sede VARCHAR(100), observaciones TEXT, fecha_creacion VARCHAR(100) NOT NULL, creado_por VARCHAR(100) NOT NULL, eliminado INTEGER DEFAULT 0
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS inventario_adjuntos (
                id SERIAL PRIMARY KEY, activo_id INTEGER REFERENCES activos_inventario(id) ON DELETE CASCADE, url TEXT NOT NULL, nombre_original VARCHAR(255) NOT NULL, subido_por VARCHAR(100) NOT NULL, fecha VARCHAR(100) NOT NULL
            )''')
            # 👁️ Registro de qué usuario ya leyó cada comunicado (se marca al ver el muro de
            # comunicados o el comunicado fijado en la bienvenida) — para saber quién falta.
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados_leidos (
                id SERIAL PRIMARY KEY, comunicado_id INTEGER REFERENCES comunicados(id) ON DELETE CASCADE, usuario VARCHAR(100) NOT NULL, fecha VARCHAR(100) NOT NULL, UNIQUE(comunicado_id, usuario)
            )''')
            # 🔔 Notificaciones internas (campanita): se generan en los mismos puntos donde ya
            # sale un correo (ticket creado, comentado, cambio de estado).
            cursor.execute('''CREATE TABLE IF NOT EXISTS notificaciones (
                id SERIAL PRIMARY KEY, usuario VARCHAR(100) NOT NULL, tipo VARCHAR(50) DEFAULT 'ticket', mensaje TEXT NOT NULL, url TEXT DEFAULT '', leida INTEGER DEFAULT 0, fecha VARCHAR(100) NOT NULL
            )''')
            # 🆔 Catálogo de aplicativos/herramientas para los que se crean credenciales a los
            # colaboradores (KUBAPP, SAMI, Moodle, Wolkvox, Correo, Solvyx...). Administrable:
            # el equipo de soporte puede agregar o desactivar aplicativos sin tocar código.
            cursor.execute('''CREATE TABLE IF NOT EXISTS aplicativos_catalogo (
                id SERIAL PRIMARY KEY, nombre VARCHAR(150) NOT NULL, estado VARCHAR(20) DEFAULT 'activo'
            )''')
            # 🪪 Altas y bajas de credenciales de colaboradores: un registro por cada aplicativo
            # que se le habilita a una persona (no por colaborador), para poder deshabilitar el
            # acceso a un aplicativo puntual sin afectar los demás que tenga esa misma persona.
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales_colaboradores (
                id SERIAL PRIMARY KEY, colaborador VARCHAR(200) NOT NULL, aplicativo VARCHAR(150) NOT NULL, password_cifrada TEXT NOT NULL, fecha_creacion VARCHAR(100), fecha_solicitud VARCHAR(100), analista_gestiona VARCHAR(150), solicitado_por VARCHAR(150), capacitado_por VARCHAR(150), medio_envio VARCHAR(30), estado VARCHAR(20) DEFAULT 'activo', fecha_deshabilitacion VARCHAR(100), deshabilitado_por VARCHAR(150), fecha_registro VARCHAR(100) NOT NULL, registrado_por VARCHAR(150) NOT NULL
            )''')
            conn.commit()

            for col_query in [
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS categoria VARCHAR(100) DEFAULT 'General';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tipo VARCHAR(100) DEFAULT 'Instructivo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS vistas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS descargas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS area VARCHAR(100) DEFAULT 'General';",
                # 👁️ Visibilidad del instructivo: 'todos' (lo ve cualquier usuario logueado) o
                # 'admin' (solo lo ven las cuentas Admin/Agente). Por defecto 'todos', para no
                # ocultar de golpe instructivos que ya existían antes de esta función.
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS visibilidad VARCHAR(20) DEFAULT 'todos';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS url_archivo TEXT DEFAULT '';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS nombre_original VARCHAR(255) DEFAULT '';",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                # 🔐 Auditoría de accesos: en qué credencial quedó registrada cada consulta/copia
                # de clave (ver _revelar_credencial); NULL para el resto de acciones del log.
                "ALTER TABLE logs ADD COLUMN IF NOT EXISTS credencial_id INTEGER;",
                # 🔁 Política de rotación de contraseñas (opcional, por credencial): cada cuántos
                # días se debería cambiar, cuándo se rotó por última vez, y cuándo se avisó (una
                # sola vez por ciclo) que ya toca — ver _revisar_recordatorios_rotacion().
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS rotacion_dias INTEGER;",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS fecha_ultima_rotacion VARCHAR(100);",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS rotacion_recordatorio_fecha VARCHAR(100);",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado VARCHAR(20) DEFAULT 'activo';",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS nombre VARCHAR(200);",
                # 📞 Teléfono de contacto del usuario: opcional, se usa para prellenar el número
                # de contacto al crear un ticket y para que soporte tenga cómo ubicarlo.
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS telefono VARCHAR(50);",
                # 🎨 Preferencia de tema (claro/oscuro) de cada usuario: se guarda en su cuenta
                # (no solo en el navegador) para que lo siga a donde inicie sesión.
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS tema VARCHAR(20) DEFAULT 'oscuro';",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS tipo VARCHAR(20) DEFAULT 'Incidente';",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_respuesta_limite VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_resolucion_limite VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_respuesta_cumplida VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_resolucion_cumplida VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_modificaciones INTEGER DEFAULT 0;",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS calificacion INTEGER;",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS calificacion_fecha VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS area VARCHAR(100);",
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sede VARCHAR(100);",
                # 📞 Número de contacto para ESTE ticket en particular: puede ser distinto al
                # teléfono registrado en el perfil del usuario (p. ej. reporta desde la
                # extensión de otra persona). Se prellena con el del perfil pero es editable.
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS telefono_contacto VARCHAR(50);",
                # 🔔 Último nivel de alerta de SLA ya avisado para este ticket ('proximo_a_vencer'
                # o 'vencido') — evita reenviar el mismo aviso en cada visita a la lista de
                # tickets; se limpia cuando se extiende el SLA para que pueda volver a avisar.
                "ALTER TABLE tickets ADD COLUMN IF NOT EXISTS sla_alerta_nivel VARCHAR(20);",
                # 📢 Fecha en que se envió (una sola vez) el recordatorio automático de lectura
                # pendiente de este comunicado — ver _revisar_recordatorios_lectura(). NULL
                # mientras no se haya enviado ninguno (automático o manual) todavía.
                "ALTER TABLE comunicados ADD COLUMN IF NOT EXISTS recordatorio_enviado_fecha VARCHAR(100);",
                # 📍 Dirección física y usuario responsable de cada Sede (solo aplican cuando
                # tipo = 'sede'; para 'area'/'categoria' quedan en NULL sin usarse).
                "ALTER TABLE ticket_configuraciones ADD COLUMN IF NOT EXISTS direccion TEXT;",
                "ALTER TABLE ticket_configuraciones ADD COLUMN IF NOT EXISTS responsable VARCHAR(100);"
            ]:
                try:
                    cursor.execute(col_query)
                    conn.commit()
                except Exception:
                    conn.rollback()

        else:
            cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, correo TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'estandar', estado TEXT NOT NULL DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id TEXT PRIMARY KEY, titulo TEXT NOT NULL, descripcion TEXT, fecha_subida TEXT, categoria TEXT DEFAULT 'General', area TEXT DEFAULT 'General', tipo TEXT DEFAULT 'Instructivo', tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, galeria_id TEXT, filename TEXT, url_archivo TEXT NOT NULL DEFAULT '', nombre_original TEXT NOT NULL DEFAULT '', estado TEXT DEFAULT 'activo', FOREIGN KEY(galeria_id) REFERENCES galerias(id) ON DELETE CASCADE
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, accion TEXT NOT NULL, detalles TEXT, fecha TEXT NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, url_acceso TEXT, usuario_acceso TEXT NOT NULL, password_cifrada TEXT NOT NULL, area TEXT DEFAULT 'General', notas TEXT, fecha_creacion VARCHAR(100) NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, contenido TEXT NOT NULL, nivel TEXT DEFAULT 'info', fijado INTEGER DEFAULT 0, imagen_url TEXT DEFAULT '', estado TEXT DEFAULT 'activo', fecha TEXT NOT NULL, autor TEXT NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descripcion TEXT NOT NULL, tipo TEXT DEFAULT 'Incidente', categoria TEXT DEFAULT 'Otro', prioridad TEXT DEFAULT 'Media', estado TEXT DEFAULT 'Abierto', creado_por TEXT NOT NULL, asignado_a TEXT, fecha_creacion TEXT NOT NULL, fecha_actualizacion TEXT NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets_comentarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, autor TEXT NOT NULL, mensaje TEXT NOT NULL, tipo TEXT DEFAULT 'comentario', fecha TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS tickets_adjuntos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, comentario_id INTEGER, url TEXT NOT NULL, nombre_original TEXT NOT NULL, subido_por TEXT NOT NULL, fecha TEXT NOT NULL, FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE, FOREIGN KEY(comentario_id) REFERENCES tickets_comentarios(id) ON DELETE CASCADE
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS conocimiento_articulos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, descripcion TEXT, url_documento TEXT NOT NULL, nombre_archivo TEXT NOT NULL, vistas INTEGER DEFAULT 0, creado_por TEXT NOT NULL, fecha_creacion TEXT NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS ticket_configuraciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, tipo TEXT NOT NULL, nombre TEXT NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS activos_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, tipo_activo TEXT DEFAULT 'Otro', marca TEXT, modelo TEXT, numero_serie TEXT, estado TEXT DEFAULT 'Disponible', asignado_a TEXT, sede TEXT, observaciones TEXT, fecha_creacion TEXT NOT NULL, creado_por TEXT NOT NULL, eliminado INTEGER DEFAULT 0
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS inventario_adjuntos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, activo_id INTEGER, url TEXT NOT NULL, nombre_original TEXT NOT NULL, subido_por TEXT NOT NULL, fecha TEXT NOT NULL, FOREIGN KEY(activo_id) REFERENCES activos_inventario(id) ON DELETE CASCADE
            )''')
            # 👁️ Registro de qué usuario ya leyó cada comunicado (se marca al ver el muro de
            # comunicados o el comunicado fijado en la bienvenida) — para saber quién falta.
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados_leidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, comunicado_id INTEGER NOT NULL, usuario TEXT NOT NULL, fecha TEXT NOT NULL, FOREIGN KEY(comunicado_id) REFERENCES comunicados(id) ON DELETE CASCADE, UNIQUE(comunicado_id, usuario)
            )''')
            # 🔔 Notificaciones internas (campanita): se generan en los mismos puntos donde ya
            # sale un correo (ticket creado, comentado, cambio de estado).
            cursor.execute('''CREATE TABLE IF NOT EXISTS notificaciones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, tipo TEXT DEFAULT 'ticket', mensaje TEXT NOT NULL, url TEXT DEFAULT '', leida INTEGER DEFAULT 0, fecha TEXT NOT NULL
            )''')
            # 🆔 Catálogo de aplicativos/herramientas para los que se crean credenciales a los
            # colaboradores (KUBAPP, SAMI, Moodle, Wolkvox, Correo, Solvyx...). Administrable:
            # el equipo de soporte puede agregar o desactivar aplicativos sin tocar código.
            cursor.execute('''CREATE TABLE IF NOT EXISTS aplicativos_catalogo (
                id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            # 🪪 Altas y bajas de credenciales de colaboradores: un registro por cada aplicativo
            # que se le habilita a una persona (no por colaborador), para poder deshabilitar el
            # acceso a un aplicativo puntual sin afectar los demás que tenga esa misma persona.
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales_colaboradores (
                id INTEGER PRIMARY KEY AUTOINCREMENT, colaborador TEXT NOT NULL, aplicativo TEXT NOT NULL, password_cifrada TEXT NOT NULL, fecha_creacion TEXT, fecha_solicitud TEXT, analista_gestiona TEXT, solicitado_por TEXT, capacitado_por TEXT, medio_envio TEXT, estado TEXT DEFAULT 'activo', fecha_deshabilitacion TEXT, deshabilitado_por TEXT, fecha_registro TEXT NOT NULL, registrado_por TEXT NOT NULL
            )''')

            for col_sql in ["categoria", "tipo", "tags", "vistas", "descargas", "estado"]:
                try:
                    cursor.execute(f"ALTER TABLE galerias ADD COLUMN {col_sql} TEXT DEFAULT 'activo';")
                    conn.commit()
                except Exception:
                    pass
            try:
                cursor.execute("ALTER TABLE archivos ADD COLUMN estado TEXT DEFAULT 'activo';")
                conn.commit()
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE credenciales ADD COLUMN estado TEXT DEFAULT 'activo';")
                conn.commit()
            except Exception:
                pass
            for col_credencial_sql in [
                "ALTER TABLE logs ADD COLUMN credencial_id INTEGER;",
                "ALTER TABLE credenciales ADD COLUMN rotacion_dias INTEGER;",
                "ALTER TABLE credenciales ADD COLUMN fecha_ultima_rotacion TEXT;",
                "ALTER TABLE credenciales ADD COLUMN rotacion_recordatorio_fecha TEXT;"
            ]:
                try:
                    cursor.execute(col_credencial_sql)
                    conn.commit()
                except Exception:
                    pass
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN estado TEXT DEFAULT 'activo';")
                conn.commit()
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN nombre TEXT;")
                conn.commit()
            except Exception:
                pass
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN telefono TEXT;")
                conn.commit()
            except Exception:
                pass
            try:
                # 🎨 Preferencia de tema (claro/oscuro) de cada usuario: se guarda en su cuenta
                # (no solo en el navegador) para que lo siga a donde inicie sesión.
                cursor.execute("ALTER TABLE usuarios ADD COLUMN tema TEXT DEFAULT 'oscuro';")
                conn.commit()
            except Exception:
                pass
            for col_ticket_sql in [
                "ALTER TABLE tickets ADD COLUMN tipo TEXT DEFAULT 'Incidente';",
                "ALTER TABLE tickets ADD COLUMN sla_respuesta_limite TEXT;",
                "ALTER TABLE tickets ADD COLUMN sla_resolucion_limite TEXT;",
                "ALTER TABLE tickets ADD COLUMN sla_respuesta_cumplida TEXT;",
                "ALTER TABLE tickets ADD COLUMN sla_resolucion_cumplida TEXT;",
                "ALTER TABLE tickets ADD COLUMN sla_modificaciones INTEGER DEFAULT 0;",
                "ALTER TABLE tickets ADD COLUMN calificacion INTEGER;",
                "ALTER TABLE tickets ADD COLUMN calificacion_fecha TEXT;",
                "ALTER TABLE tickets ADD COLUMN area TEXT;",
                "ALTER TABLE tickets ADD COLUMN sede TEXT;",
                "ALTER TABLE tickets ADD COLUMN telefono_contacto TEXT;",
                "ALTER TABLE tickets ADD COLUMN sla_alerta_nivel TEXT;"
            ]:
                try:
                    cursor.execute(col_ticket_sql)
                    conn.commit()
                except Exception:
                    pass
            for col_comunicado_sql in [
                "ALTER TABLE comunicados ADD COLUMN recordatorio_enviado_fecha TEXT;"
            ]:
                try:
                    cursor.execute(col_comunicado_sql)
                    conn.commit()
                except Exception:
                    pass
            try:
                cursor.execute("ALTER TABLE galerias ADD COLUMN visibilidad TEXT DEFAULT 'todos';")
                conn.commit()
            except Exception:
                pass
            for col_config_sql in [
                "ALTER TABLE ticket_configuraciones ADD COLUMN direccion TEXT;",
                "ALTER TABLE ticket_configuraciones ADD COLUMN responsable TEXT;"
            ]:
                try:
                    cursor.execute(col_config_sql)
                    conn.commit()
                except Exception:
                    pass

        # Siembra las categorías de ticket por defecto la primera vez (instalación nueva o
        # actualización desde una versión sin `ticket_configuraciones`), para que la lista no
        # aparezca vacía. Áreas y Sedes NO se siembran: son específicas de la organización y
        # las define el equipo de soporte desde /tickets/configuracion.
        q_count_cat = "SELECT COUNT(*) FROM ticket_configuraciones WHERE tipo = %s" if db_type == 'postgres' else "SELECT COUNT(*) FROM ticket_configuraciones WHERE tipo = ?"
        cursor.execute(q_count_cat, ('categoria',))
        if cursor.fetchone()[0] == 0:
            q_seed_cat = "INSERT INTO ticket_configuraciones (tipo, nombre) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO ticket_configuraciones (tipo, nombre) VALUES (?, ?)"
            for nombre_cat in ['Hardware', 'Software', 'Acceso/Credenciales', 'Red/Internet', 'Otro']:
                cursor.execute(q_seed_cat, ('categoria', nombre_cat))
            conn.commit()

        # 🆔 Siembra el catálogo de aplicativos con los que ya se manejan hoy, solo la primera
        # vez (instalación nueva o actualización desde una versión sin esta tabla). Después de
        # esto, el catálogo se administra por completo desde el módulo (agregar/desactivar).
        cursor.execute("SELECT COUNT(*) FROM aplicativos_catalogo")
        if cursor.fetchone()[0] == 0:
            q_seed_app = "INSERT INTO aplicativos_catalogo (nombre) VALUES (%s)" if db_type == 'postgres' else "INSERT INTO aplicativos_catalogo (nombre) VALUES (?)"
            for nombre_app in ['KUBAPP', 'SAMI', 'Moodle', 'Wolkvox', 'Correo (cPanel / Outlook)', 'Solvyx']:
                cursor.execute(q_seed_app, (nombre_app,))
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            # Solo se ejecuta si la tabla usuarios está realmente vacía (instalación nueva).
            # La contraseña inicial se define por variable de entorno; si no está seteada,
            # se genera una aleatoria y se imprime UNA vez en los logs de Render para que la copies.
            pass_inicial = os.environ.get('ADMIN_PASSWORD_INICIAL')
            if not pass_inicial:
                pass_inicial = base64.urlsafe_b64encode(os.urandom(9)).decode('utf-8')
                print(f"🔑 Usuario admin creado. Contraseña inicial generada (cámbiala tras iniciar sesión): {pass_inicial}")
            query_admin = "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (?, ?, ?, ?)"
            cursor.execute(query_admin, ('admin', generate_password_hash(pass_inicial), 'jesus.mosqueraro@gmail.com', 'admin'))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error inicializando base de datos: {e}")

init_db()

def registrar_log(usuario, accion, detalles="", credencial_id=None):
    """credencial_id es opcional: solo se usa para marcar qué entradas del log son consultas a
    la bóveda de Credenciales (ver _revelar_credencial), y así poder filtrar/armar la auditoría
    de accesos por credencial sin tener que parsear el texto libre de 'detalles'."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha_actual = obtener_fecha_actual()
        query = "INSERT INTO logs (usuario, accion, detalles, fecha, credencial_id) VALUES (%s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO logs (usuario, accion, detalles, fecha, credencial_id) VALUES (?, ?, ?, ?, ?)"
        cursor.execute(query, (usuario, accion, detalles, fecha_actual, credencial_id))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrando log: {e}")

def _migrar_password_a_hash(usuario, password_plano):
    """Re-guarda con hash una contraseña que todavía estaba en texto plano."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        nuevo_hash = generate_password_hash(password_plano)
        query = "UPDATE usuarios SET password_hash = %s WHERE usuario = %s" if db_type == 'postgres' else "UPDATE usuarios SET password_hash = ? WHERE usuario = ?"
        cursor.execute(query, (nuevo_hash, usuario))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error migrando password a hash para {usuario}: {e}")

def verificar_recaptcha(response_token):
    if not response_token: return False
    url = "https://www.google.com/recaptcha/api/siteverify"
    data = urllib.parse.urlencode({'secret': RECAPTCHA_SECRET_KEY, 'response': response_token}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8')).get('success', False)
    except Exception as e:
        return False

def archivo_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'): return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('rol') != 'admin': return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# 🧑‍💼 Rol "Agente": analista de soporte TI que resuelve PQRS/Tickets. Tiene el mismo nivel
# de acceso operativo que Admin en (casi) todos los módulos — Gestor de Archivos, Comunicados,
# Tickets/Soporte TI completo, Bóveda de Accesos, Papelera y Auditoría — con DOS excepciones
# que quedan exclusivas del rol 'admin': Gestión de Usuarios y el Gestor de Base de Datos
# (ambas siguen usando @admin_required, no este decorador).
ROLES_CON_ACCESO_OPERATIVO = ('admin', 'agente')

def agente_o_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('rol') not in ROLES_CON_ACCESO_OPERATIVO: return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# 🗄️ MÓDULO ADMINISTRADOR DE BASE DE DATOS (LECTURA + CONSOLA SQL LIBRE)
@app.route('/admin/db', methods=['GET', 'POST'])
@login_required
@admin_required
def visor_db():
    tabla_seleccionada = request.args.get('tabla', 'usuarios')
    q_sql = request.form.get('sql', '').strip() or request.args.get('sql', '').strip()
    
    tablas_permitidas = [
        'usuarios', 'galerias', 'archivos', 'logs', 'credenciales', 'comunicados',
        'tickets', 'tickets_comentarios', 'tickets_adjuntos', 'conocimiento_articulos',
        'ticket_configuraciones', 'activos_inventario', 'aplicativos_catalogo',
        'credenciales_colaboradores'
    ]
    if tabla_seleccionada not in tablas_permitidas:
        tabla_seleccionada = 'usuarios'

    columnas = []
    registros = []
    mensaje_exito = None
    error_sql = None

    # 🛡️ Ejecutar SQL libre aquí puede saltarse por completo las protecciones de
    # jerarquía de administradores (editar_usuario, eliminar_usuario, etc.), ya que
    # con una sola consulta cualquier Admin común podría auto-promoverse, editar la
    # cuenta 'admin' o cambiarle la contraseña. Por eso, aunque la vista de tablas
    # sigue abierta para todos los admins, ejecutar SQL personalizado queda
    # restringido únicamente a la cuenta super-admin ('admin').
    if q_sql and session.get('username') != 'admin':
        registrar_log(session.get('username'), "SQL Manual Bloqueado", f"Intento de ejecutar SQL personalizado sin ser super-admin: {q_sql[:120]}")
        q_sql = ''
        error_sql = "Solo la cuenta 'admin' (super-admin) puede ejecutar consultas SQL personalizadas. Puedes seguir explorando las tablas normalmente."

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        if q_sql:
            cursor.execute(q_sql)
            if q_sql.lower().startswith('select'):
                registros = cursor.fetchall()
                if cursor.description:
                    columnas = [desc[0] for desc in cursor.description]
            else:
                conn.commit()
                mensaje_exito = f"Sentencia SQL ejecutada con éxito. Filas afectadas: {cursor.rowcount}"
                registrar_log(session['username'], "Ejecución SQL Manual", f"SQL: {q_sql[:120]}")
                cursor.execute(f"SELECT * FROM {tabla_seleccionada} LIMIT 100")
                registros = cursor.fetchall()
                if cursor.description:
                    columnas = [desc[0] for desc in cursor.description]
        else:
            cursor.execute(f"SELECT * FROM {tabla_seleccionada} LIMIT 100")
            registros = cursor.fetchall()
            if cursor.description:
                columnas = [desc[0] for desc in cursor.description]
    except Exception as e:
        conn.rollback()
        error_sql = str(e)
    finally:
        conn.close()

    return render_template(
        'admin_db.html',
        tabla=tabla_seleccionada,
        tablas=tablas_permitidas,
        columnas=columnas,
        registros=registros,
        sql=q_sql,
        exito=mensaje_exito,
        error=error_sql,
        es_superadmin=(session.get('username') == 'admin')
    )


# 💾 MÓDULO DE RESPALDOS DE BASE DE DATOS ------------------------------------------------
# Vuelca todas las tablas (datos y metadatos — los ARCHIVOS en sí ya viven aparte, en
# Cloudinary) a un archivo JSON. Dos vías: un botón manual "Generar y descargar ahora"
# (esta sección), y un hilo en segundo plano que genera uno automático cada día (ver
# _respaldo_diario_automatico más abajo). Ambos guardan el archivo en RESPALDOS_DIR, que
# debe apuntar a un disco PERSISTENTE de Render (Mount Path /var/data) — sin eso, cualquier
# archivo escrito en el propio servidor se pierde en el siguiente despliegue.
RESPALDOS_DIR = os.environ.get('RESPALDOS_DIR', '/var/data/respaldos')
RESPALDOS_RETENCION_DIAS = 30  # Antigüedad máxima de los respaldos AUTOMÁTICOS antes de borrarlos solos.

TABLAS_RESPALDO = [
    'usuarios', 'galerias', 'archivos', 'logs', 'credenciales', 'comunicados',
    'comunicados_leidos', 'notificaciones', 'tickets', 'tickets_comentarios',
    'tickets_adjuntos', 'conocimiento_articulos', 'ticket_configuraciones',
    'activos_inventario', 'inventario_adjuntos', 'aplicativos_catalogo',
    'credenciales_colaboradores'
]


def _valor_respaldo_serializable(v):
    """json.dumps no sabe convertir algunos tipos que psycopg2/sqlite3 entregan tal cual
    (datetime, Decimal) — esto los vuelve texto/número plano antes de serializar, sin tocar
    el resto."""
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    return v


def _generar_respaldo_datos():
    """Vuelca todas las tablas de TABLAS_RESPALDO a un diccionario serializable — el
    contenido real del archivo de respaldo. Si una tabla puntual falla (p. ej. todavía no
    existe en una instalación muy vieja), se omite y se sigue con las demás: un respaldo
    parcial es mejor que ninguno."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    respaldo = {
        'generado': datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M:%S'),
        'motor': db_type,
        'tablas': {}
    }
    for tabla in TABLAS_RESPALDO:
        try:
            cursor.execute(f"SELECT * FROM {tabla}")
            columnas = [d[0] for d in cursor.description]
            filas = cursor.fetchall()
            respaldo['tablas'][tabla] = {
                'columnas': columnas,
                'filas': [[_valor_respaldo_serializable(v) for v in fila] for fila in filas]
            }
        except Exception as e:
            print(f"⚠️ Error respaldando tabla '{tabla}': {e}")
    conn.close()
    return respaldo


def _guardar_respaldo_en_disco(prefijo='manual'):
    """Genera el respaldo y lo guarda como JSON en RESPALDOS_DIR. Devuelve la ruta completa
    del archivo creado, o None si no se pudo escribir (p. ej. el disco persistente de Render
    todavía no está montado — la carpeta ni siquiera se puede crear)."""
    try:
        os.makedirs(RESPALDOS_DIR, exist_ok=True)
    except Exception as e:
        print(f"⚠️ No se pudo crear/acceder a la carpeta de respaldos '{RESPALDOS_DIR}': {e}")
        return None
    datos = _generar_respaldo_datos()
    nombre = f"{prefijo}_{datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d_%H%M%S')}.json"
    ruta = os.path.join(RESPALDOS_DIR, nombre)
    try:
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(datos, f, ensure_ascii=False)
        return ruta
    except Exception as e:
        print(f"⚠️ Error escribiendo el respaldo en '{ruta}': {e}")
        return None


def _listar_respaldos():
    """Lista los archivos de respaldo ya guardados en RESPALDOS_DIR, más recientes primero.
    Devuelve [] si la carpeta no existe todavía (nunca se ha generado un respaldo, o el
    disco persistente no está montado)."""
    try:
        if not os.path.isdir(RESPALDOS_DIR):
            return []
        items = []
        for nombre in os.listdir(RESPALDOS_DIR):
            if not nombre.endswith('.json'):
                continue
            ruta = os.path.join(RESPALDOS_DIR, nombre)
            try:
                stat = os.stat(ruta)
                items.append({
                    'nombre': nombre,
                    'tipo': 'Automático (diario)' if nombre.startswith('auto_') else 'Manual',
                    'tamano_kb': round(stat.st_size / 1024, 1),
                    'fecha': datetime.fromtimestamp(stat.st_mtime, tz=ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M:%S')
                })
            except Exception:
                continue
        items.sort(key=lambda x: x['fecha'], reverse=True)
        return items
    except Exception as e:
        print(f"⚠️ Error listando respaldos: {e}")
        return []


def _limpiar_respaldos_viejos():
    """Borra respaldos AUTOMÁTICOS ('auto_...') con más de RESPALDOS_RETENCION_DIAS de
    antigüedad, para que el disco no se llene solo con el tiempo. Los respaldos MANUALES
    nunca se borran solos — quien los generó decide cuándo quitarlos desde la página."""
    try:
        if not os.path.isdir(RESPALDOS_DIR):
            return
        limite = datetime.now(ZONA_HORARIA_COLOMBIA) - timedelta(days=RESPALDOS_RETENCION_DIAS)
        for nombre in os.listdir(RESPALDOS_DIR):
            if not nombre.startswith('auto_') or not nombre.endswith('.json'):
                continue
            ruta = os.path.join(RESPALDOS_DIR, nombre)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(ruta), tz=ZONA_HORARIA_COLOMBIA)
                if mtime < limite:
                    os.remove(ruta)
                    print(f"🧹 Respaldo automático vencido eliminado: {nombre}")
            except Exception:
                pass
    except Exception as e:
        print(f"⚠️ Error limpiando respaldos viejos: {e}")


def _respaldo_diario_automatico():
    """Hilo en segundo plano (arranca una vez al cargar la app): cada hora revisa si ya se
    generó el respaldo automático de HOY y, si no, lo genera. El propio nombre del archivo
    del día actúa como candado (se crea con modo exclusivo 'x', que falla si ya existe) —
    así, aunque Render corra 2 procesos gunicorn de esta misma app en paralelo (como está
    configurado), solo uno de ellos termina generando el respaldo cada día."""
    time.sleep(30)  # Pequeña espera para no competir con el arranque del propio servidor.
    while True:
        try:
            os.makedirs(RESPALDOS_DIR, exist_ok=True)
            hoy = datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d')
            marcador = os.path.join(RESPALDOS_DIR, f"auto_{hoy}.json")
            try:
                fh = os.open(marcador, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fh)
            except FileExistsError:
                pass  # Ya se generó hoy (por este proceso o por otro worker) — nada que hacer.
            else:
                datos = _generar_respaldo_datos()
                with open(marcador, 'w', encoding='utf-8') as f:
                    json.dump(datos, f, ensure_ascii=False)
                print(f"✅ Respaldo automático diario generado: {marcador}")
                _limpiar_respaldos_viejos()
        except Exception as e:
            print(f"⚠️ Error en el hilo de respaldo automático: {e}")
        time.sleep(3600)  # Revisa cada hora si ya cambió el día.


if os.environ.get('DESHABILITAR_RESPALDO_AUTOMATICO') != '1':
    threading.Thread(target=_respaldo_diario_automatico, daemon=True).start()


@app.route('/admin/respaldos')
@login_required
@admin_required
def ver_respaldos():
    disco_disponible = os.path.isdir(RESPALDOS_DIR) or _crear_dir_respaldos_silencioso()
    return render_template('respaldos.html', respaldos=_listar_respaldos(), respaldos_dir=RESPALDOS_DIR, disco_disponible=disco_disponible)


def _crear_dir_respaldos_silencioso():
    try:
        os.makedirs(RESPALDOS_DIR, exist_ok=True)
        return True
    except Exception:
        return False


@app.route('/admin/respaldos/generar', methods=['POST'])
@login_required
@admin_required
def generar_respaldo():
    """Botón "Generar y descargar ahora": crea un respaldo manual, lo guarda en el disco
    (queda listado igual que los automáticos) y lo entrega de inmediato como descarga."""
    ruta = _guardar_respaldo_en_disco(prefijo='manual')
    if not ruta:
        flash("No se pudo generar el respaldo: la carpeta de respaldos no está disponible (¿el disco persistente de Render ya está montado en /var/data?).", "error")
        return redirect(url_for('ver_respaldos'))
    registrar_log(session.get('username'), "Respaldo de Base de Datos", f"Respaldo manual generado: {os.path.basename(ruta)}")
    return send_file(ruta, as_attachment=True, download_name=os.path.basename(ruta))


@app.route('/admin/respaldos/descargar/<nombre>')
@login_required
@admin_required
def descargar_respaldo(nombre):
    nombre_seguro = os.path.basename(nombre)
    ruta = os.path.join(RESPALDOS_DIR, nombre_seguro)
    if not nombre_seguro.endswith('.json') or not os.path.isfile(ruta):
        flash("Ese archivo de respaldo ya no existe.", "error")
        return redirect(url_for('ver_respaldos'))
    return send_file(ruta, as_attachment=True, download_name=nombre_seguro)


@app.route('/admin/respaldos/eliminar/<nombre>', methods=['POST'])
@login_required
@admin_required
def eliminar_respaldo(nombre):
    nombre_seguro = os.path.basename(nombre)
    ruta = os.path.join(RESPALDOS_DIR, nombre_seguro)
    if nombre_seguro.endswith('.json') and os.path.isfile(ruta):
        try:
            os.remove(ruta)
            registrar_log(session.get('username'), "Respaldo de Base de Datos", f"Respaldo eliminado manualmente: {nombre_seguro}")
        except Exception as e:
            print(f"⚠️ Error eliminando respaldo '{nombre_seguro}': {e}")
    return redirect(url_for('ver_respaldos'))


# 📢 MÓDULO MURO DE COMUNICADOS
@app.route('/comunicados')
@login_required
def ver_comunicados():
    pestana = request.args.get('tab', 'activos')
    q_busqueda = request.args.get('q', '').strip().lower()
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    estado_filtro = 'activo' if pestana == 'activos' else 'archivado'
    
    try:
        query = "SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor FROM comunicados WHERE estado = %s ORDER BY fijado DESC, id DESC" if db_type == 'postgres' else "SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor FROM comunicados WHERE estado = ? ORDER BY fijado DESC, id DESC"
        cursor.execute(query, (estado_filtro,))
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando comunicados: {e}")
        rows = []

    conn.close()

    # 👤 "Publicado por" muestra el nombre/alias real del autor, no su usuario de inicio de
    # sesión crudo (p. ej. 'analistati' en vez de 'Ana Lisboa T.').
    nombres_usuarios = _mapa_nombres_usuarios()

    comunicados = []
    for r in rows:
        c_id, titulo, contenido, nivel, fijado, img_url, estado, fecha, autor = r
        texto_full = f"{titulo} {contenido} {autor}".lower()
        if not q_busqueda or q_busqueda in texto_full:
            comunicados.append({
                'id': c_id,
                'titulo': titulo,
                'contenido': contenido,
                'nivel': nivel,
                'fijado': fijado,
                'imagen_url': img_url,
                'estado': estado,
                'fecha': fecha,
                'autor': _nombre_para_mostrar(autor, nombres_usuarios)
            })

    # 👁️ Ver el muro de Comunicados marca como "leídos" todos los que están activos (no los
    # archivados: esos ya son historial, no algo pendiente por leer).
    usuario_actual = session.get('username')
    if pestana == 'activos':
        for c in comunicados:
            _marcar_comunicado_leido(c['id'], usuario_actual)

    # 👁️ Para soporte/admin, se muestra cuántos usuarios (de los activos) ya leyeron cada
    # comunicado — útil para políticas de lectura obligatoria.
    es_soporte = session.get('rol') in ROLES_CON_ACCESO_OPERATIVO
    if es_soporte:
        # 📢 Recordatorio automático de lectura pendiente — ver _revisar_recordatorios_lectura().
        _revisar_recordatorios_lectura()
    if es_soporte and comunicados:
        conteos = _conteo_lecturas_comunicados([c['id'] for c in comunicados])
        total_usuarios = _total_usuarios_activos()
        for c in comunicados:
            c['leidos'] = conteos.get(c['id'], 0)
            c['total_usuarios'] = total_usuarios

    return render_template('comunicados.html', comunicados=comunicados, pestana=pestana, q_busqueda=q_busqueda, rol=session.get('rol'), es_soporte=es_soporte)

@app.route('/comunicados/crear', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_comunicado():
    titulo = request.form.get('titulo', '').strip()
    # 📝 El contenido llega como HTML del editor de texto enriquecido (Quill) — se limpia
    # ANTES de guardarlo, para no confiar en lo que manda el navegador.
    contenido = _sanitizar_html_enriquecido(request.form.get('contenido', '').strip())
    nivel = request.form.get('nivel', 'info').strip()
    # ⚠️ Usar un bool nativo de Python (no 0/1 literal): la columna "fijado" en Neon
    # es de tipo BOOLEAN, y Postgres rechaza "column is of type boolean but expression
    # is of type integer" si se le pasa un entero. psycopg2 adapta True/False
    # correctamente a boolean, y sqlite3 los guarda igual de bien como 0/1.
    fijado = (request.form.get('fijado') == 'on')
    imagen = request.files.get('imagen')
    
    imagen_url = ""
    if imagen and archivo_permitido(imagen.filename):
        try:
            upload_result = cloudinary.uploader.upload(
                imagen, 
                resource_type="image",
                use_filename=True,
                unique_filename=True
            )
            imagen_url = upload_result.get('secure_url', '')
        except Exception as e:
            print(f"Error subiendo imagen de comunicado: {e}")

    if titulo and contenido and not _html_esta_vacio(contenido):
        fecha_act = obtener_fecha_actual()
        autor = session.get('username', 'Admin')

        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q_ins = "INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor) VALUES (%s, %s, %s, %s, %s, 'activo', %s, %s)" if db_type == 'postgres' else "INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor) VALUES (?, ?, ?, ?, ?, 'activo', ?, ?)"
            cursor.execute(q_ins, (titulo, contenido, nivel, fijado, imagen_url, fecha_act, autor))
            conn.commit()
            registrar_log(autor, "Publicación de Comunicado", f"Nuevo comunicado: '{titulo}' [{nivel}]")
        except Exception as e:
            conn.rollback()
            print(f"Error creando comunicado: {e}")
        conn.close()

    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/editar/<int:com_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        q_sel = "SELECT imagen_url FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT imagen_url FROM comunicados WHERE id = ?"
        cursor.execute(q_sel, (com_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return redirect(url_for('ver_comunicados'))

        imagen_url_actual = row[0] or ""

        titulo = request.form.get('titulo', '').strip()
        # 📝 El contenido llega como HTML del editor de texto enriquecido (Quill) — se limpia
        # ANTES de guardarlo, para no confiar en lo que manda el navegador.
        contenido = _sanitizar_html_enriquecido(request.form.get('contenido', '').strip())
        nivel = request.form.get('nivel', 'info').strip()
        fijado = (request.form.get('fijado') == 'on')
        imagen = request.files.get('imagen')

        if not titulo or not contenido or _html_esta_vacio(contenido):
            conn.close()
            return redirect(url_for('ver_comunicados'))

        # Si se adjunta una nueva imagen válida, se reemplaza; si no, se conserva la actual.
        imagen_url = imagen_url_actual
        if imagen and imagen.filename and archivo_permitido(imagen.filename):
            try:
                upload_result = cloudinary.uploader.upload(
                    imagen,
                    resource_type="image",
                    use_filename=True,
                    unique_filename=True
                )
                imagen_url = upload_result.get('secure_url', imagen_url_actual)
            except Exception as e:
                print(f"Error subiendo nueva imagen de comunicado {com_id}: {e}")

        q_upd = "UPDATE comunicados SET titulo = %s, contenido = %s, nivel = %s, fijado = %s, imagen_url = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET titulo = ?, contenido = ?, nivel = ?, fijado = ?, imagen_url = ? WHERE id = ?"
        cursor.execute(q_upd, (titulo, contenido, nivel, fijado, imagen_url, com_id))
        conn.commit()
        registrar_log(session.get('username'), "Edición de Comunicado", f"Comunicado '{titulo}' (ID {com_id}) actualizado")
    except Exception as e:
        conn.rollback()
        print(f"Error editando comunicado {com_id}: {e}")

    conn.close()
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/archivar/<int:com_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def archivar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        q_sel = "SELECT estado, titulo FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT estado, titulo FROM comunicados WHERE id = ?"
        cursor.execute(q_sel, (com_id,))
        row = cursor.fetchone()

        if row:
            nuevo_estado = 'archivado' if row[0] == 'activo' else 'activo'
            # "fijado = 0" literal fallaba en Postgres contra la columna BOOLEAN real; "false" funciona en ambos motores.
            q_upd = "UPDATE comunicados SET estado = %s, fijado = false WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = ?, fijado = false WHERE id = ?"
            cursor.execute(q_upd, (nuevo_estado, com_id))
            conn.commit()
            registrar_log(session['username'], "Cambio Estado Comunicado", f"Comunicado '{row[1]}' movido a {nuevo_estado}")
    except Exception as e:
        conn.rollback()
        print(f"Error archivando/reactivando comunicado {com_id}: {e}")

    conn.close()
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/eliminar/<int:com_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_comunicado(com_id):
    # El propio botón en comunicados.html pregunta "¿Enviar este comunicado a la papelera?",
    # así que esto debe ser un envío a la papelera (estado='eliminado'), no un borrado
    # permanente inmediato — igual que ya se hace con instructivos y credenciales.
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM comunicados WHERE id = ?"
        cursor.execute(q_sel, (com_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else f"ID {com_id}"

        q_upd = "UPDATE comunicados SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Comunicado", f"Se envió a la papelera el comunicado '{titulo}'")
    except Exception as e:
        conn.rollback()
        print(f"Error enviando comunicado {com_id} a la papelera: {e}")

    conn.close()
    # 🧭 Antes esto volvía al muro de Comunicados, donde el aviso simplemente desaparecía sin
    # ninguna confirmación visible de a dónde fue — eso hacía parecer que se había borrado para
    # siempre. Ahora se redirige directo a la Papelera con la pestaña de Comunicados ya abierta,
    # para que quede claro que sigue ahí y se puede restaurar.
    return redirect(url_for('ver_papelera', tab='comunicados'))

@app.route('/comunicados/<int:com_id>/lecturas')
@login_required
@agente_o_admin_required
def lecturas_comunicado(com_id):
    """JSON con quién (de las cuentas activas) ya leyó este comunicado y quién falta —
    usado por el modal de "Ver lecturas" en el muro de Comunicados."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT usuario, COALESCE(nombre, usuario) FROM usuarios WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY usuario ASC")
        todos = {r[0]: r[1] for r in cursor.fetchall()}

        q = "SELECT usuario, fecha FROM comunicados_leidos WHERE comunicado_id = %s" if db_type == 'postgres' else "SELECT usuario, fecha FROM comunicados_leidos WHERE comunicado_id = ?"
        cursor.execute(q, (com_id,))
        leidos = {r[0]: r[1] for r in cursor.fetchall()}
        conn.close()

        leyeron = [{'usuario': u, 'nombre': todos.get(u, u), 'fecha': f} for u, f in leidos.items() if u in todos]
        faltan = [{'usuario': u, 'nombre': n} for u, n in todos.items() if u not in leidos]
        leyeron.sort(key=lambda x: x['fecha'], reverse=True)
        faltan.sort(key=lambda x: x['nombre'].lower())
        return {'leyeron': leyeron, 'faltan': faltan, 'total': len(todos)}
    except Exception as e:
        conn.close()
        print(f"⚠️ Error listando lecturas del comunicado {com_id}: {e}")
        return {'leyeron': [], 'faltan': [], 'total': 0}


@app.route('/comunicados/cumplimiento')
@login_required
@agente_o_admin_required
def cumplimiento_comunicados():
    """Panel de cumplimiento de lectura: de un vistazo, qué % de las cuentas activas ya leyó
    cada comunicado activo y quién falta — sin tener que abrir el modal de cada uno por
    separado en el muro de Comunicados."""
    _revisar_recordatorios_lectura()
    detalle = _detalle_cumplimiento_comunicados()
    return render_template(
        'comunicados_cumplimiento.html', detalle=detalle,
        horas_recordatorio=HORAS_RECORDATORIO_LECTURA_COMUNICADO
    )


@app.route('/comunicados/<int:com_id>/recordatorio', methods=['POST'])
@login_required
@agente_o_admin_required
def enviar_recordatorio_comunicado(com_id):
    """Envía ahora mismo (a demanda) el recordatorio de lectura pendiente para un comunicado
    puntual — no hay que esperar a que se cumplan las horas del aviso automático."""
    detalle = _detalle_cumplimiento_comunicados()
    comunicado = next((c for c in detalle if c['id'] == com_id), None)
    if comunicado:
        cantidad = _enviar_recordatorio_lectura(comunicado)
        registrar_log(session.get('username'), "Recordatorio de Lectura Enviado", f"Comunicado '{comunicado['titulo']}' (ID {com_id}): recordatorio a {cantidad} usuario(s)")
    return redirect(url_for('cumplimiento_comunicados'))


@app.route('/restaurar_comunicado/<int:com_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def restaurar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM comunicados WHERE id = ?"
        cursor.execute(q_sel, (com_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else f"ID {com_id}"

        q_upd = "UPDATE comunicados SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Restauración de Comunicado", f"Se restauró el comunicado '{titulo}' desde la papelera.")
    except Exception as e:
        conn.rollback()
        print(f"Error restaurando comunicado {com_id}: {e}")

    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_comunicado/<int:com_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def destruir_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM comunicados WHERE id = ?"
        cursor.execute(q_sel, (com_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else f"ID {com_id}"

        q_del = "DELETE FROM comunicados WHERE id = %s" if db_type == 'postgres' else "DELETE FROM comunicados WHERE id = ?"
        cursor.execute(q_del, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Se destruyó permanentemente el comunicado '{titulo}'.")
    except Exception as e:
        conn.rollback()
        print(f"Error destruyendo comunicado {com_id}: {e}")

    conn.close()
    return redirect(url_for('ver_papelera'))

# 🎫 MÓDULO DE SOPORTE TI (TICKETS / SOLICITUDES INTERNAS)
CATEGORIAS_TICKET = ['Hardware', 'Software', 'Acceso/Credenciales', 'Red/Internet', 'Otro']
PRIORIDADES_TICKET = ['Baja', 'Media', 'Alta', 'Urgente']
ESTADOS_TICKET = ['Abierto', 'En Proceso', 'Resuelto', 'Cerrado']
TIPOS_TICKET = ['Incidente', 'Requerimiento']
# Metadatos de cada tipo para pintar las tarjetas de selección y las insignias (inspirado
# en la mesa de ayuda externa que ya usa la organización: distingue "algo se rompió" de
# "necesito algo nuevo" desde el primer paso de creación).
TIPOS_TICKET_INFO = {
    'Incidente': {
        'icono': 'fa-triangle-exclamation',
        'descripcion': 'Algo no funciona, está roto o te bloquea para trabajar.'
    },
    'Requerimiento': {
        'icono': 'fa-clipboard-list',
        'descripcion': 'Solicitas algo nuevo: acceso, equipo, software o información.'
    }
}
MAX_ADJUNTOS_TICKET = 5

# 📦 INVENTARIO DE ACTIVOS DE TI
ESTADOS_ACTIVO = ['Disponible', 'Asignado', 'Mantenimiento', 'Baja']
TIPOS_ACTIVO = ['Computador de Escritorio', 'Portátil', 'Impresora', 'Monitor', 'Teléfono/Celular', 'Servidor', 'Red (Switch/Router/AP)', 'Otro']

# ⏱️ SLA (Acuerdos de Nivel de Servicio): horas máximas de "primera respuesta" (sacar el
# ticket de 'Abierto') y de "resolución" (llegar a 'Resuelto'/'Cerrado') según la prioridad.
# Son valores de partida razonables para un equipo de soporte interno; se pueden ajustar
# aquí si el equipo de TI define otros tiempos formales más adelante.
SLA_HORAS_POR_PRIORIDAD = {
    'Urgente': {'respuesta': 2, 'resolucion': 24},
    'Alta': {'respuesta': 4, 'resolucion': 48},
    'Media': {'respuesta': 8, 'resolucion': 96},
    'Baja': {'respuesta': 24, 'resolucion': 168},
}
MAX_MODIFICACIONES_SLA = 2
FORMATO_FECHA_TICKET = "%Y-%m-%d %H:%M:%S"

# 🙂 Calificación de satisfacción (1 a 5 estrellas) que el solicitante puede dejar una sola
# vez, cuando su ticket ya está Resuelto o Cerrado — igual que en la mesa de ayuda externa.
CALIFICACION_MIN = 1
CALIFICACION_MAX = 5

# ⏳ Umbral para distinguir "Vigente" de "Próximo a vencer" en los filtros de la lista: si
# queda menos del 20% del tiempo total de resolución (o menos de 4 horas, lo que sea mayor),
# se considera que el ticket está por vencer.
UMBRAL_PROXIMO_A_VENCER_PORCENTAJE = 0.2
UMBRAL_PROXIMO_A_VENCER_HORAS_MIN = 4


def _puede_ver_ticket(creado_por):
    """Un ticket solo lo puede ver quien lo creó o cualquier cuenta con rol admin (equipo de soporte TI)."""
    return session.get('rol') in ROLES_CON_ACCESO_OPERATIVO or session.get('username') == creado_por


def _parsear_fecha_ticket(fecha_str):
    """Convierte el formato de fecha usado en todo el módulo ('YYYY-MM-DD HH:MM:SS') a
    datetime. Devuelve None si el valor está vacío o no tiene el formato esperado."""
    if not fecha_str:
        return None
    try:
        return datetime.strptime(fecha_str, FORMATO_FECHA_TICKET)
    except Exception:
        return None


def _calcular_limite_sla(fecha_base_str, horas):
    """Suma 'horas' a una fecha base (en el formato del módulo) y devuelve el resultado en
    ese mismo formato. Si la fecha base no se puede interpretar, usa el momento actual."""
    base = _parsear_fecha_ticket(fecha_base_str) or datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)
    return (base + timedelta(hours=horas)).strftime(FORMATO_FECHA_TICKET)


def _calcular_sla_ticket(ticket):
    """Calcula, a partir de los campos crudos del ticket, el estado de cumplimiento del SLA
    de RESOLUCIÓN (el que se muestra de forma prominente en la interfaz, como hace la mesa
    de ayuda externa con su 'Compromiso con el usuario'). Devuelve un dict listo para pintar:
    {'estado': 'en_tiempo'|'vencido'|'cumplido'|'incumplido'|'sin_datos', 'texto': ..., 'color': ...}
    """
    limite = _parsear_fecha_ticket(ticket.get('sla_resolucion_limite'))
    if not limite:
        return {'estado': 'sin_datos', 'texto': 'Sin datos de SLA', 'color': 'slate'}

    cumplida = _parsear_fecha_ticket(ticket.get('sla_resolucion_cumplida'))
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)

    if cumplida:
        if cumplida <= limite:
            return {'estado': 'cumplido', 'texto': 'Resuelto en tiempo', 'color': 'emerald'}
        return {'estado': 'incumplido', 'texto': 'Resuelto fuera de tiempo', 'color': 'rose'}

    if ahora > limite:
        return {'estado': 'vencido', 'texto': 'SLA vencido', 'color': 'rose'}

    restante = limite - ahora
    if restante.days >= 1:
        texto = f"Quedan ~{restante.days} día(s)"
    else:
        horas_restantes = max(1, restante.seconds // 3600)
        texto = f"Quedan ~{horas_restantes} hora(s)"
    return {'estado': 'en_tiempo', 'texto': texto, 'color': 'cyan'}


def _bucket_cumplimiento_ticket(ticket):
    """Agrupa el ticket en una de las categorías que se muestran como pestañas filtrables en
    la lista (inspirado en la mesa de ayuda externa): 'cerrado' (ya Resuelto/Cerrado, sin
    importar si llegó a tiempo o no), 'vencido' (abierto y ya pasó la fecha límite),
    'proximo_a_vencer' (abierto y le queda poco tiempo) o 'vigente' (abierto, con margen)."""
    if ticket.get('estado') in ('Resuelto', 'Cerrado'):
        return 'cerrado'

    sla = ticket.get('sla') or _calcular_sla_ticket(ticket)
    if sla.get('estado') == 'vencido':
        return 'vencido'
    if sla.get('estado') != 'en_tiempo':
        # 'sin_datos' (no debería pasar para un ticket abierto, pero por seguridad) se trata
        # como vigente en vez de ocultarlo de todas las pestañas.
        return 'vigente'

    limite = _parsear_fecha_ticket(ticket.get('sla_resolucion_limite'))
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)
    horas_totales = SLA_HORAS_POR_PRIORIDAD.get(ticket.get('prioridad'), SLA_HORAS_POR_PRIORIDAD['Media'])['resolucion']
    umbral_horas = max(UMBRAL_PROXIMO_A_VENCER_HORAS_MIN, horas_totales * UMBRAL_PROXIMO_A_VENCER_PORCENTAJE)
    horas_restantes = (limite - ahora).total_seconds() / 3600 if limite else 0
    return 'proximo_a_vencer' if horas_restantes <= umbral_horas else 'vigente'


def _progreso_ticket(ticket):
    """Calcula qué porcentaje del tiempo total de SLA de resolución ya transcurrió (o
    transcurrió hasta que se resolvió), como una barra de avance visual en la lista de
    tickets. No depende de nueva información en la BD: se deriva de fechas ya existentes."""
    creado = _parsear_fecha_ticket(ticket.get('fecha_creacion'))
    if not creado:
        return 0
    horas_totales = SLA_HORAS_POR_PRIORIDAD.get(ticket.get('prioridad'), SLA_HORAS_POR_PRIORIDAD['Media'])['resolucion']
    if horas_totales <= 0:
        return 0

    cumplida = _parsear_fecha_ticket(ticket.get('sla_resolucion_cumplida'))
    fin = cumplida if (ticket.get('estado') in ('Resuelto', 'Cerrado') and cumplida) else datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)

    horas_transcurridas = (fin - creado).total_seconds() / 3600
    return max(0, min(100, round(horas_transcurridas / horas_totales * 100)))


def _revisar_alertas_sla():
    """Revisa los tickets abiertos/en proceso y avisa (campanita + correo) la primera vez que
    uno entra en 'Próximo a vencer' o se escala a 'Vencido' — así el equipo no depende de estar
    mirando la lista para enterarse. No hay un scheduler aparte corriendo en Render, así que
    esto se llama de forma perezosa (best-effort, nunca debe tumbar la página) cada vez que
    alguien del equipo de soporte abre la lista de tickets o los indicadores. 'sla_alerta_nivel'
    guarda el último nivel ya avisado por ticket para no repetir el mismo aviso una y otra vez;
    se limpia a NULL cuando se extiende el SLA (ver extender_sla_ticket) para que pueda volver
    a avisar si se vuelve a acercar la nueva fecha límite."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, titulo, tipo, prioridad, estado, asignado_a, fecha_creacion, "
            "sla_resolucion_limite, sla_resolucion_cumplida, sla_alerta_nivel FROM tickets "
            "WHERE estado NOT IN ('Resuelto', 'Cerrado')"
        )
        filas = cursor.fetchall()

        for (ticket_id, titulo, tipo, prioridad, estado, asignado_a, fecha_creacion,
             sla_limite, sla_cumplida, nivel_previo) in filas:
            t = {
                'estado': estado, 'prioridad': prioridad, 'fecha_creacion': fecha_creacion,
                'sla_resolucion_limite': sla_limite, 'sla_resolucion_cumplida': sla_cumplida,
            }
            bucket = _bucket_cumplimiento_ticket(t)
            if bucket not in ('proximo_a_vencer', 'vencido'):
                continue
            if bucket == nivel_previo or (bucket == 'proximo_a_vencer' and nivel_previo == 'vencido'):
                continue  # ya se avisó este nivel (o uno peor) — no repetir ni "des-escalar"

            q_upd = ("UPDATE tickets SET sla_alerta_nivel = %s WHERE id = %s" if db_type == 'postgres'
                      else "UPDATE tickets SET sla_alerta_nivel = ? WHERE id = ?")
            cursor.execute(q_upd, (bucket, ticket_id))
            conn.commit()

            codigo = _codigo_ticket(tipo or 'Incidente', ticket_id, fecha_creacion)
            url_ticket = url_for('ver_ticket', ticket_id=ticket_id)
            equipo = [] if asignado_a else _equipo_soporte_activo()
            destinatarios = [asignado_a] if asignado_a else [m['usuario'] for m in equipo]

            if bucket == 'vencido':
                mensaje = f"⛔ SLA vencido en la solicitud {codigo}: '{titulo}'"
                asunto = f"[Arkiv] SLA vencido — solicitud {codigo}"
                cuerpo_estado = "ya superó"
            else:
                mensaje = f"⏳ La solicitud {codigo} está próxima a vencer su SLA: '{titulo}'"
                asunto = f"[Arkiv] SLA próximo a vencer — solicitud {codigo}"
                cuerpo_estado = "está por superar"
            cuerpo = (
                f"La solicitud de soporte {codigo} ('{titulo}') {cuerpo_estado} su tiempo límite de resolución.\n\n"
                f"Ingresa a Arkiv, módulo Solicitudes TI, para revisarla.\n\n---\nArkiv"
            )

            crear_notificacion_para_varios(destinatarios, mensaje, url=url_ticket)
            if asignado_a:
                correo_dest = _correo_de_usuario(asignado_a)
                if correo_dest:
                    threading.Thread(target=enviar_correo_ticket, args=(correo_dest, asunto, cuerpo)).start()
            else:
                for miembro in equipo:
                    if miembro['correo']:
                        threading.Thread(target=enviar_correo_ticket, args=(miembro['correo'], asunto, cuerpo)).start()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error revisando alertas de SLA: {e}")


def _config_ticket_lista(tipo_config):
    """Devuelve [{'id', 'nombre', 'direccion', 'responsable'}] de las Áreas, Sedes o
    Categorías activas configuradas por el equipo de soporte en /tickets/configuracion
    (tipo_config: 'area' | 'sede' | 'categoria'). 'direccion' y 'responsable' solo tienen
    contenido real para tipo_config == 'sede'; para área/categoría quedan en None.
    Si la tabla no existe todavía o falla la consulta, devuelve una lista vacía en vez de
    romper la página que la llama."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT id, nombre, direccion, responsable FROM ticket_configuraciones WHERE tipo = %s AND estado = 'activo' ORDER BY nombre ASC" if db_type == 'postgres' else "SELECT id, nombre, direccion, responsable FROM ticket_configuraciones WHERE tipo = ? AND estado = 'activo' ORDER BY nombre ASC"
        cursor.execute(q, (tipo_config,))
        filas = [{'id': r[0], 'nombre': r[1], 'direccion': r[2], 'responsable': r[3]} for r in cursor.fetchall()]
        conn.close()
        return filas
    except Exception as e:
        print(f"⚠️ Error listando configuración de tickets ('{tipo_config}'): {e}")
        return []


def _correo_de_usuario(username):
    """Busca el correo registrado de un usuario por su nombre de cuenta. Devuelve None si no
    existe o si algo falla (nunca debe tumbar el flujo del ticket que lo llama)."""
    if not username:
        return None
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT correo FROM usuarios WHERE usuario = %s" if db_type == 'postgres' else "SELECT correo FROM usuarios WHERE usuario = ?"
        cursor.execute(q, (username,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        print(f"⚠️ Error buscando correo de '{username}': {e}")
        return None


def _info_usuario(username):
    """Trae el perfil completo (nombre, correo, teléfono, rol) de un usuario por su cuenta de
    inicio de sesión. Se usa para mostrar la mayor cantidad de información posible del
    solicitante en el detalle de un ticket. Devuelve None si no existe o si algo falla."""
    if not username:
        return None
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT usuario, nombre, correo, telefono, rol FROM usuarios WHERE usuario = %s" if db_type == 'postgres' else "SELECT usuario, nombre, correo, telefono, rol FROM usuarios WHERE usuario = ?"
        cursor.execute(q, (username,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return {'usuario': row[0], 'nombre': row[1], 'correo': row[2], 'telefono': row[3], 'rol': row[4]}
    except Exception as e:
        print(f"⚠️ Error buscando perfil de '{username}': {e}")
        return None


def _equipo_soporte_activo():
    """Devuelve la lista de cuentas activas con rol 'admin' o 'agente' — el 'equipo de
    soporte' que se notifica cuando se crea un ticket nuevo (salvo que quede asignado
    automáticamente a alguien puntual). Devuelve [] si algo falla."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT usuario, correo FROM usuarios WHERE estado = 'activo' AND rol IN ('admin', 'agente')" if db_type == 'postgres' else "SELECT usuario, correo FROM usuarios WHERE estado = 'activo' AND rol IN ('admin', 'agente')"
        cursor.execute(q)
        filas = [{'usuario': r[0], 'correo': r[1]} for r in cursor.fetchall()]
        conn.close()
        return filas
    except Exception as e:
        print(f"⚠️ Error listando equipo de soporte: {e}")
        return []


def crear_notificacion(usuario, mensaje, url='', tipo='ticket'):
    """Crea una notificación interna (campanita) para un usuario puntual. Nunca debe tumbar
    el flujo que la llama: cualquier error se registra en consola y se ignora."""
    if not usuario:
        return
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha = datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M:%S')
        q = "INSERT INTO notificaciones (usuario, tipo, mensaje, url, fecha) VALUES (%s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO notificaciones (usuario, tipo, mensaje, url, fecha) VALUES (?, ?, ?, ?, ?)"
        cursor.execute(q, (usuario, tipo, mensaje, url, fecha))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error creando notificación para '{usuario}': {e}")


def crear_notificacion_para_varios(usuarios, mensaje, url='', tipo='ticket'):
    """Igual que crear_notificacion pero para una lista de usuarios (p. ej. todo el equipo
    de soporte), sin duplicar destinatarios."""
    for u in set(u for u in (usuarios or []) if u):
        crear_notificacion(u, mensaje, url=url, tipo=tipo)


def _marcar_comunicado_leido(comunicado_id, usuario):
    """Registra que 'usuario' ya vio este comunicado (muro de Comunicados o el fijado en la
    bienvenida). Si ya estaba marcado, no hace nada — la tabla tiene un UNIQUE(comunicado_id,
    usuario) para evitar duplicados; el intento repetido se ignora silenciosamente."""
    if not comunicado_id or not usuario:
        return
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha = datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M:%S')
        if db_type == 'postgres':
            q = "INSERT INTO comunicados_leidos (comunicado_id, usuario, fecha) VALUES (%s, %s, %s) ON CONFLICT (comunicado_id, usuario) DO NOTHING"
        else:
            q = "INSERT OR IGNORE INTO comunicados_leidos (comunicado_id, usuario, fecha) VALUES (?, ?, ?)"
        cursor.execute(q, (comunicado_id, usuario, fecha))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error marcando comunicado {comunicado_id} como leído por '{usuario}': {e}")


def _conteo_lecturas_comunicados(ids_comunicados):
    """Devuelve {comunicado_id: cantidad_de_usuarios_que_lo_leyeron} para una lista de ids —
    usado en el muro de Comunicados para que soporte/admin vea cuántos ya lo vieron."""
    if not ids_comunicados:
        return {}
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        placeholders = ','.join(['%s' if db_type == 'postgres' else '?'] * len(ids_comunicados))
        q = f"SELECT comunicado_id, COUNT(*) FROM comunicados_leidos WHERE comunicado_id IN ({placeholders}) GROUP BY comunicado_id"
        cursor.execute(q, tuple(ids_comunicados))
        conteos = {r[0]: r[1] for r in cursor.fetchall()}
        conn.close()
        return conteos
    except Exception as e:
        print(f"⚠️ Error contando lecturas de comunicados: {e}")
        return {}


def _total_usuarios_activos():
    """Cantidad de cuentas activas — el denominador para mostrar 'X de Y ya lo leyeron'."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM usuarios WHERE COALESCE(estado, 'activo') = 'activo'")
        total = cursor.fetchone()[0]
        conn.close()
        return total or 0
    except Exception:
        return 0


# ⏳ Cuántas horas después de publicado se envía (una sola vez) el recordatorio automático de
# lectura pendiente a quien todavía no haya leído un comunicado activo.
HORAS_RECORDATORIO_LECTURA_COMUNICADO = 48


def _detalle_cumplimiento_comunicados():
    """Para cada comunicado activo (no archivado ni eliminado), cuántos usuarios activos ya lo
    leyeron y cuáles faltan — la base tanto del panel de Cumplimiento como de los recordatorios
    automáticos/manuales. Devuelve una lista ordenada del más reciente al más antiguo."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, titulo, nivel, fecha, autor, recordatorio_enviado_fecha FROM comunicados WHERE estado = 'activo' ORDER BY id DESC")
        comunicados_rows = cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Error listando comunicados para cumplimiento: {e}")
        conn.close()
        return []

    try:
        cursor.execute("SELECT usuario, COALESCE(nombre, usuario), correo FROM usuarios WHERE COALESCE(estado, 'activo') = 'activo'")
        activos = [{'usuario': r[0], 'nombre': r[1], 'correo': r[2]} for r in cursor.fetchall()]
    except Exception as e:
        print(f"⚠️ Error listando usuarios activos para cumplimiento: {e}")
        activos = []

    leidos_por_comunicado = {}
    try:
        ids = [r[0] for r in comunicados_rows]
        if ids:
            placeholders = ','.join(['%s' if db_type == 'postgres' else '?'] * len(ids))
            cursor.execute(f"SELECT comunicado_id, usuario FROM comunicados_leidos WHERE comunicado_id IN ({placeholders})", tuple(ids))
            for com_id, usuario in cursor.fetchall():
                leidos_por_comunicado.setdefault(com_id, set()).add(usuario)
    except Exception as e:
        print(f"⚠️ Error listando lecturas para cumplimiento: {e}")

    conn.close()

    total_activos = len(activos)
    resultado = []
    for com_id, titulo, nivel, fecha, autor, recordatorio_fecha in comunicados_rows:
        leidos_usuarios = leidos_por_comunicado.get(com_id, set())
        faltan = [u for u in activos if u['usuario'] not in leidos_usuarios]
        resultado.append({
            'id': com_id, 'titulo': titulo, 'nivel': nivel, 'fecha': fecha, 'autor': autor,
            'recordatorio_enviado_fecha': recordatorio_fecha,
            'leidos': len(leidos_usuarios), 'total': total_activos,
            'porcentaje': round((len(leidos_usuarios) / total_activos) * 100) if total_activos else 100,
            'faltan': faltan
        })
    return resultado


def _enviar_recordatorio_lectura(comunicado, marcar_enviado=True):
    """Notifica (campanita + correo) a cada usuario en comunicado['faltan'] que le falta leer
    ese comunicado, y opcionalmente marca recordatorio_enviado_fecha para que el chequeo
    automático no lo vuelva a enviar. Nunca debe tumbar la página que lo llama."""
    if not comunicado.get('faltan'):
        return 0
    try:
        url_comunicado = url_for('ver_comunicados')
        mensaje = f"📢 Te falta leer el comunicado '{comunicado['titulo']}'"
        asunto = f"[Arkiv] Recordatorio: te falta leer '{comunicado['titulo']}'"
        cuerpo = (
            f"Hola,\n\nTe falta leer el comunicado '{comunicado['titulo']}' publicado en el muro de "
            f"Novedades y Comunicados de Arkiv.\n\nIngresa a Arkiv para revisarlo.\n\n---\nArkiv"
        )
        for u in comunicado['faltan']:
            crear_notificacion(u['usuario'], mensaje, url=url_comunicado, tipo='comunicado')
            if u.get('correo'):
                threading.Thread(target=enviar_correo_ticket, args=(u['correo'], asunto, cuerpo)).start()

        if marcar_enviado:
            fecha_act = obtener_fecha_actual()
            conn, db_type = get_db()
            cursor = conn.cursor()
            q = "UPDATE comunicados SET recordatorio_enviado_fecha = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET recordatorio_enviado_fecha = ? WHERE id = ?"
            cursor.execute(q, (fecha_act, comunicado['id']))
            conn.commit()
            conn.close()
        return len(comunicado['faltan'])
    except Exception as e:
        print(f"⚠️ Error enviando recordatorio de lectura del comunicado {comunicado.get('id')}: {e}")
        return 0


def _revisar_recordatorios_lectura():
    """Recordatorio automático (una sola vez por comunicado): si pasaron más de
    HORAS_RECORDATORIO_LECTURA_COMUNICADO horas desde que se publicó un comunicado activo y
    todavía faltan usuarios por leerlo, se les avisa por campanita/correo. Se llama de forma
    perezosa (sin scheduler externo, ver _revisar_alertas_sla para el mismo patrón en Tickets)
    cada vez que el equipo de soporte visita el muro de Comunicados o el panel de Cumplimiento —
    nunca debe tumbar esa página si algo falla."""
    try:
        ahora = datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)
        for c in _detalle_cumplimiento_comunicados():
            if c['recordatorio_enviado_fecha']:
                continue  # ya se envió (automático o manual) — no repetir
            fecha_pub = _parsear_fecha_ticket(c['fecha'])  # mismo formato 'YYYY-MM-DD HH:MM:SS'
            if not fecha_pub or (ahora - fecha_pub).total_seconds() < HORAS_RECORDATORIO_LECTURA_COMUNICADO * 3600:
                continue
            if not c['faltan']:
                continue
            _enviar_recordatorio_lectura(c)
    except Exception as e:
        print(f"⚠️ Error revisando recordatorios de lectura de comunicados: {e}")


# 📝 Editor de texto enriquecido (Quill): negrilla, cursiva, subrayado, resaltado de color y
# listas en la descripción de tickets, sus comentarios/respuestas, y el contenido de los
# Comunicados. Quill entrega HTML (p. ej. "<p><strong>hola</strong> <span style=\"background-
# color: rgb(255,255,0)\">urgente</span></p>"), así que ese HTML se limpia ANTES de guardarlo
# — nunca se confía en lo que llega del navegador — permitiendo solo un puñado de etiquetas y
# el estilo de color/resaltado, y quitando cualquier <script>, atributo onerror/onclick, o
# link javascript: que alguien intente colar.
_QUILL_TAGS_PERMITIDAS = ['p', 'br', 'strong', 'em', 'u', 's', 'span', 'ol', 'ul', 'li']
_QUILL_ATRIBUTOS_PERMITIDOS = {'span': ['style'], 'li': ['data-list']}
_QUILL_CSS_PERMITIDO = ['background-color', 'color']

if bleach and CSSSanitizer:
    _sanitizador_css = CSSSanitizer(allowed_css_properties=_QUILL_CSS_PERMITIDO)
else:
    _sanitizador_css = None


def _sanitizar_html_enriquecido(html_bruto):
    """Limpia el HTML que llega del editor de texto enriquecido antes de guardarlo. Si
    'bleach' no está disponible por alguna razón, se cae a texto plano (se escapan todas las
    etiquetas) — nunca se guarda HTML sin filtrar en la base de datos."""
    if not html_bruto:
        return html_bruto
    if not bleach:
        from markupsafe import escape
        return str(escape(html_bruto))
    return bleach.clean(
        html_bruto, tags=_QUILL_TAGS_PERMITIDAS, attributes=_QUILL_ATRIBUTOS_PERMITIDOS,
        css_sanitizer=_sanitizador_css, strip=True
    )


def _html_esta_vacio(html):
    """El editor de texto enriquecido (Quill) manda '<p><br></p>' cuando el usuario no
    escribió nada — sigue siendo una cadena "verdadera" en Python, así que una validación
    tipo `if contenido:` no detecta que en realidad está vacío. Esta función sí lo detecta,
    quitando TODAS las etiquetas y mirando si queda algo de texto real."""
    if not html:
        return True
    if bleach:
        texto_plano = bleach.clean(html, tags=[], attributes={}, strip=True)
    else:
        texto_plano = re.sub(r'<[^>]+>', '', html)
    return not texto_plano.strip()


def _mapa_nombres_usuarios():
    """Devuelve {usuario: nombre_para_mostrar} de TODOS los usuarios (activos o no), para
    resolver en bloque el alias/nombre real de quien publicó algo (comunicados, tickets, etc.)
    en vez de mostrar la cuenta de inicio de sesión cruda. Si un usuario no tiene 'nombre'
    guardado, o la cuenta ya no existe, se usa su propio usuario como respaldo — nunca deja el
    campo vacío."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT usuario, nombre FROM usuarios")
        mapa = {u[0]: (u[1] or u[0]) for u in cursor.fetchall()}
        conn.close()
        return mapa
    except Exception as e:
        print(f"⚠️ Error cargando el mapa de nombres de usuarios: {e}")
        return {}


def _nombre_para_mostrar(username, mapa_nombres):
    """Alias legible de 'username' según 'mapa_nombres' (ver _mapa_nombres_usuarios) — si no
    aparece ahí, se muestra el mismo username tal cual, para no dejar el campo vacío."""
    if not username:
        return username
    return mapa_nombres.get(username, username)


# 📞 Código de país por defecto para los números de contacto: la organización opera en
# Colombia y casi todos los teléfonos se guardan en formato local (10 dígitos, sin +57).
CODIGO_PAIS_WHATSAPP_DEFAULT = '57'


def _normalizar_telefono_whatsapp(telefono):
    """Convierte un teléfono guardado en cualquier formato local (con espacios, guiones,
    paréntesis, con o sin +57) al formato que exige wa.me: solo dígitos, con código de país.
    Devuelve None si no queda un número razonable (muy corto) para evitar generar un enlace
    de WhatsApp roto."""
    if not telefono:
        return None
    solo_digitos = re.sub(r'\D', '', telefono)
    if not solo_digitos:
        return None
    # Un celular colombiano local tiene 10 dígitos (empieza en 3) y no trae el código de país
    # todavía — se lo anteponemos. Si ya viene con el 57 delante (12 dígitos) se deja tal cual.
    if len(solo_digitos) == 10:
        solo_digitos = CODIGO_PAIS_WHATSAPP_DEFAULT + solo_digitos
    if len(solo_digitos) < 10:
        return None
    return solo_digitos


def _link_whatsapp_ticket(ticket, creador_info, nombre_agente):
    """Arma el enlace 'click to chat' de WhatsApp (wa.me) para contactar al solicitante de un
    ticket, con un mensaje ya redactado que el agente puede revisar y enviar desde WhatsApp
    Web/Desktop — Arkiv no manda el mensaje por sí solo, solo deja el borrador listo.

    El botón siempre se genera (para que el agente lo tenga disponible en todos los tickets,
    igual que en la referencia): si hay un teléfono de contacto válido, el chat se abre
    directamente con el solicitante; si no hay ninguno registrado, se arma el enlace sin
    número (wa.me/?text=...), que abre WhatsApp Web/Desktop con el mensaje ya redactado para
    que el agente elija el contacto manualmente."""
    telefono = _normalizar_telefono_whatsapp(ticket.get('telefono_contacto'))
    nombre_solicitante = (creador_info or {}).get('nombre') or ticket.get('creado_por') or 'usuario'
    # El mensaje nombra el tipo real del ticket (incidente/requerimiento) en vez de un genérico
    # "solicitud", igual a como lo redacta la referencia (Solvyx) con su "tu solicitud RQ-...").
    tipo_ticket = (ticket.get('tipo') or '').strip().lower()
    if tipo_ticket not in ('incidente', 'requerimiento'):
        tipo_ticket = 'solicitud'
    mensaje = (
        f"Hola {nombre_solicitante}, soy {nombre_agente} de Preventiva Salud SAS. "
        f"Te escribo respecto a tu {tipo_ticket} {ticket.get('codigo')} sobre \"{ticket.get('titulo')}\". "
        f"Estoy revisando el caso y quería coordinar contigo para resolverlo lo antes posible. "
        f"¿Cuándo te queda bien que conversemos?"
    )
    texto = urllib.parse.quote(mensaje)
    if telefono:
        return f"https://wa.me/{telefono}?text={texto}"
    return f"https://wa.me/?text={texto}"


# 🗓️ Motivos preestablecidos para justificar un corrimiento de la fecha límite de solución.
# Se muestran como opciones en el modal "Modificar fecha" del detalle del ticket, para que el
# equipo de soporte deje registrado explícitamente si el atraso depende de un tercero (proveedor,
# garantía, importación, etc.) y no necesariamente del analista o agente asignado.
MOTIVOS_MODIFICACION_SLA = [
    'Depende de un proveedor o tercero externo',
    'Se requiere repuesto, licencia o material no disponible',
    'Complejidad técnica mayor a la esperada',
    'El usuario solicitó reprogramar',
    'Otro',
]


def _codigo_ticket(tipo, id_ticket, fecha_creacion):
    """Código legible tipo 'IN-2026-000042' / 'RQ-2026-000042', solo para mostrar en la interfaz."""
    prefijo = 'RQ' if tipo == 'Requerimiento' else 'IN'
    anio = (fecha_creacion or '')[:4]
    if not anio.isdigit():
        anio = str(datetime.now().year)
    return f"{prefijo}-{anio}-{str(id_ticket).zfill(6)}"


def _subir_adjuntos_ticket(files):
    """Sube hasta MAX_ADJUNTOS_TICKET archivos (evidencias: fotos, capturas, PDFs, documentos)
    a Cloudinary y devuelve una lista de (url, nombre_original). Un archivo con extensión no
    permitida, o que falle al subir, simplemente se descarta: nunca debe tumbar la creación
    del ticket/comentario que lo acompaña."""
    subidos = []
    for file in (files or [])[:MAX_ADJUNTOS_TICKET]:
        if not file or not file.filename or not archivo_permitido(file.filename):
            continue
        try:
            ext = file.filename.rsplit('.', 1)[1].lower()
            if ext == 'pdf':
                upload_result = cloudinary.uploader.upload(
                    file, resource_type="image", format="pdf",
                    use_filename=True, unique_filename=True, timeout=60
                )
            elif ext in ['mp4', 'mov', 'webm', 'avi']:
                upload_result = cloudinary.uploader.upload(
                    file, resource_type="video",
                    use_filename=True, unique_filename=True, timeout=120
                )
            elif ext in ['zip', 'rar', '7z', 'tar', 'gz', 'txt', 'docx', 'xlsx', 'pptx']:
                upload_result = cloudinary.uploader.upload(
                    file, resource_type="raw",
                    use_filename=True, unique_filename=True, timeout=60
                )
            else:
                upload_result = cloudinary.uploader.upload(
                    file, resource_type="image",
                    use_filename=True, unique_filename=True, timeout=60
                )
            subidos.append((upload_result['secure_url'], file.filename))
        except Exception as e:
            print(f"⚠️ Error subiendo adjunto de ticket '{file.filename}': {e}")
    return subidos


def _guardar_adjuntos_ticket(cursor, db_type, ticket_id, comentario_id, subidos, usuario, fecha):
    q = "INSERT INTO tickets_adjuntos (ticket_id, comentario_id, url, nombre_original, subido_por, fecha) VALUES (%s, %s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO tickets_adjuntos (ticket_id, comentario_id, url, nombre_original, subido_por, fecha) VALUES (?, ?, ?, ?, ?, ?)"
    for url, nombre in subidos:
        cursor.execute(q, (ticket_id, comentario_id, url, nombre, usuario, fecha))


def _guardar_adjuntos_inventario(cursor, db_type, activo_id, subidos, usuario, fecha):
    """Guarda en 'inventario_adjuntos' los archivos ya subidos a Cloudinary (mismo patrón que
    los adjuntos de tickets) para un activo del Inventario."""
    q = "INSERT INTO inventario_adjuntos (activo_id, url, nombre_original, subido_por, fecha) VALUES (%s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO inventario_adjuntos (activo_id, url, nombre_original, subido_por, fecha) VALUES (?, ?, ?, ?, ?)"
    for url, nombre in subidos:
        cursor.execute(q, (activo_id, url, nombre, usuario, fecha))


@app.route('/tickets')
@login_required
def ver_tickets():
    q_estado = request.args.get('estado', '').strip()
    q_prioridad = request.args.get('prioridad', '').strip()
    q_categoria = request.args.get('categoria', '').strip()
    q_tipo = request.args.get('tipo', '').strip()
    q_area = request.args.get('area', '').strip()
    q_sede = request.args.get('sede', '').strip()
    q_busqueda = request.args.get('q', '').strip().lower()
    q_cumplimiento = request.args.get('cumplimiento', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()

    es_soporte = (session.get('rol') in ROLES_CON_ACCESO_OPERATIVO)
    if es_soporte:
        # 🔔 Aviso perezoso de SLA por vencer/vencido — ver _revisar_alertas_sla(). Solo tiene
        # sentido correrlo cuando quien mira la lista es del equipo de soporte.
        _revisar_alertas_sla()

    categorias_config = _config_ticket_lista('categoria')
    areas_config = _config_ticket_lista('area')
    sedes_config = _config_ticket_lista('sede')
    nombres_categorias = [c['nombre'] for c in categorias_config] or CATEGORIAS_TICKET
    nombres_areas = [a['nombre'] for a in areas_config]
    nombres_sedes = [s['nombre'] for s in sedes_config]

    query = "SELECT id, titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, sla_resolucion_limite, sla_resolucion_cumplida, area, sede FROM tickets WHERE 1=1"
    params = []

    if not es_soporte:
        # Un usuario estándar solo ve las solicitudes que él mismo creó.
        query += " AND creado_por = %s" if db_type == 'postgres' else " AND creado_por = ?"
        params.append(session.get('username'))

    if q_estado in ESTADOS_TICKET:
        query += " AND estado = %s" if db_type == 'postgres' else " AND estado = ?"
        params.append(q_estado)
    if q_prioridad in PRIORIDADES_TICKET:
        query += " AND prioridad = %s" if db_type == 'postgres' else " AND prioridad = ?"
        params.append(q_prioridad)
    if q_categoria in nombres_categorias:
        query += " AND categoria = %s" if db_type == 'postgres' else " AND categoria = ?"
        params.append(q_categoria)
    if q_tipo in TIPOS_TICKET:
        query += " AND tipo = %s" if db_type == 'postgres' else " AND tipo = ?"
        params.append(q_tipo)
    if q_area in nombres_areas:
        query += " AND area = %s" if db_type == 'postgres' else " AND area = ?"
        params.append(q_area)
    if q_sede in nombres_sedes:
        query += " AND sede = %s" if db_type == 'postgres' else " AND sede = ?"
        params.append(q_sede)

    query += " ORDER BY (estado = 'Cerrado'), (estado = 'Resuelto'), id DESC"

    try:
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando tickets: {e}")
        rows = []

    # 👤 Nombre completo por usuario (para mostrar "Creado por"/"Asignado a" en la tabla con
    # el nombre real de la persona en lugar de su usuario de inicio de sesión, un alias poco
    # reconocible como 'escobar' o 'tmira').
    cursor.execute("SELECT usuario, nombre FROM usuarios")
    nombres_usuarios = {u[0]: (u[1] or u[0]) for u in cursor.fetchall()}
    conn.close()

    tickets = []
    for r in rows:
        texto_full = f"{r[1]} {r[2]} {r[7]}".lower()
        if not q_busqueda or q_busqueda in texto_full:
            tipo_t = r[3] or 'Incidente'
            t = {
                'id': r[0], 'titulo': r[1], 'descripcion': r[2], 'tipo': tipo_t, 'categoria': r[4],
                'prioridad': r[5], 'estado': r[6], 'creado_por': r[7], 'asignado_a': r[8],
                'creado_por_nombre': nombres_usuarios.get(r[7], r[7]),
                'asignado_a_nombre': nombres_usuarios.get(r[8], r[8]) if r[8] else None,
                'fecha_creacion': r[9], 'fecha_actualizacion': r[10],
                'codigo': _codigo_ticket(tipo_t, r[0], r[9]),
                'sla_resolucion_limite': r[11], 'sla_resolucion_cumplida': r[12],
                'area': r[13], 'sede': r[14]
            }
            t['sla'] = _calcular_sla_ticket(t)
            t['cumplimiento'] = _bucket_cumplimiento_ticket(t)
            t['progreso'] = _progreso_ticket(t)
            tickets.append(t)

    # Conteos para las pestañas de cumplimiento de SLA (Vigentes/Próximos a vencer/Vencidos/
    # Cerrados), calculados ANTES de aplicar el filtro de pestaña, para que cada pestaña
    # muestre cuántos tickets hay en las demás sin perder los otros filtros ya aplicados.
    conteos_cumplimiento = {'vigente': 0, 'proximo_a_vencer': 0, 'vencido': 0, 'cerrado': 0}
    for t in tickets:
        conteos_cumplimiento[t['cumplimiento']] = conteos_cumplimiento.get(t['cumplimiento'], 0) + 1
    total_tickets = len(tickets)

    if q_cumplimiento in conteos_cumplimiento:
        tickets = [t for t in tickets if t['cumplimiento'] == q_cumplimiento]

    # 📞 Prellena el número de contacto de "Nueva Solicitud" con el que el usuario ya tiene
    # registrado en su perfil (si tiene uno) — sigue siendo editable en el formulario, por si
    # para este ticket en particular hay que dejar otro número (p. ej. de un tercero).
    perfil_actual = _info_usuario(session.get('username'))
    telefono_usuario_actual = perfil_actual['telefono'] if perfil_actual else None

    return render_template(
        'tickets.html', tickets=tickets, es_soporte=es_soporte,
        categorias=nombres_categorias, prioridades=PRIORIDADES_TICKET, estados=ESTADOS_TICKET,
        tipos=TIPOS_TICKET, tipos_info=TIPOS_TICKET_INFO,
        areas=nombres_areas, sedes=nombres_sedes,
        q_estado=q_estado, q_prioridad=q_prioridad, q_categoria=q_categoria, q_tipo=q_tipo, q_busqueda=q_busqueda,
        q_area=q_area, q_sede=q_sede,
        q_cumplimiento=q_cumplimiento, conteos_cumplimiento=conteos_cumplimiento, total_tickets=total_tickets,
        telefono_usuario_actual=telefono_usuario_actual
    )


@app.route('/tickets/crear', methods=['POST'])
@login_required
def crear_ticket():
    titulo = request.form.get('titulo', '').strip()
    # 📝 La descripción llega como HTML del editor de texto enriquecido (Quill) — se limpia
    # ANTES de guardarla, para no confiar en lo que manda el navegador.
    descripcion = _sanitizar_html_enriquecido(request.form.get('descripcion', '').strip())
    tipo = request.form.get('tipo', 'Incidente').strip()
    categoria = request.form.get('categoria', 'Otro').strip()
    prioridad = request.form.get('prioridad', 'Media').strip()
    area = request.form.get('area', '').strip()
    sede = request.form.get('sede', '').strip()
    telefono_contacto = request.form.get('telefono_contacto', '').strip() or None

    nombres_categorias = [c['nombre'] for c in _config_ticket_lista('categoria')] or CATEGORIAS_TICKET
    nombres_areas = [a['nombre'] for a in _config_ticket_lista('area')]
    nombres_sedes = [s['nombre'] for s in _config_ticket_lista('sede')]

    if tipo not in TIPOS_TICKET:
        tipo = 'Incidente'
    if categoria not in nombres_categorias:
        categoria = 'Otro'
    if prioridad not in PRIORIDADES_TICKET:
        prioridad = 'Media'
    # Área y Sede son opcionales: si el valor enviado no corresponde a una configuración
    # activa (o el equipo de soporte todavía no ha configurado ninguna), se guarda vacío.
    area = area if area in nombres_areas else None
    sede = sede if sede in nombres_sedes else None

    if titulo and descripcion and not _html_esta_vacio(descripcion):
        fecha_act = obtener_fecha_actual()
        usuario = session.get('username')
        archivos_subidos = _subir_adjuntos_ticket(request.files.getlist('adjuntos'))

        horas_sla = SLA_HORAS_POR_PRIORIDAD.get(prioridad, SLA_HORAS_POR_PRIORIDAD['Media'])
        sla_respuesta_limite = _calcular_limite_sla(fecha_act, horas_sla['respuesta'])
        sla_resolucion_limite = _calcular_limite_sla(fecha_act, horas_sla['resolucion'])

        # 🤖 Asignación automática: si el equipo de soporte configuró un responsable para
        # esta categoría (o, si no hay, para el área) en /tickets/configuracion, el ticket
        # nace ya asignado a esa persona en vez de quedar "Sin asignar" hasta que alguien lo
        # tome manualmente. Prioridad: categoría primero, área como respaldo.
        asignado_auto = None
        for cfg in _config_ticket_lista('categoria'):
            if cfg['nombre'] == categoria and cfg.get('responsable'):
                asignado_auto = cfg['responsable']
                break
        if not asignado_auto and area:
            for cfg in _config_ticket_lista('area'):
                if cfg['nombre'] == area and cfg.get('responsable'):
                    asignado_auto = cfg['responsable']
                    break

        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            if db_type == 'postgres':
                q_ins = "INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, sla_respuesta_limite, sla_resolucion_limite, sla_modificaciones, area, sede, telefono_contacto) VALUES (%s, %s, %s, %s, %s, 'Abierto', %s, %s, %s, %s, %s, %s, 0, %s, %s, %s) RETURNING id"
                cursor.execute(q_ins, (titulo, descripcion, tipo, categoria, prioridad, usuario, asignado_auto, fecha_act, fecha_act, sla_respuesta_limite, sla_resolucion_limite, area, sede, telefono_contacto))
                nuevo_id = cursor.fetchone()[0]
            else:
                q_ins = "INSERT INTO tickets (titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, sla_respuesta_limite, sla_resolucion_limite, sla_modificaciones, area, sede, telefono_contacto) VALUES (?, ?, ?, ?, ?, 'Abierto', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)"
                cursor.execute(q_ins, (titulo, descripcion, tipo, categoria, prioridad, usuario, asignado_auto, fecha_act, fecha_act, sla_respuesta_limite, sla_resolucion_limite, area, sede, telefono_contacto))
                nuevo_id = cursor.lastrowid

            if archivos_subidos:
                _guardar_adjuntos_ticket(cursor, db_type, nuevo_id, None, archivos_subidos, usuario, fecha_act)

            conn.commit()
            detalle_log = f"Nuevo ticket [{tipo}]: '{titulo}' [{categoria} / {prioridad}]"
            if archivos_subidos:
                detalle_log += f" — {len(archivos_subidos)} adjunto(s)"
            if asignado_auto:
                detalle_log += f" — auto-asignado a {asignado_auto}"
            registrar_log(usuario, "Solicitud de Soporte Creada", detalle_log)

            # 📧🔔 Avisamos de la solicitud nueva: confirmación al que la creó, y aviso a quien
            # deba atenderla — si quedó auto-asignada a alguien puntual (arriba), solo a esa
            # persona recibe el correo/notificación (para no saturar a todo el equipo con algo
            # que ya tiene dueño); si no quedó asignada, se avisa a todo el equipo de soporte
            # activo (admins + agentes), igual que pidió Tomas.
            codigo = _codigo_ticket(tipo, nuevo_id, fecha_act)
            url_ticket = url_for('ver_ticket', ticket_id=nuevo_id)

            correo_creador = _correo_de_usuario(usuario)
            if correo_creador:
                asunto_creador = f"[Arkiv] Recibimos tu solicitud {codigo}"
                cuerpo_creador = (
                    f"Hola,\n\nRecibimos tu solicitud de soporte {codigo} ('{titulo}').\n\n"
                    f"Puedes ver el detalle y su avance ingresando a Arkiv, módulo Solicitudes TI.\n\n"
                    f"---\nEquipo de Soporte TI - Arkiv"
                )
                threading.Thread(target=enviar_correo_ticket, args=(correo_creador, asunto_creador, cuerpo_creador)).start()

            asunto_soporte = f"[Arkiv] Nueva solicitud {codigo}: '{titulo}'"
            cuerpo_soporte = (
                f"Se creó una nueva solicitud de soporte {codigo} ('{titulo}') — {categoria} / prioridad {prioridad}.\n"
                f"Creada por: {usuario}.\n\nPuedes verla ingresando a Arkiv, módulo Solicitudes TI.\n\n---\nArkiv"
            )
            if asignado_auto:
                correo_asignado = _correo_de_usuario(asignado_auto)
                if correo_asignado:
                    threading.Thread(target=enviar_correo_ticket, args=(correo_asignado, asunto_soporte, cuerpo_soporte)).start()
                crear_notificacion(asignado_auto, f"Nueva solicitud {codigo} asignada a ti: '{titulo}'", url=url_ticket)
            else:
                equipo = _equipo_soporte_activo()
                for miembro in equipo:
                    if miembro['correo']:
                        threading.Thread(target=enviar_correo_ticket, args=(miembro['correo'], asunto_soporte, cuerpo_soporte)).start()
                crear_notificacion_para_varios([m['usuario'] for m in equipo], f"Nueva solicitud {codigo}: '{titulo}'", url=url_ticket)
        except Exception as e:
            conn.rollback()
            print(f"Error creando ticket: {e}")
        conn.close()

    return redirect(url_for('ver_tickets'))


@app.route('/tickets/<int:ticket_id>')
@login_required
def ver_ticket(ticket_id):
    conn, db_type = get_db()
    cursor = conn.cursor()

    q_sel = "SELECT id, titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, sla_respuesta_limite, sla_resolucion_limite, sla_respuesta_cumplida, sla_resolucion_cumplida, sla_modificaciones, calificacion, calificacion_fecha, area, sede, telefono_contacto FROM tickets WHERE id = %s" if db_type == 'postgres' else "SELECT id, titulo, descripcion, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, sla_respuesta_limite, sla_resolucion_limite, sla_respuesta_cumplida, sla_resolucion_cumplida, sla_modificaciones, calificacion, calificacion_fecha, area, sede, telefono_contacto FROM tickets WHERE id = ?"
    cursor.execute(q_sel, (ticket_id,))
    row = cursor.fetchone()

    if not row or not _puede_ver_ticket(row[7]):
        conn.close()
        return redirect(url_for('ver_tickets'))

    es_soporte = (session.get('rol') in ROLES_CON_ACCESO_OPERATIVO)
    tipo_t = row[3] or 'Incidente'

    ticket = {
        'id': row[0], 'titulo': row[1], 'descripcion': row[2], 'tipo': tipo_t, 'categoria': row[4],
        'prioridad': row[5], 'estado': row[6], 'creado_por': row[7], 'asignado_a': row[8],
        'fecha_creacion': row[9], 'fecha_actualizacion': row[10],
        'codigo': _codigo_ticket(tipo_t, row[0], row[9]),
        'sla_respuesta_limite': row[11], 'sla_resolucion_limite': row[12],
        'sla_respuesta_cumplida': row[13], 'sla_resolucion_cumplida': row[14],
        'sla_modificaciones': row[15] or 0,
        'calificacion': row[16], 'calificacion_fecha': row[17],
        'area': row[18], 'sede': row[19], 'telefono_contacto': row[20]
    }
    ticket['sla'] = _calcular_sla_ticket(ticket)

    # 🧑 La mayor cantidad de información posible sobre quién levantó la solicitud: nombre
    # completo, correo y teléfono registrados en su perfil de Arkiv (si los tiene). Si el
    # ticket no trae un teléfono de contacto propio, se usa el del perfil como respaldo.
    creador_info = _info_usuario(ticket['creado_por']) or {}
    if not ticket['telefono_contacto']:
        ticket['telefono_contacto'] = creador_info.get('telefono')

    # 👤 El nombre completo del agente asignado (no su usuario de inicio de sesión) se usa
    # para mostrar "Asignado a" de forma legible, igual que en el desplegable de arriba.
    if ticket['asignado_a']:
        info_asignado = _info_usuario(ticket['asignado_a'])
        ticket['asignado_a_nombre'] = (info_asignado or {}).get('nombre') or ticket['asignado_a']
    else:
        ticket['asignado_a_nombre'] = None

    # Adjuntos cargados junto con la solicitud original (no pertenecen a ningún comentario).
    q_adj_ticket = "SELECT url, nombre_original FROM tickets_adjuntos WHERE ticket_id = %s AND comentario_id IS NULL ORDER BY id ASC" if db_type == 'postgres' else "SELECT url, nombre_original FROM tickets_adjuntos WHERE ticket_id = ? AND comentario_id IS NULL ORDER BY id ASC"
    cursor.execute(q_adj_ticket, (ticket_id,))
    ticket['adjuntos'] = [{'url': a[0], 'nombre_original': a[1]} for a in cursor.fetchall()]

    if es_soporte:
        q_com = "SELECT id, autor, mensaje, tipo, fecha FROM tickets_comentarios WHERE ticket_id = %s ORDER BY id ASC" if db_type == 'postgres' else "SELECT id, autor, mensaje, tipo, fecha FROM tickets_comentarios WHERE ticket_id = ? ORDER BY id ASC"
    else:
        # Un usuario estándar no debe ver las notas internas que el equipo de soporte deja
        # únicamente para coordinarse entre ellos.
        q_com = "SELECT id, autor, mensaje, tipo, fecha FROM tickets_comentarios WHERE ticket_id = %s AND tipo != 'interno' ORDER BY id ASC" if db_type == 'postgres' else "SELECT id, autor, mensaje, tipo, fecha FROM tickets_comentarios WHERE ticket_id = ? AND tipo != 'interno' ORDER BY id ASC"
    cursor.execute(q_com, (ticket_id,))
    comentarios = [{'id': c[0], 'autor': c[1], 'mensaje': c[2], 'tipo': c[3], 'fecha': c[4], 'adjuntos': []} for c in cursor.fetchall()]

    ids_com = [c['id'] for c in comentarios]
    if ids_com:
        placeholder = '%s' if db_type == 'postgres' else '?'
        placeholders = ','.join([placeholder] * len(ids_com))
        q_adj_com = f"SELECT comentario_id, url, nombre_original FROM tickets_adjuntos WHERE comentario_id IN ({placeholders}) ORDER BY id ASC"
        cursor.execute(q_adj_com, tuple(ids_com))
        adjuntos_por_com = {}
        for com_id, url, nombre in cursor.fetchall():
            adjuntos_por_com.setdefault(com_id, []).append({'url': url, 'nombre_original': nombre})
        for c in comentarios:
            c['adjuntos'] = adjuntos_por_com.get(c['id'], [])

    agentes = []
    if es_soporte:
        # 👤 Se muestra el nombre completo de cada agente/admin en el desplegable "Asignar a"
        # (no el usuario de inicio de sesión, que suele ser un alias técnico poco reconocible).
        q_ag = "SELECT usuario, nombre FROM usuarios WHERE rol IN ('admin', 'agente') AND COALESCE(estado, 'activo') = 'activo' ORDER BY usuario ASC"
        cursor.execute(q_ag)
        agentes = [{'usuario': a[0], 'nombre': a[1] or a[0]} for a in cursor.fetchall()]

    conn.close()

    # 💬 Enlace "click to chat" de WhatsApp para contactar al solicitante desde el detalle del
    # ticket (solo el equipo de soporte lo ve — es una herramienta de gestión, no algo que el
    # propio solicitante necesite). Arkiv NO envía el mensaje: solo abre WhatsApp Web/Desktop
    # con un borrador ya redactado, el agente decide si lo edita y lo envía.
    whatsapp_url = None
    whatsapp_tiene_numero = False
    if es_soporte:
        perfil_agente = _info_usuario(session.get('username'))
        nombre_agente = (perfil_agente or {}).get('nombre') or session.get('username') or 'Soporte TI'
        whatsapp_url = _link_whatsapp_ticket(ticket, creador_info, nombre_agente)
        whatsapp_tiene_numero = bool(_normalizar_telefono_whatsapp(ticket.get('telefono_contacto')))

    return render_template(
        'ticket_detalle.html', ticket=ticket, comentarios=comentarios,
        es_soporte=es_soporte, agentes=agentes, creador_info=creador_info,
        estados=ESTADOS_TICKET, prioridades=PRIORIDADES_TICKET,
        whatsapp_tiene_numero=whatsapp_tiene_numero,
        max_modificaciones_sla=MAX_MODIFICACIONES_SLA, motivos_sla=MOTIVOS_MODIFICACION_SLA,
        calificacion_max=CALIFICACION_MAX, session_username=session.get('username'),
        whatsapp_url=whatsapp_url
    )


@app.route('/tickets/<int:ticket_id>/comentar', methods=['POST'])
@login_required
def comentar_ticket(ticket_id):
    # 📝 El mensaje llega como HTML del editor de texto enriquecido (Quill) — se limpia ANTES
    # de guardarlo, para no confiar en lo que manda el navegador.
    mensaje = _sanitizar_html_enriquecido(request.form.get('mensaje', '').strip())
    if _html_esta_vacio(mensaje):
        mensaje = ''
    es_admin = (session.get('rol') in ROLES_CON_ACCESO_OPERATIVO)
    es_interno = es_admin and request.form.get('interno') == 'on'

    conn, db_type = get_db()
    cursor = conn.cursor()
    q_sel = "SELECT creado_por, estado, titulo, tipo, fecha_creacion, asignado_a FROM tickets WHERE id = %s" if db_type == 'postgres' else "SELECT creado_por, estado, titulo, tipo, fecha_creacion, asignado_a FROM tickets WHERE id = ?"
    cursor.execute(q_sel, (ticket_id,))
    row = cursor.fetchone()

    if not row or not _puede_ver_ticket(row[0]):
        conn.close()
        return redirect(url_for('ver_tickets'))
    creado_por, estado_actual, titulo_ticket, tipo_ticket, fecha_creacion_ticket, asignado_actual = row

    # Un ticket cerrado ya no admite comentarios de quien lo creó (solo soporte TI podría
    # necesitar dejar una nota adicional sobre uno ya cerrado).
    if estado_actual == 'Cerrado' and not es_admin:
        conn.close()
        return redirect(url_for('ver_ticket', ticket_id=ticket_id))

    archivos_subidos = _subir_adjuntos_ticket(request.files.getlist('adjuntos'))

    if mensaje or archivos_subidos:
        fecha_act = obtener_fecha_actual()
        usuario = session.get('username')
        tipo_comentario = 'interno' if es_interno else 'comentario'
        mensaje_final = mensaje or "(adjuntó archivo(s) sin comentario)"
        try:
            if db_type == 'postgres':
                q_ins = "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (%s, %s, %s, %s, %s) RETURNING id"
                cursor.execute(q_ins, (ticket_id, usuario, mensaje_final, tipo_comentario, fecha_act))
                nuevo_com_id = cursor.fetchone()[0]
            else:
                q_ins = "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (?, ?, ?, ?, ?)"
                cursor.execute(q_ins, (ticket_id, usuario, mensaje_final, tipo_comentario, fecha_act))
                nuevo_com_id = cursor.lastrowid

            if archivos_subidos:
                _guardar_adjuntos_ticket(cursor, db_type, ticket_id, nuevo_com_id, archivos_subidos, usuario, fecha_act)

            q_upd = "UPDATE tickets SET fecha_actualizacion = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE tickets SET fecha_actualizacion = ? WHERE id = ?"
            cursor.execute(q_upd, (fecha_act, ticket_id))
            conn.commit()
            etiqueta = "Comentario interno" if es_interno else "Comentario"
            registrar_log(usuario, "Comentario en Ticket", f"{etiqueta} agregado al ticket #{ticket_id}" + (f" ({len(archivos_subidos)} adjunto(s))" if archivos_subidos else ""))

            # 📧🔔 Avisamos al solicitante cuando alguien más (típicamente soporte TI) responde
            # su ticket. Las notas internas nunca generan este aviso: son solo para
            # coordinación entre el equipo de soporte.
            url_ticket = url_for('ver_ticket', ticket_id=ticket_id)
            codigo = _codigo_ticket(tipo_ticket or 'Incidente', ticket_id, fecha_creacion_ticket)
            if not es_interno and usuario != creado_por:
                correo_solicitante = _correo_de_usuario(creado_por)
                if correo_solicitante:
                    asunto = f"[Arkiv] Nueva respuesta en tu solicitud {codigo}"
                    cuerpo = (
                        f"Hola,\n\nTu solicitud de soporte {codigo} ('{titulo_ticket}') tiene una respuesta nueva "
                        f"de {usuario}.\n\nPuedes verla ingresando a Arkiv, módulo Solicitudes TI.\n\n---\n"
                        f"Equipo de Soporte TI - Arkiv"
                    )
                    threading.Thread(target=enviar_correo_ticket, args=(correo_solicitante, asunto, cuerpo)).start()
                crear_notificacion(creado_por, f"Nueva respuesta en tu solicitud {codigo}", url=url_ticket)
            # 🔔 Si quien comenta es el propio solicitante, avisamos (solo campanita, sin correo
            # adicional) a quien tenga el ticket asignado — o a todo el equipo si nadie lo ha
            # tomado — para que sepan que hay actividad nueva por atender.
            elif not es_interno and usuario == creado_por:
                if asignado_actual:
                    crear_notificacion(asignado_actual, f"{usuario} respondió la solicitud {codigo}", url=url_ticket)
                else:
                    crear_notificacion_para_varios([m['usuario'] for m in _equipo_soporte_activo()], f"{usuario} respondió la solicitud {codigo}", url=url_ticket)
        except Exception as e:
            conn.rollback()
            print(f"Error comentando ticket {ticket_id}: {e}")

    conn.close()
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))


@app.route('/tickets/<int:ticket_id>/actualizar', methods=['POST'])
@login_required
@agente_o_admin_required
def actualizar_ticket(ticket_id):
    nuevo_estado = request.form.get('estado', '').strip()
    nueva_prioridad = request.form.get('prioridad', '').strip()
    nuevo_asignado = request.form.get('asignado_a', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT estado, prioridad, asignado_a, sla_respuesta_cumplida, sla_resolucion_cumplida, creado_por, titulo, tipo, fecha_creacion FROM tickets WHERE id = %s" if db_type == 'postgres' else "SELECT estado, prioridad, asignado_a, sla_respuesta_cumplida, sla_resolucion_cumplida, creado_por, titulo, tipo, fecha_creacion FROM tickets WHERE id = ?"
        cursor.execute(q_sel, (ticket_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return redirect(url_for('ver_tickets'))

        (estado_old, prioridad_old, asignado_old, respuesta_cumplida_old, resolucion_cumplida_old,
         creado_por, titulo_ticket, tipo_ticket, fecha_creacion_ticket) = row
        estado_final = nuevo_estado if nuevo_estado in ESTADOS_TICKET else estado_old
        prioridad_final = nueva_prioridad if nueva_prioridad in PRIORIDADES_TICKET else prioridad_old
        asignado_final = nuevo_asignado or None

        # 👤 Si el ticket se resuelve/cierra sin que nadie quedara asignado (el agente cambió
        # el estado pero dejó el selector "Asignar a" en "Sin asignar"), se asigna
        # automáticamente a quien hizo el cambio. Sin esto, "Top agentes por solicitudes
        # resueltas" en Indicadores queda vacío aunque sí haya tickets resueltos, porque
        # ese indicador cuenta por 'asignado_a' — y de paso deja un registro correcto de
        # quién atendió realmente el caso.
        if estado_final in ('Resuelto', 'Cerrado') and not asignado_final:
            asignado_final = session.get('username')

        fecha_act = obtener_fecha_actual()

        # SLA de "primera respuesta": queda marcado la primera vez que el ticket sale de
        # 'Abierto' (y no se vuelve a tocar aunque después cambie de estado otra vez).
        respuesta_cumplida_final = respuesta_cumplida_old
        if estado_final != 'Abierto' and not respuesta_cumplida_final:
            respuesta_cumplida_final = fecha_act

        # SLA de "resolución": se marca al llegar a Resuelto/Cerrado. Si el ticket se
        # reabre (vuelve a Abierto/En Proceso), deja de contar como resuelto a tiempo.
        if estado_final in ('Resuelto', 'Cerrado'):
            resolucion_cumplida_final = resolucion_cumplida_old or fecha_act
        else:
            resolucion_cumplida_final = None

        q_upd = "UPDATE tickets SET estado = %s, prioridad = %s, asignado_a = %s, fecha_actualizacion = %s, sla_respuesta_cumplida = %s, sla_resolucion_cumplida = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE tickets SET estado = ?, prioridad = ?, asignado_a = ?, fecha_actualizacion = ?, sla_respuesta_cumplida = ?, sla_resolucion_cumplida = ? WHERE id = ?"
        cursor.execute(q_upd, (estado_final, prioridad_final, asignado_final, fecha_act, respuesta_cumplida_final, resolucion_cumplida_final, ticket_id))

        cambios = []
        if estado_final != estado_old:
            cambios.append(f"estado: '{estado_old}' → '{estado_final}'")
        if prioridad_final != prioridad_old:
            cambios.append(f"prioridad: '{prioridad_old}' → '{prioridad_final}'")
        if asignado_final != asignado_old:
            cambios.append(f"asignado a: '{asignado_old or 'nadie'}' → '{asignado_final or 'nadie'}'")

        usuario = session.get('username')
        if cambios:
            mensaje_sistema = f"{usuario} actualizó el ticket — " + "; ".join(cambios)
            q_ins = "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (%s, %s, %s, 'sistema', %s)" if db_type == 'postgres' else "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (?, ?, ?, 'sistema', ?)"
            cursor.execute(q_ins, (ticket_id, usuario, mensaje_sistema, fecha_act))

        conn.commit()

        if cambios:
            registrar_log(usuario, "Actualización de Ticket", f"Ticket #{ticket_id}: {'; '.join(cambios)}")

        # 📧 Avisamos por correo al solicitante cuando su ticket cambia de ESTADO (no en cada
        # cambio de prioridad/asignación, que es más una gestión interna del equipo de TI).
        if estado_final != estado_old and creado_por != usuario:
            codigo = _codigo_ticket(tipo_ticket or 'Incidente', ticket_id, fecha_creacion_ticket)
            correo_solicitante = _correo_de_usuario(creado_por)
            if correo_solicitante:
                asunto = f"[Arkiv] Tu solicitud {codigo} cambió a '{estado_final}'"
                cuerpo = (
                    f"Hola,\n\nTu solicitud de soporte {codigo} ('{titulo_ticket}') cambió de estado: "
                    f"'{estado_old}' → '{estado_final}'.\n\nPuedes ver el detalle completo ingresando a Arkiv, "
                    f"módulo Solicitudes TI.\n\n---\nEquipo de Soporte TI - Arkiv"
                )
                threading.Thread(target=enviar_correo_ticket, args=(correo_solicitante, asunto, cuerpo)).start()
            crear_notificacion(creado_por, f"Tu solicitud {codigo} cambió a '{estado_final}'", url=url_for('ver_ticket', ticket_id=ticket_id))
    except Exception as e:
        conn.rollback()
        print(f"Error actualizando ticket {ticket_id}: {e}")

    conn.close()
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))


@app.route('/tickets/<int:ticket_id>/modificar_sla', methods=['POST'])
@login_required
@agente_o_admin_required
def modificar_sla_ticket(ticket_id):
    """Permite al equipo de soporte correr la fecha límite de SOLUCIÓN de un ticket (el
    'compromiso con el usuario'), siempre con un motivo y un tope de MAX_MODIFICACIONES_SLA
    veces — igual que en la mesa de ayuda externa que ya usa la organización."""
    nueva_fecha_raw = request.form.get('nueva_fecha', '').strip()  # <input type="datetime-local">
    motivo_categoria = request.form.get('motivo_categoria', '').strip()
    motivo_detalle = request.form.get('motivo', '').strip()
    if motivo_categoria not in MOTIVOS_MODIFICACION_SLA:
        motivo_categoria = 'Otro'
    # El registro guarda la categoría (p. ej. "Depende de un proveedor o tercero externo",
    # para dejar explícito que el atraso no depende del analista/agente) junto con el detalle
    # libre que el equipo de soporte escriba.
    motivo = f"{motivo_categoria} — {motivo_detalle}" if motivo_detalle else motivo_categoria

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT sla_modificaciones, estado FROM tickets WHERE id = %s" if db_type == 'postgres' else "SELECT sla_modificaciones, estado FROM tickets WHERE id = ?"
        cursor.execute(q_sel, (ticket_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return redirect(url_for('ver_tickets'))

        mods_actuales = row[0] or 0
        # El detalle libre (motivo_detalle) sigue exigiendo mínimo 10 caracteres, igual que
        # antes; la categoría (motivo_categoria) es obligatoria por separado vía el <select>.
        if mods_actuales >= MAX_MODIFICACIONES_SLA or len(motivo_detalle) < 10 or not nueva_fecha_raw:
            conn.close()
            return redirect(url_for('ver_ticket', ticket_id=ticket_id))

        try:
            nueva_fecha_fmt = datetime.strptime(nueva_fecha_raw, "%Y-%m-%dT%H:%M").strftime(FORMATO_FECHA_TICKET)
        except Exception:
            conn.close()
            return redirect(url_for('ver_ticket', ticket_id=ticket_id))

        fecha_act = obtener_fecha_actual()
        usuario = session.get('username')

        # 🔔 Se limpia el nivel de alerta de SLA ya avisado: con la nueva fecha límite el ticket
        # vuelve a "vigente", y así puede volver a avisar más adelante si se acerca de nuevo.
        q_upd = "UPDATE tickets SET sla_resolucion_limite = %s, sla_modificaciones = sla_modificaciones + 1, fecha_actualizacion = %s, sla_alerta_nivel = NULL WHERE id = %s" if db_type == 'postgres' else "UPDATE tickets SET sla_resolucion_limite = ?, sla_modificaciones = sla_modificaciones + 1, fecha_actualizacion = ?, sla_alerta_nivel = NULL WHERE id = ?"
        cursor.execute(q_upd, (nueva_fecha_fmt, fecha_act, ticket_id))

        mensaje_sistema = f"{usuario} modificó la fecha límite de solución a {nueva_fecha_fmt} — Motivo: {motivo}"
        q_ins = "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (%s, %s, %s, 'sistema', %s)" if db_type == 'postgres' else "INSERT INTO tickets_comentarios (ticket_id, autor, mensaje, tipo, fecha) VALUES (?, ?, ?, 'sistema', ?)"
        cursor.execute(q_ins, (ticket_id, usuario, mensaje_sistema, fecha_act))

        conn.commit()
        registrar_log(usuario, "SLA de Ticket Modificado", f"Ticket #{ticket_id}: nueva fecha límite de solución {nueva_fecha_fmt} ({mods_actuales + 1}/{MAX_MODIFICACIONES_SLA}) — {motivo}")
    except Exception as e:
        conn.rollback()
        print(f"Error modificando SLA del ticket {ticket_id}: {e}")

    conn.close()
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))


@app.route('/tickets/<int:ticket_id>/calificar', methods=['POST'])
@login_required
def calificar_ticket(ticket_id):
    """El propio solicitante puede calificar de 1 a 5 estrellas su experiencia, una sola vez,
    y solo cuando el ticket ya está Resuelto o Cerrado — igual que en la mesa de ayuda externa."""
    try:
        calificacion = int(request.form.get('calificacion', '0'))
    except (TypeError, ValueError):
        calificacion = 0

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT creado_por, estado, calificacion FROM tickets WHERE id = %s" if db_type == 'postgres' else "SELECT creado_por, estado, calificacion FROM tickets WHERE id = ?"
        cursor.execute(q_sel, (ticket_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return redirect(url_for('ver_tickets'))

        creado_por, estado_actual, calificacion_previa = row
        puede_calificar = (
            session.get('username') == creado_por and
            estado_actual in ('Resuelto', 'Cerrado') and
            not calificacion_previa and
            CALIFICACION_MIN <= calificacion <= CALIFICACION_MAX
        )
        if puede_calificar:
            fecha_act = obtener_fecha_actual()
            q_upd = "UPDATE tickets SET calificacion = %s, calificacion_fecha = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE tickets SET calificacion = ?, calificacion_fecha = ? WHERE id = ?"
            cursor.execute(q_upd, (calificacion, fecha_act, ticket_id))
            conn.commit()
            registrar_log(session.get('username'), "Calificación de Ticket", f"Ticket #{ticket_id} calificado con {calificacion}/{CALIFICACION_MAX} estrellas")
    except Exception as e:
        conn.rollback()
        print(f"Error calificando ticket {ticket_id}: {e}")

    conn.close()
    return redirect(url_for('ver_ticket', ticket_id=ticket_id))


@app.route('/tickets/inicio')
@login_required
def inicio_tickets():
    """Página de aterrizaje propia del módulo Solicitudes TI (no la Bienvenida general de
    Arkiv): un resumen rápido distinto según el rol, más los tickets más recientes."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    es_soporte = (session.get('rol') in ROLES_CON_ACCESO_OPERATIVO)
    usuario = session.get('username')
    ph = '%s' if db_type == 'postgres' else '?'

    resumen = {}
    try:
        if es_soporte:
            cursor.execute(f"SELECT COUNT(*) FROM tickets WHERE asignado_a = {ph} AND estado IN ('Abierto', 'En Proceso')", (usuario,))
            resumen['asignados_abiertos'] = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE (asignado_a IS NULL OR asignado_a = '') AND estado IN ('Abierto', 'En Proceso')")
            resumen['sin_asignar'] = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM tickets WHERE asignado_a = {ph} AND estado IN ('Resuelto', 'Cerrado')", (usuario,))
            resumen['resueltos_por_mi'] = cursor.fetchone()[0]
        else:
            cursor.execute(f"SELECT COUNT(*) FROM tickets WHERE creado_por = {ph} AND estado IN ('Abierto', 'En Proceso')", (usuario,))
            resumen['mis_abiertos'] = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM tickets WHERE creado_por = {ph} AND estado IN ('Resuelto', 'Cerrado')", (usuario,))
            resumen['mis_resueltos'] = cursor.fetchone()[0]
            cursor.execute(f"SELECT COUNT(*) FROM tickets WHERE creado_por = {ph}", (usuario,))
            resumen['mis_total'] = cursor.fetchone()[0]
    except Exception as e:
        print(f"Error calculando resumen de inicio de tickets: {e}")

    query = "SELECT id, titulo, tipo, categoria, prioridad, estado, creado_por, fecha_creacion FROM tickets WHERE 1=1"
    params = []
    if not es_soporte:
        query += f" AND creado_por = {ph}"
        params.append(usuario)
    query += " ORDER BY id DESC LIMIT 5"

    recientes = []
    try:
        cursor.execute(query, tuple(params))
        for r in cursor.fetchall():
            tipo_t = r[2] or 'Incidente'
            recientes.append({
                'id': r[0], 'titulo': r[1], 'tipo': tipo_t, 'categoria': r[3], 'prioridad': r[4],
                'estado': r[5], 'creado_por': r[6], 'codigo': _codigo_ticket(tipo_t, r[0], r[7])
            })
    except Exception as e:
        print(f"Error consultando recientes de inicio de tickets: {e}")

    conn.close()
    return render_template('tickets_inicio.html', es_soporte=es_soporte, resumen=resumen, recientes=recientes)


# 📚 BASE DE CONOCIMIENTO (artículos con un documento adjunto, visibles para todos los
# roles del módulo de Tickets; solo el equipo de soporte TI los crea/edita/elimina).
@app.route('/tickets/conocimiento')
@login_required
def ver_conocimiento():
    q_busqueda = request.args.get('q', '').strip().lower()
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, titulo, descripcion, url_documento, nombre_archivo, vistas, fecha_creacion FROM conocimiento_articulos WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY id DESC")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando base de conocimiento: {e}")
        rows = []
    conn.close()

    articulos = []
    for r in rows:
        texto_full = f"{r[1]} {r[2] or ''}".lower()
        if not q_busqueda or q_busqueda in texto_full:
            articulos.append({
                'id': r[0], 'titulo': r[1], 'descripcion': r[2], 'url_documento': r[3],
                'nombre_archivo': r[4], 'vistas': r[5] or 0, 'fecha_creacion': r[6]
            })

    es_soporte = (session.get('rol') in ROLES_CON_ACCESO_OPERATIVO)
    return render_template('conocimiento.html', articulos=articulos, es_soporte=es_soporte, q_busqueda=q_busqueda)


@app.route('/tickets/conocimiento/nuevo', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_conocimiento():
    titulo = request.form.get('titulo', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    archivo = request.files.get('documento')

    if titulo and archivo and archivo.filename and archivo_permitido(archivo.filename):
        subidos = _subir_adjuntos_ticket([archivo])
        if subidos:
            url_doc, nombre_doc = subidos[0]
            fecha_act = obtener_fecha_actual()
            usuario = session.get('username')
            conn, db_type = get_db()
            cursor = conn.cursor()
            try:
                q_ins = "INSERT INTO conocimiento_articulos (titulo, descripcion, url_documento, nombre_archivo, vistas, creado_por, fecha_creacion, estado) VALUES (%s, %s, %s, %s, 0, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO conocimiento_articulos (titulo, descripcion, url_documento, nombre_archivo, vistas, creado_por, fecha_creacion, estado) VALUES (?, ?, ?, ?, 0, ?, ?, 'activo')"
                cursor.execute(q_ins, (titulo, descripcion, url_doc, nombre_doc, usuario, fecha_act))
                conn.commit()
                registrar_log(usuario, "Artículo de Conocimiento Creado", f"'{titulo}' ({nombre_doc})")
            except Exception as e:
                conn.rollback()
                print(f"Error creando artículo de conocimiento: {e}")
            conn.close()

    return redirect(url_for('ver_conocimiento'))


@app.route('/tickets/conocimiento/<int:articulo_id>/editar', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_conocimiento(articulo_id):
    titulo = request.form.get('titulo', '').strip()
    descripcion = request.form.get('descripcion', '').strip()
    archivo = request.files.get('documento')

    if not titulo:
        return redirect(url_for('ver_conocimiento'))

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        if archivo and archivo.filename and archivo_permitido(archivo.filename):
            subidos = _subir_adjuntos_ticket([archivo])
            if subidos:
                url_doc, nombre_doc = subidos[0]
                q_upd = "UPDATE conocimiento_articulos SET titulo = %s, descripcion = %s, url_documento = %s, nombre_archivo = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE conocimiento_articulos SET titulo = ?, descripcion = ?, url_documento = ?, nombre_archivo = ? WHERE id = ?"
                cursor.execute(q_upd, (titulo, descripcion, url_doc, nombre_doc, articulo_id))
            else:
                q_upd = "UPDATE conocimiento_articulos SET titulo = %s, descripcion = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE conocimiento_articulos SET titulo = ?, descripcion = ? WHERE id = ?"
                cursor.execute(q_upd, (titulo, descripcion, articulo_id))
        else:
            q_upd = "UPDATE conocimiento_articulos SET titulo = %s, descripcion = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE conocimiento_articulos SET titulo = ?, descripcion = ? WHERE id = ?"
            cursor.execute(q_upd, (titulo, descripcion, articulo_id))
        conn.commit()
        registrar_log(session.get('username'), "Artículo de Conocimiento Editado", f"Artículo #{articulo_id}: '{titulo}'")
    except Exception as e:
        conn.rollback()
        print(f"Error editando artículo de conocimiento {articulo_id}: {e}")
    conn.close()
    return redirect(url_for('ver_conocimiento'))


@app.route('/tickets/conocimiento/<int:articulo_id>/eliminar', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_conocimiento(articulo_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE conocimiento_articulos SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE conocimiento_articulos SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (articulo_id,))
        conn.commit()
        registrar_log(session.get('username'), "Artículo de Conocimiento Eliminado", f"Artículo #{articulo_id}")
    except Exception as e:
        conn.rollback()
        print(f"Error eliminando artículo de conocimiento {articulo_id}: {e}")
    conn.close()
    return redirect(url_for('ver_conocimiento'))


@app.route('/tickets/conocimiento/<int:articulo_id>/abrir')
@login_required
def abrir_conocimiento(articulo_id):
    """Registra una vista y redirige al documento real (alojado en Cloudinary)."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    url_doc = None
    try:
        q_sel = "SELECT url_documento FROM conocimiento_articulos WHERE id = %s" if db_type == 'postgres' else "SELECT url_documento FROM conocimiento_articulos WHERE id = ?"
        cursor.execute(q_sel, (articulo_id,))
        row = cursor.fetchone()
        if row:
            url_doc = row[0]
            q_upd = "UPDATE conocimiento_articulos SET vistas = COALESCE(vistas, 0) + 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE conocimiento_articulos SET vistas = COALESCE(vistas, 0) + 1 WHERE id = ?"
            cursor.execute(q_upd, (articulo_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Error registrando vista de artículo {articulo_id}: {e}")
    conn.close()

    if not url_doc:
        return redirect(url_for('ver_conocimiento'))
    return redirect(url_doc)


# ⚙️ CONFIGURACIÓN DE ÁREAS, SEDES Y CATEGORÍAS (solo equipo de soporte). Estos valores
# alimentan los desplegables al crear una solicitud y los filtros de la lista de tickets.
@app.route('/tickets/configuracion')
@login_required
@agente_o_admin_required
def configuracion_tickets():
    areas = _config_ticket_lista('area')
    sedes = _config_ticket_lista('sede')
    categorias = _config_ticket_lista('categoria')

    # 👤 Lista de usuarios activos para elegir el "responsable" de cada sede desde un
    # desplegable (en vez de escribir un nombre libre que podría no corresponder a
    # ninguna cuenta real del sistema).
    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario, nombre FROM usuarios WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY usuario ASC")
    usuarios_disponibles = [{'usuario': r[0], 'nombre': r[1]} for r in cursor.fetchall()]
    conn.close()

    return render_template('tickets_configuracion.html', es_soporte=True, areas=areas, sedes=sedes, categorias=categorias, usuarios_disponibles=usuarios_disponibles)


@app.route('/tickets/configuracion/nuevo', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_configuracion_ticket():
    tipo = request.form.get('tipo', '').strip()
    nombre = request.form.get('nombre', '').strip()
    # 📍 Dirección solo aplica a Sedes y Áreas. Responsable aplica a los tres tipos (se usa
    # para la asignación automática de tickets por categoría/área).
    direccion = request.form.get('direccion', '').strip() or None
    responsable = request.form.get('responsable', '').strip() or None
    if tipo not in ('sede', 'area'):
        direccion = None
    if tipo not in ('sede', 'area', 'categoria'):
        responsable = None
    if tipo in ('area', 'sede', 'categoria') and nombre:
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q = "INSERT INTO ticket_configuraciones (tipo, nombre, direccion, responsable) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO ticket_configuraciones (tipo, nombre, direccion, responsable) VALUES (?, ?, ?, ?)"
            cursor.execute(q, (tipo, nombre, direccion, responsable))
            conn.commit()
            detalle = f"Se agregó {tipo} '{nombre}'"
            if tipo in ('sede', 'area') and (direccion or responsable):
                detalle += f" (dirección: {direccion or 'sin especificar'}, responsable: {responsable or 'sin asignar'})"
            registrar_log(session.get('username'), "Configuración de Tickets", detalle)
        except Exception as e:
            conn.rollback()
            print(f"Error creando configuración de ticket: {e}")
        conn.close()
    return redirect(url_for('configuracion_tickets'))


@app.route('/tickets/configuracion/<int:config_id>/editar', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_configuracion_ticket(config_id):
    nombre = request.form.get('nombre', '').strip()
    if nombre:
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q_sel = "SELECT tipo FROM ticket_configuraciones WHERE id = %s" if db_type == 'postgres' else "SELECT tipo FROM ticket_configuraciones WHERE id = ?"
            cursor.execute(q_sel, (config_id,))
            fila = cursor.fetchone()
            tipo_actual = fila[0] if fila else None

            if tipo_actual in ('sede', 'area'):
                # 📍 Sedes y Áreas tienen dirección y responsable; sus formularios envían
                # estos dos campos junto con el nombre.
                direccion = request.form.get('direccion', '').strip() or None
                responsable = request.form.get('responsable', '').strip() or None
                q = "UPDATE ticket_configuraciones SET nombre = %s, direccion = %s, responsable = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE ticket_configuraciones SET nombre = ?, direccion = ?, responsable = ? WHERE id = ?"
                cursor.execute(q, (nombre, direccion, responsable, config_id))
                etiqueta_tipo = 'sede' if tipo_actual == 'sede' else 'área'
                detalle = f"Se editó la {etiqueta_tipo} '{nombre}' (dirección: {direccion or 'sin especificar'}, responsable: {responsable or 'sin asignar'})"
            elif tipo_actual == 'categoria':
                # 🤖 Categoría no tiene dirección, pero sí responsable (para la asignación
                # automática de tickets por categoría).
                responsable = request.form.get('responsable', '').strip() or None
                q = "UPDATE ticket_configuraciones SET nombre = %s, responsable = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE ticket_configuraciones SET nombre = ?, responsable = ? WHERE id = ?"
                cursor.execute(q, (nombre, responsable, config_id))
                detalle = f"Se editó la categoría '{nombre}' (responsable: {responsable or 'sin asignar'})"
            else:
                q = "UPDATE ticket_configuraciones SET nombre = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE ticket_configuraciones SET nombre = ? WHERE id = ?"
                cursor.execute(q, (nombre, config_id))
                detalle = f"Se renombró configuración #{config_id} a '{nombre}'"

            conn.commit()
            registrar_log(session.get('username'), "Configuración de Tickets", detalle)
        except Exception as e:
            conn.rollback()
            print(f"Error editando configuración de ticket: {e}")
        conn.close()
    return redirect(url_for('configuracion_tickets'))


@app.route('/tickets/configuracion/<int:config_id>/eliminar', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_configuracion_ticket(config_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "UPDATE ticket_configuraciones SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE ticket_configuraciones SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q, (config_id,))
        conn.commit()
        registrar_log(session.get('username'), "Configuración de Tickets", f"Se eliminó configuración #{config_id}")
    except Exception as e:
        conn.rollback()
        print(f"Error eliminando configuración de ticket: {e}")
    conn.close()
    return redirect(url_for('configuracion_tickets'))


# 📊 INDICADORES Y KPIS (solo equipo de soporte): panorama general del módulo de tickets —
# cumplimiento de SLA, distribución por prioridad/categoría/área/sede, satisfacción de los
# solicitantes y tendencia de solicitudes de los últimos 14 días — más exportación a Excel.
def _calcular_indicadores_tickets():
    """Calcula todos los indicadores/KPIs de Tickets (por estado, prioridad, tipo, cumplimiento
    de SLA, categoría/área/sede, calificación promedio, top agentes y tendencia de 14 días).
    Lo usan tanto la página de Indicadores como sus exportaciones a PDF/Excel, para no duplicar
    la lógica de agregación en dos lugares."""
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, tipo, categoria, prioridad, estado, creado_por, asignado_a, fecha_creacion, sla_resolucion_limite, sla_resolucion_cumplida, calificacion, area, sede FROM tickets")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando indicadores de tickets: {e}")
        rows = []
    conn.close()

    tickets = []
    for r in rows:
        t = {
            'id': r[0], 'tipo': r[1] or 'Incidente', 'categoria': r[2], 'prioridad': r[3],
            'estado': r[4], 'creado_por': r[5], 'asignado_a': r[6], 'fecha_creacion': r[7],
            'sla_resolucion_limite': r[8], 'sla_resolucion_cumplida': r[9],
            'calificacion': r[10], 'area': r[11], 'sede': r[12]
        }
        t['sla'] = _calcular_sla_ticket(t)
        t['cumplimiento'] = _bucket_cumplimiento_ticket(t)
        tickets.append(t)

    total = len(tickets)
    por_estado = {e: 0 for e in ESTADOS_TICKET}
    por_prioridad = {p: 0 for p in PRIORIDADES_TICKET}
    por_tipo = {tp: 0 for tp in TIPOS_TICKET}
    por_cumplimiento = {'vigente': 0, 'proximo_a_vencer': 0, 'vencido': 0, 'cerrado': 0}
    por_categoria, por_area, por_sede, por_agente = {}, {}, {}, {}
    calificaciones = []
    conteo_por_fecha = {}

    for t in tickets:
        if t['estado'] in por_estado:
            por_estado[t['estado']] += 1
        if t['prioridad'] in por_prioridad:
            por_prioridad[t['prioridad']] += 1
        if t['tipo'] in por_tipo:
            por_tipo[t['tipo']] += 1
        por_cumplimiento[t['cumplimiento']] = por_cumplimiento.get(t['cumplimiento'], 0) + 1
        cat = t['categoria'] or 'Sin categoría'
        por_categoria[cat] = por_categoria.get(cat, 0) + 1
        area_n = t['area'] or 'Sin área'
        por_area[area_n] = por_area.get(area_n, 0) + 1
        sede_n = t['sede'] or 'Sin sede'
        por_sede[sede_n] = por_sede.get(sede_n, 0) + 1
        if t['calificacion']:
            calificaciones.append(t['calificacion'])
        if t['estado'] in ('Resuelto', 'Cerrado') and t['asignado_a']:
            por_agente[t['asignado_a']] = por_agente.get(t['asignado_a'], 0) + 1
        fecha_corta = (t['fecha_creacion'] or '')[:10]
        if fecha_corta:
            conteo_por_fecha[fecha_corta] = conteo_por_fecha.get(fecha_corta, 0) + 1

    hoy = datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)
    dias_tendencia = []
    for i in range(13, -1, -1):
        dia = (hoy - timedelta(days=i)).strftime('%Y-%m-%d')
        dias_tendencia.append({'fecha': dia, 'cantidad': conteo_por_fecha.get(dia, 0)})

    promedio_calificacion = round(sum(calificaciones) / len(calificaciones), 2) if calificaciones else None
    # 👤 Igual que en el resto de Tickets, se muestra el nombre/alias real del agente, no su
    # usuario de inicio de sesión.
    nombres_usuarios_ind = _mapa_nombres_usuarios()
    top_agentes = [
        (_nombre_para_mostrar(u, nombres_usuarios_ind), cant)
        for u, cant in sorted(por_agente.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    return {
        'total': total, 'por_estado': por_estado, 'por_prioridad': por_prioridad, 'por_tipo': por_tipo,
        'por_cumplimiento': por_cumplimiento, 'por_categoria': por_categoria,
        'por_area': por_area, 'por_sede': por_sede, 'dias_tendencia': dias_tendencia,
        'promedio_calificacion': promedio_calificacion, 'total_calificaciones': len(calificaciones),
        'top_agentes': top_agentes
    }


@app.route('/tickets/indicadores')
@login_required
@agente_o_admin_required
def indicadores_tickets():
    # 🔔 Aviso perezoso de SLA por vencer/vencido — ver _revisar_alertas_sla(). Esta página ya
    # está gateada a admin/agente, así que se corre sin condición adicional.
    _revisar_alertas_sla()

    ind = _calcular_indicadores_tickets()
    return render_template('tickets_indicadores.html', es_soporte=True, **ind)


@app.route('/tickets/indicadores/exportar_csv')
@login_required
@agente_o_admin_required
def exportar_indicadores_tickets():
    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, tipo, titulo, categoria, area, sede, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, calificacion FROM tickets ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['CÓDIGO', 'TIPO', 'TÍTULO', 'CATEGORÍA', 'ÁREA', 'SEDE', 'PRIORIDAD', 'ESTADO', 'CREADO POR', 'ASIGNADO A', 'FECHA CREACIÓN', 'ÚLTIMA ACTUALIZACIÓN', 'CALIFICACIÓN'])

    for row in rows:
        tipo_t = row[1] or 'Incidente'
        codigo = _codigo_ticket(tipo_t, row[0], row[10])
        writer.writerow([codigo, tipo_t, row[2], row[3], row[4] or '', row[5] or '', row[6], row[7], row[8], row[9] or '', row[10], row[11], row[12] or ''])

    csv_bytes = '﻿' + output.getvalue()
    fecha_filename = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d_%H%M")
    filename = f"Arkiv_Indicadores_Tickets_{fecha_filename}.csv"

    headers = {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }
    registrar_log(session.get('username'), "Exportación de Indicadores", f"Exportó {len(rows)} tickets a Excel/CSV")
    return Response(csv_bytes, headers=headers, status=200)


# 📊 Traducciones legibles para las tablas de los reportes de Indicadores (PDF/Excel) — los
# diccionarios internos usan claves técnicas ('proximo_a_vencer') que no se le muestran así a
# Tomas/gerencia en el reporte descargado.
ETIQUETAS_CUMPLIMIENTO_SLA = {
    'vigente': 'Vigente', 'proximo_a_vencer': 'Próximo a vencer',
    'vencido': 'Vencido', 'cerrado': 'Cerrado'
}


@app.route('/tickets/indicadores/exportar_pdf')
@login_required
@agente_o_admin_required
def exportar_indicadores_tickets_pdf():
    """Reporte de indicadores de Tickets en PDF — mismo contenido que se ve en pantalla, listo
    para imprimir o adjuntar en un correo a gerencia."""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet

    ind = _calcular_indicadores_tickets()
    estilos = getSampleStyleSheet()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, topMargin=1.5 * cm, bottomMargin=1.5 * cm)
    ahora_txt = datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M')

    def tabla_conteos(titulo, datos, encabezados=('Categoría', 'Cantidad')):
        elementos = [Paragraph(titulo, estilos['Heading3'])]
        filas = [list(encabezados)] + [[k, str(v)] for k, v in datos]
        t = Table(filas, colWidths=[10 * cm, 4 * cm])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cbd5e1')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f1f5f9')]),
        ]))
        elementos.append(t)
        elementos.append(Spacer(1, 0.5 * cm))
        return elementos

    contenido = [
        Paragraph("Arkiv — Indicadores de Tickets de Soporte TI", estilos['Title']),
        Paragraph(f"Generado el {ahora_txt} (hora Colombia) — Total de solicitudes: {ind['total']}", estilos['Normal']),
        Spacer(1, 0.5 * cm),
    ]
    if ind['promedio_calificacion'] is not None:
        contenido.append(Paragraph(
            f"Calificación promedio de satisfacción: {ind['promedio_calificacion']}/5 "
            f"({ind['total_calificaciones']} calificaciones recibidas)", estilos['Normal']
        ))
        contenido.append(Spacer(1, 0.5 * cm))

    contenido += tabla_conteos("Por estado", ind['por_estado'].items(), ('Estado', 'Cantidad'))
    contenido += tabla_conteos("Por prioridad", ind['por_prioridad'].items(), ('Prioridad', 'Cantidad'))
    contenido += tabla_conteos("Por tipo", ind['por_tipo'].items(), ('Tipo', 'Cantidad'))
    contenido += tabla_conteos(
        "Cumplimiento de SLA",
        [(ETIQUETAS_CUMPLIMIENTO_SLA.get(k, k), v) for k, v in ind['por_cumplimiento'].items()],
        ('Estado de SLA', 'Cantidad')
    )
    if ind['por_categoria']:
        contenido += tabla_conteos("Por categoría", sorted(ind['por_categoria'].items(), key=lambda x: x[1], reverse=True), ('Categoría', 'Cantidad'))
    if ind['por_area']:
        contenido += tabla_conteos("Por área", sorted(ind['por_area'].items(), key=lambda x: x[1], reverse=True), ('Área', 'Cantidad'))
    if ind['por_sede']:
        contenido += tabla_conteos("Por sede", sorted(ind['por_sede'].items(), key=lambda x: x[1], reverse=True), ('Sede', 'Cantidad'))
    if ind['top_agentes']:
        contenido += tabla_conteos("Top agentes (tickets resueltos/cerrados)", ind['top_agentes'], ('Agente', 'Tickets'))
    contenido += tabla_conteos("Tendencia — solicitudes creadas por día (últimos 14 días)", [(d['fecha'], d['cantidad']) for d in ind['dias_tendencia']], ('Fecha', 'Cantidad'))

    doc.build(contenido)
    buffer.seek(0)

    fecha_filename = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d_%H%M")
    filename = f"Arkiv_Indicadores_Tickets_{fecha_filename}.pdf"
    registrar_log(session.get('username'), "Exportación de Indicadores", "Exportó los indicadores de Tickets a PDF")
    return Response(buffer.getvalue(), headers={
        'Content-Type': 'application/pdf',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }, status=200)


@app.route('/tickets/indicadores/exportar_xlsx')
@login_required
@agente_o_admin_required
def exportar_indicadores_tickets_xlsx():
    """Reporte de indicadores de Tickets en un libro de Excel real (con formato), a diferencia
    del CSV de detalle que ya existía — una hoja de Resumen con los KPIs y una de Detalle con
    el listado completo de tickets."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    ind = _calcular_indicadores_tickets()
    wb = openpyxl.Workbook()

    relleno_encabezado = PatternFill(start_color='0F172A', end_color='0F172A', fill_type='solid')
    fuente_encabezado = Font(color='FFFFFF', bold=True)
    fuente_titulo = Font(bold=True, size=14)

    resumen = wb.active
    resumen.title = 'Resumen'
    fila = 1
    resumen.cell(row=fila, column=1, value='Arkiv — Indicadores de Tickets de Soporte TI').font = fuente_titulo
    fila += 1
    ahora_txt = datetime.now(ZONA_HORARIA_COLOMBIA).strftime('%Y-%m-%d %H:%M')
    resumen.cell(row=fila, column=1, value=f"Generado el {ahora_txt} — Total de solicitudes: {ind['total']}")
    fila += 2
    if ind['promedio_calificacion'] is not None:
        resumen.cell(row=fila, column=1, value=(
            f"Calificación promedio de satisfacción: {ind['promedio_calificacion']}/5 "
            f"({ind['total_calificaciones']} calificaciones)"
        ))
        fila += 2

    def volcar_seccion(titulo, datos, encabezados):
        nonlocal fila
        resumen.cell(row=fila, column=1, value=titulo).font = Font(bold=True, size=12)
        fila += 1
        for col, texto in enumerate(encabezados, start=1):
            c = resumen.cell(row=fila, column=col, value=texto)
            c.fill = relleno_encabezado
            c.font = fuente_encabezado
        fila += 1
        for clave, valor in datos:
            resumen.cell(row=fila, column=1, value=clave)
            resumen.cell(row=fila, column=2, value=valor)
            fila += 1
        fila += 1

    volcar_seccion('Por estado', ind['por_estado'].items(), ['Estado', 'Cantidad'])
    volcar_seccion('Por prioridad', ind['por_prioridad'].items(), ['Prioridad', 'Cantidad'])
    volcar_seccion('Por tipo', ind['por_tipo'].items(), ['Tipo', 'Cantidad'])
    volcar_seccion(
        'Cumplimiento de SLA',
        [(ETIQUETAS_CUMPLIMIENTO_SLA.get(k, k), v) for k, v in ind['por_cumplimiento'].items()],
        ['Estado de SLA', 'Cantidad']
    )
    if ind['por_categoria']:
        volcar_seccion('Por categoría', sorted(ind['por_categoria'].items(), key=lambda x: x[1], reverse=True), ['Categoría', 'Cantidad'])
    if ind['por_area']:
        volcar_seccion('Por área', sorted(ind['por_area'].items(), key=lambda x: x[1], reverse=True), ['Área', 'Cantidad'])
    if ind['por_sede']:
        volcar_seccion('Por sede', sorted(ind['por_sede'].items(), key=lambda x: x[1], reverse=True), ['Sede', 'Cantidad'])
    if ind['top_agentes']:
        volcar_seccion('Top agentes (tickets resueltos/cerrados)', ind['top_agentes'], ['Agente', 'Tickets'])
    volcar_seccion('Tendencia — últimos 14 días', [(d['fecha'], d['cantidad']) for d in ind['dias_tendencia']], ['Fecha', 'Cantidad'])

    resumen.column_dimensions['A'].width = 32
    resumen.column_dimensions['B'].width = 14

    # 📋 Hoja de detalle: el mismo listado completo de tickets que ya ofrece la exportación CSV,
    # para tener ambas vistas (resumen y detalle) en un solo archivo.
    detalle = wb.create_sheet('Detalle')
    encabezados_detalle = ['CÓDIGO', 'TIPO', 'TÍTULO', 'CATEGORÍA', 'ÁREA', 'SEDE', 'PRIORIDAD', 'ESTADO', 'CREADO POR', 'ASIGNADO A', 'FECHA CREACIÓN', 'ÚLTIMA ACTUALIZACIÓN', 'CALIFICACIÓN']
    for col, texto in enumerate(encabezados_detalle, start=1):
        c = detalle.cell(row=1, column=col, value=texto)
        c.fill = relleno_encabezado
        c.font = fuente_encabezado

    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, tipo, titulo, categoria, area, sede, prioridad, estado, creado_por, asignado_a, fecha_creacion, fecha_actualizacion, calificacion FROM tickets ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    for i, row in enumerate(rows, start=2):
        tipo_t = row[1] or 'Incidente'
        codigo = _codigo_ticket(tipo_t, row[0], row[10])
        valores = [codigo, tipo_t, row[2], row[3], row[4] or '', row[5] or '', row[6], row[7], row[8], row[9] or '', row[10], row[11], row[12] or '']
        for col, valor in enumerate(valores, start=1):
            detalle.cell(row=i, column=col, value=valor)
    for letra, ancho in zip('ABCDEFGHIJKLM', [16, 12, 30, 18, 16, 16, 12, 12, 14, 14, 18, 18, 12]):
        detalle.column_dimensions[letra].width = ancho

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    fecha_filename = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d_%H%M")
    filename = f"Arkiv_Indicadores_Tickets_{fecha_filename}.xlsx"
    registrar_log(session.get('username'), "Exportación de Indicadores", "Exportó los indicadores de Tickets a Excel")
    return Response(buffer.getvalue(), headers={
        'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }, status=200)


# 📦 INVENTARIO DE ACTIVOS DE TI (solo equipo de soporte): registro de equipos/activos y a
# quién/qué sede están asignados. Reutiliza las Sedes configuradas en /tickets/configuracion.
@app.route('/tickets/inventario')
@login_required
@agente_o_admin_required
def ver_inventario():
    q_estado = request.args.get('estado', '').strip()
    q_tipo = request.args.get('tipo', '').strip()
    q_sede = request.args.get('sede', '').strip()
    q_busqueda = request.args.get('q', '').strip().lower()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, nombre, tipo_activo, marca, modelo, numero_serie, estado, asignado_a, sede, observaciones, fecha_creacion, creado_por FROM activos_inventario WHERE eliminado = 0 ORDER BY id DESC")
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando inventario: {e}")
        rows = []

    # 📎 Adjuntos de todos los activos, agrupados por activo_id, en una sola consulta (en vez
    # de una consulta por activo dentro del ciclo).
    adjuntos_por_activo = {}
    try:
        cursor.execute("SELECT id, activo_id, url, nombre_original FROM inventario_adjuntos ORDER BY id ASC")
        for adj_id, activo_id, url, nombre_original in cursor.fetchall():
            adjuntos_por_activo.setdefault(activo_id, []).append({'id': adj_id, 'url': url, 'nombre_original': nombre_original})
    except Exception as e:
        print(f"Error consultando adjuntos de inventario: {e}")
    conn.close()

    activos_todos = [{
        'id': r[0], 'nombre': r[1], 'tipo_activo': r[2], 'marca': r[3], 'modelo': r[4],
        'numero_serie': r[5], 'estado': r[6], 'asignado_a': r[7], 'sede': r[8],
        'observaciones': r[9], 'fecha_creacion': r[10], 'creado_por': r[11],
        'adjuntos': adjuntos_por_activo.get(r[0], [])
    } for r in rows]
    total_activos_general = len(activos_todos)

    # 🏢 Distribución por sede: cuántos activos hay en cada sede y en qué estado están, sin
    # importar los filtros aplicados — le da al equipo de soporte una vista completa de la
    # organización de un vistazo, y cada fila enlaza a la vista filtrada por esa sede.
    distribucion_por_sede = {}
    for a in activos_todos:
        clave = a['sede'] or 'Sin sede asignada'
        fila = distribucion_por_sede.setdefault(clave, {'sede': clave, 'total': 0, 'estados': {e: 0 for e in ESTADOS_ACTIVO}})
        fila['total'] += 1
        fila['estados'][a['estado']] = fila['estados'].get(a['estado'], 0) + 1
    distribucion_por_sede = sorted(distribucion_por_sede.values(), key=lambda f: (f['sede'] == 'Sin sede asignada', -f['total'], f['sede']))

    # 📊 Los indicadores de arriba (Disponibles/Asignados/...) responden a la sede, tipo y
    # búsqueda ya elegidos —para que, al filtrar por una sede, se vea cuántos activos de ESA
    # sede están en cada estado— pero no al estado en sí, así el agente puede seguir comparando
    # los 4 estados entre ellos en vez de que el filtro los reduzca a uno solo.
    activos_en_contexto = activos_todos
    if q_sede:
        activos_en_contexto = [a for a in activos_en_contexto if (a['sede'] or '') == q_sede]
    if q_tipo in TIPOS_ACTIVO:
        activos_en_contexto = [a for a in activos_en_contexto if a['tipo_activo'] == q_tipo]
    if q_busqueda:
        activos_en_contexto = [a for a in activos_en_contexto if q_busqueda in f"{a['nombre']} {a['marca'] or ''} {a['modelo'] or ''} {a['numero_serie'] or ''} {a['asignado_a'] or ''}".lower()]

    conteos_estado = {e: 0 for e in ESTADOS_ACTIVO}
    for a in activos_en_contexto:
        conteos_estado[a['estado']] = conteos_estado.get(a['estado'], 0) + 1
    total_activos = len(activos_en_contexto)

    # 📊 "Por tipo de activo": mismo criterio de contexto que arriba — responde a la sede y la
    # búsqueda ya elegidas, pero no al tipo en sí, para poder comparar los tipos entre ellos en
    # vez de que el propio filtro de tipo colapse el gráfico a una sola barra.
    activos_para_tipo = activos_todos
    if q_sede:
        activos_para_tipo = [a for a in activos_para_tipo if (a['sede'] or '') == q_sede]
    if q_busqueda:
        activos_para_tipo = [a for a in activos_para_tipo if q_busqueda in f"{a['nombre']} {a['marca'] or ''} {a['modelo'] or ''} {a['numero_serie'] or ''} {a['asignado_a'] or ''}".lower()]
    por_tipo_activo = {}
    for a in activos_para_tipo:
        tp = a['tipo_activo'] or 'Otro'
        por_tipo_activo[tp] = por_tipo_activo.get(tp, 0) + 1
    por_tipo_activo = dict(sorted(por_tipo_activo.items(), key=lambda kv: kv[1], reverse=True))

    activos = activos_en_contexto
    if q_estado in ESTADOS_ACTIVO:
        activos = [a for a in activos if a['estado'] == q_estado]

    sedes = _config_ticket_lista('sede')
    return render_template(
        'tickets_inventario.html', es_soporte=True, activos=activos,
        tipos_activo=TIPOS_ACTIVO, estados_activo=ESTADOS_ACTIVO, sedes=sedes,
        q_estado=q_estado, q_tipo=q_tipo, q_sede=q_sede, q_busqueda=q_busqueda,
        conteos_estado=conteos_estado, total_activos=total_activos,
        total_activos_general=total_activos_general, distribucion_por_sede=distribucion_por_sede,
        por_tipo_activo=por_tipo_activo
    )


@app.route('/tickets/inventario/nuevo', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_activo():
    nombre = request.form.get('nombre', '').strip()
    tipo_activo = request.form.get('tipo_activo', 'Otro').strip()
    marca = request.form.get('marca', '').strip()
    modelo = request.form.get('modelo', '').strip()
    numero_serie = request.form.get('numero_serie', '').strip()
    estado = request.form.get('estado', 'Disponible').strip()
    asignado_a = request.form.get('asignado_a', '').strip()
    sede = request.form.get('sede', '').strip()
    observaciones = request.form.get('observaciones', '').strip()

    if tipo_activo not in TIPOS_ACTIVO:
        tipo_activo = 'Otro'
    if estado not in ESTADOS_ACTIVO:
        estado = 'Disponible'
    sedes_validas = [s['nombre'] for s in _config_ticket_lista('sede')]
    sede = sede if sede in sedes_validas else None

    if nombre:
        fecha_act = obtener_fecha_actual()
        usuario = session.get('username')
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q_ins = "INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, asignado_a, sede, observaciones, fecha_creacion, creado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO activos_inventario (nombre, tipo_activo, marca, modelo, numero_serie, estado, asignado_a, sede, observaciones, fecha_creacion, creado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            cursor.execute(q_ins, (nombre, tipo_activo, marca or None, modelo or None, numero_serie or None, estado, asignado_a or None, sede, observaciones or None, fecha_act, usuario))
            conn.commit()
            registrar_log(usuario, "Inventario de Activos", f"Se registró el activo '{nombre}' [{tipo_activo}]")
        except Exception as e:
            conn.rollback()
            print(f"Error creando activo: {e}")
        conn.close()
    return redirect(url_for('ver_inventario'))


@app.route('/tickets/inventario/<int:activo_id>/editar', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_activo(activo_id):
    nombre = request.form.get('nombre', '').strip()
    tipo_activo = request.form.get('tipo_activo', 'Otro').strip()
    marca = request.form.get('marca', '').strip()
    modelo = request.form.get('modelo', '').strip()
    numero_serie = request.form.get('numero_serie', '').strip()
    estado = request.form.get('estado', 'Disponible').strip()
    asignado_a = request.form.get('asignado_a', '').strip()
    sede = request.form.get('sede', '').strip()
    observaciones = request.form.get('observaciones', '').strip()

    if tipo_activo not in TIPOS_ACTIVO:
        tipo_activo = 'Otro'
    if estado not in ESTADOS_ACTIVO:
        estado = 'Disponible'
    sedes_validas = [s['nombre'] for s in _config_ticket_lista('sede')]
    sede = sede if sede in sedes_validas else None

    if nombre:
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q_upd = "UPDATE activos_inventario SET nombre = %s, tipo_activo = %s, marca = %s, modelo = %s, numero_serie = %s, estado = %s, asignado_a = %s, sede = %s, observaciones = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE activos_inventario SET nombre = ?, tipo_activo = ?, marca = ?, modelo = ?, numero_serie = ?, estado = ?, asignado_a = ?, sede = ?, observaciones = ? WHERE id = ?"
            cursor.execute(q_upd, (nombre, tipo_activo, marca or None, modelo or None, numero_serie or None, estado, asignado_a or None, sede, observaciones or None, activo_id))
            conn.commit()
            registrar_log(session.get('username'), "Inventario de Activos", f"Se editó el activo #{activo_id} ('{nombre}')")
        except Exception as e:
            conn.rollback()
            print(f"Error editando activo {activo_id}: {e}")
        conn.close()
    return redirect(url_for('ver_inventario'))


@app.route('/tickets/inventario/<int:activo_id>/eliminar', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_activo(activo_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "UPDATE activos_inventario SET eliminado = 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE activos_inventario SET eliminado = 1 WHERE id = ?"
        cursor.execute(q, (activo_id,))
        conn.commit()
        registrar_log(session.get('username'), "Inventario de Activos", f"Se eliminó el activo #{activo_id}")
    except Exception as e:
        conn.rollback()
        print(f"Error eliminando activo {activo_id}: {e}")
    conn.close()
    return redirect(url_for('ver_inventario'))


# 📎 ADJUNTAR ARCHIVOS A UN ACTIVO DEL INVENTARIO (facturas, fotos, garantías, manuales...).
# Reutiliza el mismo subidor de Cloudinary que ya usan los adjuntos de tickets.
@app.route('/tickets/inventario/<int:activo_id>/adjuntar', methods=['POST'])
@login_required
@agente_o_admin_required
def adjuntar_archivo_inventario(activo_id):
    archivos = request.files.getlist('adjuntos')
    subidos = _subir_adjuntos_ticket(archivos)

    if subidos:
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            fecha_act = obtener_fecha_actual()
            usuario = session.get('username')
            _guardar_adjuntos_inventario(cursor, db_type, activo_id, subidos, usuario, fecha_act)
            conn.commit()
            registrar_log(usuario, "Inventario de Activos", f"Se adjuntaron {len(subidos)} archivo(s) al activo #{activo_id}")
        except Exception as e:
            conn.rollback()
            print(f"Error adjuntando archivos al activo {activo_id}: {e}")
        conn.close()
    return redirect(url_for('ver_inventario'))


@app.route('/tickets/inventario/adjunto/<int:adjunto_id>/eliminar', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_adjunto_inventario(adjunto_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "DELETE FROM inventario_adjuntos WHERE id = %s" if db_type == 'postgres' else "DELETE FROM inventario_adjuntos WHERE id = ?"
        cursor.execute(q, (adjunto_id,))
        conn.commit()
        registrar_log(session.get('username'), "Inventario de Activos", f"Se eliminó el adjunto #{adjunto_id}")
    except Exception as e:
        conn.rollback()
        print(f"Error eliminando adjunto de inventario {adjunto_id}: {e}")
    conn.close()
    return redirect(url_for('ver_inventario'))


# 📧 ENVÍO VÍA GMAIL APPS SCRIPT (PUERTO 443 HTTPS - SIN BLOQUEOS)
def enviar_correo_recuperacion(email_destino, usuario_nombre, codigo):
    try:
        cuerpo = f"Hola {usuario_nombre},\n\nTu código de verificación para restablecer tu contraseña en ARKIV es: {codigo}\n\nSi no solicitaste este cambio, por favor ignora este mensaje.\n---\nEquipo de Soporte - ARKIV System"
        
        payload = {
            "para": email_destino,
            "asunto": f"Código de Verificación - Gestor de Archivos",
            "cuerpo": cuerpo
        }

        if requests:
            res = requests.post(GMAIL_SCRIPT_URL, json=payload, timeout=15)
            print(f"✅ EXITO: Correo enviado a {email_destino} vía Google Script. Status: {res.status_code}")
            return True
        else:
            data_json = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(GMAIL_SCRIPT_URL, data=data_json, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=15) as response:
                res_text = response.read().decode('utf-8')
                print(f"✅ EXITO: Correo enviado a {email_destino} vía urllib. Respuesta: {res_text}")
                return True

    except Exception as e:
        print(f"❌ Error en envío vía Google Script: {e}")
        traceback.print_exc()
        return False


# 🎫📧 Notificaciones por correo de Tickets: reutiliza el mismo webhook de Apps Script que ya
# usa la recuperación de contraseña. Se llama siempre en un hilo aparte (threading.Thread)
# desde las rutas de tickets para no hacer esperar al usuario a que el correo salga.
def enviar_correo_ticket(email_destino, asunto, cuerpo):
    if not email_destino:
        return False
    try:
        payload = {"para": email_destino, "asunto": asunto, "cuerpo": cuerpo}
        if requests:
            res = requests.post(GMAIL_SCRIPT_URL, json=payload, timeout=15)
            print(f"✅ Correo de ticket enviado a {email_destino}. Status: {res.status_code}")
        else:
            data_json = json.dumps(payload).encode('utf-8')
            req = urllib.request.Request(GMAIL_SCRIPT_URL, data=data_json, headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=15) as response:
                response.read()
            print(f"✅ Correo de ticket enviado a {email_destino} vía urllib.")
        return True
    except Exception as e:
        print(f"⚠️ Error enviando correo de ticket a {email_destino}: {e}")
        return False

# 🔑 PASO 1: SOLICITAR CÓDIGO POR CORREO
@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar_clave():
    if request.method == 'POST':
        email_ingresado = request.form.get('email', '').strip().lower()
        print(f"📩 Solicitud de recuperación recibida para: '{email_ingresado}'")
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        query = "SELECT usuario FROM usuarios WHERE LOWER(TRIM(correo)) = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE LOWER(TRIM(correo)) = ?"
        cursor.execute(query, (email_ingresado,))
        user = cursor.fetchone()
        conn.close()

        if user:
            usuario_nombre = user[0]
            codigo_verificacion = str(random.randint(100000, 999999))

            session['reset_email'] = email_ingresado
            session['reset_user'] = usuario_nombre
            session['reset_code'] = codigo_verificacion
            # 🛡️ El código expira a los 10 minutos y se limita el número de intentos de
            # adivinarlo, para que no quede indefinidamente válido ni sea adivinable por fuerza bruta.
            session['reset_code_expira'] = datetime.now(timezone.utc).timestamp() + 600
            session['reset_intentos'] = 0

            threading.Thread(
                target=enviar_correo_recuperacion,
                args=(email_ingresado, usuario_nombre, codigo_verificacion)
            ).start()

            # 🛡️ El código NUNCA se escribe en el log: la tabla logs es visible para
            # cualquier admin en /logs, y dejarlo en texto plano permitiría a otro admin
            # secuestrar la recuperación de un tercero. Solo se envía por correo.
            registrar_log(usuario_nombre, "Solicitud de Código", f"Se generó un código de verificación para: {email_ingresado}")
            return render_template('recuperar.html', paso=2, email=email_ingresado)
        else:
            return render_template('recuperar.html', paso=1, error="El correo ingresado no está registrado en el sistema.")

    return render_template('recuperar.html', paso=1)

# 🔑 PASO 2: VALIDAR CÓDIGO Y CAMBIAR CONTRASEÑA
@app.route('/validar_codigo', methods=['POST'])
def validar_codigo():
    codigo_ingresado = request.form.get('codigo', '').strip()
    nueva_pass = request.form.get('nueva_password', '').strip()

    codigo_correcto = session.get('reset_code')
    email_usuario = session.get('reset_email')
    nombre_usuario = session.get('reset_user')
    expira = session.get('reset_code_expira')

    if not codigo_correcto or not email_usuario:
        return render_template('recuperar.html', paso=1, error="La sesión expiró. Por favor solicita un nuevo código.")

    # 🛡️ Código vencido (10 minutos desde que se generó): obliga a pedir uno nuevo.
    if not expira or datetime.now(timezone.utc).timestamp() > expira:
        session.pop('reset_code', None)
        session.pop('reset_email', None)
        session.pop('reset_user', None)
        session.pop('reset_code_expira', None)
        session.pop('reset_intentos', None)
        return render_template('recuperar.html', paso=1, error="El código de verificación expiró. Solicita uno nuevo.")

    if codigo_ingresado != codigo_correcto:
        # 🛡️ Límite de intentos: tras 5 códigos incorrectos se invalida y hay que pedir uno nuevo,
        # para que un código de 6 dígitos no quede expuesto a fuerza bruta ilimitada.
        intentos = session.get('reset_intentos', 0) + 1
        session['reset_intentos'] = intentos
        if intentos >= 5:
            session.pop('reset_code', None)
            session.pop('reset_email', None)
            session.pop('reset_user', None)
            session.pop('reset_code_expira', None)
            session.pop('reset_intentos', None)
            return render_template('recuperar.html', paso=1, error="Demasiados intentos fallidos. Solicita un nuevo código.")
        return render_template('recuperar.html', paso=2, email=email_usuario, error="El código de verificación es incorrecto.")

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        nuevo_hash = generate_password_hash(nueva_pass)
        # 🛡️ Se filtra por correo Y por el usuario que resolvió el paso 1: si en el futuro
        # dos cuentas volvieran a compartir el mismo correo, esto evita que una sola
        # recuperación cambie la clave de todas a la vez.
        q_upd = "UPDATE usuarios SET password_hash = %s WHERE LOWER(TRIM(correo)) = %s AND usuario = %s" if db_type == 'postgres' else "UPDATE usuarios SET password_hash = ? WHERE LOWER(TRIM(correo)) = ? AND usuario = ?"
        cursor.execute(q_upd, (nuevo_hash, email_usuario, nombre_usuario))
        conn.commit()
        conn.close()

        session.pop('reset_code', None)
        session.pop('reset_email', None)
        session.pop('reset_user', None)
        session.pop('reset_code_expira', None)
        session.pop('reset_intentos', None)

        registrar_log(nombre_usuario, "Cambio Exitoso de Clave", "Se actualizó la clave vía código de verificación.")
        return render_template('recuperar.html', paso=1, exito="¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.")

    except Exception as e:
        conn.rollback()
        conn.close()
        return render_template('recuperar.html', paso=2, email=email_usuario, error="Ocurrió un error al actualizar la contraseña.")

# 🔑 LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            username = request.form.get('usuario') or request.form.get('username') or ''
            password = request.form.get('contrasena') or request.form.get('password') or ''
            recaptcha_response = request.form.get('g-recaptcha-response')

            if not verificar_recaptcha(recaptcha_response):
                return render_template('login.html', error="Por favor, marca la casilla 'No soy un robot'.")

            try:
                conn, db_type = get_db()
                cursor = conn.cursor()
                query = "SELECT usuario, password_hash, rol, estado, tema FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(%s))" if db_type == 'postgres' else "SELECT usuario, password_hash, rol, estado, tema FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(?))"
                cursor.execute(query, (username,))
                user = cursor.fetchone()
                conn.close()

                clave_db = str(user[1] or '') if user else ''
                es_valida = False
                if user:
                    if clave_db.startswith('pbkdf2:') or clave_db.startswith('scrypt:'):
                        es_valida = check_password_hash(clave_db, password)
                    else:
                        # Contraseña vieja guardada en texto plano: valida por compatibilidad
                        # y de una vez la re-guarda ya hasheada para dejar de usar texto plano.
                        # compare_digest en vez de == : evita que el tiempo de respuesta filtre,
                        # carácter por carácter, cuánto de la contraseña coincidió (timing attack).
                        es_valida = hmac.compare_digest(clave_db, password)
                        if es_valida:
                            _migrar_password_a_hash(user[0], password)

                if es_valida:
                    # ⚠️ user[3] es la columna "estado" (activo/inactivo). Un usuario bloqueado
                    # por un administrador no debe poder iniciar sesión aunque su clave sea correcta.
                    if (user[3] or 'activo') == 'inactivo':
                        registrar_log(user[0], "Inicio de Sesión Bloqueado", "Intento de acceso de una cuenta desactivada.")
                        return render_template('login.html', error="Tu cuenta ha sido desactivada. Contacta a un administrador.")
                    session.permanent = True
                    session['logged_in'] = True
                    session['username'] = user[0]
                    session['rol'] = user[2]
                    session['instance_id'] = SERVER_INSTANCE_ID
                    session['tema'] = user[4] or 'oscuro'
                    registrar_log(user[0], "Inicio de Sesión", "Inicio de sesión exitoso")
                    return redirect(url_for('bienvenida'))
            except Exception as db_err:
                print(f"Error consultando usuario en BD: {db_err}")

            return render_template('login.html', error="Usuario o contraseña incorrectos.")

        except Exception as e:
            print(f"Error general en login: {e}")
            return render_template('login.html', error="Ocurrió un error en el servidor. Por favor intenta de nuevo.")

    mensaje_expirado = "⚠️ Tu sesión ha expirado. Por favor ingresa nuevamente." if request.args.get('expirado') == '1' else None
    return render_template('login.html', mensaje_expirado=mensaje_expirado)

# 📊 RUTAS DE MÉTRICAS
@app.route('/incrementar_vista/<galeria_id>', methods=['POST'])
@csrf.exempt
@login_required
def incrementar_vista(galeria_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (galeria_id,))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200

@app.route('/incrementar_descarga/<galeria_id>', methods=['POST'])
@csrf.exempt
@login_required
def incrementar_descarga(galeria_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        
        q_tit = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_tit, (galeria_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q = "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (galeria_id,))
        conn.commit()
        conn.close()

        usuario_actual = session.get('username', 'Anónimo')
        registrar_log(usuario_actual, "Descarga de Archivo", f"El usuario descargó material del instructivo: '{titulo}'")

        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200

# 🛡️ Dominios de Cloudinary a los que este proxy tiene permitido conectarse.
# Cualquier otro destino se rechaza ANTES de hacer la petición saliente: sin esto,
# /pdf_proxy podía usarse como SSRF hacia servidores externos, y si esos servidores
# respondían 401, la app terminaba reenviando las credenciales reales de Cloudinary.
DOMINIOS_CLOUDINARY_PERMITIDOS = {'res.cloudinary.com', 'res-console.cloudinary.com'}


def _url_cloudinary_valida(url):
    try:
        partes = urllib.parse.urlparse(url)
    except Exception:
        return False
    return (
        partes.scheme == 'https'
        and (partes.hostname or '').lower() in DOMINIOS_CLOUDINARY_PERMITIDOS
    )


# 🚀 PROXY AUTENTICADO
@app.route('/pdf_proxy')
@login_required
def pdf_proxy():
    url_target = request.args.get('url')
    download_flag = request.args.get('download', '0')
    filename_custom = request.args.get('name', '')

    if not url_target:
        return "URL requerida", 400

    try:
        if not filename_custom:
            filename_custom = url_target.split('/')[-1]

        clean_url = url_target.replace('/fl_attachment/', '/').replace('/upload/fl_attachment/', '/upload/')

        # 🛡️ Bloquea SSRF: solo se permite reenviar la petición si el destino final
        # es realmente Cloudinary. Sin esta validación, cualquier usuario autenticado
        # podía apuntar "url" a un servidor propio y capturar las credenciales de
        # Cloudinary (ver comentario de DOMINIOS_CLOUDINARY_PERMITIDOS arriba).
        if not _url_cloudinary_valida(clean_url):
            usuario_actual = session.get('username', 'Anónimo')
            registrar_log(usuario_actual, "Intento de Proxy Bloqueado", f"URL no permitida (no es Cloudinary): {url_target[:200]}")
            return "URL no permitida: este proxy solo puede usarse para documentos alojados en Cloudinary.", 400

        if download_flag == '1':
            usuario_actual = session.get('username', 'Anónimo')
            registrar_log(usuario_actual, "Descarga de Documento", f"Archivo: '{filename_custom}'")

        disposition = 'attachment' if download_flag == '1' else 'inline'

        fname_lower = filename_custom.lower()
        if fname_lower.endswith('.png'):
            content_type = 'image/png'
        elif fname_lower.endswith(('.jpg', '.jpeg')):
            content_type = 'image/jpeg'
        elif fname_lower.endswith('.gif'):
            content_type = 'image/gif'
        elif fname_lower.endswith('.webp'):
            content_type = 'image/webp'
        elif fname_lower.endswith(('.mp4', '.mov', '.webm', '.avi')):
            content_type = 'video/mp4'
        elif fname_lower.endswith(('.zip', '.rar', '.7z', '.tar', '.gz')):
            content_type = 'application/zip'
        else:
            content_type = 'application/pdf'

        headers = {
            'Content-Type': content_type,
            'Content-Disposition': f'{disposition}; filename="{filename_custom}"'
        }

        # 🚿 STREAMING: para videos/PDFs grandes, no cargamos el archivo completo en
        # memoria (eso podía colgar el worker o agotar la RAM en Render con archivos
        # pesados, dejando la previsualización/descarga en blanco o con error).
        # Se transmite en bloques directamente desde Cloudinary hacia el navegador.
        if requests:
            upstream = requests.get(clean_url, timeout=(10, 60), stream=True)
            if upstream.status_code == 401:
                api_key = os.environ.get('CLOUDINARY_API_KEY')
                api_secret = os.environ.get('CLOUDINARY_API_SECRET')
                if api_key and api_secret:
                    upstream = requests.get(clean_url, auth=(api_key, api_secret), timeout=(10, 60), stream=True)

            if upstream.status_code >= 400:
                return f"Error obteniendo documento: el origen respondió {upstream.status_code}", 502

            content_length = upstream.headers.get('Content-Length')
            if content_length:
                headers['Content-Length'] = content_length

            def _generar():
                try:
                    for chunk in upstream.iter_content(chunk_size=65536):
                        if chunk:
                            yield chunk
                finally:
                    upstream.close()

            return Response(stream_with_context(_generar()), headers=headers, status=200)
        else:
            req = urllib.request.Request(clean_url)
            with urllib.request.urlopen(req) as response:
                content_data = response.read()
            return Response(content_data, headers=headers, status=200)
    except Exception as e:
        return f"Error obteniendo documento: {e}", 500

def _estado_rotacion_credencial(rotacion_dias, fecha_ultima_rotacion):
    """Calcula si a una credencial ya le toca rotar la contraseña, según su política opcional
    (rotacion_dias) y la fecha del último cambio. Devuelve None si no tiene política configurada
    — esa credencial simplemente no se hace seguimiento de rotación."""
    if not rotacion_dias:
        return None
    fecha_base = _parsear_fecha_ticket(fecha_ultima_rotacion)
    if not fecha_base:
        return {'vencida': False, 'dias_transcurridos': 0, 'dias_limite': rotacion_dias}
    ahora = datetime.now(ZONA_HORARIA_COLOMBIA).replace(tzinfo=None)
    dias_transcurridos = (ahora - fecha_base).days
    return {
        'vencida': dias_transcurridos >= rotacion_dias,
        'dias_transcurridos': dias_transcurridos,
        'dias_limite': rotacion_dias
    }


def _revisar_recordatorios_rotacion():
    """Recordatorio automático (una vez por ciclo) de rotación de contraseñas vencida: avisa por
    campanita/correo a todo el equipo de soporte activo. Se limpia (puede volver a avisar) en
    cuanto se cambia esa contraseña desde editar_credencial. Se llama de forma perezosa cada vez
    que se visita la bóveda o la Auditoría — nunca debe tumbar esa página si algo falla."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT id, titulo, rotacion_dias, fecha_ultima_rotacion FROM credenciales WHERE COALESCE(estado, 'activo') = 'activo' AND rotacion_dias IS NOT NULL AND rotacion_recordatorio_fecha IS NULL")
        filas = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error revisando recordatorios de rotación: {e}")
        return

    for cred_id, titulo, rotacion_dias, fecha_ultima_rotacion in filas:
        estado = _estado_rotacion_credencial(rotacion_dias, fecha_ultima_rotacion)
        if not estado or not estado['vencida']:
            continue

        equipo = _equipo_soporte_activo()
        url_cred = url_for('ver_credenciales')
        mensaje = f"🔐 Toca rotar la contraseña de '{titulo}' (política de {rotacion_dias} días)"
        asunto = f"[Arkiv] Rotación de contraseña pendiente: '{titulo}'"
        cuerpo = (
            f"La credencial '{titulo}' en la bóveda de Arkiv ya superó su política de rotación "
            f"({rotacion_dias} días sin cambiarse). Por seguridad, cambia esa contraseña y actualízala en Arkiv.\n\n---\nArkiv"
        )
        crear_notificacion_para_varios([m['usuario'] for m in equipo], mensaje, url=url_cred, tipo='credencial')
        for miembro in equipo:
            if miembro['correo']:
                threading.Thread(target=enviar_correo_ticket, args=(miembro['correo'], asunto, cuerpo)).start()

        try:
            conn, db_type = get_db()
            cursor = conn.cursor()
            fecha_act = obtener_fecha_actual()
            q = "UPDATE credenciales SET rotacion_recordatorio_fecha = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET rotacion_recordatorio_fecha = ? WHERE id = ?"
            cursor.execute(q, (fecha_act, cred_id))
            conn.commit()
            conn.close()
        except Exception as e:
            print(f"⚠️ Error marcando recordatorio de rotación de la credencial {cred_id}: {e}")


# 🔑 MÓDULO BÓVEDA DE CREDENCIALES
@app.route('/credenciales')
@login_required
@agente_o_admin_required
def ver_credenciales():
    # 🔐 Aviso perezoso de rotación de contraseñas vencida — ver _revisar_recordatorios_rotacion().
    _revisar_recordatorios_rotacion()

    q_busqueda = request.args.get('q', '').strip().lower()

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        # 🔒 Ya NO se trae ni se descifra password_cifrada aquí: la clave en texto plano solo
        # se entrega a demanda, vía /credenciales/<id>/revelar, para que la auditoría de accesos
        # registre consultas reales y no simplemente "abrió la página".
        cursor.execute("SELECT id, titulo, url_acceso, usuario_acceso, area, notas, fecha_creacion, rotacion_dias, fecha_ultima_rotacion FROM credenciales WHERE COALESCE(estado, 'activo') != 'eliminado' ORDER BY titulo ASC")
        rows = cursor.fetchall()
    except Exception:
        rows = []

    conn.close()

    lista_credenciales = []
    for r in rows:
        try:
            c_id, servicio, url, usuario, categoria, notas, fecha, rotacion_dias, fecha_ultima_rotacion = r
            texto_full = f"{servicio} {usuario} {categoria} {notas}".lower()
            if not q_busqueda or q_busqueda in texto_full:
                lista_credenciales.append({
                    'id': c_id,
                    'servicio': servicio,
                    'url': url or '',
                    'usuario': usuario,
                    'categoria': categoria or 'General',
                    'notas': notas or '',
                    'fecha': fecha,
                    'rotacion_dias': rotacion_dias,
                    'rotacion': _estado_rotacion_credencial(rotacion_dias, fecha_ultima_rotacion)
                })
        except Exception as e_row:
            # No dejar que una fila con datos inconsistentes tumbe toda la bóveda.
            print(f"⚠️ Error procesando credencial {r[0] if r else '?'}: {e_row}")
            continue

    return render_template('credenciales.html', credenciales=lista_credenciales, q_busqueda=q_busqueda)


@app.route('/credenciales/<int:cred_id>/revelar', methods=['POST'])
@login_required
@agente_o_admin_required
def revelar_credencial(cred_id):
    """Descifra la clave de una credencial puntual, a demanda, y deja constancia en el log
    general (con credencial_id) de quién la consultó/copió y cuándo — la base de la Auditoría
    de Accesos."""
    accion = request.form.get('accion', 'ver')
    accion_legible = 'copió' if accion == 'copiar' else 'vio'
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT titulo, password_cifrada FROM credenciales WHERE id = %s" if db_type == 'postgres' else "SELECT titulo, password_cifrada FROM credenciales WHERE id = ?"
        cursor.execute(q, (cred_id,))
        row = cursor.fetchone()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error consultando credencial {cred_id} para revelar: {e}")
        return jsonify({'error': 'error interno'}), 500

    if not row:
        return jsonify({'error': 'no encontrada'}), 404

    titulo, pass_enc = row
    pass_real = desencriptar_texto(pass_enc, cred_id)
    registrar_log(session.get('username'), "Consulta de Credencial", f"Se {accion_legible} la clave de '{titulo}' (ID {cred_id})", credencial_id=cred_id)
    return jsonify({'password': pass_real})


@app.route('/credenciales/auditoria')
@login_required
@agente_o_admin_required
def auditoria_credenciales():
    """Panel de auditoría de la bóveda: estado de rotación de cada credencial activa (según su
    política opcional) y el historial reciente de consultas/copias de claves — quién, cuál
    credencial y cuándo."""
    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT id, titulo, area, rotacion_dias, fecha_ultima_rotacion FROM credenciales WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY titulo ASC")
        filas_cred = cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Error listando credenciales para auditoría: {e}")
        filas_cred = []

    rotacion = []
    for c_id, titulo, area, rotacion_dias, fecha_ultima_rotacion in filas_cred:
        rotacion.append({
            'id': c_id, 'titulo': titulo, 'area': area or 'General',
            'rotacion_dias': rotacion_dias,
            'estado': _estado_rotacion_credencial(rotacion_dias, fecha_ultima_rotacion)
        })
    # Vencidas primero, luego con política vigente, luego sin política configurada.
    rotacion.sort(key=lambda c: (0 if (c['estado'] and c['estado']['vencida']) else (1 if c['estado'] else 2), c['titulo']))

    try:
        cursor.execute("SELECT usuario, detalles, fecha, credencial_id FROM logs WHERE credencial_id IS NOT NULL ORDER BY id DESC LIMIT 200")
        filas_log = cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Error listando accesos a credenciales: {e}")
        filas_log = []
    conn.close()

    accesos = [{'usuario': u, 'detalles': d, 'fecha': f, 'credencial_id': cid} for u, d, f, cid in filas_log]

    return render_template('credenciales_auditoria.html', rotacion=rotacion, accesos=accesos)

@app.route('/credenciales/crear', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_credencial():
    servicio = request.form.get('servicio', '').strip()
    url = request.form.get('url', '').strip()
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '').strip()
    categoria = request.form.get('categoria', 'General').strip()
    notas = request.form.get('notas', '').strip()
    rotacion_dias = _parsear_dias_rotacion(request.form.get('rotacion_dias', ''))

    if servicio and usuario and password:
        try:
            pass_cifrada = encriptar_texto(password)
            fecha_act = obtener_fecha_actual()

            conn, db_type = get_db()
            cursor = conn.cursor()
            # 🔁 fecha_ultima_rotacion arranca igual a fecha_creacion: recién guardada, la
            # clave "acaba de rotarse" para efectos del recordatorio de rotación.
            q_ins = "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, rotacion_dias, fecha_ultima_rotacion) VALUES (%s, %s, %s, %s, %s, %s, %s, 'activo', %s, %s)" if db_type == 'postgres' else "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado, rotacion_dias, fecha_ultima_rotacion) VALUES (?, ?, ?, ?, ?, ?, ?, 'activo', ?, ?)"
            cursor.execute(q_ins, (servicio, url, usuario, pass_cifrada, categoria, notas, fecha_act, rotacion_dias, fecha_act))
            conn.commit()
            conn.close()

            registrar_log(session['username'], "Guardado de Credencial", f"Se registró el acceso para el aplicativo '{servicio}'")
        except Exception as e:
            print(f"⚠️ Error guardando credencial '{servicio}': {e}")

    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/editar/<int:cred_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_credencial(cred_id):
    servicio = request.form.get('servicio', '').strip()
    url = request.form.get('url', '').strip()
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '').strip()
    categoria = request.form.get('categoria', 'General').strip()
    notas = request.form.get('notas', '').strip()
    rotacion_dias = _parsear_dias_rotacion(request.form.get('rotacion_dias', ''))

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        if password:
            # 🔁 Se cambió la clave de verdad: cuenta como una rotación — se actualiza
            # fecha_ultima_rotacion a ahora y se limpia el recordatorio ya enviado, para que
            # el próximo aviso de "toca rotar" se calcule desde este momento en adelante.
            pass_cifrada = encriptar_texto(password)
            fecha_act = obtener_fecha_actual()
            q_upd = "UPDATE credenciales SET titulo=%s, url_acceso=%s, usuario_acceso=%s, password_cifrada=%s, area=%s, notas=%s, rotacion_dias=%s, fecha_ultima_rotacion=%s, rotacion_recordatorio_fecha=NULL WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url_acceso=?, usuario_acceso=?, password_cifrada=?, area=?, notas=?, rotacion_dias=?, fecha_ultima_rotacion=?, rotacion_recordatorio_fecha=NULL WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, pass_cifrada, categoria, notas, rotacion_dias, fecha_act, cred_id))
        else:
            q_upd = "UPDATE credenciales SET titulo=%s, url_acceso=%s, usuario_acceso=%s, area=%s, notas=%s, rotacion_dias=%s WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url_acceso=?, usuario_acceso=?, area=?, notas=?, rotacion_dias=? WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, categoria, notas, rotacion_dias, cred_id))

        conn.commit()
        registrar_log(session['username'], "Edición de Credencial", f"Se actualizó la credencial ID '{cred_id}' ({servicio})")
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Error editando credencial {cred_id}: {e}")

    conn.close()
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/eliminar/<int:cred_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    q_upd = "UPDATE credenciales SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET estado = 'eliminado' WHERE id = ?"
    cursor.execute(q_upd, (cred_id,))
    conn.commit()
    conn.close()
    
    registrar_log(session['username'], "Eliminación de Credencial", f"Se envió a la papelera la credencial ID '{cred_id}'")
    return redirect(url_for('ver_credenciales'))


# 🪪 MÓDULO ALTAS Y BAJAS DE CREDENCIALES DE COLABORADORES — bitácora de qué credenciales se
# le crean a cada colaborador nuevo (o existente) en cada aplicativo institucional (KUBAPP,
# SAMI, Moodle, Wolkvox, Correo, Solvyx...), quién las gestionó/capacitó y por qué medio se
# entregaron. Es un registro por aplicativo (no por colaborador), para poder dar de baja el
# acceso a uno puntual sin afectar los demás que tenga esa misma persona. Distinto de la
# Bóveda de Accesos (que guarda credenciales de sistemas/servidores para el equipo de soporte).
MEDIOS_ENVIO_CREDENCIAL = ('WhatsApp', 'Correo', 'SMS', 'Chat Teams')


def _catalogo_aplicativos_activos():
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id, nombre FROM aplicativos_catalogo WHERE COALESCE(estado, 'activo') = 'activo' ORDER BY nombre ASC")
        filas = cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Error listando catálogo de aplicativos: {e}")
        filas = []
    conn.close()
    return [{'id': f[0], 'nombre': f[1]} for f in filas]


@app.route('/credenciales/colaboradores')
@login_required
@agente_o_admin_required
def ver_credenciales_colaboradores():
    q_busqueda = request.args.get('q', '').strip().lower()
    f_aplicativo = request.args.get('aplicativo', '').strip()
    f_estado = request.args.get('estado', 'activo').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT id, colaborador, aplicativo, fecha_creacion, fecha_solicitud, analista_gestiona, "
            "solicitado_por, capacitado_por, medio_envio, estado, fecha_deshabilitacion, deshabilitado_por "
            "FROM credenciales_colaboradores ORDER BY id DESC"
        )
        filas = cursor.fetchall()
    except Exception as e:
        print(f"⚠️ Error listando credenciales de colaboradores: {e}")
        filas = []
    conn.close()

    registros = []
    aplicativos_en_uso = set()
    for r in filas:
        (r_id, colaborador, aplicativo, fecha_creacion, fecha_solicitud, analista_gestiona,
         solicitado_por, capacitado_por, medio_envio, estado, fecha_deshabilitacion, deshabilitado_por) = r
        aplicativos_en_uso.add(aplicativo)

        if f_estado and f_estado != 'todos' and estado != f_estado:
            continue
        if f_aplicativo and aplicativo != f_aplicativo:
            continue
        if q_busqueda and q_busqueda not in f"{colaborador} {aplicativo} {solicitado_por or ''}".lower():
            continue

        registros.append({
            'id': r_id, 'colaborador': colaborador, 'aplicativo': aplicativo,
            'fecha_creacion': fecha_creacion, 'fecha_solicitud': fecha_solicitud,
            'analista_gestiona': analista_gestiona, 'solicitado_por': solicitado_por,
            'capacitado_por': capacitado_por, 'medio_envio': medio_envio, 'estado': estado,
            'fecha_deshabilitacion': fecha_deshabilitacion, 'deshabilitado_por': deshabilitado_por
        })

    conn2, db_type2 = get_db()
    cursor2 = conn2.cursor()
    try:
        cursor2.execute(
            "SELECT usuario, nombre FROM usuarios WHERE COALESCE(estado, 'activo') = 'activo' "
            "AND rol IN ('admin', 'agente') ORDER BY nombre ASC"
        )
        equipo_soporte = [{'usuario': r[0], 'nombre': r[1] or r[0]} for r in cursor2.fetchall()]
    except Exception as e:
        print(f"⚠️ Error listando equipo de soporte para altas de credenciales: {e}")
        equipo_soporte = []
    conn2.close()

    conn3, db_type3 = get_db()
    cursor3 = conn3.cursor()
    try:
        # 📋 Nombres de colaboradores ya registrados antes (en cualquier aplicativo), para que
        # el campo "Colaborador" del modal sugiera autocompletar en vez de obligar a retipear el
        # nombre completo cada vez que a la misma persona se le da de alta un acceso más. Sigue
        # siendo texto libre: si la persona es nueva, se puede escribir un nombre que no esté aquí.
        cursor3.execute("SELECT DISTINCT colaborador FROM credenciales_colaboradores ORDER BY colaborador ASC")
        colaboradores_existentes = [r[0] for r in cursor3.fetchall() if r[0]]
    except Exception as e:
        print(f"⚠️ Error listando colaboradores existentes para autocompletar: {e}")
        colaboradores_existentes = []
    conn3.close()

    return render_template(
        'credenciales_colaboradores.html', registros=registros,
        aplicativos=_catalogo_aplicativos_activos(), medios=MEDIOS_ENVIO_CREDENCIAL,
        q_busqueda=q_busqueda, f_aplicativo=f_aplicativo, f_estado=f_estado,
        equipo_soporte=equipo_soporte, colaboradores_existentes=colaboradores_existentes
    )


@app.route('/credenciales/colaboradores/crear', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_credencial_colaborador():
    colaborador = request.form.get('colaborador', '').strip()
    aplicativo = request.form.get('aplicativo', '').strip()
    password = request.form.get('password', '').strip()
    fecha_creacion = request.form.get('fecha_creacion', '').strip() or None
    fecha_solicitud = request.form.get('fecha_solicitud', '').strip() or None
    analista_gestiona = request.form.get('analista_gestiona', '').strip() or None
    solicitado_por = request.form.get('solicitado_por', '').strip() or None
    capacitado_por = request.form.get('capacitado_por', '').strip() or None
    medio_envio = request.form.get('medio_envio', '').strip() or None
    if medio_envio not in MEDIOS_ENVIO_CREDENCIAL:
        medio_envio = None

    if colaborador and aplicativo and password:
        try:
            pass_cifrada = encriptar_texto(password)
            fecha_act = obtener_fecha_actual()
            conn, db_type = get_db()
            cursor = conn.cursor()
            q_ins = (
                "INSERT INTO credenciales_colaboradores (colaborador, aplicativo, password_cifrada, fecha_creacion, "
                "fecha_solicitud, analista_gestiona, solicitado_por, capacitado_por, medio_envio, estado, "
                "fecha_registro, registrado_por) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'activo', %s, %s)"
                if db_type == 'postgres' else
                "INSERT INTO credenciales_colaboradores (colaborador, aplicativo, password_cifrada, fecha_creacion, "
                "fecha_solicitud, analista_gestiona, solicitado_por, capacitado_por, medio_envio, estado, "
                "fecha_registro, registrado_por) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'activo', ?, ?)"
            )
            cursor.execute(q_ins, (colaborador, aplicativo, pass_cifrada, fecha_creacion, fecha_solicitud,
                                    analista_gestiona, solicitado_por, capacitado_por, medio_envio,
                                    fecha_act, session.get('username')))
            conn.commit()
            conn.close()
            registrar_log(session.get('username'), "Alta de Credencial de Colaborador",
                          f"Se creó la credencial de '{aplicativo}' para {colaborador}")
        except Exception as e:
            print(f"⚠️ Error creando credencial de colaborador '{colaborador}'/{aplicativo}: {e}")

    return redirect(url_for('ver_credenciales_colaboradores'))


@app.route('/credenciales/colaboradores/<int:reg_id>/deshabilitar', methods=['POST'])
@login_required
@agente_o_admin_required
def deshabilitar_credencial_colaborador(reg_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha_act = obtener_fecha_actual()
        q = (
            "UPDATE credenciales_colaboradores SET estado = 'deshabilitado', fecha_deshabilitacion = %s, deshabilitado_por = %s WHERE id = %s"
            if db_type == 'postgres' else
            "UPDATE credenciales_colaboradores SET estado = 'deshabilitado', fecha_deshabilitacion = ?, deshabilitado_por = ? WHERE id = ?"
        )
        cursor.execute(q, (fecha_act, session.get('username'), reg_id))
        conn.commit()
        conn.close()
        registrar_log(session.get('username'), "Baja de Credencial de Colaborador", f"Se deshabilitó la credencial ID {reg_id}")
    except Exception as e:
        print(f"⚠️ Error deshabilitando credencial de colaborador {reg_id}: {e}")
    return redirect(url_for('ver_credenciales_colaboradores'))


@app.route('/credenciales/colaboradores/<int:reg_id>/reactivar', methods=['POST'])
@login_required
@agente_o_admin_required
def reactivar_credencial_colaborador(reg_id):
    """Vuelve a 'activo' una fila de Altas de Credenciales que había quedado 'deshabilitado' —
    flujo simétrico al de deshabilitar. Limpia fecha_deshabilitacion/deshabilitado_por para que
    la fila quede exactamente como si nunca se hubiera dado de baja."""
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_sel = "SELECT colaborador, aplicativo FROM credenciales_colaboradores WHERE id = %s" if db_type == 'postgres' else "SELECT colaborador, aplicativo FROM credenciales_colaboradores WHERE id = ?"
        cursor.execute(q_sel, (reg_id,))
        row = cursor.fetchone()
        colaborador = row[0] if row else f"ID {reg_id}"
        aplicativo = row[1] if row else ""

        q_upd = (
            "UPDATE credenciales_colaboradores SET estado = 'activo', fecha_deshabilitacion = NULL, deshabilitado_por = NULL WHERE id = %s"
            if db_type == 'postgres' else
            "UPDATE credenciales_colaboradores SET estado = 'activo', fecha_deshabilitacion = NULL, deshabilitado_por = NULL WHERE id = ?"
        )
        cursor.execute(q_upd, (reg_id,))
        conn.commit()
        conn.close()
        registrar_log(session.get('username'), "Reactivación de Credencial de Colaborador", f"Se reactivó el acceso a '{aplicativo}' de {colaborador} (ID {reg_id})")
    except Exception as e:
        print(f"⚠️ Error reactivando credencial de colaborador {reg_id}: {e}")
    return redirect(url_for('ver_credenciales_colaboradores'))


@app.route('/credenciales/colaboradores/<int:reg_id>/revelar', methods=['POST'])
@login_required
@agente_o_admin_required
def revelar_credencial_colaborador(reg_id):
    """Descifra a demanda la clave de una credencial de colaborador puntual y deja constancia
    en el log general de quién la consultó/copió — misma idea que /credenciales/<id>/revelar
    para la Bóveda de Accesos."""
    accion = request.form.get('accion', 'ver')
    accion_legible = 'copió' if accion == 'copiar' else 'vio'
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "SELECT colaborador, aplicativo, password_cifrada FROM credenciales_colaboradores WHERE id = %s" if db_type == 'postgres' else "SELECT colaborador, aplicativo, password_cifrada FROM credenciales_colaboradores WHERE id = ?"
        cursor.execute(q, (reg_id,))
        row = cursor.fetchone()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error consultando credencial de colaborador {reg_id} para revelar: {e}")
        return jsonify({'error': 'error interno'}), 500

    if not row:
        return jsonify({'error': 'no encontrada'}), 404

    colaborador, aplicativo, pass_enc = row
    pass_real = desencriptar_texto(pass_enc)
    registrar_log(session.get('username'), "Consulta de Credencial de Colaborador",
                  f"Se {accion_legible} la clave de '{aplicativo}' de {colaborador} (ID {reg_id})")
    return jsonify({'password': pass_real})


@app.route('/credenciales/colaboradores/aplicativos/crear', methods=['POST'])
@login_required
@agente_o_admin_required
def crear_aplicativo_catalogo():
    nombre = request.form.get('nombre', '').strip()
    if nombre:
        conn, db_type = get_db()
        cursor = conn.cursor()
        try:
            q = "INSERT INTO aplicativos_catalogo (nombre) VALUES (%s)" if db_type == 'postgres' else "INSERT INTO aplicativos_catalogo (nombre) VALUES (?)"
            cursor.execute(q, (nombre,))
            conn.commit()
            registrar_log(session.get('username'), "Catálogo de Aplicativos", f"Se agregó el aplicativo '{nombre}'")
        except Exception as e:
            conn.rollback()
            print(f"⚠️ Error agregando aplicativo '{nombre}': {e}")
        conn.close()
    return redirect(url_for('ver_credenciales_colaboradores'))


@app.route('/credenciales/colaboradores/aplicativos/<int:app_id>/eliminar', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_aplicativo_catalogo(app_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "UPDATE aplicativos_catalogo SET estado = 'inactivo' WHERE id = %s" if db_type == 'postgres' else "UPDATE aplicativos_catalogo SET estado = 'inactivo' WHERE id = ?"
        cursor.execute(q, (app_id,))
        conn.commit()
        registrar_log(session.get('username'), "Catálogo de Aplicativos", f"Se desactivó el aplicativo ID {app_id}")
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Error desactivando aplicativo {app_id}: {e}")
    conn.close()
    return redirect(url_for('ver_credenciales_colaboradores'))


# ♻️ MÓDULO PAPELERA DE RECICLAJE
@app.route('/papelera')
@login_required
@agente_o_admin_required
def ver_papelera():
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, titulo, descripcion, fecha_subida, categoria, tipo FROM galerias WHERE estado = 'eliminado' ORDER BY fecha_subida DESC")
        eliminados = cursor.fetchall()
    except Exception:
        eliminados = []

    try:
        query_arch_elim = """
            SELECT a.id, COALESCE(a.filename, a.url_archivo), g.id, g.titulo, g.categoria
            FROM archivos a
            JOIN galerias g ON a.galeria_id = g.id
            WHERE a.estado = 'eliminado' AND COALESCE(g.estado, 'activo') != 'eliminado'
        """
        cursor.execute(query_arch_elim)
        archivos_eliminados = cursor.fetchall()
    except Exception:
        archivos_eliminados = []

    try:
        cursor.execute("SELECT id, titulo, usuario_acceso, area, fecha_creacion FROM credenciales WHERE estado = 'eliminado' ORDER BY id DESC")
        credenciales_eliminadas = cursor.fetchall()
    except Exception:
        credenciales_eliminadas = []

    try:
        cursor.execute("SELECT id, titulo, nivel, fecha, autor FROM comunicados WHERE estado = 'eliminado' ORDER BY id DESC")
        rows_com = cursor.fetchall()
    except Exception:
        rows_com = []

    # 👤 Igual que en el Muro de Comunicados: se muestra el alias/nombre real del autor.
    _nombres_papelera = _mapa_nombres_usuarios()
    comunicados_eliminados = [
        {'id': r[0], 'titulo': r[1], 'nivel': r[2], 'fecha': r[3], 'autor': _nombre_para_mostrar(r[4], _nombres_papelera)} for r in rows_com
    ]

    conn.close()
    return render_template(
        'papelera.html',
        eliminados=eliminados,
        archivos_eliminados=archivos_eliminados,
        credenciales_eliminadas=credenciales_eliminadas,
        comunicados_eliminados=comunicados_eliminados
    )

# 🔄 RESTAURAR CREDENCIAL
@app.route('/restaurar_credencial/<int:cred_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def restaurar_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM credenciales WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM credenciales WHERE id = ?"
        cursor.execute(q_sel, (cred_id,))
        row = cursor.fetchone()
        servicio = row[0] if row else f"ID {cred_id}"

        q_upd = "UPDATE credenciales SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (cred_id,))
        conn.commit()

        registrar_log(session['username'], "Restauración de Credencial", f"Se restauró el acceso '{servicio}' desde la papelera.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

# 💥 DESTRUIR CREDENCIAL
@app.route('/destruir_credencial/<int:cred_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def destruir_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM credenciales WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM credenciales WHERE id = ?"
        cursor.execute(q_sel, (cred_id,))
        row = cursor.fetchone()
        servicio = row[0] if row else f"ID {cred_id}"

        q_del = "DELETE FROM credenciales WHERE id = %s" if db_type == 'postgres' else "DELETE FROM credenciales WHERE id = ?"
        cursor.execute(q_del, (cred_id,))
        conn.commit()

        registrar_log(session['username'], "Eliminación Permanente", f"Se destruyó permanentemente la credencial '{servicio}'.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

# 🔄 RESTAURAR INSTRUCTIVO COMPLETO
@app.route('/restaurar_galeria/<galeria_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def restaurar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q_upd = "UPDATE galerias SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (galeria_id,))
        conn.commit()

        registrar_log(session['username'], "Restauración de Instructivo", f"El instructivo '{titulo}' fue restaurado desde la papelera.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

# 💥 BORRADO DEFINITIVO DE INSTRUCTIVO
@app.route('/destruir_galeria/<galeria_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def destruir_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q_del1 = "DELETE FROM galerias WHERE id = %s" if db_type == 'postgres' else "DELETE FROM galerias WHERE id = ?"
        q_del2 = "DELETE FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ?"
        cursor.execute(q_del1, (galeria_id,))
        cursor.execute(q_del2, (galeria_id,))
        conn.commit()

        registrar_log(session['username'], "Eliminación Permanente", f"El instructivo '{titulo}' fue eliminado definitivamente del sistema.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

# 🗑️ BORRADO LÓGICO DE ARCHIVO INDIVIDUAL
@app.route('/eliminar_imagen/<galeria_id>/<path:filename>', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_imagen(galeria_id, filename):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q_upd = "UPDATE archivos SET estado = 'eliminado' WHERE galeria_id = %s AND COALESCE(filename, url_archivo) = %s" if db_type == 'postgres' else "UPDATE archivos SET estado = 'eliminado' WHERE galeria_id = ? AND COALESCE(filename, url_archivo) = ?"
        cursor.execute(q_upd, (galeria_id, filename))
        conn.commit()

        nombre_limpio = filename.split('/')[-1] if 'http' in filename else filename
        registrar_log(session['username'], "Envío a Papelera (Archivo)", f"Se movió el archivo '{nombre_limpio}' del instructivo '{titulo}' a la papelera.")

    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('index'))

# 🔄 RESTAURAR ARCHIVO INDIVIDUAL
@app.route('/restaurar_archivo/<int:archivo_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def restaurar_archivo(archivo_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        query_info = """
            SELECT COALESCE(a.filename, a.url_archivo), g.titulo
            FROM archivos a
            JOIN galerias g ON a.galeria_id = g.id
            WHERE a.id = %s
        """ if db_type == 'postgres' else """
            SELECT COALESCE(a.filename, a.url_archivo), g.titulo
            FROM archivos a
            JOIN galerias g ON a.galeria_id = g.id
            WHERE a.id = ?
        """
        cursor.execute(query_info, (archivo_id,))
        row = cursor.fetchone()

        q_upd = "UPDATE archivos SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE archivos SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (archivo_id,))
        conn.commit()

        if row:
            nombre_limpio = row[0].split('/')[-1] if 'http' in row[0] else row[0]
            registrar_log(session['username'], "Restauración de Archivo", f"Se reintegró el archivo '{nombre_limpio}' al instructivo '{row[1]}'.")

    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

# 💥 DESTRUIR ARCHIVO INDIVIDUAL PERMANENTEMENTE
@app.route('/destruir_archivo/<int:archivo_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def destruir_archivo(archivo_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM archivos WHERE id = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE id = ?"
        cursor.execute(q_del, (archivo_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación Permanente (Archivo)", f"Se destruyó permanentemente un archivo adjunto ID '{archivo_id}'.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def gestion_usuarios():
    conn, db_type = get_db()
    cursor = conn.cursor()
    error = None
    form_data = None

    if request.method == 'POST':
        primer_nombre = (request.form.get('primer_nombre') or '').strip()
        segundo_nombre = (request.form.get('segundo_nombre') or '').strip()
        primer_apellido = (request.form.get('primer_apellido') or '').strip()
        segundo_apellido = (request.form.get('segundo_apellido') or '').strip()
        nuevo_pass = request.form.get('password') or ''
        nuevo_email = (request.form.get('email') or '').strip()
        nuevo_telefono = (request.form.get('telefono') or '').strip() or None
        nuevo_rol = request.form.get('rol', 'estandar')
        # 🛡️ Solo se aceptan los 3 roles válidos del sistema; cualquier otro valor (enviado a
        # mano, no desde el formulario) cae a 'estandar' por seguridad.
        if nuevo_rol not in ('admin', 'agente', 'estandar'):
            nuevo_rol = 'estandar'
        # 🛡️ Solo la cuenta 'admin' (super-admin) puede otorgar el rol 'admin' a un usuario
        # nuevo. Cualquier otro admin sí puede crear cuentas 'agente' (analistas de soporte
        # TI) libremente, igual que ya podía crear cuentas 'estandar'. Esto evita que un admin
        # cualquiera se cree una cuenta admin "aliada" para sortear las protecciones entre
        # administradores.
        if nuevo_rol == 'admin' and session.get('username') != 'admin':
            nuevo_rol = 'estandar'
        form_data = {
            'primer_nombre': primer_nombre, 'segundo_nombre': segundo_nombre,
            'primer_apellido': primer_apellido, 'segundo_apellido': segundo_apellido,
            'email': nuevo_email, 'rol': nuevo_rol, 'telefono': nuevo_telefono
        }

        if not primer_nombre or not primer_apellido or not nuevo_pass or not nuevo_email:
            error = "Nombre, primer apellido, correo y contraseña son obligatorios para crear un usuario."

        if not error:
            try:
                # 🧑 El nombre de usuario (login) ya NO lo escribe el admin a mano: se genera
                # automáticamente con la estructura "primer nombre + primer apellido" y, si ya
                # existe, se prueban estructuras alternativas hasta encontrar una libre (ver
                # _generar_username_unico). El nombre completo sí se guarda tal cual para
                # mostrarlo en pantalla — antes quedaba vacío ("None") porque este formulario
                # nunca lo pedía.
                nuevo_user = _generar_username_unico(primer_nombre, primer_apellido, segundo_nombre, segundo_apellido)
                nombre_completo = ' '.join(p for p in [primer_nombre, segundo_nombre, primer_apellido, segundo_apellido] if p)
                nuevo_hash = generate_password_hash(nuevo_pass)
                q_ins = "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre, telefono) VALUES (%s, %s, %s, %s, 'activo', %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado, nombre, telefono) VALUES (?, ?, ?, ?, 'activo', ?, ?)"
                cursor.execute(q_ins, (nuevo_user, nuevo_hash, nuevo_email, nuevo_rol, nombre_completo, nuevo_telefono))
                conn.commit()
                registrar_log(session['username'], "Creación de Usuario", f"Usuario '{nuevo_user}' ({nombre_completo}) [{nuevo_rol}]")
                conn.close()
                return redirect(url_for('gestion_usuarios', creado=nuevo_user))
            except Exception as e:
                conn.rollback()
                error = "No se pudo crear el usuario. Verifica los datos e intenta de nuevo."

    # 🛡️ La cuenta 'admin' queda oculta del listado para el resto de administradores: solo
    # la propia sesión de 'admin' la ve. El resto de admins no sabe que existe esta fila.
    if session.get('username') == 'admin':
        cursor.execute("SELECT id, usuario, correo, rol, estado, nombre, telefono FROM usuarios ORDER BY id ASC")
    else:
        cursor.execute("SELECT id, usuario, correo, rol, estado, nombre, telefono FROM usuarios WHERE usuario != 'admin' ORDER BY id ASC")
    lista_usuarios = cursor.fetchall()
    conn.close()
    usuario_creado = request.args.get('creado', '').strip()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda="", error=error, form_data=form_data, usuario_creado=usuario_creado)

# ✏️ EDITAR USUARIO
@app.route('/editar_usuario/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def editar_usuario(usuario_id):
    nuevo_email = request.form.get('email', '').strip()
    nuevo_rol = request.form.get('rol', 'estandar').strip()
    if nuevo_rol not in ('admin', 'agente', 'estandar'):
        nuevo_rol = 'estandar'
    nueva_pass = request.form.get('password', '').strip()
    nuevo_nombre = request.form.get('nombre', '').strip()
    nuevo_telefono = request.form.get('telefono', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT usuario, rol, nombre, telefono FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario, rol, nombre, telefono FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()
        user_target = row[0] if row else None
        rol_target = row[1] if row else None
        # Si el admin deja el campo Nombre o Teléfono vacío en el formulario de edición, se
        # conserva el valor que ya tenía (permite editar solo correo/rol/contraseña sin borrar
        # los demás datos).
        nombre_final = nuevo_nombre or (row[2] if row else None)
        telefono_final = nuevo_telefono or (row[3] if row else None)

        if user_target is None:
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        es_superadmin = (session.get('username') == 'admin')
        es_propio = (user_target == session.get('username'))

        # 🛡️ Solo la cuenta 'admin' (super-admin) puede editar los datos (correo, rol o
        # contraseña) de OTRA cuenta con rol 'admin'. Esto protege tanto a la cuenta literal
        # 'admin' como a cualquier otro admin frente a sus pares — un admin comprometido o
        # malicioso ya no puede tomar control de otra cuenta admin. Cada admin conserva la
        # posibilidad de editar sus propios datos.
        if rol_target == 'admin' and not es_superadmin and not es_propio:
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        # 🛡️ Solo el super-admin puede ASCENDER a alguien a rol 'admin'. Sin esto, un admin
        # podría evadir la protección anterior ascendiendo a un usuario estándar a admin.
        if nuevo_rol == 'admin' and not es_superadmin:
            nuevo_rol = rol_target or 'estandar'

        if nueva_pass:
            nuevo_hash = generate_password_hash(nueva_pass)
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s, password_hash = %s, nombre = %s, telefono = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ?, password_hash = ?, nombre = ?, telefono = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, nuevo_hash, nombre_final, telefono_final, usuario_id))
            detalle_log = f"Se actualizó correo, rol y CONTRASEÑA del usuario '{user_target}'"
        else:
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s, nombre = %s, telefono = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ?, nombre = ?, telefono = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, nombre_final, telefono_final, usuario_id))
            detalle_log = f"Se actualizó correo y rol del usuario '{user_target}'"

        conn.commit()
        registrar_log(session['username'], "Edición de Usuario", detalle_log)
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('gestion_usuarios'))

# ❌ ELIMINAR USUARIO
@app.route('/eliminar_usuario/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(usuario_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT usuario, rol FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario, rol FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        user_target, rol_target = row[0], row[1]

        # 🛡️ Nunca permitir eliminar la cuenta 'admin' (dejaría a todos sin acceso) ni la
        # propia cuenta con la que se inició sesión (evita un auto-eliminado accidental).
        if user_target == 'admin' or user_target == session.get('username'):
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        # 🛡️ Solo la cuenta 'admin' (super-admin) puede eliminar a OTRA cuenta con rol 'admin'.
        if rol_target == 'admin' and session.get('username') != 'admin':
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        q_del = "DELETE FROM usuarios WHERE id = %s" if db_type == 'postgres' else "DELETE FROM usuarios WHERE id = ?"
        cursor.execute(q_del, (usuario_id,))
        conn.commit()

        registrar_log(session['username'], "Eliminación de Usuario", f"Se eliminó el usuario '{user_target}' del sistema")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('gestion_usuarios'))

# 🔒 BLOQUEAR / DESBLOQUEAR USUARIO
@app.route('/usuarios/toggle_estado/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def toggle_estado_usuario(usuario_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT usuario, estado, rol FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario, estado, rol FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()

        if row:
            user_target, estado_actual, rol_target = row[0], (row[1] or 'activo'), row[2]
            # 🛡️ Nunca permitir bloquear la cuenta 'admin' (dejaría a todos sin acceso) ni la
            # propia cuenta con la que se inició sesión (evita un auto-bloqueo accidental).
            if user_target == 'admin' or user_target == session.get('username'):
                conn.close()
                return redirect(url_for('gestion_usuarios'))

            # 🛡️ Solo la cuenta 'admin' (super-admin) puede bloquear/desbloquear a OTRA
            # cuenta con rol 'admin'.
            if rol_target == 'admin' and session.get('username') != 'admin':
                conn.close()
                return redirect(url_for('gestion_usuarios'))

            nuevo_estado = 'inactivo' if estado_actual == 'activo' else 'activo'
            q_upd = "UPDATE usuarios SET estado = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET estado = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_estado, usuario_id))
            conn.commit()

            accion = "Bloqueo de Usuario" if nuevo_estado == 'inactivo' else "Desbloqueo de Usuario"
            registrar_log(session['username'], accion, f"El usuario '{user_target}' fue marcado como '{nuevo_estado}'")
    except Exception as e:
        conn.rollback()
        print(f"Error cambiando estado del usuario {usuario_id}: {e}")

    conn.close()
    return redirect(url_for('gestion_usuarios'))

# 📑 RUTA /LOGS CON FILTROS
@app.route('/logs')
@login_required
@agente_o_admin_required
def ver_logs():
    q_usuario = request.args.get('usuario', '').strip()
    q_accion = request.args.get('accion', '').strip()
    q_busqueda = request.args.get('q', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT DISTINCT usuario FROM logs ORDER BY usuario ASC")
    lista_usuarios = [u[0] for u in cursor.fetchall() if u[0]]

    cursor.execute("SELECT DISTINCT accion FROM logs ORDER BY accion ASC")
    lista_acciones = [a[0] for a in cursor.fetchall() if a[0]]

    query = "SELECT usuario, accion, detalles, fecha FROM logs WHERE 1=1"
    params = []

    if q_usuario:
        query += " AND usuario = %s" if db_type == 'postgres' else " AND usuario = ?"
        params.append(q_usuario)

    if q_accion:
        query += " AND accion = %s" if db_type == 'postgres' else " AND accion = ?"
        params.append(q_accion)

    if q_busqueda:
        p_busq = f"%{q_busqueda}%"
        if db_type == 'postgres':
            query += " AND (detalles ILIKE %s OR fecha ILIKE %s)"
            params.extend([p_busq, p_busq])
        else:
            query += " AND (detalles LIKE ? OR fecha LIKE ?)"
            params.extend([p_busq, p_busq])

    query += " ORDER BY id DESC"

    cursor.execute(query, tuple(params))
    lista_logs = cursor.fetchall()
    conn.close()

    return render_template(
        'logs.html', 
        logs=lista_logs, 
        usuarios_opt=lista_usuarios, 
        acciones_opt=lista_acciones,
        q_usuario=q_usuario,
        q_accion=q_accion,
        q_busqueda=q_busqueda
    )

# 📊 EXPORTAR AUDITORÍA A EXCEL / CSV
@app.route('/exportar_logs_csv')
@login_required
@agente_o_admin_required
def exportar_logs_csv():
    q_usuario = request.args.get('usuario', '').strip()
    q_accion = request.args.get('accion', '').strip()
    q_busqueda = request.args.get('q', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()

    query = "SELECT fecha, usuario, accion, detalles FROM logs WHERE 1=1"
    params = []

    if q_usuario:
        query += " AND usuario = %s" if db_type == 'postgres' else " AND usuario = ?"
        params.append(q_usuario)

    if q_accion:
        query += " AND accion = %s" if db_type == 'postgres' else " AND accion = ?"
        params.append(q_accion)

    if q_busqueda:
        p_busq = f"%{q_busqueda}%"
        if db_type == 'postgres':
            query += " AND (detalles ILIKE %s OR fecha ILIKE %s)"
            params.extend([p_busq, p_busq])
        else:
            query += " AND (detalles LIKE ? OR fecha LIKE ?)"
            params.extend([p_busq, p_busq])

    query += " ORDER BY id DESC"

    cursor.execute(query, tuple(params))
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['FECHA Y HORA', 'USUARIO', 'ACCIÓN', 'DETALLE DEL CAMBIO'])

    for row in rows:
        writer.writerow(row)

    csv_bytes = '\ufeff' + output.getvalue()
    
    fecha_filename = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d_%H%M")
    filename = f"Arkiv_Auditoria_Logs_{fecha_filename}.csv"

    headers = {
        'Content-Type': 'text/csv; charset=utf-8',
        'Content-Disposition': f'attachment; filename="{filename}"'
    }

    return Response(csv_bytes, headers=headers, status=200)

@app.route('/perfil/tema', methods=['POST'])
@login_required
def cambiar_tema():
    """Alterna el tema claro/oscuro del usuario que tiene la sesión abierta. Se guarda en su
    cuenta (no solo en el navegador) para que lo siga a donde inicie sesión — y de paso se
    actualiza la sesión actual para que se vea reflejado de inmediato, sin tener que
    volver a iniciar sesión."""
    nuevo_tema = request.form.get('tema', '').strip()
    if nuevo_tema not in ('claro', 'oscuro'):
        nuevo_tema = 'oscuro'
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "UPDATE usuarios SET tema = %s WHERE usuario = %s" if db_type == 'postgres' else "UPDATE usuarios SET tema = ? WHERE usuario = ?"
        cursor.execute(q, (nuevo_tema, session.get('username')))
        conn.commit()
        conn.close()
        session['tema'] = nuevo_tema
    except Exception as e:
        print(f"⚠️ Error guardando preferencia de tema: {e}")
    # Vuelve a la misma página desde la que se alternó el tema (con un respaldo razonable
    # por si el navegador no manda 'Referer').
    destino = request.referrer or url_for('bienvenida')
    return redirect(destino)


@app.route('/logout')
def logout():
    if session.get('username'):
        registrar_log(session['username'], "Cierre de Sesión", "Cierre de sesión de usuario")
    session.clear()
    return redirect(url_for('login'))


# 🔔 NOTIFICACIONES (campanita) ------------------------------------------------------------
# Se generan en los mismos puntos donde ya sale un correo (ticket creado, comentado, cambio
# de estado — ver crear_ticket/comentar_ticket/actualizar_ticket) vía crear_notificacion() /
# crear_notificacion_para_varios(). Estas rutas son las que alimenta el ícono de campana que
# aparece en la barra de navegación de toda página autenticada.

@app.route('/notificaciones/resumen')
@login_required
def notificaciones_resumen():
    """JSON con el contador de no leídas y las últimas notificaciones del usuario en sesión —
    consultado periódicamente por la campanita en la barra de navegación."""
    usuario = session.get('username')
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_count = "SELECT COUNT(*) FROM notificaciones WHERE usuario = %s AND leida = 0" if db_type == 'postgres' else "SELECT COUNT(*) FROM notificaciones WHERE usuario = ? AND leida = 0"
        cursor.execute(q_count, (usuario,))
        no_leidas = cursor.fetchone()[0]

        q_lista = "SELECT id, tipo, mensaje, url, leida, fecha FROM notificaciones WHERE usuario = %s ORDER BY id DESC LIMIT 10" if db_type == 'postgres' else "SELECT id, tipo, mensaje, url, leida, fecha FROM notificaciones WHERE usuario = ? ORDER BY id DESC LIMIT 10"
        cursor.execute(q_lista, (usuario,))
        recientes = [{'id': r[0], 'tipo': r[1], 'mensaje': r[2], 'url': r[3], 'leida': bool(r[4]), 'fecha': r[5]} for r in cursor.fetchall()]
        conn.close()
        return {'no_leidas': no_leidas, 'recientes': recientes}
    except Exception as e:
        conn.close()
        print(f"⚠️ Error obteniendo resumen de notificaciones de '{usuario}': {e}")
        return {'no_leidas': 0, 'recientes': []}


@app.route('/notificaciones/<int:notif_id>/ir')
@login_required
def notificacion_ir(notif_id):
    """La campanita enlaza cada notificación acá en vez de directo a su URL destino: esto
    la marca como leída y de una vez redirige adonde corresponda (el ticket, etc.)."""
    usuario = session.get('username')
    conn, db_type = get_db()
    cursor = conn.cursor()
    destino = url_for('bienvenida')
    try:
        q_sel = "SELECT usuario, url FROM notificaciones WHERE id = %s" if db_type == 'postgres' else "SELECT usuario, url FROM notificaciones WHERE id = ?"
        cursor.execute(q_sel, (notif_id,))
        row = cursor.fetchone()
        if row and row[0] == usuario:
            destino = row[1] or destino
            q_upd = "UPDATE notificaciones SET leida = 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE notificaciones SET leida = 1 WHERE id = ?"
            cursor.execute(q_upd, (notif_id,))
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Error marcando notificación {notif_id} como leída: {e}")
    conn.close()
    return redirect(destino)


@app.route('/notificaciones/marcar_todas_leidas', methods=['POST'])
@login_required
def notificaciones_marcar_todas_leidas():
    usuario = session.get('username')
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q = "UPDATE notificaciones SET leida = 1 WHERE usuario = %s AND leida = 0" if db_type == 'postgres' else "UPDATE notificaciones SET leida = 1 WHERE usuario = ? AND leida = 0"
        cursor.execute(q, (usuario,))
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Error marcando todas las notificaciones de '{usuario}' como leídas: {e}")
    conn.close()
    return ('', 204)


@app.route('/')
def home():
    return redirect(url_for('bienvenida')) if session.get('logged_in') else redirect(url_for('login'))

@app.route('/bienvenida')
@login_required
def bienvenida():
    conn, db_type = get_db()
    cursor = conn.cursor()
    comunicado_fijado = None
    try:
        # "fijado = 1" literal fallaba en Postgres contra la columna BOOLEAN real; "true" funciona en ambos motores.
        query_fij = "SELECT id, titulo, contenido, nivel, imagen_url, fecha, autor FROM comunicados WHERE fijado = true AND estado = 'activo' ORDER BY id DESC LIMIT 1" if db_type == 'postgres' else "SELECT id, titulo, contenido, nivel, imagen_url, fecha, autor FROM comunicados WHERE fijado = 1 AND estado = 'activo' ORDER BY id DESC LIMIT 1"
        cursor.execute(query_fij)
        row = cursor.fetchone()
        if row:
            comunicado_fijado = {
                'id': row[0],
                'titulo': row[1],
                'contenido': row[2],
                'nivel': row[3],
                'imagen_url': row[4],
                'fecha': row[5],
                # 👤 Alias/nombre real de quien publicó, no su usuario de inicio de sesión.
                'autor': _nombre_para_mostrar(row[6], _mapa_nombres_usuarios())
            }
    except Exception:
        comunicado_fijado = None
    conn.close()

    # 👁️ Ver el comunicado fijado en la bienvenida también cuenta como "leído".
    if comunicado_fijado:
        _marcar_comunicado_leido(comunicado_fijado['id'], session.get('username'))

    return render_template('bienvenida.html', username=session.get('username'), rol=session.get('rol'), comunicado_fijado=comunicado_fijado)

@app.route('/gestor')
@login_required
def index():
    busqueda_raw = request.args.get('q', '').strip()
    cat_filtro = request.args.get('cat', '').strip()
    tipo_filtro = request.args.get('tipo', '').strip()
    formato_filtro = request.args.get('formato', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    
    # 👁️ Un usuario Estándar solo debe ver instructivos marcados como 'todos'; Admin y Agente
    # ven absolutamente todo (incluidos los marcados 'admin'), sin filtrar por visibilidad.
    puede_ver_todo = session.get('rol') in ROLES_CON_ACCESO_OPERATIVO

    try:
        cursor.execute("SELECT id, titulo, descripcion, fecha_subida, categoria, tipo, tags, vistas, descargas, visibilidad FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
        rows = cursor.fetchall()
    except Exception:
        try:
            conn.rollback()
            cursor.execute("SELECT id, titulo, descripcion, fecha_subida, categoria, tipo, tags FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
            raw_rows = cursor.fetchall()
            rows = [r + (0, 0, 'todos') for r in raw_rows]
        except Exception:
            rows = []

    galerias = []
    sugerencias_titulos = []
    fecha_defecto = obtener_fecha_actual()

    STOP_WORDS = {'de', 'del', 'la', 'las', 'el', 'los', 'un', 'una', 'unos', 'unas', 'y', 'e', 'o', 'u', 'a', 'en', 'con', 'por', 'para'}

    palabras_clave = []
    if busqueda_raw:
        palabras_limpias = [normalizar(p) for p in busqueda_raw.split() if normalizar(p)]
        palabras_clave = [p for p in palabras_limpias if p not in STOP_WORDS]
        if not palabras_clave:
            palabras_clave = palabras_limpias

    for r in rows:
        galeria_id, titulo, descripcion, fecha = r[0], r[1], r[2], r[3]
        categoria = r[4] if len(r) > 4 and r[4] else 'General'
        tipo = r[5] if len(r) > 5 and r[5] else 'Instructivo'
        tags = r[6] if len(r) > 6 and r[6] else ''
        vistas = r[7] if len(r) > 7 and r[7] is not None else 0
        descargas = r[8] if len(r) > 8 and r[8] is not None else 0
        visibilidad = r[9] if len(r) > 9 and r[9] else 'todos'

        # 👁️ Si es un usuario Estándar y este instructivo quedó marcado "Solo Admin", ni
        # siquiera entra a construir el item: no debe aparecer en su listado ni en las
        # sugerencias de búsqueda.
        if visibilidad == 'admin' and not puede_ver_todo:
            continue

        sugerencias_titulos.append(titulo)

        try:
            query_arch = "SELECT COALESCE(filename, url_archivo) FROM archivos WHERE galeria_id = %s AND COALESCE(estado, 'activo') != 'eliminado'" if db_type == 'postgres' else "SELECT COALESCE(filename, url_archivo) FROM archivos WHERE galeria_id = ? AND COALESCE(estado, 'activo') != 'eliminado'"
            cursor.execute(query_arch, (galeria_id,))
            archivos = [f[0] for f in cursor.fetchall()]
        except Exception as e_arch:
            # No dejar que un problema puntual (ej. tipos de dato inconsistentes
            # en galeria_id) tumbe toda la página de instructivos.
            print(f"⚠️ Error leyendo archivos de la galería {galeria_id}: {e_arch}")
            if db_type == 'postgres':
                conn.rollback()
            archivos = []

        item = {
            'id': galeria_id,
            'titulo': titulo,
            'descripcion': descripcion,
            'fecha': fecha or fecha_defecto,
            'categoria': categoria,
            'tipo': tipo,
            'tags': tags,
            'vistas': vistas,
            'descargas': descargas,
            'visibilidad': visibilidad,
            'archivos': archivos
        }

        texto_busqueda = normalizar(f"{titulo} {descripcion} {categoria} {tipo} {tags} {' '.join(archivos)}")

        if palabras_clave:
            coincide_busqueda = any(palabra in texto_busqueda for palabra in palabras_clave)
        else:
            coincide_busqueda = True

        coincide_cat = not cat_filtro or categoria == cat_filtro
        coincide_tipo = not tipo_filtro or tipo == tipo_filtro

        coincide_formato = True
        if formato_filtro == 'imagen':
            coincide_formato = any(any(ext in a.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']) or '/image/upload/' in a for a in archivos)
        elif formato_filtro == 'video':
            coincide_formato = any(any(ext in a.lower() for ext in ['.mp4', '.mov', '.webm', '.avi']) or '/video/upload/' in a for a in archivos)
        elif formato_filtro == 'pdf':
            coincide_formato = any('.pdf' in a.lower() or '.docx' in a.lower() or '.txt' in a.lower() or '/raw/upload/' in a for a in archivos)

        if coincide_busqueda and coincide_cat and coincide_tipo and coincide_formato:
            galerias.append(item)

    conn.close()
    return render_template('index.html', galerias=galerias, busqueda=busqueda_raw, cat_filtro=cat_filtro, tipo_filtro=tipo_filtro, formato_filtro=formato_filtro, sugerencias_titulos=list(set(sugerencias_titulos)), rol=session.get('rol'))

# 📦 SUBIDA DE ARCHIVOS (IMÁGENES, VIDEOS, DOCUMENTOS Y COMPRIMIDOS .ZIP/.RAR)
@app.route('/subir', methods=['POST'])
@login_required
@agente_o_admin_required
def subir_archivo():
    archivos = request.files.getlist('archivo')
    titulo = request.form.get('titulo', 'Sin título')
    descripcion = request.form.get('descripcion', '')
    categoria = request.form.get('categoria', 'General')
    tipo = request.form.get('tipo', 'Instructivo')
    tags = request.form.get('tags', '')
    # 👁️ Visibilidad del instructivo: 'todos' (cualquier usuario logueado) o 'admin' (solo
    # Admin/Agente). Cualquier otro valor recibido se descarta a favor de 'todos'.
    visibilidad = request.form.get('visibilidad', 'todos').strip()
    if visibilidad not in ('todos', 'admin'):
        visibilidad = 'todos'

    galeria_id = str(uuid.uuid4())[:8]
    fecha_actual = obtener_fecha_actual()
    
    archivos_guardados = []
    for file in archivos:
        if file and archivo_permitido(file.filename):
            try:
                ext = file.filename.rsplit('.', 1)[1].lower()

                if ext in ['mp4', 'mov', 'webm', 'avi']:
                    # 🛡️ Los videos van por upload_large (subida en fragmentos/"chunks"): el
                    # endpoint normal de Cloudinary (upload) rechaza con 413 "Request Entity
                    # Too Large" cualquier archivo que pase de ~100 MB, sin importar el plan
                    # de la cuenta. upload_large sube el archivo en pedazos y evita ese límite.
                    # ⚠️ Se le pasa file.stream (no el FileStorage de Flask/Werkzeug): upload_large
                    # hace "with file_io:" internamente, y FileStorage no implementa el protocolo
                    # de gestor de contexto (__enter__/__exit__) — el stream real sí. "filename"
                    # se pasa explícito porque el stream no trae el nombre original del archivo.
                    upload_result = cloudinary.uploader.upload_large(
                        file.stream,
                        resource_type="video",
                        filename=file.filename,
                        use_filename=True,
                        unique_filename=True,
                        chunk_size=6000000,
                        timeout=600
                    )
                elif ext == 'pdf':
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="image",
                        format="pdf",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
                    )
                elif ext in ['zip', 'rar', '7z', 'tar', 'gz', 'txt', 'docx', 'xlsx', 'pptx']:
                    # 🛡️ Mismo límite de ~100 MB aplica a archivos "raw" (zip, comprimidos, etc.):
                    # se sube por chunks para evitar el mismo 413 con paquetes grandes.
                    upload_result = cloudinary.uploader.upload_large(
                        file.stream,
                        resource_type="raw",
                        filename=file.filename,
                        use_filename=True,
                        unique_filename=True,
                        chunk_size=6000000,
                        timeout=600
                    )
                else:
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="image",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
                    )

                archivos_guardados.append((upload_result['secure_url'], file.filename))
            except Exception as e:
                # No dejar que un archivo con problema (ej. Cloudinary rechazándolo,
                # o sin credenciales configuradas) tumbe la subida completa del instructivo.
                print(f"⚠️ Error subiendo el archivo '{file.filename}' a Cloudinary: {e}")

    if archivos_guardados:
        try:
            conn, db_type = get_db()
            cursor = conn.cursor()
            # 'area' es NOT NULL en Neon sin valor por defecto: reutilizamos la categoría
            # elegida, ya que hoy no hay un campo separado de área en el formulario.
            q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha_subida, categoria, area, tipo, tags, vistas, descargas, estado, visibilidad) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 'activo', %s)" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha_subida, categoria, area, tipo, tags, vistas, descargas, estado, visibilidad) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'activo', ?)"
            cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual, categoria, categoria, tipo, tags, visibilidad))

            # 'nombre_original' y 'url_archivo' son NOT NULL en Neon sin valor por defecto.
            # Se llenan junto con 'filename' (que se conserva por compatibilidad con lecturas existentes).
            q_archivo = "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (%s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (?, ?, ?, ?, 'activo')"
            for url_arch, nombre_orig in archivos_guardados:
                cursor.execute(q_archivo, (galeria_id, url_arch, url_arch, nombre_orig))

            conn.commit()
            conn.close()
            registrar_log(session['username'], "Creación de Instructivo", f"Instructivo '{titulo}' [{categoria} / {tipo}] (visibilidad: {'solo Admin/Agente' if visibilidad == 'admin' else 'todos los usuarios'})")
        except Exception as e:
            print(f"⚠️ Error guardando el instructivo '{titulo}' en la base de datos: {e}")

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def editar_galeria(galeria_id):
    nuevo_titulo = (request.form.get('titulo') or '').strip()
    nueva_desc = (request.form.get('descripcion') or '').strip()
    nueva_cat = (request.form.get('categoria') or 'General').strip()
    nuevo_tipo = (request.form.get('tipo') or 'Instructivo').strip()
    nuevos_tags = (request.form.get('tags') or '').strip()
    nueva_visibilidad = (request.form.get('visibilidad') or 'todos').strip()
    if nueva_visibilidad not in ('todos', 'admin'):
        nueva_visibilidad = 'todos'
    nuevos_archivos = request.files.getlist('nuevos_archivos')

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        q_sel = "SELECT titulo, descripcion, categoria, tipo, tags, visibilidad FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo, descripcion, categoria, tipo, tags, visibilidad FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        antiguo = cursor.fetchone()

        cambios = []
        if antiguo:
            tit_old = (antiguo[0] or '').strip()
            desc_old = (antiguo[1] or '').strip()
            cat_old = (antiguo[2] or 'General').strip()
            tipo_old = (antiguo[3] or 'Instructivo').strip()
            tags_old = (antiguo[4] or '').strip()
            visibilidad_old = (antiguo[5] or 'todos').strip()

            if tit_old != nuevo_titulo:
                cambios.append(f"Título: '{tit_old}' ➔ '{nuevo_titulo}'")
            if desc_old != nueva_desc:
                cambios.append(f"Descripción: '{desc_old}' ➔ '{nueva_desc}'")
            if cat_old != nueva_cat:
                cambios.append(f"Categoría: '{cat_old}' ➔ '{nueva_cat}'")
            if tipo_old != nuevo_tipo:
                cambios.append(f"Tipo: '{tipo_old}' ➔ '{nuevo_tipo}'")
            if tags_old != nuevos_tags:
                cambios.append(f"Tags: '{tags_old}' ➔ '{nuevos_tags}'")
            if visibilidad_old != nueva_visibilidad:
                cambios.append(f"Visibilidad: '{visibilidad_old}' ➔ '{nueva_visibilidad}'")

        q_upd = "UPDATE galerias SET titulo = %s, descripcion = %s, categoria = %s, tipo = %s, tags = %s, visibilidad = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, descripcion = ?, categoria = ?, tipo = ?, tags = ?, visibilidad = ? WHERE id = ?"
        cursor.execute(q_upd, (nuevo_titulo, nueva_desc, nueva_cat, nuevo_tipo, nuevos_tags, nueva_visibilidad, galeria_id))
        
        archivos_agregados = 0
        for file in nuevos_archivos:
            if file and archivo_permitido(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                
                if ext in ['mp4', 'mov', 'webm', 'avi']:
                    # 🛡️ Igual que en /subir: upload_large evita el 413 de Cloudinary en
                    # archivos de más de ~100 MB, subiéndolos en fragmentos. Se pasa file.stream
                    # (no el FileStorage) porque upload_large necesita un objeto que soporte
                    # "with ... :", y FileStorage no lo soporta; "filename" se pasa explícito
                    # porque el stream no trae el nombre original del archivo.
                    upload_result = cloudinary.uploader.upload_large(
                        file.stream,
                        resource_type="video",
                        filename=file.filename,
                        use_filename=True,
                        unique_filename=True,
                        chunk_size=6000000,
                        timeout=600
                    )
                elif ext == 'pdf':
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="image",
                        format="pdf",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
                    )
                elif ext in ['zip', 'rar', '7z', 'tar', 'gz', 'txt', 'docx', 'xlsx', 'pptx']:
                    upload_result = cloudinary.uploader.upload_large(
                        file.stream,
                        resource_type="raw",
                        filename=file.filename,
                        use_filename=True,
                        unique_filename=True,
                        chunk_size=6000000,
                        timeout=600
                    )
                else:
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="image",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
                    )

                # 'nombre_original' y 'url_archivo' son NOT NULL en Neon sin valor por defecto.
                q_ins_arch = "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (%s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (?, ?, ?, ?, 'activo')"
                cursor.execute(q_ins_arch, (galeria_id, upload_result['secure_url'], upload_result['secure_url'], file.filename))
                archivos_agregados += 1

        if archivos_agregados > 0:
            cambios.append(f"Archivos: +{archivos_agregados} nuevo(s)")

        conn.commit()

        if cambios:
            detalles_log = f"'{nuevo_titulo}' :: " + " | ".join(cambios)
        else:
            detalles_log = f"'{nuevo_titulo}' re-guardado sin cambios detectados"

        registrar_log(session['username'], "Edición de Galería", detalles_log)

    except Exception as e:
        conn.rollback()
        print(f"Error procesando edición en BD: {e}")

    conn.close()
    return redirect(url_for('index'))

# 🗑️ BORRADO LÓGICO DE INSTRUCTIVO
@app.route('/eliminar_galeria/<galeria_id>', methods=['POST'])
@login_required
@agente_o_admin_required
def eliminar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q_upd = "UPDATE galerias SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (galeria_id,))
        conn.commit()

        registrar_log(session['username'], "Envío a Papelera", f"El instructivo '{titulo}' fue movido a la papelera de reciclaje.")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('index'))

if __name__ == '__main__':
    # 🛡️ debug=False: este bloque no lo usa producción (Render arranca con gunicorn,
    # ver Procfile), pero si algún día el comando de arranque cambiara a "python app.py",
    # debug=True habilita el depurador interactivo de Werkzeug, que permite ejecutar
    # código Python arbitrario desde el navegador. Mejor dejarlo en False siempre.
    app.run(host='0.0.0.0', port=5000, debug=False)
