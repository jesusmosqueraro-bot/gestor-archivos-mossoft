import os
import uuid
import random
import smtplib
import sqlite3
import urllib.request
import urllib.parse
import json
import unicodedata
import psycopg2
import cloudinary
import cloudinary.uploader
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash

app = Flask(__name__)
app.secret_key = 'clave_secreta_gestor_archivos_ultra_segura'

SERVER_INSTANCE_ID = str(uuid.uuid4())
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

# 🇨🇴 ZONA HORARIA COLOMBIA
ZONA_HORARIA_COLOMBIA = ZoneInfo("America/Bogota")

def obtener_fecha_actual():
    return datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%d/%m/%Y %I:%M %p")

# 🧹 FUNCIÓN PARA NORMALIZAR TEXTO (QUITA TILDES Y CONVIERTE A MINÚSCULAS)
def normalizar(texto):
    if not texto: return ""
    texto = unicodedata.normalize('NFD', str(texto))
    texto = ''.join(c for c in texto if unicodedata.category(c) != 'Mn')
    return texto.lower().strip()

# ☁️ CLOUDINARY
cloudinary.config(
    cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME'),
    api_key=os.environ.get('CLOUDINARY_API_KEY'),
    api_secret=os.environ.get('CLOUDINARY_API_SECRET')
)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx', 'mp4', 'mov', 'webm', 'avi'}
app.config['MAX_CONTENT_LENGTH'] = 55 * 1024 * 1024

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "jesus.mosqueraro@gmail.com"
SMTP_PASSWORD = "gyod xyny fzvw bsxu"
RECAPTCHA_SECRET_KEY = "6Lel3V4tAAAAAAWsc9oCEgoWBN95V2zQZ1E3dx2X"

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
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1) if DATABASE_URL.startswith("postgres://") else DATABASE_URL
        conn = psycopg2.connect(url)
        return conn, 'postgres'
    else:
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
        DB_NAME = os.path.join(BASE_DIR, "gestor.db")
        conn = sqlite3.connect(DB_NAME)
        return conn, 'sqlite'

def init_db():
    conn, db_type = get_db()
    cursor = conn.cursor()
    if db_type == 'postgres':
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password VARCHAR(200) NOT NULL, email VARCHAR(200) NOT NULL, rol VARCHAR(50) NOT NULL DEFAULT 'estandar'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
            id VARCHAR(50) PRIMARY KEY, titulo VARCHAR(200) NOT NULL, descripcion TEXT, fecha VARCHAR(100), categoria VARCHAR(100) DEFAULT 'General', tipo VARCHAR(100) DEFAULT 'Instructivo'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
            id SERIAL PRIMARY KEY, galeria_id VARCHAR(50) REFERENCES galerias(id) ON DELETE CASCADE, filename TEXT NOT NULL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY, usuario VARCHAR(100) NOT NULL, accion VARCHAR(100) NOT NULL, detalles TEXT, fecha VARCHAR(100) NOT NULL
        )''')
        try:
            cursor.execute("ALTER TABLE galerias ADD COLUMN IF NOT EXISTS categoria VARCHAR(100) DEFAULT 'General';")
            cursor.execute("ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tipo VARCHAR(100) DEFAULT 'Instructivo';")
        except Exception:
            pass
    else:
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, email TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'estandar'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
            id TEXT PRIMARY KEY, titulo TEXT NOT NULL, descripcion TEXT, fecha TEXT, categoria TEXT DEFAULT 'General', tipo TEXT DEFAULT 'Instructivo'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, galeria_id TEXT, filename TEXT NOT NULL, FOREIGN KEY(galeria_id) REFERENCES galerias(id) ON DELETE CASCADE
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, accion TEXT NOT NULL, detalles TEXT, fecha TEXT NOT NULL
        )''')
        try:
            cursor.execute("ALTER TABLE galerias ADD COLUMN categoria TEXT DEFAULT 'General';")
        except Exception: pass
        try:
            cursor.execute("ALTER TABLE galerias ADD COLUMN tipo TEXT DEFAULT 'Instructivo';")
        except Exception: pass
    
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    if cursor.fetchone()[0] == 0:
        query_admin = "INSERT INTO usuarios (username, password, email, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)"
        cursor.execute(query_admin, ('admin', '1234', 'admin@ejemplo.com', 'admin'))

    conn.commit()
    conn.close()

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

