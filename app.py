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
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify
from werkzeug.security import generate_password_hash, check_password_hash

# PostgreSQL Driver
try:
    import psycopg2
except Exception:
    psycopg2 = None

# Cifrado seguro AES-128 Fernet
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:
    Fernet = None
    InvalidToken = Exception

import cloudinary
import cloudinary.uploader

try:
    import requests
except Exception:
    requests = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_secreta_gestor_archivos_ultra_segura_2026_prod')

SERVER_INSTANCE_ID = str(uuid.uuid4())
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

# 🇨🇴 ZONA HORARIA COLOMBIA - HORARIO MILITAR 24H
try:
    ZONA_HORARIA_COLOMBIA = ZoneInfo("America/Bogota")
except Exception:
    ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

def obtener_fecha_actual():
    try:
        return datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y %H:%M")

def formatear_fecha_militar(fecha_val):
    if not fecha_val:
        return obtener_fecha_actual()
    try:
        if isinstance(fecha_val, datetime):
            if fecha_val.tzinfo is None:
                fecha_val = fecha_val.replace(tzinfo=timezone.utc)
            return fecha_val.astimezone(ZONA_HORARIA_COLOMBIA).strftime("%d/%m/%Y %H:%M")
        
        texto = str(fecha_val).strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M"):
            try:
                dt = datetime.strptime(texto[:19], fmt[:len(texto[:19])])
                return dt.strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass
        return texto[:16]
    except Exception:
        return str(fecha_val)[:16]

def normalizar(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower().strip()

# 🔐 CIFRADO FERNET (AES-128 + HMAC)
_ENCRYPTION_KEY = os.environ.get('ENCRYPTION_KEY', 'Wid07RW2qTCSFw-y4s8p3QLzDdDb0lhiDI0KJyxjn5Y=')
_fernet = None
if Fernet and _ENCRYPTION_KEY:
    try:
        _fernet = Fernet(_ENCRYPTION_KEY.encode('utf-8'))
    except Exception as _e:
        print(f"⚠️ Error inicializando Fernet con ENCRYPTION_KEY: {_e}")
        _fernet = None

def desencriptar_texto_legacy_xor(texto_cifrado):
    if not texto_cifrado: return ""
    try:
        clave = app.secret_key.encode('utf-8')
        bytes_cifrados = base64.b64decode(texto_cifrado.encode('utf-8'))
        descifrado = bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_cifrados)])
        return descifrado.decode('utf-8')
    except Exception:
        return ""

def encriptar_texto(texto):
    if not texto: return ""
    if _fernet:
        return _fernet.encrypt(texto.encode('utf-8')).decode('utf-8')
    clave = app.secret_key.encode('utf-8')
    bytes_texto = texto.encode('utf-8')
    cifrado = bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_texto)])
    return base64.b64encode(cifrado).decode('utf-8')

def desencriptar_texto(texto_cifrado):
    if not texto_cifrado: return ""
    if _fernet:
        try:
            return _fernet.decrypt(texto_cifrado.encode('utf-8')).decode('utf-8')
        except (InvalidToken, Exception):
            legacy = desencriptar_texto_legacy_xor(texto_cifrado)
            if legacy: return legacy
    return desencriptar_texto_legacy_xor(texto_cifrado)

# ☁️ CLOUDINARY
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

ALLOWED_EXTENSIONS = {
    'png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico',
    'pdf', 'txt', 'docx', 'xlsx', 'pptx', 'csv',
    'mp4', 'mov', 'webm', 'avi', 'mkv', 'flv', 'wmv',
    'zip', 'rar', '7z', 'tar', 'gz'
}
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

