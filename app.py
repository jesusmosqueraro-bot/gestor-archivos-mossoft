import os
import uuid
import random
import smtplib
import sqlite3
import urllib.request
import urllib.parse
import json
import unicodedata
import io
import csv
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response, jsonify

# psycopg2 seguro para Render
try:
    import psycopg2
except Exception:
    psycopg2 = None

import cloudinary
import cloudinary.uploader

# requests seguro
try:
    import requests
except Exception:
    requests = None

app = Flask(__name__)
app.secret_key = 'clave_secreta_gestor_archivos_ultra_segura'

SERVER_INSTANCE_ID = str(uuid.uuid4())
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

# 🇨🇴 ZONA HORARIA COLOMBIA
ZONA_HORARIA_COLOMBIA = ZoneInfo("America/Bogota")

def obtener_fecha_actual():
    return datetime.now(ZONA_HORARIA_COLOMBIA).strftime("%d/%m/%Y %I:%M %p")

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

# 🔑 CLAVE SECRETA DE RECAPTCHA V2
RECAPTCHA_SECRET_KEY = "6LcU0mAtAAAAANT3I4V9q0k5LaBA0B8rEFfvhspC"

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
                id SERIAL PRIMARY KEY, username VARCHAR(100) UNIQUE NOT NULL, password VARCHAR(200) NOT NULL, email VARCHAR(200) NOT NULL, rol VARCHAR(50) NOT NULL DEFAULT 'estandar'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id VARCHAR(50) PRIMARY KEY, titulo VARCHAR(200) NOT NULL, descripcion TEXT, fecha VARCHAR(100), categoria VARCHAR(100) DEFAULT 'General', tipo VARCHAR(100) DEFAULT 'Instructivo', tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, estado VARCHAR(50) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id SERIAL PRIMARY KEY, galeria_id VARCHAR(50) REFERENCES galerias(id) ON DELETE CASCADE, filename TEXT NOT NULL, estado VARCHAR(50) DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY, usuario VARCHAR(100) NOT NULL, accion VARCHAR(100) NOT NULL, detalles TEXT, fecha VARCHAR(100) NOT NULL
            )''')
            
            for col_query in [
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS categoria VARCHAR(100) DEFAULT 'General';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tipo VARCHAR(100) DEFAULT 'Instructivo';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS tags TEXT DEFAULT '';",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS vistas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS descargas INTEGER DEFAULT 0;",
                "ALTER TABLE galerias ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';",
                "ALTER TABLE archivos ADD COLUMN IF NOT EXISTS estado VARCHAR(50) DEFAULT 'activo';"
            ]:
                try:
                    cursor.execute(col_query)
                    conn.commit()
                except Exception:
                    conn.rollback()

        else:
            cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, email TEXT NOT NULL, rol TEXT NOT NULL DEFAULT 'estandar'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
                id TEXT PRIMARY KEY, titulo TEXT NOT NULL, descripcion TEXT, fecha TEXT, categoria TEXT DEFAULT 'General', tipo TEXT DEFAULT 'Instructivo', tags TEXT DEFAULT '', vistas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, estado TEXT DEFAULT 'activo'
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, galeria_id TEXT, filename TEXT NOT NULL, estado TEXT DEFAULT 'activo', FOREIGN KEY(galeria_id) REFERENCES galerias(id) ON DELETE CASCADE
            )''')
            cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, accion TEXT NOT NULL, detalles TEXT, fecha TEXT NOT NULL
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

        cursor.execute("SELECT COUNT(*) FROM usuarios")
        if cursor.fetchone()[0] == 0:
            query_admin = "INSERT INTO usuarios (username, password, email, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)"
            cursor.execute(query_admin, ('admin', '1234', 'jesus.mosqueraro@gmail.com', 'admin'))

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

# 📊 RUTAS DE MÉTRICAS
@app.route('/incrementar_vista/<galeria_id>', methods=['POST'])
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
    filename_custom = request.args.get('name', 'documento.pdf')

    if not url_target:
        return "URL requerida", 400

    try:
        clean_url = url_target.replace('/fl_attachment/', '/').replace('/upload/fl_attachment/', '/upload/')
        
        if requests:
            res = requests.get(clean_url, timeout=15)
            if res.status_code == 401:
                api_key = os.environ.get('CLOUDINARY_API_KEY')
                api_secret = os.environ.get('CLOUDINARY_API_SECRET')
                if api_key and api_secret:
                    res = requests.get(clean_url, auth=(api_key, api_secret), timeout=15)
            content_data = res.content
        else:
            req = urllib.request.Request(clean_url)
            with urllib.request.urlopen(req) as response:
                content_data = response.read()

        if download_flag == '1':
            usuario_actual = session.get('username', 'Anónimo')
            registrar_log(usuario_actual, "Descarga de Documento", f"Archivo: '{filename_custom}'")

        disposition = 'attachment' if download_flag == '1' else 'inline'
        
        headers = {
            'Content-Type': 'application/pdf',
            'Content-Disposition': f'{disposition}; filename="{filename_custom}"'
        }
        return Response(content_data, headers=headers, status=200)
    except Exception as e:
        return f"Error obteniendo documento: {e}", 500

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

