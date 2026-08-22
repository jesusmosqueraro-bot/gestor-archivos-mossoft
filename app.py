import os
import uuid
import random
import sqlite3
import urllib.request
import urllib.parse
import json
import unicodedata
import io
import csv
import threading
import base64
import hashlib
import traceback
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify, stream_with_context
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
# 📦 LÍMITE AMPLIADO A 100 MB PARA VIDEOS DE HASTA 5-10 MINUTOS
app.config['MAX_CONTENT_LENGTH'] = 350 * 1024 * 1024

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
            conn.commit()
            
            for col_query in [
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS categoria VARCHAR(100) DEFAULT 'General';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tipo VARCHAR(100) DEFAULT 'Instructivo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS vistas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS descargas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS area VARCHAR(100) DEFAULT 'General';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS url_archivo TEXT DEFAULT '';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS nombre_original VARCHAR(255) DEFAULT '';",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE usuarios ADD COLUMN IF NOT EXISTS estado VARCHAR(20) DEFAULT 'activo';"
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
            try:
                cursor.execute("ALTER TABLE usuarios ADD COLUMN estado TEXT DEFAULT 'activo';")
                conn.commit()
            except Exception:
                pass

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

def registrar_log(usuario, accion, detalles=""):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha_actual = obtener_fecha_actual()
        query = "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)"
        cursor.execute(query, (usuario, accion, detalles, fecha_actual))
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

# 🗄️ MÓDULO ADMINISTRADOR DE BASE DE DATOS (LECTURA + CONSOLA SQL LIBRE)
@app.route('/admin/db', methods=['GET', 'POST'])
@login_required
@admin_required
def visor_db():
    tabla_seleccionada = request.args.get('tabla', 'usuarios')
    q_sql = request.form.get('sql', '').strip() or request.args.get('sql', '').strip()
    
    tablas_permitidas = ['usuarios', 'galerias', 'archivos', 'logs', 'credenciales', 'comunicados']
    if tabla_seleccionada not in tablas_permitidas:
        tabla_seleccionada = 'usuarios'
        
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    columnas = []
    registros = []
    mensaje_exito = None
    error_sql = None
    
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
        error=error_sql
    )

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
                'autor': autor
            })

    return render_template('comunicados.html', comunicados=comunicados, pestana=pestana, q_busqueda=q_busqueda, rol=session.get('rol'))

@app.route('/comunicados/crear', methods=['POST'])
@login_required
@admin_required
def crear_comunicado():
    titulo = request.form.get('titulo', '').strip()
    contenido = request.form.get('contenido', '').strip()
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

    if titulo and contenido:
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

@app.route('/comunicados/archivar/<int:com_id>', methods=['POST'])
@login_required
@admin_required
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
@admin_required
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
    return redirect(url_for('ver_comunicados'))

@app.route('/restaurar_comunicado/<int:com_id>', methods=['POST'])
@login_required
@admin_required
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
@admin_required
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
                query = "SELECT usuario, password_hash, rol, estado FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(%s))" if db_type == 'postgres' else "SELECT usuario, password_hash, rol, estado FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(?))"
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
                        es_valida = (clave_db == password)
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

# 🔑 MÓDULO BÓVEDA DE CREDENCIALES
@app.route('/credenciales')
@login_required
@admin_required
def ver_credenciales():
    q_busqueda = request.args.get('q', '').strip().lower()
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion FROM credenciales WHERE COALESCE(estado, 'activo') != 'eliminado' ORDER BY titulo ASC")
        rows = cursor.fetchall()
    except Exception:
        rows = []

    conn.close()
    
    lista_credenciales = []
    for r in rows:
        try:
            c_id, servicio, url, usuario, pass_enc, categoria, notas, fecha = r  # nombres locales; columnas reales: titulo/url_acceso/usuario_acceso/password_cifrada/area/fecha_creacion
            pass_real = desencriptar_texto(pass_enc, c_id)

            texto_full = f"{servicio} {usuario} {categoria} {notas}".lower()
            if not q_busqueda or q_busqueda in texto_full:
                lista_credenciales.append({
                    'id': c_id,
                    'servicio': servicio,
                    'url': url or '',
                    'usuario': usuario,
                    'password': pass_real,
                    'categoria': categoria or 'General',
                    'notas': notas or '',
                    'fecha': fecha
                })
        except Exception as e_row:
            # No dejar que una fila con datos inconsistentes tumbe toda la bóveda.
            print(f"⚠️ Error procesando credencial {r[0] if r else '?'}: {e_row}")
            continue
            
    return render_template('credenciales.html', credenciales=lista_credenciales, q_busqueda=q_busqueda)