def verificar_recaptcha(response_token):
    if not response_token: return False
    url = "https://www.google.com/recaptcha/api/siteverify"
    data = urllib.parse.urlencode({'secret': RECAPTCHA_SECRET_KEY, 'response': response_token}).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as response:
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

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('usuario') or request.form.get('username')
        password = request.form.get('contrasena') or request.form.get('password')
        recaptcha_response = request.form.get('g-recaptcha-response')

        if not verificar_recaptcha(recaptcha_response):
            return render_template('login.html', error="Por favor, marca la casilla 'No soy un robot'.")

        if username == 'admin' and password == '1234':
            session.permanent = True
            session['logged_in'] = True
            session['username'] = 'admin'
            session['rol'] = 'admin'
            session['instance_id'] = SERVER_INSTANCE_ID
            registrar_log('admin', "Inicio de Sesión", "Inicio de sesión exitoso como admin")
            return redirect(url_for('bienvenida'))

        conn, db_type = get_db()
        cursor = conn.cursor()
        query = "SELECT username, password, rol FROM usuarios WHERE username = %s" if db_type == 'postgres' else "SELECT username, password, rol FROM usuarios WHERE username = ?"
        cursor.execute(query, (username,))
        user = cursor.fetchone()
        conn.close()

        if user and user[1] == password:
            session.permanent = True
            session['logged_in'] = True
            session['username'] = user[0]
            session['rol'] = user[2]
            session['instance_id'] = SERVER_INSTANCE_ID
            registrar_log(user[0], "Inicio de Sesión", "Inicio de sesión exitoso")
            return redirect(url_for('bienvenida'))

        return render_template('login.html', error="Usuario o contraseña incorrectos.")

    mensaje_expirado = "⚠️ Tu sesión ha expirado. Por favor ingresa nuevamente." if request.args.get('expirado') == '1' else None
    return render_template('login.html', mensaje_expirado=mensaje_expirado)

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
    return render_template('bienvenida.html', username=session.get('username'), rol=session.get('rol'))

@app.route('/gestor')
@login_required
def index():
    busqueda_raw = request.args.get('q', '').strip()
    cat_filtro = request.args.get('cat', '').strip()
    tipo_filtro = request.args.get('tipo', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, descripcion, fecha, categoria, tipo FROM galerias")
    rows = cursor.fetchall()
    
    galerias = []
    fecha_defecto = obtener_fecha_actual()

    # Solo descartar palabras irrelevantes muy cortas de 1 o 2 letras (ej: 'de', 'la', 'a', 'e')
    STOP_WORDS = {'de', 'del', 'la', 'las', 'el', 'los', 'un', 'una', 'unos', 'unas', 'y', 'e', 'o', 'u', 'a', 'en', 'con', 'por', 'para'}

    palabras_clave = []
    if busqueda_raw:
        # Extrae y normaliza las palabras (elimina tildes y convierte a minúsculas)
        palabras_limpias = [normalizar(p) for p in busqueda_raw.split() if normalizar(p)]
        # Filtra únicamente conectores cortitos
        palabras_clave = [p for p in palabras_limpias if p not in STOP_WORDS]
        if not palabras_clave:
            palabras_clave = palabras_limpias

    for r in rows:
        galeria_id, titulo, descripcion, fecha = r[0], r[1], r[2], r[3]
        categoria = r[4] if len(r) > 4 and r[4] else 'General'
        tipo = r[5] if len(r) > 5 and r[5] else 'Instructivo'

        query_arch = "SELECT filename FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "SELECT filename FROM archivos WHERE galeria_id = ?"
        cursor.execute(query_arch, (galeria_id,))
        archivos = [f[0] for f in cursor.fetchall()]

        item = {
            'id': galeria_id,
            'titulo': titulo,
            'descripcion': descripcion,
            'fecha': fecha or fecha_defecto,
            'categoria': categoria,
            'tipo': tipo,
            'archivos': archivos
        }

        # Texto consolidado y normalizado (sin tildes) donde buscará el motor
        texto_busqueda = normalizar(f"{titulo} {descripcion} {categoria} {tipo} {' '.join(archivos)}")

        # Búsqueda Inteligente: verifica si CUALQUIERA de las palabras clave está en el texto
        if palabras_clave:
            coincide_busqueda = any(palabra in texto_busqueda for palabra in palabras_clave)
        else:
            coincide_busqueda = True

        coincide_cat = not cat_filtro or categoria == cat_filtro
        coincide_tipo = not tipo_filtro or tipo == tipo_filtro

        if coincide_busqueda and coincide_cat and coincide_tipo:
            galerias.append(item)

    conn.close()
    return render_template('index.html', galerias=galerias, busqueda=busqueda_raw, cat_filtro=cat_filtro, tipo_filtro=tipo_filtro, rol=session.get('rol'))

@app.route('/subir', methods=['POST'])
@login_required
@admin_required
def subir_archivo():
    archivos = request.files.getlist('archivo')
    titulo = request.form.get('titulo', 'Sin título')
    descripcion = request.form.get('descripcion', '')
    categoria = request.form.get('categoria', 'General')
    tipo = request.form.get('tipo', 'Instructivo')

    galeria_id = str(uuid.uuid4())[:8]
    fecha_actual = obtener_fecha_actual()
    
    archivos_guardados = []
    for file in archivos:
        if file and archivo_permitido(file.filename):
            ext = file.filename.rsplit('.', 1)[1].lower()
            resource_type = "video" if ext in ['mp4', 'mov', 'webm', 'avi'] else "auto"
            upload_result = cloudinary.uploader.upload(file, resource_type=resource_type)
            archivos_guardados.append(upload_result['secure_url'])

    if archivos_guardados:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha, categoria, tipo) VALUES (%s, %s, %s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha, categoria, tipo) VALUES (?, ?, ?, ?, ?, ?)"
        cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual, categoria, tipo))
        
        q_archivo = "INSERT INTO archivos (galeria_id, filename) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)"
        for fname in archivos_guardados:
            cursor.execute(q_archivo, (galeria_id, fname))
        
        conn.commit()
        conn.close()
        registrar_log(session['username'], "Creación de Instructivo", f"Instructivo '{titulo}' [{categoria} / {tipo}]")

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def editar_galeria(galeria_id):
    nuevo_titulo = request.form.get('titulo')
    nueva_desc = request.form.get('descripcion')
    nueva_cat = request.form.get('categoria', 'General')
    nuevo_tipo = request.form.get('tipo', 'Instructivo')
    nuevos_archivos = request.files.getlist('nuevos_archivos')
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        q_upd = "UPDATE galerias SET titulo = %s, descripcion = %s, categoria = %s, tipo = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, descripcion = ?, categoria = ?, tipo = ? WHERE id = ?"
        cursor.execute(q_upd, (nuevo_titulo, nueva_desc, nueva_cat, nuevo_tipo, galeria_id))
        
        for file in nuevos_archivos:
            if file and archivo_permitido(file.filename):
                ext = file.filename.rsplit('.', 1)[1].lower()
                resource_type = "video" if ext in ['mp4', 'mov', 'webm', 'avi'] else "auto"
                upload_result = cloudinary.uploader.upload(file, resource_type=resource_type)
                
                q_ins_arch = "INSERT INTO archivos (galeria_id, filename) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)"
                cursor.execute(q_ins_arch, (galeria_id, upload_result['secure_url']))

        conn.commit()
        registrar_log(session['username'], "Edición de Galería", f"Galería ID {galeria_id} actualizada")
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('index'))