# 📧 FUNCIÓN AUXILIAR EN SEGUNDO PLANO PARA ENVIAR CORREO SIN BLOQUEAR RENDER
def enviar_correo_recuperacion(email_destino, usuario_nombre, codigo):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = email_destino
        msg['Subject'] = f"Código de Verificación - Gestor de Archivos ({codigo})"

        cuerpo = f"""
        Hola {usuario_nombre},

        Tu código de verificación para restablecer tu contraseña es: {codigo}

        Si no solicitaste este cambio, por favor ignora este mensaje.
        """
        msg.attach(MIMEText(cuerpo, 'plain'))

        # Intentar primero por SSL (Puerto 465)
        try:
            server = smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=5)
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()
        except Exception:
            # Fallback a TLS (Puerto 587)
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=5)
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.send_message(msg)
            server.quit()

        print(f"✅ Correo enviado con éxito a {email_destino}")
    except Exception as e:
        print(f"⚠️ Error enviando correo: {e}")

# 🔑 PASO 1: SOLICITAR CÓDIGO POR CORREO
@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar_clave():
    if request.method == 'POST':
        email_ingresado = request.form.get('email', '').strip()
        
        conn, db_type = get_db()
        cursor = conn.cursor()
        query = "SELECT username FROM usuarios WHERE email = %s" if db_type == 'postgres' else "SELECT username FROM usuarios WHERE email = ?"
        cursor.execute(query, (email_ingresado,))
        user = cursor.fetchone()
        conn.close()

        if user:
            usuario_nombre = user[0]
            codigo_verificacion = str(random.randint(100000, 999999))
            
            session['reset_email'] = email_ingresado
            session['reset_user'] = usuario_nombre
            session['reset_code'] = codigo_verificacion

            # Envío asíncrono para respuesta web instantánea en Render
            hilo_correo = threading.Thread(
                target=enviar_correo_recuperacion, 
                args=(email_ingresado, usuario_nombre, codigo_verificacion)
            )
            hilo_correo.start()

            registrar_log(usuario_nombre, "Solicitud de Código", f"Código generado para: {email_ingresado}")
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

    if not codigo_correcto or not email_usuario:
        return render_template('recuperar.html', paso=1, error="La sesión expiró. Por favor solicita un nuevo código.")

    if codigo_ingresado != codigo_correcto:
        return render_template('recuperar.html', paso=2, email=email_usuario, error="El código de verificación es incorrecto.")

    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_upd = "UPDATE usuarios SET password = %s WHERE email = %s" if db_type == 'postgres' else "UPDATE usuarios SET password = ? WHERE email = ?"
        cursor.execute(q_upd, (nueva_pass, email_usuario))
        conn.commit()
        conn.close()

        session.pop('reset_code', None)
        session.pop('reset_email', None)
        session.pop('reset_user', None)

        registrar_log(nombre_usuario, "Cambio Exitoso de Clave", "Se actualizó la clave vía código de verificación.")
        return render_template('recuperar.html', paso=1, exito="¡Contraseña actualizada con éxito! Ya puedes iniciar sesión.")

    except Exception as e:
        conn.rollback()
        conn.close()
        return render_template('recuperar.html', paso=2, email=email_usuario, error="Ocurrió un error al actualizar la contraseña.")

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
    formato_filtro = request.args.get('formato', '').strip()

    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id, titulo, descripcion, fecha, categoria, tipo, tags, vistas, descargas FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
        rows = cursor.fetchall()
    except Exception:
        try:
            conn.rollback()
            cursor.execute("SELECT id, titulo, descripcion, fecha, categoria, tipo, tags FROM galerias WHERE COALESCE(estado, 'activo') != 'eliminado'")
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

        query_arch = "SELECT filename FROM archivos WHERE galeria_id = %s AND COALESCE(estado, 'activo') != 'eliminado'" if db_type == 'postgres' else "SELECT filename FROM archivos WHERE galeria_id = ? AND COALESCE(estado, 'activo') != 'eliminado'"
        cursor.execute(query_arch, (galeria_id,))
        archivos = [f[0] for f in cursor.fetchall()]

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
            ext = file.filename.rsplit('.', 1)[1].lower()
            
            if ext in ['mp4', 'mov', 'webm', 'avi']:
                upload_result = cloudinary.uploader.upload(
                    file, 
                    resource_type="video",
                    use_filename=True,
                    unique_filename=True
                )
            elif ext == 'pdf':
                upload_result = cloudinary.uploader.upload(
                    file, 
                    resource_type="image",
                    format="pdf",
                    use_filename=True,
                    unique_filename=True
                )
            elif ext in ['txt', 'docx']:
                upload_result = cloudinary.uploader.upload(
                    file, 
                    resource_type="raw",
                    use_filename=True,
                    unique_filename=True
                )
            else:
                upload_result = cloudinary.uploader.upload(
                    file, 
                    resource_type="image",
                    use_filename=True,
                    unique_filename=True
                )

            archivos_guardados.append(upload_result['secure_url'])

    if archivos_guardados:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha, categoria, tipo, tags, vistas, descargas, estado) VALUES (%s, %s, %s, %s, %s, %s, %s, 0, 0, 'activo')" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha, categoria, tipo, tags, vistas, descargas, estado) VALUES (?, ?, ?, ?, ?, ?, ?, 0, 0, 'activo')"
        cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual, categoria, tipo, tags))
        
        q_archivo = "INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')"
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
                        unique_filename=True
                    )
                elif ext == 'pdf':
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        resource_type="image",
                        format="pdf",
                        use_filename=True,
                        unique_filename=True
                    )
                elif ext in ['txt', 'docx']:
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        resource_type="raw",
                        use_filename=True,
                        unique_filename=True
                    )
                else:
                    upload_result = cloudinary.uploader.upload(
                        file, 
                        resource_type="image",
                        use_filename=True,
                        unique_filename=True
                    )
                
                q_ins_arch = "INSERT INTO archivos (galeria_id, filename, estado) VALUES (%s, %s, 'activo')" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename, estado) VALUES (?, ?, 'activo')"
                cursor.execute(q_ins_arch, (galeria_id, upload_result['secure_url']))
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

