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
import ssl
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify

# Hasheo y sanitización segura
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect

# PostgreSQL Drivers
try:
    import pg8000.dbapi
except Exception:
    pg8000 = None

try:
    import psycopg2
except Exception:
    psycopg2 = None

import cloudinary
import cloudinary.uploader

try:
    import requests
except Exception:
    requests = None

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_secreta_gestor_archivos_ultra_segura_2026_prod')

csrf = CSRFProtect(app)
SERVER_INSTANCE_ID = str(uuid.uuid4())
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

# 🇨🇴 ZONA HORARIA COLOMBIA
try:
    ZONA_HORARIA_COLOMBIA = ZoneInfo("America/Bogota")
except Exception:
    ZONA_HORARIA_COLOMBIA = timezone(timedelta(hours=-5))

def obtener_fecha_actual():
    try:
        return datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%d/%m/%Y %I:%M %p")
    except Exception:
        return datetime.now().strftime("%d/%m/%Y %I:%M %p")

def normalizar(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower().strip()

# 🔐 CIFRADO Y DESCIFRADO NATIVO
def encriptar_texto(texto):
    if not texto: return ""
    try:
        clave = app.secret_key.encode('utf-8')
        bytes_texto = texto.encode('utf-8')
        cifrado = bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_texto)])
        return base64.b64encode(cifrado).decode('utf-8')
    except Exception:
        return texto

def desencriptar_texto(texto_cifrado):
    if not texto_cifrado: return ""
    try:
        clave = app.secret_key.encode('utf-8')
        bytes_cifrados = base64.b64decode(texto_cifrado.encode('utf-8'))
        descifrado = bytes([b ^ clave[i % len(clave)] for i, b in enumerate(bytes_cifrados)])
        return descifrado.decode('utf-8')
    except Exception:
        return texto_cifrado

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
    if DATABASE_URL:
        url = DATABASE_URL.strip()
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if "-pooler" in url:
            url = url.replace("-pooler", "")
        if "sslmode=" not in url:
            url += ("&" if "?" in url else "?") + "sslmode=require"

        if pg8000:
            parsed = urllib.parse.urlparse(url)
            ssl_ctx = ssl.create_default_context()
            conn = pg8000.dbapi.connect(
                user=parsed.username,
                password=parsed.password,
                host=parsed.hostname,
                port=parsed.port or 5432,
                database=parsed.path.lstrip('/'),
                ssl_context=ssl_ctx,
                timeout=15
            )
            conn.autocommit = True
            return conn, 'postgres'
        elif psycopg2:
            conn = psycopg2.connect(url, connect_timeout=15)
            conn.autocommit = True
            return conn, 'postgres'

    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_NAME = os.path.join(BASE_DIR, "gestor.db")
    conn = sqlite3.connect(DB_NAME)
    return conn, 'sqlite'