GMAIL_SCRIPT_URL = os.environ.get('GMAIL_SCRIPT_URL', "https://script.google.com/macros/s/AKfycbwSBbdv-2xl5ND3LjXbDZaXBpzD-mQNNLlFn2H0ih8T7RZouOhF6uEZlxHONsJHxxjq/exec")
RECAPTCHA_SECRET_KEY = os.environ.get('RECAPTCHA_SECRET_KEY', "6LcU0mAtAAAAANT3I4V9q0k5LaBA0B8rEFfvhspC")
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
                id SERIAL PRIMARY KEY,
                usuario VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                correo VARCHAR(200) NOT NULL,
                rol VARCHAR(50) NOT NULL DEFAULT 'estandar'
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id VARCHAR(50) PRIMARY KEY,
                titulo VARCHAR(200) NOT NULL,
                tipo VARCHAR(100) DEFAULT 'Instructivo',
                area VARCHAR(100) DEFAULT 'General',
                descripcion TEXT,
                fecha VARCHAR(100),
                tags TEXT DEFAULT '',
                vistas INTEGER DEFAULT 0,
                descargas INTEGER DEFAULT 0,
                estado VARCHAR(50) DEFAULT 'activo'
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id SERIAL PRIMARY KEY,
                galeria_id VARCHAR(50) NOT NULL,
                filename TEXT NOT NULL,
                estado VARCHAR(50) DEFAULT 'activo'
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                usuario VARCHAR(100) NOT NULL,
                accion VARCHAR(100) NOT NULL,
                detalles TEXT,
                fecha VARCHAR(100) NOT NULL
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(150) NOT NULL,
                url TEXT,
                usuario VARCHAR(150) NOT NULL,
                password_enc TEXT NOT NULL,
                categoria VARCHAR(100) DEFAULT 'General',
                notas TEXT,
                fecha_creacion VARCHAR(100),
                creado_por VARCHAR(100) DEFAULT 'admin',
                estado VARCHAR(50) DEFAULT 'activo'
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(200) NOT NULL,
                contenido TEXT NOT NULL,
                nivel VARCHAR(50) DEFAULT 'info',
                fijado INTEGER DEFAULT 0,
                imagen_url TEXT DEFAULT '',
                estado VARCHAR(50) DEFAULT 'activo',
                fecha VARCHAR(100) NOT NULL,
                autor VARCHAR(100) NOT NULL
            )''')

            for q in [
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS password_enc TEXT;",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE credenciales ADD COLUMN IF NOT EXISTS creado_por VARCHAR(100) DEFAULT 'admin';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS vistas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS descargas INTEGER DEFAULT 0;",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';"
            ]:
                try: cursor.execute(q)
                except Exception: pass
            conn.commit()
        else:
            cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, correo TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'estandar'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id TEXT PRIMARY KEY, titulo TEXT NOT NULL, tipo TEXT DEFAULT 'Instructivo', area TEXT DEFAULT 'General', descripcion TEXT, fecha TEXT, tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, galeria_id TEXT NOT NULL, filename TEXT NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, accion TEXT NOT NULL, detalles TEXT, fecha TEXT NOT NULL
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, url TEXT, usuario TEXT NOT NULL, password_enc TEXT NOT NULL, categoria TEXT DEFAULT 'General', notas TEXT, fecha_creacion TEXT, creado_por TEXT DEFAULT 'admin', estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, contenido TEXT NOT NULL, nivel TEXT DEFAULT 'info', fijado INTEGER DEFAULT 0, imagen_url TEXT DEFAULT '', estado TEXT DEFAULT 'activo', fecha TEXT NOT NULL, autor TEXT NOT NULL
            )''')
            conn.commit()

        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            pass_admin = os.environ.get('ADMIN_PASSWORD_INICIAL', 'admin1234')
            q_ins = "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (?, ?, ?, ?)"
            cursor.execute(q_ins, ('admin', generate_password_hash(pass_admin), 'jesus.mosqueraro@gmail.com', 'admin'))
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
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        nuevo_hash = generate_password_hash(password_plano)
        query = "UPDATE usuarios SET password_hash = %s WHERE usuario = %s" if db_type == 'postgres' else "UPDATE usuarios SET password_hash = ? WHERE usuario = ?"
        cursor.execute(query, (nuevo_hash, usuario))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error migrando password: {e}")