@app.route('/credenciales/crear', methods=['POST'])
@login_required
@admin_required
def crear_credencial():
    servicio = request.form.get('servicio', '').strip()
    url = request.form.get('url', '').strip()
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '').strip()
    categoria = request.form.get('categoria', 'General').strip()
    notas = request.form.get('notas', '').strip()
    
    if servicio and usuario and password:
        try:
            pass_cifrada = encriptar_texto(password)
            fecha_act = obtener_fecha_actual()

            conn, db_type = get_db()
            cursor = conn.cursor()
            q_ins = "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado) VALUES (%s, %s, %s, %s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO credenciales (titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, fecha_creacion, estado) VALUES (?, ?, ?, ?, ?, ?, ?, 'activo')"
            cursor.execute(q_ins, (servicio, url, usuario, pass_cifrada, categoria, notas, fecha_act))
            conn.commit()
            conn.close()

            registrar_log(session['username'], "Guardado de Credencial", f"Se registró el acceso para el aplicativo '{servicio}'")
        except Exception as e:
            print(f"⚠️ Error guardando credencial '{servicio}': {e}")

    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/editar/<int:cred_id>', methods=['POST'])
@login_required
@admin_required
def editar_credencial(cred_id):
    servicio = request.form.get('servicio', '').strip()
    url = request.form.get('url', '').strip()
    usuario = request.form.get('usuario', '').strip()
    password = request.form.get('password', '').strip()
    categoria = request.form.get('categoria', 'General').strip()
    notas = request.form.get('notas', '').strip()
    
    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        if password:
            pass_cifrada = encriptar_texto(password)
            q_upd = "UPDATE credenciales SET titulo=%s, url_acceso=%s, usuario_acceso=%s, password_cifrada=%s, area=%s, notas=%s WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url_acceso=?, usuario_acceso=?, password_cifrada=?, area=?, notas=? WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, pass_cifrada, categoria, notas, cred_id))
        else:
            q_upd = "UPDATE credenciales SET titulo=%s, url_acceso=%s, usuario_acceso=%s, area=%s, notas=%s WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url_acceso=?, usuario_acceso=?, area=?, notas=? WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, categoria, notas, cred_id))

        conn.commit()
        registrar_log(session['username'], "Edición de Credencial", f"Se actualizó la credencial ID '{cred_id}' ({servicio})")
    except Exception as e:
        conn.rollback()
        print(f"⚠️ Error editando credencial {cred_id}: {e}")

    conn.close()
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/eliminar/<int:cred_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    q_upd = "UPDATE credenciales SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET estado = 'eliminado' WHERE id = ?"
    cursor.execute(q_upd, (cred_id,))
    conn.commit()
    conn.close()
    
    registrar_log(session['username'], "Eliminación de Credencial", f"Se envió a la papelera la credencial ID '{cred_id}'")
    return redirect(url_for('ver_credenciales'))