# 🛡️ INICIALIZACIÓN Y ESQUEMA EXACTO
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
                rol VARCHAR(50) NOT NULL DEFAULT 'estandar',
                nombre VARCHAR(100) DEFAULT '',
                area VARCHAR(100) DEFAULT '',
                activo BOOLEAN DEFAULT TRUE
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(200) NOT NULL,
                tipo VARCHAR(100) DEFAULT 'Instructivo',
                area VARCHAR(100) DEFAULT 'General',
                descripcion TEXT,
                subido_por VARCHAR(100) DEFAULT 'admin',
                fecha_subida TIMESTAMP DEFAULT NOW(),
                eliminado BOOLEAN DEFAULT FALSE,
                fecha_eliminacion TIMESTAMP,
                eliminado_por VARCHAR(100),
                tags TEXT DEFAULT '',
                vistas INTEGER DEFAULT 0,
                descargas INTEGER DEFAULT 0
            )''')
            
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id SERIAL PRIMARY KEY,
                galeria_id VARCHAR(50) NOT NULL,
                filename TEXT NOT NULL,
                estado VARCHAR(50) DEFAULT 'activo'
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS auditoria_logs (
                id SERIAL PRIMARY KEY,
                usuario VARCHAR(100),
                accion VARCHAR(100),
                detalles TEXT,
                fecha VARCHAR(100)
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(150) NOT NULL,
                usuario_acceso VARCHAR(150) NOT NULL,
                password_cifrada TEXT NOT NULL,
                area VARCHAR(100) DEFAULT 'General',
                url_acceso TEXT DEFAULT '',
                notas TEXT DEFAULT '',
                creado_por VARCHAR(100) DEFAULT 'admin',
                fecha_creacion TIMESTAMP DEFAULT NOW(),
                eliminado BOOLEAN DEFAULT FALSE,
                fecha_eliminacion TIMESTAMP,
                eliminado_por VARCHAR(100)
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id SERIAL PRIMARY KEY,
                titulo VARCHAR(200) NOT NULL,
                contenido TEXT NOT NULL,
                nivel VARCHAR(50) DEFAULT 'info',
                fijado BOOLEAN DEFAULT FALSE,
                imagen_url TEXT DEFAULT '',
                estado VARCHAR(50) DEFAULT 'activo',
                fecha_publicacion TIMESTAMP DEFAULT NOW(),
                autor VARCHAR(100) NOT NULL
            )''')

            for q in [
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS vistas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS descargas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS filename TEXT;",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';"
            ]:
                try: cursor.execute(q)
                except Exception: pass
        else:
            cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, correo TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'estandar'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, tipo TEXT DEFAULT 'Instructivo', area TEXT DEFAULT 'General', descripcion TEXT, subido_por TEXT DEFAULT 'admin', fecha_subida TEXT, eliminado INTEGER DEFAULT 0, tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, galeria_id TEXT, filename TEXT NOT NULL, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS auditoria_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT, accion TEXT, detalles TEXT, fecha TEXT
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS credenciales (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, usuario_acceso TEXT NOT NULL, password_cifrada TEXT NOT NULL, area TEXT DEFAULT 'General', url_acceso TEXT DEFAULT '', notas TEXT DEFAULT '', creado_por TEXT DEFAULT 'admin', fecha_creacion TEXT, eliminado INTEGER DEFAULT 0
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS comunicados (
                id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT NOT NULL, contenido TEXT NOT NULL, nivel TEXT DEFAULT 'info', fijado INTEGER DEFAULT 0, imagen_url TEXT DEFAULT '', estado TEXT DEFAULT 'activo', fecha_publicacion TEXT, autor TEXT NOT NULL
            )''')

        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            cursor.execute("INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (?, ?, ?, ?)",
                           ('admin', '1234', 'jesus.mosqueraro@gmail.com', 'admin'))

        conn.close()
    except Exception as e:
        print(f"Error inicializando base de datos: {e}")

init_db()

def registrar_log(usuario, accion, detalles=""):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha_actual = obtener_fecha_actual()
        query = "INSERT INTO auditoria_logs (usuario, accion, detalles, fecha) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO auditoria_logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)"
        cursor.execute(query, (usuario, accion, detalles, fecha_actual))
        if db_type == 'sqlite': conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrando log: {e}")

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

# 📧 CORREO DE RECUPERACIÓN
def enviar_correo_recuperacion(email_destino, usuario_nombre, codigo):
    try:
        cuerpo = f"Hola {usuario_nombre},\n\nTu código de verificación para restablecer tu contraseña en ARKIV es: {codigo}\n\nSi no solicitaste este cambio, por favor ignora este mensaje.\n---\nEquipo de Soporte - ARKIV System"
        payload = {"para": email_destino, "asunto": "Código de Verificación - ARKIV", "cuerpo": cuerpo}
        data_json = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(GMAIL_SCRIPT_URL, data=data_json, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(req, context=ctx, timeout=15) as response:
            return True
    except Exception as e:
        print(f"❌ Error enviando correo: {e}")
        return False

@app.route('/recuperar', methods=['GET', 'POST'])
@csrf.exempt
def recuperar_clave():
    if request.method == 'POST':
        email_ingresado = (request.form.get('email') or request.form.get('correo') or '').strip().lower()
        conn, db_type = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT usuario FROM usuarios WHERE LOWER(TRIM(correo)) = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE LOWER(TRIM(correo)) = ?", (email_ingresado,))
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
@csrf.exempt
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
        pass_hash = generate_password_hash(nueva_pass)
        cursor.execute("UPDATE usuarios SET password_hash = %s WHERE LOWER(TRIM(correo)) = %s" if db_type == 'postgres' else "UPDATE usuarios SET password_hash = ? WHERE LOWER(TRIM(correo)) = ?", (pass_hash, email_usuario))
        if db_type == 'sqlite': conn.commit()
        conn.close()

        session.pop('reset_code', None)
        session.pop('reset_email', None)
        session.pop('reset_user', None)

        registrar_log(nombre_usuario, "Cambio Exitoso de Clave", "Se actualizó la contraseña vía recuperación.")
        return render_template('recuperar.html', paso=1, exito="¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.")
    except Exception as e:
        conn.close()
        return render_template('recuperar.html', paso=2, email=email_usuario, error=f"Error actualizando clave: {e}")

# 🔑 INICIO DE SESIÓN
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
            cursor.execute("SELECT usuario, password_hash, rol FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(%s))" if db_type == 'postgres' else "SELECT usuario, password_hash, rol FROM usuarios WHERE LOWER(TRIM(usuario)) = LOWER(TRIM(?))", (username,))
            user = cursor.fetchone()
            conn.close()

            if user:
                clave_db = str(user[1] or '')
                es_valida = check_password_hash(clave_db, password) if (clave_db.startswith('pbkdf2:') or clave_db.startswith('scrypt:')) else (clave_db == password)
                
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
@csrf.exempt
@login_required
def incrementar_vista(galeria_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q = "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id::text = %s" if db_type == 'postgres' else "UPDATE galerias SET vistas = COALESCE(vistas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (str(galeria_id),))
        if db_type == 'sqlite': conn.commit()
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
        q_tit = "SELECT titulo FROM galerias WHERE id::text = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_tit, (str(galeria_id),))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        q = "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id::text = %s" if db_type == 'postgres' else "UPDATE galerias SET descargas = COALESCE(descargas, 0) + 1 WHERE id = ?"
        cursor.execute(q, (str(galeria_id),))
        if db_type == 'sqlite': conn.commit()
        conn.close()

        usuario_actual = session.get('username', 'Anónimo')
        registrar_log(usuario_actual, "Descarga de Archivo", f"Descarga del instructivo: '{titulo}'")
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 200

# 🚀 PROXY AUTENTICADO DE DOCUMENTOS Y MULTIMEDIA
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
        cursor.execute("""
            SELECT id, 
                   COALESCE(titulo, 'Sin título'), 
                   COALESCE(descripcion, ''), 
                   COALESCE(fecha_subida::text, ''), 
                   COALESCE(area, 'General'), 
                   COALESCE(tipo, 'Instructivo'), 
                   COALESCE(tags, ''), 
                   COALESCE(vistas, 0), 
                   COALESCE(descargas, 0) 
            FROM galerias 
            WHERE eliminado IS NOT TRUE 
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error consultando galerias: {e}")
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
        galeria_id, titulo, descripcion, fecha_subida, categoria, tipo, tags, vistas, descargas = r
        sugerencias_titulos.append(titulo)

        query_arch = "SELECT filename FROM archivos WHERE galeria_id::text = %s AND COALESCE(estado, 'activo') != 'eliminado'" if db_type == 'postgres' else "SELECT filename FROM archivos WHERE galeria_id = ? AND COALESCE(estado, 'activo') != 'eliminado'"
        cursor.execute(query_arch, (str(galeria_id),))
        archivos = [f[0] for f in cursor.fetchall() if f[0]]

        item = {
            'id': str(galeria_id),
            'titulo': titulo,
            'descripcion': descripcion or '',
            'fecha': str(fecha_subida)[:16] if fecha_subida else fecha_defecto,
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

# 🚀 SUBIDA DE ARCHIVOS MÚLTIPLES (CUALQUIER FORMATO)
@app.route('/subir', methods=['POST'])
@csrf.exempt
@login_required
@admin_required
def subir_archivo():
    try:
        archivos = request.files.getlist('archivo') or request.files.getlist('archivos') or request.files.getlist('file')
        titulo = (request.form.get('titulo') or 'Sin título').strip()
        descripcion = (request.form.get('descripcion') or '').strip()
        categoria = (request.form.get('categoria') or 'General').strip()
        tipo = (request.form.get('tipo') or 'Instructivo').strip()
        tags = (request.form.get('tags') or '').strip()
        autor = session.get('username', 'admin')

        archivos_guardados = []
        for file in archivos:
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if ext in ['mp4', 'mov', 'webm', 'avi', 'mkv', 'flv', 'wmv']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="video", use_filename=True, unique_filename=True)
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="image", use_filename=True, unique_filename=True)
                else:
                    upload_result = cloudinary.uploader.upload(file, resource_type="raw", use_filename=True, unique_filename=True)

                archivos_guardados.append(upload_result['secure_url'])

        if archivos_guardados:
            conn, db_type = get_db()
            cursor = conn.cursor()
            
            if db_type == 'postgres':
                cursor.execute("""
                    INSERT INTO galerias (titulo, tipo, area, descripcion, subido_por, fecha_subida, eliminado, tags, vistas, descargas) 
                    VALUES (%s, %s, %s, %s, %s, NOW(), FALSE, %s, 0, 0)
                    RETURNING id
                """, (titulo, tipo, categoria, descripcion, autor, tags))
                nuevo_id = str(cursor.fetchone()[0])
            else:
                cursor.execute("""
                    INSERT INTO galerias (titulo, tipo, area, descripcion, subido_por, fecha_subida, eliminado, tags, vistas, descargas) 
                    VALUES (?, ?, ?, ?, ?, datetime('now'), 0, ?, 0, 0)
                """, (titulo, tipo, categoria, descripcion, autor, tags))
                nuevo_id = str(cursor.lastrowid)

            for fname in archivos_guardados:
                cursor.execute("INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')", (nuevo_id, fname))

            if db_type == 'sqlite': conn.commit()
            conn.close()
            registrar_log(session['username'], "Creación de Instructivo", f"Instructivo '{titulo}' [{categoria} / {tipo}] con {len(archivos_guardados)} archivo(s)")
            flash(f"Instructivo '{titulo}' publicado con éxito.")
    except Exception as e:
        print(f"❌ Error subiendo instructivo: {e}")
        traceback.print_exc()
        flash("Ocurrió un error al subir el instructivo.")

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@csrf.exempt
@login_required
@admin_required
def editar_galeria(galeria_id):
    try:
        nuevo_titulo = (request.form.get('titulo') or '').strip()
        nueva_desc = (request.form.get('descripcion') or '').strip()
        nueva_cat = (request.form.get('categoria') or 'General').strip()
        nuevo_tipo = (request.form.get('tipo') or 'Instructivo').strip()
        nuevos_tags = (request.form.get('tags') or '').strip()
        nuevos_archivos = request.files.getlist('nuevos_archivos') or request.files.getlist('archivo') or request.files.getlist('archivos')
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        
        q_upd = "UPDATE galerias SET titulo = %s, area = %s, tipo = %s, descripcion = %s, tags = %s WHERE id::text = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, area = ?, tipo = ?, descripcion = ?, tags = ? WHERE id = ?"
        cursor.execute(q_upd, (nuevo_titulo, nueva_cat, nuevo_tipo, nueva_desc, nuevos_tags, str(galeria_id)))
        
        archivos_agregados = 0
        for file in nuevos_archivos:
            if file and file.filename:
                ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                if ext in ['mp4', 'mov', 'webm', 'avi', 'mkv', 'flv', 'wmv']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="video", use_filename=True, unique_filename=True)
                elif ext in ['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico']:
                    upload_result = cloudinary.uploader.upload(file, resource_type="image", use_filename=True, unique_filename=True)
                else:
                    upload_result = cloudinary.uploader.upload(file, resource_type="raw", use_filename=True, unique_filename=True)
                
                q_ins = "INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')"
                cursor.execute(q_ins, (str(galeria_id), upload_result['secure_url']))
                archivos_agregados += 1

        if db_type == 'sqlite': conn.commit()
        conn.close()
        registrar_log(session['username'], "Edición de Instructivo", f"Se editó '{nuevo_titulo}' (+{archivos_agregados} archivos)")
    except Exception as e:
        print(f"Error procesando edición: {e}")

    return redirect(url_for('index'))

@app.route('/eliminar_galeria/<galeria_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def eliminar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT titulo FROM galerias WHERE id::text = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?", (str(galeria_id),))
        row = cursor.fetchone()
        titulo = row[0] if row else galeria_id

        autor = session.get('username', 'admin')
        cursor.execute("UPDATE galerias SET eliminado = TRUE, fecha_eliminacion = NOW(), eliminado_por = %s WHERE id::text = %s" if db_type == 'postgres' else "UPDATE galerias SET eliminado = 1 WHERE id = ?", (autor, str(galeria_id)) if db_type == 'postgres' else (str(galeria_id),))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Envío a Papelera", f"Instructivo '{titulo}' enviado a papelera.")
    except Exception:
        pass
    conn.close()
    return redirect(url_for('index'))

# 🔑 BÓVEDA DE CREDENCIALES
@app.route('/credenciales')
@login_required
@admin_required
def ver_credenciales():
    q_busqueda = request.args.get('q', '').strip().lower()
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    lista_credenciales = []
    try:
        cursor.execute("""
            SELECT id, titulo, url_acceso, usuario_acceso, password_cifrada, area, notas, COALESCE(fecha_creacion::text, '') 
            FROM credenciales 
            WHERE eliminado IS NOT TRUE 
            ORDER BY id DESC
        """)
        rows = cursor.fetchall()
        for r in rows:
            c_id, titulo, url, usuario, pass_enc, area, notas, fecha = r
            pass_real = desencriptar_texto(pass_enc)
            texto_full = f"{titulo} {usuario} {area} {notas}".lower()
            if not q_busqueda or q_busqueda in texto_full:
                lista_credenciales.append({
                    'id': c_id,
                    'servicio': titulo or 'Sin Nombre',
                    'url': url or '',
                    'usuario': usuario or '',
                    'password': pass_real,
                    'categoria': area or 'General',
                    'notas': notas or '',
                    'fecha': str(fecha)[:16] if fecha else ''
                })
    except Exception as e:
        print(f"Error consultando credenciales: {e}")

    conn.close()
    return render_template('credenciales.html', credenciales=lista_credenciales, q_busqueda=q_busqueda)

@app.route('/credenciales/crear', methods=['POST'])
@csrf.exempt
@login_required
@admin_required
def crear_credencial():
    try:
        servicio = (request.form.get('servicio') or request.form.get('nombre') or request.form.get('titulo') or '').strip()
        url = (request.form.get('url') or request.form.get('url_acceso') or '').strip()
        usuario = (request.form.get('usuario') or request.form.get('username') or request.form.get('usuario_acceso') or '').strip()
        password = (request.form.get('password') or request.form.get('contrasena') or '').strip()
        categoria = (request.form.get('categoria') or request.form.get('area') or 'General').strip()
        notas = (request.form.get('notas') or '').strip()
        autor = session.get('username', 'admin')
        
        if servicio and usuario and password:
            pass_cifrada = encriptar_texto(password)
            conn, db_type = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO credenciales (titulo, usuario_acceso, password_cifrada, area, url_acceso, notas, creado_por, fecha_creacion, eliminado) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), FALSE)
            """ if db_type == 'postgres' else """
                INSERT INTO credenciales (titulo, usuario_acceso, password_cifrada, area, url_acceso, notas, creado_por, fecha_creacion, eliminado) 
                VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'), 0)
            """, (servicio, usuario, pass_cifrada, categoria, url, notas, autor))
            
            if db_type == 'sqlite': conn.commit()
            conn.close()
            registrar_log(autor, "Guardado de Credencial", f"Acceso registrado: '{servicio}'")
            flash(f"Credencial '{servicio}' registrada con éxito.")
    except Exception as e:
        print(f"Error creando credencial: {e}")
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/editar/<int:cred_id>', methods=['POST'])
@csrf.exempt
@login_required
@admin_required
def editar_credencial(cred_id):
    try:
        servicio = (request.form.get('servicio') or request.form.get('titulo') or '').strip()
        url = (request.form.get('url') or request.form.get('url_acceso') or '').strip()
        usuario = (request.form.get('usuario') or request.form.get('usuario_acceso') or '').strip()
        password = (request.form.get('password') or request.form.get('contrasena') or '').strip()
        categoria = (request.form.get('categoria') or request.form.get('area') or 'General').strip()
        notas = (request.form.get('notas') or '').strip()
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        if password:
            pass_cifrada = encriptar_texto(password)
            cursor.execute("""
                UPDATE credenciales 
                SET titulo=%s, usuario_acceso=%s, password_cifrada=%s, area=%s, url_acceso=%s, notas=%s 
                WHERE id=%s
            """ if db_type == 'postgres' else """
                UPDATE credenciales 
                SET titulo=?, usuario_acceso=?, password_cifrada=?, area=?, url_acceso=?, notas=? 
                WHERE id=?
            """, (servicio, usuario, pass_cifrada, categoria, url, notas, cred_id))
        else:
            cursor.execute("""
                UPDATE credenciales 
                SET titulo=%s, usuario_acceso=%s, area=%s, url_acceso=%s, notas=%s 
                WHERE id=%s
            """ if db_type == 'postgres' else """
                UPDATE credenciales 
                SET titulo=?, usuario_acceso=?, area=?, url_acceso=?, notas=? 
                WHERE id=?
            """, (servicio, usuario, categoria, url, notas, cred_id))
            
        if db_type == 'sqlite': conn.commit()
        conn.close()
        registrar_log(session['username'], "Edición de Credencial", f"Actualizada credencial ID '{cred_id}' ({servicio})")
    except Exception as e:
        print(f"Error editando credencial: {e}")
    return redirect(url_for('ver_credenciales'))

@app.route('/credenciales/eliminar/<int:cred_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def eliminar_credencial(cred_id):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        autor = session.get('username', 'admin')
        cursor.execute("UPDATE credenciales SET eliminado = TRUE, fecha_eliminacion = NOW(), eliminado_por = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET eliminado = 1 WHERE id = ?", (autor, cred_id) if db_type == 'postgres' else (cred_id,))
        if db_type == 'sqlite': conn.commit()
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
        
        # 1. Instructivos
        cursor.execute("""
            SELECT id, titulo, descripcion, COALESCE(fecha_eliminacion::text, fecha_subida::text, ''), area, tipo 
            FROM galerias 
            WHERE eliminado IS TRUE 
            ORDER BY id DESC
        """ if db_type == 'postgres' else """
            SELECT id, titulo, descripcion, COALESCE(fecha_subida, ''), area, tipo 
            FROM galerias 
            WHERE eliminado = 1 
            ORDER BY id DESC
        """)
        eliminados = cursor.fetchall()

        # 2. Archivos
        cursor.execute("""
            SELECT a.id, a.filename, g.id, g.titulo, g.area 
            FROM archivos a 
            JOIN galerias g ON a.galeria_id::text = g.id::text 
            WHERE a.estado = 'eliminado' AND g.eliminado IS NOT TRUE
        """ if db_type == 'postgres' else """
            SELECT a.id, a.filename, g.id, g.titulo, g.area 
            FROM archivos a 
            JOIN galerias g ON a.galeria_id = g.id 
            WHERE a.estado = 'eliminado' AND g.eliminado != 1
        """)
        archivos_eliminados = cursor.fetchall()

        # 3. Credenciales
        cursor.execute("""
            SELECT id, titulo, usuario_acceso, area, COALESCE(fecha_eliminacion::text, fecha_creacion::text, '') 
            FROM credenciales 
            WHERE eliminado IS TRUE 
            ORDER BY id DESC
        """ if db_type == 'postgres' else """
            SELECT id, titulo, usuario_acceso, area, COALESCE(fecha_creacion, '') 
            FROM credenciales 
            WHERE eliminado = 1 
            ORDER BY id DESC
        """)
        credenciales_eliminadas = cursor.fetchall()

        # 4. Comunicados
        cursor.execute("""
            SELECT id, titulo, COALESCE(nivel, 'info'), COALESCE(fecha_publicacion::text, ''), autor 
            FROM comunicados 
            WHERE LOWER(TRIM(COALESCE(estado, 'activo'))) = 'eliminado' 
            ORDER BY id DESC
        """)
        rows_com = cursor.fetchall()
        for r in rows_com:
            comunicados_eliminados.append({
                'id': r[0],
                'titulo': r[1],
                'nivel': r[2],
                'fecha': str(r[3])[:16] if r[3] else '',
                'autor': r[4]
            })

        conn.close()
    except Exception as e:
        print(f"Error cargando papelera: {e}")
        traceback.print_exc()

    return render_template(
        'papelera.html', 
        eliminados=eliminados, 
        archivos_eliminados=archivos_eliminados, 
        credenciales_eliminadas=credenciales_eliminadas, 
        comunicados_eliminados=comunicados_eliminados
    )

@app.route('/restaurar_galeria/<galeria_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def restaurar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE galerias SET eliminado = FALSE, fecha_eliminacion = NULL, eliminado_por = NULL WHERE id::text = %s" if db_type == 'postgres' else "UPDATE galerias SET eliminado = 0 WHERE id = ?", (str(galeria_id),))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Restauración de Instructivo", f"Instructivo ID '{galeria_id}' restaurado.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_galeria/<galeria_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def destruir_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM galerias WHERE id::text = %s" if db_type == 'postgres' else "DELETE FROM galerias WHERE id = ?", (str(galeria_id),))
        cursor.execute("DELETE FROM archivos WHERE galeria_id::text = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ?", (str(galeria_id),))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Instructivo ID '{galeria_id}' destruido.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/restaurar_credencial/<int:cred_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def restaurar_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE credenciales SET eliminado = FALSE, fecha_eliminacion = NULL, eliminado_por = NULL WHERE id = %s" if db_type == 'postgres' else "UPDATE credenciales SET eliminado = 0 WHERE id = ?", (cred_id,))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Restauración de Credencial", f"Credencial ID '{cred_id}' restaurada.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/destruir_credencial/<int:cred_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def destruir_credencial(cred_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM credenciales WHERE id = %s" if db_type == 'postgres' else "DELETE FROM credenciales WHERE id = ?", (cred_id,))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Eliminación Permanente", f"Credencial ID '{cred_id}' destruida.")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_papelera'))

@app.route('/eliminar_imagen/<galeria_id>/<path:filename>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def eliminar_imagen(galeria_id, filename):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM archivos WHERE galeria_id::text = %s AND filename = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ? AND filename = ?", (str(galeria_id), filename))
        if db_type == 'sqlite': conn.commit()
        nombre_limpio = filename.split('/')[-1] if 'http' in filename else filename
        registrar_log(session['username'], "Eliminación de Archivo", f"Se eliminó '{nombre_limpio}' del instructivo ID '{galeria_id}'.")
    except Exception: pass
    conn.close()
    return redirect(url_for('index'))

# 👥 USUARIOS
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
                cursor.execute("INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (usuario, password_hash, correo, rol) VALUES (?, ?, ?, ?)", (nuevo_user, pass_hash, nuevo_email, nuevo_rol))
                if db_type == 'sqlite': conn.commit()
                registrar_log(session['username'], "Creación de Usuario", f"Usuario '{nuevo_user}' [{nuevo_rol}]")
                conn.close()
                return redirect(url_for('gestion_usuarios'))
            except Exception: pass

    try:
        cursor.execute("SELECT id, usuario, correo, rol FROM usuarios ORDER BY id ASC")
        lista_usuarios = cursor.fetchall()
    except Exception:
        lista_usuarios = []

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
        user_target = f"ID {usuario_id}"
        cursor.execute("SELECT usuario FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT usuario FROM usuarios WHERE id = ?", (usuario_id,))
        row = cursor.fetchone()
        if row: user_target = row[0]

        if nueva_pass:
            pass_hash = generate_password_hash(nueva_pass)
            cursor.execute("UPDATE usuarios SET correo = %s, rol = %s, password_hash = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ?, password_hash = ? WHERE id = ?", (nuevo_email, nuevo_rol, pass_hash, usuario_id))
        else:
            cursor.execute("UPDATE usuarios SET correo = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET correo = ?, rol = ? WHERE id = ?", (nuevo_email, nuevo_rol, usuario_id))

        if db_type == 'sqlite': conn.commit()
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
        cursor.execute("DELETE FROM usuarios WHERE id = %s" if db_type == 'postgres' else "DELETE FROM usuarios WHERE id = ?", (usuario_id,))
        if db_type == 'sqlite': conn.commit()
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
        cursor.execute("SELECT DISTINCT usuario FROM auditoria_logs ORDER BY usuario ASC")
        lista_usuarios = [u[0] for u in cursor.fetchall() if u[0]]
        cursor.execute("SELECT DISTINCT accion FROM auditoria_logs ORDER BY accion ASC")
        lista_acciones = [a[0] for a in cursor.fetchall() if a[0]]

        query = "SELECT usuario, accion, detalles, fecha FROM auditoria_logs WHERE 1=1"
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
        lista_logs = cursor.fetchall()
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
    cursor.execute("SELECT fecha, usuario, accion, detalles FROM auditoria_logs ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow(['FECHA Y HORA', 'USUARIO', 'ACCIÓN', 'DETALLE DEL CAMBIO'])
    for row in rows: writer.writerow(row)

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
        cursor.execute("""
            SELECT titulo, contenido, nivel, imagen_url, COALESCE(fecha_publicacion::text, ''), autor 
            FROM comunicados 
            WHERE fijado IS TRUE AND COALESCE(estado, 'activo') = 'activo' 
            ORDER BY id DESC LIMIT 1
        """ if db_type == 'postgres' else """
            SELECT titulo, contenido, nivel, imagen_url, fecha_publicacion, autor 
            FROM comunicados 
            WHERE fijado = 1 AND estado = 'activo' 
            ORDER BY id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        if row:
            comunicado_fijado = {'titulo': row[0], 'contenido': row[1], 'nivel': row[2], 'imagen_url': row[3], 'fecha': str(row[4])[:16], 'autor': row[5]}
    except Exception: comunicado_fijado = None
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
        cursor.execute("""
            SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, COALESCE(fecha_publicacion::text, ''), autor 
            FROM comunicados 
            WHERE COALESCE(estado, 'activo') = %s 
            ORDER BY fijado DESC, id DESC
        """ if db_type == 'postgres' else """
            SELECT id, titulo, contenido, nivel, fijado, imagen_url, estado, fecha_publicacion, autor 
            FROM comunicados 
            WHERE estado = ? 
            ORDER BY fijado DESC, id DESC
        """, (estado_filtro,))
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
                'fecha': str(fecha)[:16] if fecha else '', 'autor': autor
            })
    return render_template('comunicados.html', comunicados=comunicados, pestana=pestana, q_busqueda=q_busqueda, rol=session.get('rol'))

@app.route('/comunicados/crear', methods=['POST'])
@csrf.exempt
@login_required
@admin_required
def crear_comunicado():
    try:
        titulo = request.form.get('titulo', '').strip()
        contenido = request.form.get('contenido', '').strip()
        nivel = request.form.get('nivel', 'info').strip()
        fijado = True if request.form.get('fijado') in ['on', '1', 'true', True] else False
        imagen = request.files.get('imagen')
        imagen_url = ""
        if imagen and imagen.filename:
            upload_result = cloudinary.uploader.upload(imagen, resource_type="image", use_filename=True, unique_filename=True)
            imagen_url = upload_result.get('secure_url', '')

        if titulo and contenido:
            autor = session.get('username', 'Admin')
            conn, db_type = get_db()
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha_publicacion, autor) 
                VALUES (%s, %s, %s, %s, %s, 'activo', NOW(), %s)
            """ if db_type == 'postgres' else """
                INSERT INTO comunicados (titulo, contenido, nivel, fijado, imagen_url, estado, fecha_publicacion, autor) 
                VALUES (?, ?, ?, ?, ?, 'activo', datetime('now'), ?)
            """, (titulo, contenido, nivel, fijado, imagen_url, autor))
            
            if db_type == 'sqlite': conn.commit()
            conn.close()
            registrar_log(autor, "Publicación de Comunicado", f"Comunicado: '{titulo}' [{nivel}]")
            flash("Comunicado publicado con éxito.")
    except Exception as e:
        print(f"Error creando comunicado: {e}")
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/archivar/<int:com_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def archivar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT estado, titulo FROM comunicados WHERE id = %s" if db_type == 'postgres' else "SELECT estado, titulo FROM comunicados WHERE id = ?", (com_id,))
        row = cursor.fetchone()
        if row:
            nuevo_estado = 'archivado' if (row[0] or 'activo') == 'activo' else 'activo'
            cursor.execute("UPDATE comunicados SET estado = %s, fijado = FALSE WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = ?, fijado = 0 WHERE id = ?", (nuevo_estado, com_id))
            if db_type == 'sqlite': conn.commit()
            registrar_log(session['username'], "Cambio Estado Comunicado", f"Comunicado '{row[1]}' movido a {nuevo_estado}")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_comunicados'))

@app.route('/comunicados/eliminar/<int:com_id>', methods=['POST', 'GET'])
@csrf.exempt
@login_required
@admin_required
def eliminar_comunicado(com_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE comunicados SET estado = 'eliminado' WHERE id = %s" if db_type == 'postgres' else "UPDATE comunicados SET estado = 'eliminado' WHERE id = ?", (com_id,))
        if db_type == 'sqlite': conn.commit()
        registrar_log(session['username'], "Eliminación de Comunicado", f"Comunicado ID {com_id} movido a papelera")
    except Exception: pass
    conn.close()
    return redirect(url_for('ver_comunicados'))

@app.route('/admin/db', methods=['GET', 'POST'])
@login_required
@admin_required
def visor_db():
    tabla_seleccionada = request.args.get('tabla', 'usuarios')
    tablas_permitidas = ['usuarios', 'galerias', 'archivos', 'auditoria_logs', 'credenciales', 'comunicados']
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