def verificar_recaptcha(response_token):
    if not response_token: return False
    url = "https://www.google.com/recaptcha/api/siteverify"
    data = urllib.parse.urlencode({'secret': RECAPTCHA_SECRET_KEY, 'response': response_token}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8')).get('success', False)
    except Exception:
        return True

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

# 📧 RECUPERACIÓN DE CONTRASEÑA
def enviar_correo_recuperacion(email_destino, usuario_nombre, codigo):
    try:
        cuerpo = f"Hola {usuario_nombre},\n\nTu código de verificación para restablecer tu contraseña en ARKIV es: {codigo}\n\nSi no solicitaste este cambio, por favor ignora este mensaje.\n---\nEquipo de Soporte - ARKIV System"
        payload = {"para": email_destino, "asunto": "Código de Verificación - ARKIV", "cuerpo": cuerpo}
        data_json = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(GMAIL_SCRIPT_URL, data=data_json, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
        with urllib.request.urlopen(req, timeout=15) as response:
            return True
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")
        return False

@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar_clave():
    if request.method == 'POST':
        email_ingresado = (request.form.get('email') or request.form.get('correo') or '').strip().lower()
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
            threading.Thread(target=enviar_correo_recuperacion, args=(email_ingresado, usuario_nombre, codigo_verificacion)).start()
            registrar_log(usuario_nombre, "Solicitud de Código", f"Código generado para: {email_ingresado}")
            return render_template('recuperar.html', paso=2, email=email_ingresado)
        else:
            return render_template('recuperar.html', paso=1, error="El correo ingresado no está registrado en el sistema.")
    return render_template('recuperar.html', paso=1)

@app.route('/validar_codigo', methods=['POST'])
def validar_codigo():
    codigo_ingresado = (request.form.get('codigo') or '').strip()
    nueva_pass = (request.form.get('nueva_password') or request.form.get('password') or '').strip()
    codigo_correcto = session.get('reset_code')
    email_usuario = session.get('reset_email')
    nombre_usuario = session.get('reset_user')

    if not codigo_correcto or not email_usuario:
        return render_template('recuperar.html', paso=1, error="La sesión expiró. Por favor solicita un nuevo código.")

    if codigo_ingresado != codigo_correcto:
        return render_template('recuperar.html', paso=2, email=email_usuario, error="El código de verificación es incorrecto.")

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        nuevo_hash = generate_password_hash(nueva_pass)
        q_upd = "UPDATE usuarios SET password_hash = %s WHERE LOWER(TRIM(correo)) = %s" if db_type == 'postgres' else "UPDATE usuarios SET password_hash = ? WHERE LOWER(TRIM(correo)) = ?"
        cursor.execute(q_upd, (nuevo_hash, email_usuario))
        conn.commit()
        conn.close()

        session.pop('reset_code', None)
        session.pop('reset_email', None)
        session.pop('reset_user', None)

        registrar_log(nombre_usuario, "Cambio Exitoso de Clave", "Se actualizó la contraseña vía recuperación.")
        return render_template('recuperar.html', paso=1, exito="¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.")
    except Exception as e:
        conn.close()
        return render_template('recuperar.html', paso=2, email=email_usuario, error=f"Error actualizando clave: {e}")

# 🔑 LOGIN SEGURO (SIN BYPASS ADMIN/1234)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            username = (request.form.get('usuario') or request.form.get('username') or '').strip()
            password = (request.form.get('contrasena') or request.form.get('password') or '').strip()
            recaptcha_response = request.form.get('g-recaptcha-response')

            if not verificar_recaptcha(recaptcha_response):
                return render_template('login.html', error="Por favor, marca la casilla 'No soy un robot'.")

            conn, db_type = get_db()
            cursor = conn.cursor()
            query = "SELECT usuario, password_hash, rol FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(%s))" if db_type == 'postgres' else "SELECT usuario, password_hash, rol FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(?))"
            cursor.execute(query, (username,))
            user = cursor.fetchone()
            conn.close()

            if user:
                clave_db = str(user[1] or '')
                es_valida = False
                if clave_db.startswith('pbkdf2:') or clave_db.startswith('scrypt:'):
                    es_valida = check_password_hash(clave_db, password)
                else:
                    es_valida = (clave_db == password)
                    if es_valida:
                        _migrar_password_a_hash(user[0], password)

                if es_valida:
                    session.permanent = True
                    session['logged_in'] = True
                    session['username'] = user[0]
                    session['rol'] = user[2]
                    session['instance_id'] = SERVER_INSTANCE_ID
                    registrar_log(user[0], "Inicio de Sesión", "Inicio de sesión exitoso")
                    return redirect(url_for('bienvenida'))

            return render_template('login.html', error="Usuario o contraseña incorrectos.")
        except Exception as e:
            return render_template('login.html', error=f"Error en el servidor: {e}")

    mensaje_expirado = "⚠️ Tu sesión ha expirado. Por favor ingresa nuevamente." if request.args.get('expirado') == '1' else None
    return render_template('login.html', mensaje_expirado=mensaje_expirado)

# 📊 MÉTRICAS
@app.route('/incrementar_vista/<galeria_id>', methods=['POST'])
@login_required
def incrementar_vista(galeria_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (str(galeria_id),))
        conn.commit()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200

@app.route('/incrementar_descarga/<galeria_id>', methods=['POST'])
@login_required
def incrementar_descarga(galeria_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_tit = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_tit, (str(galeria_id),))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q = "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (str(galeria_id),))
        conn.commit()
        conn.close()

        usuario_actual = session.get('username', 'Anónimo')
        registrar_log(usuario_actual, "Descarga de Archivo", f"Descarga del instructivo: '{titulo}'")
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

    if not url_target: return "URL requerida", 400

    try:
        if not filename_custom: filename_custom = url_target.split('/')[-1]
        clean_url = url_target.replace('/fl_attachment/', '/').replace('/upload/fl_attachment/', '/upload/')
        
        if requests:
            res = requests.get(clean_url, timeout=20)
            if res.status_code == 401:
                api_key = os.environ.get('CLOUDINARY_API_KEY')
                api_secret = os.environ.get('CLOUDINARY_API_SECRET')
                if api_key and api_secret:
                    res = requests.get(clean_url, auth=(api_key, api_secret), timeout=20)
            content_data = res.content
        else:
            req = urllib.request.Request(clean_url)
            with urllib.request.urlopen(req) as response:
                content_data = response.read()

        if download_flag == '1':
            usuario_actual = session.get('username', 'Anónimo')
            registrar_log(usuario_actual, "Descarga de Documento", f"Archivo: '{filename_custom}'")

        disposition = 'attachment' if download_flag == '1' else 'inline'
        fname_lower = filename_custom.lower()

        if fname_lower.endswith('.png'): content_type = 'image/png'
        elif fname_lower.endswith(('.jpg', '.jpeg')): content_type = 'image/jpeg'
        elif fname_lower.endswith('.gif'): content_type = 'image/gif'
        elif fname_lower.endswith('.webp'): content_type = 'image/webp'
        elif fname_lower.endswith(('.mp4', '.mov', '.webm', '.avi', '.mkv')): content_type = 'video/mp4'
        elif fname_lower.endswith(('.zip', '.rar', '.7z', '.tar', '.gz')): content_type = 'application/zip'
        else: content_type = 'application/pdf'

        headers = {'Content-Type': content_type, 'Content-Disposition': f'{disposition}; filename="{filename_custom}"'}
        return Response(content_data, headers=headers, status=200)
    except Exception as e:
        return f"Error obteniendo documento: {e}", 500

# 📁 GESTOR DE INSTRUCTIVOS Y ARCHIVOS
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
        cursor.execute("SELECT id, titulo, descripcion, fecha, COALESCE(area, 'General'), tipo, tags, vistas, descargas FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado' ORDER BY fecha DESC")
        rows = cursor.fetchall()
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
        if not palabras_clave: palabras_clave = palabras_limpias

    for r in rows:
        galeria_id, titulo, descripcion, fecha, categoria, tipo, tags, vistas, descargas = r
        sugerencias_titulos.append(titulo)

        query_arch = "SELECT filename FROM archivos WHERE galeria_id = %s AND COALESCE(estado, 'activo') != 'eliminado'" if db_type == 'postgres' else "SELECT filename FROM archivos WHERE galeria_id = ? AND COALESCE(estado, 'activo') != 'eliminado'"
        cursor.execute(query_arch, (str(galeria_id),))
        archivos = [f[0] for f in cursor.fetchall()]

        item = {
            'id': str(galeria_id),
            'titulo': titulo,
            'descripcion': descripcion or '',
            'fecha': formatear_fecha_militar(fecha) if fecha else fecha_defecto,
            'categoria': categoria or 'General',
            'tipo': tipo or 'Instructivo',
            'tags': tags or '',
            'vistas': vistas or 0,
            'descargas': descargas or 0,
            'archivos': archivos
        }

        texto_busqueda = normalizar(f"{titulo} {descripcion} {categoria} {tipo} {tags} {' '.join(archivos)}")
        coincide_busqueda = any(palabra in texto_busqueda for palabra in palabras_clave) if palabras_clave else True
        coincide_cat = not cat_filtro or categoria == cat_filtro
        coincide_tipo = not tipo_filtro or tipo == tipo_filtro

        coincide_formato = True
        if formato_filtro == 'imagen':
            coincide_formato = any(any(ext in a.lower() for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg']) or '/image/upload/' in a for a in archivos)
        elif formato_filtro == 'video':
            coincide_formato = any(any(ext in a.lower() for ext in ['.mp4', '.mov', '.webm', '.avi', '.mkv']) or '/video/upload/' in a for a in archivos)
        elif formato_filtro == 'pdf':
            coincide_formato = any('.pdf' in a.lower() or '.docx' in a.lower() or '.txt' in a.lower() or '/raw/upload/' in a for a in archivos)

        if coincide_busqueda and coincide_cat and coincide_tipo and coincide_formato:
            galerias.append(item)

    conn.close()
    return render_template('index.html', galerias=galerias, busqueda=busqueda_raw, cat_filtro=cat_filtro, tipo_filtro=tipo_filtro, formato_filtro=formato_filtro, sugerencias_titulos=list(set(sugerencias_titulos)), rol=session.get('rol'))

# 🚀 SUBIDA DE ARCHIVOS Y CARPETAS
@app.route('/subir', methods=['POST'])
@login_required
@admin_required
def subir_archivo():
    try:
        archivos_sueltos = request.files.getlist('archivo') or request.files.getlist('archivos') or []
        archivos_carpeta = request.files.getlist('carpeta') or []
        todos_los_archivos = [f for f in (archivos_sueltos + archivos_carpeta) if f and hasattr(f, 'filename') and f.filename]

        titulo = (request.form.get('titulo') or 'Sin título').strip()
        descripcion = (request.form.get('descripcion') or '').strip()
        categoria = (request.form.get('categoria') or 'General').strip()
        tipo = (request.form.get('tipo') or 'Instructivo').strip()
        tags = (request.form.get('tags') or '').strip()
        
        galeria_id = str(uuid.uuid4())[:8]
        fecha_actual = obtener_fecha_actual()

        archivos_guardados = []
        for file in todos_los_archivos:
            try:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if ext in ['mp4', 'mov', 'webm', 'avi', 'mkv', 'flv', 'wmv']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="video", use_filename=True, unique_filename=True)
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="image", use_filename=True, unique_filename=True)
                else:
                    upload_result = cloudinary.uploader.upload(file, resource_type="raw", use_filename=True, unique_filename=True)

                if upload_result and 'secure_url' in upload_result:
                    archivos_guardados.append(upload_result['secure_url'])
            except Exception as e:
                print(f"Error subiendo archivo: {e}")

        conn, db_type = get_db()
        cursor = conn.cursor()
        
        q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha, area, tipo, tags, vistas, descargas, estado) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 'activo')" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha, area, tipo, tags, vistas, descargas, estado) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'activo')"
        cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual, categoria, tipo, tags))

        q_archivo = "INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')"
        for fname in archivos_guardados:
            cursor.execute(q_archivo, (galeria_id, fname))

        conn.commit()
        conn.close()
        registrar_log(session['username'], "Creación de Instructivo", f"Instructivo '{titulo}' [{categoria} / {tipo}] con {len(archivos_guardados)} archivo(s)")
    except Exception as e:
        print(f"❌ Error subiendo instructivo: {e}")
        traceback.print_exc()

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def editar_galeria(galeria_id):
    try:
        nuevo_titulo = (request.form.get('titulo') or '').strip()
        nueva_desc = (request.form.get('descripcion') or '').strip()
        nueva_cat = (request.form.get('categoria') or 'General').strip()
        nuevo_tipo = (request.form.get('tipo') or 'Instructivo').strip()
        nuevos_tags = (request.form.get('tags') or '').strip()
        
        nuevos_archivos = [f for f in (request.files.getlist('nuevos_archivos') or request.files.getlist('archivos') or request.files.getlist('archivo') or request.files.getlist('carpeta') or []) if f and hasattr(f, 'filename') and f.filename]
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        
        q_upd = "UPDATE galerias SET titulo = %s, area = %s, tipo = %s, descripcion = %s, tags = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, area = ?, tipo = ?, descripcion = ?, tags = ? WHERE id = ?"
        cursor.execute(q_upd, (nuevo_titulo, nueva_cat, nuevo_tipo, nueva_desc, nuevos_tags, str(galeria_id)))
        
        archivos_agregados = 0
        for file in nuevos_archivos:
            try:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if ext in ['mp4', 'mov', 'webm', 'avi', 'mkv', 'flv', 'wmv']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="video", use_filename=True, unique_filename=True)
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="image", use_filename=True, unique_filename=True)
                else:
                    upload_result = cloudinary.uploader.upload(file, resource_type="raw", use_filename=True, unique_filename=True)
                
                if upload_result and 'secure_url' in upload_result:
                    q_ins_arch = "INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')"
                    cursor.execute(q_ins_arch, (str(galeria_id), upload_result['secure_url']))
                    archivos_agregados += 1
            except Exception as e:
                print(f"Error editando archivo: {e}")

        conn.commit()
        conn.close()
        registrar_log(session['username'], "Edición de Instructivo", f"Se editó '{nuevo_titulo}' (+{archivos_agregados} archivos)")
    except Exception as e:
        print(f"Error procesando edición: {e}")

    return redirect(url_for('index'))