# ♻️ MÓDULO PAPELERA DE RECICLAJE
@app.route('/papelera')
@login_required
@admin_required
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

    comunicados_eliminados = [
        {'id': r[0], 'titulo': r[1], 'nivel': r[2], 'fecha': r[3], 'autor': r[4]} for r in rows_com
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
@admin_required
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
        nuevo_user = (request.form.get('username') or '').strip()
        nuevo_pass = request.form.get('password') or ''
        nuevo_email = (request.form.get('email') or '').strip()
        nuevo_rol = request.form.get('rol', 'estandar')
        form_data = {'username': nuevo_user, 'email': nuevo_email, 'rol': nuevo_rol}

        if not nuevo_user or not nuevo_pass or not nuevo_email:
            error = "Todos los campos son obligatorios para crear un usuario."
        else:
            # 🛡️ Antes de insertar, verificamos si ya existe un usuario con ese nombre
            # (sin distinguir mayúsculas/minúsculas). Antes de este fix, un nombre duplicado
            # violaba la restricción UNIQUE de la BD y el error se descartaba en silencio:
            # el admin creía haber creado el usuario, pero nada pasaba.
            q_check = "SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(%s)" if db_type == 'postgres' else "SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(?)"
            cursor.execute(q_check, (nuevo_user,))
            if cursor.fetchone():
                error = f"Ya existe un usuario con el nombre '{nuevo_user}'. Elige otro nombre."

        if not error:
            try:
                nuevo_hash = generate_password_hash(nuevo_pass)
                q_ins = "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado) VALUES (%s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol, estado) VALUES (?, ?, ?, ?, 'activo')"
                cursor.execute(q_ins, (nuevo_user, nuevo_hash, nuevo_email, nuevo_rol))
                conn.commit()
                registrar_log(session['username'], "Creación de Usuario", f"Usuario '{nuevo_user}' [{nuevo_rol}]")
                conn.close()
                return redirect(url_for('gestion_usuarios'))
            except Exception as e:
                conn.rollback()
                error = "No se pudo crear el usuario. Verifica los datos e intenta de nuevo."

    # 🛡️ La cuenta 'admin' queda oculta del listado para el resto de administradores: solo
    # la propia sesión de 'admin' la ve. El resto de admins no sabe que existe esta fila.
    if session.get('username') == 'admin':
        cursor.execute("SELECT id, usuario, correo, rol, estado FROM usuarios ORDER BY id ASC")
    else:
        cursor.execute("SELECT id, usuario, correo, rol, estado FROM usuarios WHERE usuario != 'admin' ORDER BY id ASC")
    lista_usuarios = cursor.fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda="", error=error, form_data=form_data)

# ✏️ EDITAR USUARIO
@app.route('/editar_usuario/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def editar_usuario(usuario_id):
    nuevo_email = request.form.get('email', '').strip()
    nuevo_rol = request.form.get('rol', 'estandar').strip()
    nueva_pass = request.form.get('password', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT usuario FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()
        user_target = row[0] if row else None

        # 🛡️ La cuenta 'admin' está oculta para el resto de administradores en el listado;
        # esto la protege también a nivel de servidor para que nadie más pueda editarla
        # (ni su correo, ni su rol, ni su clave) aunque adivine o pruebe su ID directamente.
        if user_target is None:
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        if user_target == 'admin' and session.get('username') != 'admin':
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        if nueva_pass:
            nuevo_hash = generate_password_hash(nueva_pass)
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s, password_hash = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ?, password_hash = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, nuevo_hash, usuario_id))
            detalle_log = f"Se actualizó correo, rol y CONTRASEÑA del usuario '{user_target}'"
        else:
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, usuario_id))
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
        q_sel = "SELECT usuario FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()

        if not row:
            conn.close()
            return redirect(url_for('gestion_usuarios'))

        user_target = row[0]

        # 🛡️ Nunca permitir eliminar la cuenta 'admin' (dejaría a todos sin acceso) ni la
        # propia cuenta con la que se inició sesión (evita un auto-eliminado accidental).
        if user_target == 'admin' or user_target == session.get('username'):
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
        q_sel = "SELECT usuario, estado FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario, estado FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()

        if row:
            user_target, estado_actual = row[0], (row[1] or 'activo')
            # 🛡️ Nunca permitir bloquear la cuenta 'admin' (dejaría a todos sin acceso) ni la
            # propia cuenta con la que se inició sesión (evita un auto-bloqueo accidental).
            if user_target == 'admin' or user_target == session.get('username'):
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
@admin_required
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
@admin_required
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