@app.route('/eliminar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del1 = "DELETE FROM galerias WHERE id = %s" if db_type == 'postgres' else "DELETE FROM galerias WHERE id = ?"
        q_del2 = "DELETE FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ?"
        cursor.execute(q_del1, (galeria_id,))
        cursor.execute(q_del2, (galeria_id,))
        conn.commit()
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('index'))

@app.route('/eliminar_imagen/<galeria_id>/<path:filename>', methods=['POST'])
@login_required
@admin_required
def eliminar_imagen(galeria_id, filename):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM archivos WHERE galeria_id = %s AND filename = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ? AND filename = ?"
        cursor.execute(q_del, (galeria_id, filename))
        conn.commit()
    except Exception as e:
        conn.rollback()

    conn.close()
    return redirect(url_for('index'))

@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def gestion_usuarios():
    conn, db_type = get_db()
    cursor = conn.cursor()
    if request.method == 'POST':
        nuevo_user = request.form.get('username')
        nuevo_pass = request.form.get('password')
        nuevo_email = request.form.get('email')
        nuevo_rol = request.form.get('rol', 'estandar')
        try:
            q_ins = "INSERT INTO usuarios (username, password, email, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)"
            cursor.execute(q_ins, (nuevo_user, nuevo_pass, nuevo_email, nuevo_rol))
            conn.commit()
            return redirect(url_for('gestion_usuarios'))
        except Exception as e:
            conn.rollback()

    cursor.execute("SELECT id, username, email, rol FROM usuarios ORDER BY id ASC")
    lista_usuarios = cursor.fetchall()
    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda="")

@app.route('/logs')
@login_required
@admin_required
def ver_logs():
    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT usuario, accion, detalles, fecha FROM logs ORDER BY id DESC")
    lista_logs = cursor.fetchall()
    conn.close()
    return render_template('logs.html', logs=lista_logs)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