@app.route('/eliminar_galeria/<galeria_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def eliminar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (str(galeria_id),))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q_upd = "UPDATE galerias SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (str(galeria_id),))
        conn.commit()

        registrar_log(session['username'], "Envío a Papelera", f"El instructivo '{titulo}' fue movido a la papelera.")
    except Exception:
        pass
    conn.close()
    return redirect(url_for('index'))

# 🔑 BÓVEDA DE CREDENCIALES (COLUMNAS NEON: titulo, url, usuario, password_enc, categoria, notas, fecha_creacion)
@app.route('/credenciales')
@login_required
@admin_required
def ver_credenciales():
    q_busqueda = request.args.get('q', '').strip().lower()
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    lista_credenciales = []
    try:
        cursor.execute("SELECT id, titulo, url, usuario, password_enc, categoria, notas, fecha_creacion FROM credenciales WHERE COALESCE(estado, 'activo') != 'eliminado' ORDER BY id DESC")
        rows = cursor.fetchall()
        for r in rows:
            c_id, titulo, url, usuario, pass_enc, categoria, notas, fecha = r
            pass_real = desencriptar_texto(pass_enc)
            texto_full = f"{titulo} {usuario} {categoria} {notas}".lower()
            if not q_busqueda or q_busqueda in texto_full:
                lista_credenciales.append({
                    'id': c_id,
                    'servicio': titulo or 'Sin Nombre',
                    'url': url or '',
                    'usuario': usuario or '',
                    'password': pass_real,
                    'categoria': categoria or 'General',
                    'notas': notas or '',
                    'fecha': formatear_fecha_militar(fecha)
                })
    except Exception as e:
        print(f"Error consultando credenciales: {e}")

    conn.close()
    return render_template('credenciales.html', credenciales=lista_credenciales, q_busqueda=q_busqueda)

@app.route('/credenciales/crear', methods=['POST'])
@login_required
@admin_required
def crear_credencial():
    try:
        servicio = (request.form.get('servicio') or request.form.get('nombre') or request.form.get('titulo') or '').strip()
        url = (request.form.get('url') or request.form.get('url_acceso') or '').strip()
        usuario = (request.form.get('usuario') or request.form.get('username') or '').strip()
        password = (request.form.get('password') or request.form.get('contrasena') or '').strip()
        categoria = (request.form.get('categoria') or request.form.get('area') or 'General').strip()
        notas = (request.form.get('notas') or '').strip()
        fecha_act = obtener_fecha_actual()
        autor = session.get('username', 'admin')
        
        if servicio and usuario and password:
            pass_cifrada = encriptar_texto(password)
            conn, db_type = get_db()
            cursor = conn.cursor()
            q_ins = "INSERT INTO credenciales (titulo, url, usuario, password_enc, categoria, notas, fecha_creacion, creado_por, estado) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO credenciales (titulo, url, usuario, password_enc, categoria, notas, fecha_creacion, creado_por, estado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'activo')"
            cursor.execute(q_ins, (servicio, url, usuario, pass_cifrada, categoria, notas, fecha_act, autor))
            conn.commit()
            conn.close()
            registrar_log(autor, "Guardado de Credencial", f"Acceso registrado: '{servicio}'")
    except Exception as e:
        print(f"Error creando credencial: {e}")
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/editar/<int:cred_id>', methods=['POST'])
@login_required
@admin_required
def editar_credencial(cred_id):
    try:
        servicio = (request.form.get('servicio') or request.form.get('titulo') or '').strip()
        url = (request.form.get('url') or request.form.get('url_acceso') or '').strip()
        usuario = (request.form.get('usuario') or '').strip()
        password = (request.form.get('password') or request.form.get('contrasena') or '').strip()
        categoria = (request.form.get('categoria') or request.form.get('area') or 'General').strip()
        notas = (request.form.get('notas') or '').strip()
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        if password:
            pass_cifrada = encriptar_texto(password)
            q_upd = "UPDATE credenciales SET titulo=%s, url=%s, usuario=%s, password_enc=%s, categoria=%s, notas=%s WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url=?, usuario=?, password_enc=?, categoria=?, notas=? WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, pass_cifrada, categoria, notas, cred_id))
        else:
            q_upd = "UPDATE credenciales SET titulo=%s, url=%s, usuario=%s, categoria=%s, notas=%s WHERE id=%s" if db_type == 'postgres' else "UPDATE credenciales SET titulo=?, url=?, usuario=?, categoria=?, notas=? WHERE id=?"
            cursor.execute(q_upd, (servicio, url, usuario, categoria, notas, cred_id))
            
        conn.commit()
        conn.close()
        registrar_log(session['username'], "Edición de Credencial", f"Actualizada credencial ID '{cred_id}' ({servicio})")
    except Exception as e:
        print(f"Error editando credencial: {e}")
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/eliminar/<int:cred_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def eliminar_credencial(cred_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_upd = "UPDATE credenciales SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (cred_id,))
        conn.commit()
        conn.close()
        registrar_log(session['username'], "Eliminación de Credencial", f"Enviada a papelera credencial ID '{cred_id}'")
    except Exception as e:
        print(f"Error eliminando credencial: {e}")
    return redirect(url_for('ver_papelera' if request.args.get('ref') == 'papelera' else 'ver_credenciales'))

# ♻️ PAPELERA DE RECICLAJE
@app.route('/papelera')
@login_required
@admin_required
def ver_papelera():
    eliminados = []
    archivos_eliminados = []
    credenciales_eliminadas = []
    comunicados_eliminados = []

    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        
        cursor.execute("SELECT id, titulo, descripcion, fecha, area, tipo FROM galerias WHERE estado = 'eliminado' ORDER BY fecha DESC")
        rows_gal = cursor.fetchall()
        for g in rows_gal:
            eliminados.append((g[0], g[1], g[2], formatear_fecha_militar(g[3]), g[4], g[5]))

        cursor.execute("SELECT a.id, a.filename, g.id, g.titulo, g.area FROM archivos a JOIN galerias g ON a.galeria_id = g.id WHERE a.estado = 'eliminado' AND COALESCE(g.estado, 'activo') != 'eliminado'")
        archivos_eliminados = cursor.fetchall()

        cursor.execute("SELECT id, titulo, usuario, categoria, fecha_creacion FROM credenciales WHERE estado = 'eliminado' ORDER BY id DESC")
        rows_c = cursor.fetchall()
        for c in rows_c:
            credenciales_eliminadas.append((c[0], c[1], c[2], c[3], formatear_fecha_militar(c[4])))

        cursor.execute("SELECT id, titulo, COALESCE(nivel, 'info'), fecha, autor FROM comunicados WHERE estado = 'eliminado' ORDER BY id DESC")
        rows_com = cursor.fetchall()
        for r in rows_com:
            comunicados_eliminados.append({
                'id': r[0], 'titulo': r[1], 'nivel': r[2], 'fecha': formatear_fecha_militar(r[3]), 'autor': r[4]
            })

        conn.close()
    except Exception as e:
        print(f"Error cargando papelera: {e}")

    return render_template(
        'papelera.html', 
        eliminados=eliminados, 
        archivos_eliminados=archivos_eliminados, 
        credenciales_eliminadas=credenciales_eliminadas, 
        comunicados_eliminados=comunicados_eliminados
    )

# 🔄 RUTAS DE RESTAURACIÓN Y DESTRUCCIÓN
@app.route('/restaurar_galeria/<galeria_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def restaurar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE galerias SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (str(galeria_id),))
        conn.commit()
        registrar_log(session['username'], "Restauración de Instructivo", f"Instructivo ID '{galeria_id}' restaurado.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_galeria/<galeria_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def destruir_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del1 = "DELETE FROM galerias WHERE id = %s" if db_type == 'postgres' else "DELETE FROM galerias WHERE id = ?"
        q_del2 = "DELETE FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ?"
        cursor.execute(q_del1, (str(galeria_id),))
        cursor.execute(q_del2, (str(galeria_id),))
        conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Instructivo ID '{galeria_id}' destruido.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/restaurar_credencial/<int:cred_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def restaurar_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE credenciales SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (cred_id,))
        conn.commit()
        registrar_log(session['username'], "Restauración de Credencial", f"Credencial ID '{cred_id}' restaurada.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_credencial/<int:cred_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def destruir_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM credenciales WHERE id = %s" if db_type == 'postgres' else "DELETE FROM credenciales WHERE id = ?"
        cursor.execute(q_del, (cred_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Credencial ID '{cred_id}' destruida.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/restaurar_comunicado/<int:com_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def restaurar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE comunicados SET estado = 'activo' WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = 'activo' WHERE id = ?"
        cursor.execute(q_upd, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Restauración de Comunicado", f"Comunicado ID {com_id} restaurado.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_comunicado/<int:com_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def destruir_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM comunicados WHERE id = %s" if db_type == 'postgres' else "DELETE FROM comunicados WHERE id = ?"
        cursor.execute(q_del, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Comunicado ID {com_id} destruido.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/eliminar_imagen/<galeria_id>/<path:filename>', methods=['POST', 'GET'])
@login_required
@admin_required
def eliminar_imagen(galeria_id, filename):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM archivos WHERE galeria_id = %s AND filename = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ? AND filename = ?"
        cursor.execute(q_del, (str(galeria_id), filename))
        conn.commit()
        nombre_limpio = filename.split('/')[-1] if 'http' in filename else filename
        registrar_log(session['username'], "Eliminación de Archivo", f"Se eliminó '{nombre_limpio}' de ID '{galeria_id}'.")
    except Exception: pass
    conn.close()
    return redirect(url_for('index'))

# 👥 GESTIÓN DE USUARIOS
@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def gestion_usuarios():
    conn, db_type = get_db()
    cursor = conn.cursor()
    if request.method == 'POST':
        nuevo_user = (request.form.get('username') or request.form.get('usuario') or '').strip()
        nuevo_pass = (request.form.get('password') or '').strip()
        nuevo_email = (request.form.get('email') or request.form.get('correo') or '').strip()
        nuevo_rol = request.form.get('rol', 'estandar').strip()
        if nuevo_user and nuevo_pass and nuevo_email:
            try:
                pass_hash = generate_password_hash(nuevo_pass)
                q_ins = "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (?, ?, ?, ?)"
                cursor.execute(q_ins, (nuevo_user, pass_hash, nuevo_email, nuevo_rol))
                conn.commit()
                registrar_log(session['username'], "Creación de Usuario", f"Usuario '{nuevo_user}' [{nuevo_rol}]")
                conn.close()
                return redirect(url_for('gestion_usuarios'))
            except Exception: pass

    cursor.execute("SELECT id, usuario, correo, rol FROM usuarios ORDER BY id ASC")
    lista_usuarios = cursor.fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda="")

@app.route('/editar_usuario/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def editar_usuario(usuario_id):
    nuevo_email = (request.form.get('email') or request.form.get('correo') or '').strip()
    nuevo_rol = request.form.get('rol', 'estandar').strip()
    nueva_pass = (request.form.get('password') or '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT usuario FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()
        user_target = row[0] if row else f"ID {usuario_id}"

        if nueva_pass:
            nuevo_hash = generate_password_hash(nueva_pass)
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s, password_hash = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ?, password_hash = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, nuevo_hash, usuario_id))
        else:
            q_upd = "UPDATE usuarios SET correo = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, usuario_id))

        conn.commit()
        registrar_log(session['username'], "Edición de Usuario", f"Actualizado usuario '{user_target}'")
    except Exception: pass
    conn.close()
    return redirect(url_for('gestion_usuarios'))

@app.route('/eliminar_usuario/<int:usuario_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(usuario_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM usuarios WHERE id = %s" if db_type == 'postgres' else "DELETE FROM usuarios WHERE id = ?"
        cursor.execute(q_del, (usuario_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Usuario", f"Se eliminó usuario ID {usuario_id}")
    except Exception: pass
    conn.close()
    return redirect(url_for('gestion_usuarios'))

# 📑 LOGS Y AUDITORÍA
@app.route('/logs')
@login_required
@admin_required
def ver_logs():
    q_usuario = request.args.get('usuario', '').strip()
    q_accion = request.args.get('accion', '').strip()
    q_busqueda = request.args.get('q', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
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
            query += " AND (detalles ILIKE %s OR fecha ILIKE %s)" if db_type == 'postgres' else " AND (detalles LIKE ? OR fecha LIKE ?)"
            params.extend([p_busq, p_busq])

        query += " ORDER BY id DESC"
        cursor.execute(query, tuple(params))
        rows_logs = cursor.fetchall()
        lista_logs = [(l[0], l[1], l[2], formatear_fecha_militar(l[3])) for l in rows_logs]
    except Exception:
        lista_logs, lista_usuarios, lista_acciones = [], [], []
    conn.close()
    return render_template('logs.html', logs=lista_logs, usuarios_opt=lista_usuarios, acciones_opt=lista_acciones, q_usuario=q_usuario, q_accion=q_accion, q_busqueda=q_busqueda)

@app.route('/exportar_logs_csv')
@login_required
@admin_required
def exportar_logs_csv():
    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT fecha, usuario, accion, detalles FROM logs ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['FECHA Y HORA (24H)', 'USUARIO', 'ACCIÓN', 'DETALLE DEL CAMBIO'])
    for row in rows:
        writer.writerow([formatear_fecha_militar(row[0]), row[1], row[2], row[3]])

    csv_bytes = '\ufeff' + output.getvalue()
    fecha_filename = datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%Y%m%d_%H%M")
    headers = {'Content-Type': 'text/csv; charset=utf-8', 'Content-Disposition': f'attachment; filename="Arkiv_Auditoria_Logs_{fecha_filename}.csv"'}
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
        cursor.execute("SELECT titulo, contenido, nivel, imagen_url, fecha, autor FROM comunicados WHERE fijado = 1 AND estado = 'activo' ORDER BY id DESC LIMIT 1")
        row = cursor.fetchone()
        if row:
            comunicado_fijado = {'titulo': row[0], 'contenido': row[1], 'nivel': row[2], 'imagen_url': row[3], 'fecha': formatear_fecha_militar(row[4]), 'autor': row[5]}
    except Exception:
        comunicado_fijado = None
    conn.close()
    return render_template('bienvenida.html', username=session.get('username'), rol=session.get('rol'), comunicado_fijado=comunicado_fijado)

# 📢 COMUNICADOS
@app.route('/comunicados')
@login_required
def ver_comunicados():
    pestana = request.args.get('tab', 'activos').strip().lower()
    q_busqueda = request.args.get('q', '').strip().lower()
    conn, db_type = get_db()
    cursor = conn.cursor()
    estado_filtro = 'activo' if pestana == 'activos' else 'archivado'
    try:
        query = "SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor FROM comunicados WHERE estado = %s ORDER BY fijado DESC, id DESC" if db_type == 'postgres' else "SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor FROM comunicados WHERE estado = ? ORDER BY fijado DESC, id DESC"
        cursor.execute(query, (estado_filtro,))
        rows = cursor.fetchall()
    except Exception: rows = []
    conn.close()

    comunicados = []
    for r in rows:
        c_id, titulo, contenido, nivel, fijado, img_url, estado, fecha, autor = r
        texto_full = f"{titulo} {contenido} {autor}".lower()
        if not q_busqueda or q_busqueda in texto_full:
            comunicados.append({
                'id': c_id, 'titulo': titulo, 'contenido': contenido, 'nivel': nivel,
                'fijado': True if str(fijado).lower() in ['true', 't', '1'] else False,
                'imagen_url': img_url, 'estado': estado,
                'fecha': formatear_fecha_militar(fecha), 'autor': autor
            })
    return render_template('comunicados.html', comunicados=comunicados, pestana=pestana, q_busqueda=q_busqueda, rol=session.get('rol'))

@app.route('/comunicados/crear', methods=['POST'])
@login_required
@admin_required
def crear_comunicado():
    try:
        titulo = request.form.get('titulo', '').strip()
        contenido = request.form.get('contenido', '').strip()
        nivel = request.form.get('nivel', 'info').strip()
        fijado = 1 if request.form.get('fijado') in ['on', '1', 'true', True] else 0
        imagen = request.files.get('imagen')
        imagen_url = ""
        if imagen and hasattr(imagen, 'filename') and imagen.filename:
            upload_result = cloudinary.uploader.upload(imagen, resource_type="image", use_filename=True, unique_filename=True)
            imagen_url = upload_result.get('secure_url', '')

        if titulo and contenido:
            autor = session.get('username', 'Admin')
            fecha_act = obtener_fecha_actual()
            conn, db_type = get_db()
            cursor = conn.cursor()
            q_ins = "INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor) VALUES (%s, %s, %s, %s, %s, 'activo', %s, %s)" if db_type == 'postgres' else "INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha, autor) VALUES (?, ?, ?, ?, ?, 'activo', ?, ?)"
            cursor.execute(q_ins, (titulo, contenido, nivel, fijado, imagen_url, fecha_act, autor))
            conn.commit()
            conn.close()
            registrar_log(autor, "Publicación de Comunicado", f"Comunicado: '{titulo}' [{nivel}]")
    except Exception as e:
        print(f"Error creando comunicado: {e}")
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/archivar/<int:com_id>', methods=['POST', 'GET'])
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
            q_upd = "UPDATE comunicados SET estado = %s, fijado = 0 WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = ?, fijado = 0 WHERE id = ?"
            cursor.execute(q_upd, (nuevo_estado, com_id))
            conn.commit()
            registrar_log(session['username'], "Cambio Estado Comunicado", f"Comunicado '{row[1]}' movido a {nuevo_estado}")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/eliminar/<int:com_id>', methods=['POST', 'GET'])
@login_required
@admin_required
def eliminar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE comunicados SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = 'eliminado' WHERE id = ?"
        cursor.execute(q_upd, (com_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Comunicado", f"Comunicado ID {com_id} movido a papelera")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_comunicados'))

# 🗄️ ADMINISTRADOR DE BASE DE DATOS
@app.route('/admin/db', methods=['GET', 'POST'])
@login_required
@admin_required
def visor_db():
    tabla_seleccionada = request.args.get('tabla', 'usuarios')
    tablas_permitidas = ['usuarios', 'galerias', 'archivos', 'logs', 'credenciales', 'comunicados']
    if tabla_seleccionada not in tablas_permitidas: tabla_seleccionada = 'usuarios'
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    columnas, registros, error_sql = [], [], None
    try:
        cursor.execute(f"SELECT * FROM {tabla_seleccionada} LIMIT 100")
        registros = cursor.fetchall()
        if cursor.description: columnas = [desc[0] for desc in cursor.description]
    except Exception: error_sql = "Error consultando la tabla."
    finally: conn.close()

    return render_template('admin_db.html', tabla=tabla_seleccionada, tablas=tablas_permitidas, columnas=columnas, registros=registros, sql="", exito=None, error=error_sql)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