# ♻️ MÓDULO PAPELERA DE RECICLAJE (INSTRUCTIVOS + ARCHIVOS ADJUNTOS)
@app.route('/papelera')
@login_required
@admin_required
def ver_papelera():
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, titulo, descripcion, fecha, categoria, tipo FROM galerias WHERE estado = 'eliminado' ORDER BY fecha DESC")
    eliminados = cursor.fetchall()

    query_arch_elim = """
        SELECT a.id, a.filename, g.id, g.titulo, g.categoria 
        FROM archivos a 
        JOIN galerias g ON a.galeria_id = g.id 
        WHERE a.estado = 'eliminado' AND COALESCE(g.estado, 'activo') != 'eliminado'
    """
    cursor.execute(query_arch_elim)
    archivos_eliminados = cursor.fetchall()

    conn.close()
    return render_template('papelera.html', eliminados=eliminados, archivos_eliminados=archivos_eliminados)

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

        q_upd = "UPDATE archivos SET estado = 'eliminado' WHERE galeria_id = %s AND filename = %s" if db_type == 'postgres' else "UPDATE archivos SET estado = 'eliminado' WHERE galeria_id = ? AND filename = ?"
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
            SELECT a.filename, g.titulo 
            FROM archivos a 
            JOIN galerias g ON a.galeria_id = g.id 
            WHERE a.id = %s
        """ if db_type == 'postgres' else """
            SELECT a.filename, g.titulo 
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

# ✏️ EDITAR USUARIO (CONTRASEÑA, CORREO, ROL)
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
        q_sel = "SELECT username FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT username FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()
        user_target = row[0] if row else f"ID {usuario_id}"

        if nueva_pass:
            q_upd = "UPDATE usuarios SET email = %s, rol = %s, password = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET email = ?, rol = ?, password = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_email, nuevo_rol, nueva_pass, usuario_id))
            detalle_log = f"Se actualizó correo, rol y CONTRASEÑA del usuario '{user_target}'"
        else:
            q_upd = "UPDATE usuarios SET email = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET email = ?, rol = ? WHERE id = ?"
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
        q_sel = "SELECT username FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT username FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (usuario_id,))
        row = cursor.fetchone()
        user_target = row[0] if row else f"ID {usuario_id}"

        q_del = "DELETE FROM usuarios WHERE id = %s" if db_type == 'postgres' else "DELETE FROM usuarios WHERE id = ?"
        cursor.execute(q_del, (usuario_id,))
        conn.commit()

        registrar_log(session['username'], "Eliminación de Usuario", f"Se eliminó el usuario '{user_target}' del sistema")
    except Exception as e:
        conn.rollback()

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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