@app.route('/logout')
def logout():
    if session.get('username'):
        registrar_log(session['username'], "Cierre de Sesión", "Cierre de sesión de usuario")
    session.clear()
    return redirect(url_for('login'))

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
        query_fij = "SELECT titulo, contenido, nivel, imagen_url, fecha, autor FROM comunicados WHERE fijado = true AND estado = 'activo' ORDER BY id DESC LIMIT 1" if db_type == 'postgres' else "SELECT titulo, contenido, nivel, imagen_url, fecha, autor FROM comunicados WHERE fijado = 1 AND estado = 'activo' ORDER BY id DESC LIMIT 1"
        cursor.execute(query_fij)
        row = cursor.fetchone()
        if row:
            comunicado_fijado = {
                'titulo': row[0],
                'contenido': row[1],
                'nivel': row[2],
                'imagen_url': row[3],
                'fecha': row[4],
                'autor': row[5]
            }
    except Exception:
        comunicado_fijado = None
    conn.close()

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
    
    try:
        cursor.execute("SELECT id, titulo, descripcion, fecha_subida, categoria, tipo, tags, vistas, descargas FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
        rows = cursor.fetchall()
    except Exception:
        try:
            conn.rollback()
            cursor.execute("SELECT id, titulo, descripcion, fecha_subida, categoria, tipo, tags FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
            raw_rows = cursor.fetchall()
            rows = [r + (0, 0) for r in raw_rows]
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
@admin_required
def subir_archivo():
    archivos = request.files.getlist('archivo')
    titulo = request.form.get('titulo', 'Sin título')
    descripcion = request.form.get('descripcion', '')
    categoria = request.form.get('categoria', 'General')
    tipo = request.form.get('tipo', 'Instructivo')
    tags = request.form.get('tags', '')

    galeria_id = str(uuid.uuid4())[:8]
    fecha_actual = obtener_fecha_actual()
    
    archivos_guardados = []
    for file in archivos:
        if file and archivo_permitido(file.filename):
            try:
                ext = file.filename.rsplit('.', 1)[1].lower()

                if ext in ['mp4', 'mov', 'webm', 'avi']:
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="video",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
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
                    upload_result = cloudinary.uploader.upload(
                        file,
                        resource_type="raw",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
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
            q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha_subida, categoria, area, tipo, tags, vistas, descargas, estado) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 0, 0, 'activo')" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha_subida, categoria, area, tipo, tags, vistas, descargas, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'activo')"
            cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual, categoria, categoria, tipo, tags))

            # 'nombre_original' y 'url_archivo' son NOT NULL en Neon sin valor por defecto.
            # Se llenan junto con 'filename' (que se conserva por compatibilidad con lecturas existentes).
            q_archivo = "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (%s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, url_archivo, nombre_original, estado) VALUES (?, ?, ?, ?, 'activo')"
            for url_arch, nombre_orig in archivos_guardados:
                cursor.execute(q_archivo, (galeria_id, url_arch, url_arch, nombre_orig))

            conn.commit()
            conn.close()
            registrar_log(session['username'], "Creación de Instructivo", f"Instructivo '{titulo}' [{categoria} / {tipo}]")
        except Exception as e:
            print(f"⚠️ Error guardando el instructivo '{titulo}' en la base de datos: {e}")

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def editar_galeria(galeria_id):
    nuevo_titulo = (request.form.get('titulo') or '').strip()
    nueva_desc = (request.form.get('descripcion') or '').strip()
    nueva_cat = (request.form.get('categoria') or 'General').strip()
    nuevo_tipo = (request.form.get('tipo') or 'Instructivo').strip()
    nuevos_tags = (request.form.get('tags') or '').strip()
    nuevos_archivos = request.files.getlist('nuevos_archivos')
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        q_sel = "SELECT titulo, descripcion, categoria, tipo, tags FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo, descripcion, categoria, tipo, tags FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        antiguo = cursor.fetchone()

        cambios = []
        if antiguo:
            tit_old = (antiguo[0] or '').strip()
            desc_old = (antiguo[1] or '').strip()
            cat_old = (antiguo[2] or 'General').strip()
            tipo_old = (antiguo[3] or 'Instructivo').strip()
            tags_old = (antiguo[4] or '').strip()

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

        q_upd = "UPDATE galerias SET titulo = %s, descripcion = %s, categoria = %s, tipo = %s, tags = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, descripcion = ?, categoria = ?, tipo = ?, tags = ? WHERE id = ?"
        cursor.execute(q_upd, (nuevo_titulo, nueva_desc, nueva_cat, nuevo_tipo, nuevos_tags, galeria_id))
        
        archivos_agregados = 0
        for file in nuevos_archivos:
            if file and archivo_permitido(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                
                if ext in ['mp4', 'mov', 'webm', 'avi']:
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        resource_type="video",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
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
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        resource_type="raw",
                        use_filename=True,
                        unique_filename=True,
                        timeout=60
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
@admin_required
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
    app.run(host='0.0.0.0', port=5000, debug=True)
