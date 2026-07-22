import os
import uuid
import random
import smtplib
import sqlite3
import urllib.request
import urllib.parse
import json
import psycopg2
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_secreta_gestor_archivos_ultra_segura'

# 🔒 IDENTIFICADOR ÚNICO DEL SERVIDOR ACTIVO
# Se regenera cada vez que Render inicia o despierta el servidor
SERVER_INSTANCE_ID = str(uuid.uuid4())

# ⏱️ CONFIGURACIÓN DE INACTIVIDAD (25 MINUTOS)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=25)

@app.before_request
def validar_instancia_y_sesion():
    session.permanent = True  # Renueva la duración de la sesión en cada petición
    
    # 🛑 PROTECCIÓN: Si el servidor se reinició / despertó de inactividad, se destruye la sesión
    if session.get('logged_in'):
        if session.get('instance_id') != SERVER_INSTANCE_ID:
            session.clear()
            return redirect(url_for('login', expirado='1'))

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx'}

# --- CONFIGURACIÓN DE CORREO Y RECAPTCHA ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "jesus.mosqueraro@gmail.com"
SMTP_PASSWORD = "gyod xyny fzvw bsxu"

RECAPTCHA_SECRET_KEY = "6Lel3V4tAAAAAAWsc9oCEgoWBN95V2zQZ1E3dx2X"

# 🌐 CONEXIÓN ADAPTATIVA A BASE DE DATOS (POSTGRESQL EN RENDER / SQLITE EN LOCAL)
DATABASE_URL = os.environ.get('DATABASE_URL')

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
            id SERIAL PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password VARCHAR(200) NOT NULL,
            email VARCHAR(200) NOT NULL,
            rol VARCHAR(50) NOT NULL DEFAULT 'estandar'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
            id VARCHAR(50) PRIMARY KEY,
            titulo VARCHAR(200) NOT NULL,
            descripcion TEXT,
            fecha VARCHAR(100)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
            id SERIAL PRIMARY KEY,
            galeria_id VARCHAR(50) REFERENCES galerias(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id SERIAL PRIMARY KEY,
            usuario VARCHAR(100) NOT NULL,
            accion VARCHAR(100) NOT NULL,
            detalles TEXT,
            fecha VARCHAR(100) NOT NULL
        )''')
    else:
        cursor.execute('''CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            email TEXT NOT NULL,
            rol TEXT NOT NULL DEFAULT 'estandar'
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS galerias (
            id TEXT PRIMARY KEY,
            titulo TEXT NOT NULL,
            descripcion TEXT,
            fecha TEXT
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS archivos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            galeria_id TEXT,
            filename TEXT NOT NULL,
            FOREIGN KEY(galeria_id) REFERENCES galerias(id) ON DELETE CASCADE
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario TEXT NOT NULL,
            accion TEXT NOT NULL,
            detalles TEXT,
            fecha TEXT NOT NULL
        )''')
    
    cursor.execute("SELECT COUNT(*) FROM usuarios")
    total_usuarios = cursor.fetchone()[0]
    if total_usuarios == 0:
        query_admin = "INSERT INTO usuarios (username, password, email, rol) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)"
        cursor.execute(query_admin, ('admin', '1234', 'admin@ejemplo.com', 'admin'))

    conn.commit()
    conn.close()

init_db()

def registrar_log(usuario, accion, detalles=""):
    try:
        conn, db_type = get_db()
        cursor = conn.cursor()
        fecha_actual = datetime.now().strftime("%d/%m/%Y %I:%M %p")
        query = "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)"
        cursor.execute(query, (usuario, accion, detalles, fecha_actual))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error registrando log: {e}")

def enviar_correo_codigo(destinatario, codigo):
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_USER
        msg['To'] = destinatario
        msg['Subject'] = "Código de Verificación - Arkiv"
        cuerpo = f"Tu código de verificación es: {codigo}"
        msg.attach(MIMEText(cuerpo, 'plain'))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, destinatario, msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"Error enviando correo: {e}")
        return False

def verificar_recaptcha(response_token):
    if not response_token:
        return False
    url = "https://www.google.com/recaptcha/api/siteverify"
    data = urllib.parse.urlencode({
        'secret': RECAPTCHA_SECRET_KEY,
        'response': response_token
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('success', False)
    except Exception as e:
        print(f"Error reCAPTCHA: {e}")
        return False

def archivo_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('rol') != 'admin':
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('usuario') or request.form.get('username')
        password = request.form.get('contrasena') or request.form.get('password')
        recaptcha_response = request.form.get('g-recaptcha-response')

        # 1. Validar reCAPTCHA
        if not verificar_recaptcha(recaptcha_response):
            return render_template('login.html', error="Por favor, marca la casilla 'No soy un robot'.")

        # 2. Respaldo prioritario para usuario administrador
        if username == 'admin' and password == '1234':
            session.permanent = True
            session['logged_in'] = True
            session['username'] = 'admin'
            session['rol'] = 'admin'
            session['instance_id'] = SERVER_INSTANCE_ID  # 🔑 Vincula la sesión a la instancia actual del servidor
            registrar_log('admin', "Inicio de Sesión", "Inicio de sesión exitoso como admin")
            return redirect(url_for('bienvenida'))

        # 3. Verificación en base de datos para el resto de usuarios
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
            session['instance_id'] = SERVER_INSTANCE_ID  # 🔑 Vincula la sesión a la instancia actual del servidor
            registrar_log(user[0], "Inicio de Sesión", "Inicio de sesión exitoso")
            return redirect(url_for('bienvenida'))

        return render_template('login.html', error="Usuario o contraseña incorrectos.")

    mensaje_expirado = None
    if request.args.get('expirado') == '1':
        mensaje_expirado = "⚠️ Tu sesión ha expirado por inactividad o reinicio del servidor. Por favor, ingresa tus credenciales nuevamente."

    return render_template('login.html', mensaje_expirado=mensaje_expirado)

@app.route('/logout')
def logout():
    if session.get('username'):
        registrar_log(session['username'], "Cierre de Sesión", "Cierre de sesión de usuario")
    session.clear()
    return redirect(url_for('login'))

@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        email = request.form.get('email')
        conn, db_type = get_db()
        cursor = conn.cursor()
        query = "SELECT username FROM usuarios WHERE email = %s" if db_type == 'postgres' else "SELECT username FROM usuarios WHERE email = ?"
        cursor.execute(query, (email,))
        user = cursor.fetchone()
        conn.close()

        if user:
            codigo = str(random.randint(100000, 999999))
            session['reset_code'] = codigo
            session['reset_user'] = user[0]
            enviado = enviar_correo_codigo(email, codigo)
            msg = f"Código enviado a {email}." if enviado else f"Código generado: {codigo}"
            return render_template('recuperar.html', paso=2, mensaje=msg)
        else:
            return render_template('recuperar.html', paso=1, error="El correo no está registrado.")

    return render_template('recuperar.html', paso=1)

@app.route('/validar_codigo', methods=['POST'])
def validar_codigo():
    codigo_ingresado = request.form.get('codigo')
    nueva_password = request.form.get('nueva_password')

    if session.get('reset_code') and codigo_ingresado == session['reset_code']:
        username = session['reset_user']
        conn, db_type = get_db()
        cursor = conn.cursor()
        query = "UPDATE usuarios SET password = %s WHERE username = %s" if db_type == 'postgres' else "UPDATE usuarios SET password = ? WHERE username = ?"
        cursor.execute(query, (nueva_password, username))
        conn.commit()
        conn.close()
        registrar_log(username, "Restablecimiento de Contraseña", "Contraseña cambiada por código")
        session.pop('reset_code', None)
        session.pop('reset_user', None)
        return render_template('login.html', mensaje="Contraseña actualizada. Inicia sesión con tus nuevas credenciales.")
    else:
        return render_template('recuperar.html', paso=2, error="El código de verificación es incorrecto.")

@app.route('/')
def home():
    if session.get('logged_in'):
        return redirect(url_for('bienvenida'))
    return redirect(url_for('login'))

@app.route('/bienvenida')
@login_required
def bienvenida():
    return render_template('bienvenida.html', username=session.get('username'), rol=session.get('rol'))

@app.route('/gestor')
@login_required
def index():
    busqueda = request.args.get('q', '').strip().lower()
    conn, db_type = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, descripcion, fecha FROM galerias")
    rows = cursor.fetchall()
    
    galerias = []
    fecha_defecto = datetime.now().strftime("%d/%m/%Y %I:%M %p")

    for r in rows:
        galeria_id, titulo, descripcion, fecha = r[0], r[1], r[2], r[3]
        if not fecha:
            fecha = fecha_defecto

        query_arch = "SELECT filename FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "SELECT filename FROM archivos WHERE galeria_id = ?"
        cursor.execute(query_arch, (galeria_id,))
        archivos = [f[0] for f in cursor.fetchall()]

        item = {'id': galeria_id, 'titulo': titulo, 'descripcion': descripcion, 'fecha': fecha, 'archivos': archivos}

        if busqueda:
            if busqueda in titulo.lower() or busqueda in descripcion.lower() or any(busqueda in a.lower() for a in archivos):
                galerias.append(item)
        else:
            galerias.append(item)

    conn.close()
    return render_template('index.html', galerias=galerias, busqueda=busqueda, rol=session.get('rol'))

@app.route('/subir', methods=['POST'])
@login_required
@admin_required
def subir_archivo():
    archivos = request.files.getlist('archivo')
    titulo = request.form.get('titulo', 'Sin título')
    descripcion = request.form.get('descripcion', '')

    galeria_id = str(uuid.uuid4())[:8]
    fecha_actual = datetime.now().strftime("%d/%m/%Y %I:%M %p")
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    
    archivos_guardados = []
    for file in archivos:
        if file and archivo_permitido(file.filename):
            nombre_seguro = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
            file.save(filepath)
            archivos_guardados.append(nombre_seguro)

    if archivos_guardados:
        conn, db_type = get_db()
        cursor = conn.cursor()
        q_galeria = "INSERT INTO galerias (id, titulo, descripcion, fecha) VALUES (%s, %s, %s, %s)" if db_type == 'postgres' else "INSERT INTO galerias (id, titulo, descripcion, fecha) VALUES (?, ?, ?, ?)"
        cursor.execute(q_galeria, (galeria_id, titulo, descripcion, fecha_actual))
        
        q_archivo = "INSERT INTO archivos (galeria_id, filename) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)"
        for fname in archivos_guardados:
            cursor.execute(q_archivo, (galeria_id, fname))
        
        conn.commit()
        conn.close()
        registrar_log(session['username'], "Creación de Galería", f"Nueva galería creada: '{titulo}' con {len(archivos_guardados)} archivo(s)")

    return redirect(url_for('index'))

@app.route('/editar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def editar_galeria(galeria_id):
    nuevo_titulo = request.form.get('titulo')
    nueva_desc = request.form.get('descripcion')
    nuevos_archivos = request.files.getlist('nuevos_archivos')
    
    conn, db_type = get_db()
    cursor = conn.cursor()
    
    try:
        q_sel = "SELECT titulo, descripcion FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo, descripcion FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        anterior = cursor.fetchone()
        
        if anterior:
            titulo_ant, desc_ant = anterior[0], anterior[1]
            q_upd = "UPDATE galerias SET titulo = %s, descripcion = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE galerias SET titulo = ?, descripcion = ? WHERE id = ?"
            cursor.execute(q_upd, (nuevo_titulo, nueva_desc, galeria_id))
            
            archivos_guardados = []
            os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
            for file in nuevos_archivos:
                if file and archivo_permitido(file.filename):
                    nombre_seguro = secure_filename(file.filename)
                    filepath = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                    file.save(filepath)
                    
                    q_ins_arch = "INSERT INTO archivos (galeria_id, filename) VALUES (%s, %s)" if db_type == 'postgres' else "INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)"
                    cursor.execute(q_ins_arch, (galeria_id, nombre_seguro))
                    archivos_guardados.append(nombre_seguro)

            conn.commit()
            
            cambios = []
            if titulo_ant != nuevo_titulo:
                cambios.append(f"Título: '{titulo_ant}' ➔ '{nuevo_titulo}'")
            if desc_ant != nueva_desc:
                cambios.append(f"Descripción: '{desc_ant}' ➔ '{nueva_desc}'")
            if archivos_guardados:
                cambios.append(f"Se agregaron {len(archivos_guardados)} archivo(s) nuevo(s)")
                
            detalle_log = " | ".join(cambios) if cambios else "Sin cambios detectados"
            registrar_log(session['username'], "Edición de Galería", f"Galería ID {galeria_id}: {detalle_log}")

    except Exception as e:
        conn.rollback()
        print(f"Error al editar galería: {e}")

    conn.close()
    return redirect(url_for('index'))

@app.route('/eliminar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_galeria(galeria_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT titulo FROM galerias WHERE id = %s" if db_type == 'postgres' else "SELECT titulo FROM galerias WHERE id = ?"
        cursor.execute(q_sel, (galeria_id,))
        galeria = cursor.fetchone()
        nombre_galeria = galeria[0] if galeria else galeria_id

        q_del1 = "DELETE FROM galerias WHERE id = %s" if db_type == 'postgres' else "DELETE FROM galerias WHERE id = ?"
        q_del2 = "DELETE FROM archivos WHERE galeria_id = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ?"
        cursor.execute(q_del1, (galeria_id,))
        cursor.execute(q_del2, (galeria_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Galería", f"Se eliminó la galería completa: '{nombre_galeria}'")
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar galería: {e}")

    conn.close()
    return redirect(url_for('index'))

@app.route('/eliminar_imagen/<galeria_id>/<filename>', methods=['POST'])
@login_required
@admin_required
def eliminar_imagen(galeria_id, filename):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_del = "DELETE FROM archivos WHERE galeria_id = %s AND filename = %s" if db_type == 'postgres' else "DELETE FROM archivos WHERE galeria_id = ? AND filename = ?"
        cursor.execute(q_del, (galeria_id, filename))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Imagen", f"Se eliminó el archivo: '{filename}' (Galería ID: {galeria_id})")
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar imagen: {e}")

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
            registrar_log(session['username'], "Creación de Usuario", f"Nuevo usuario: '{nuevo_user}' (Rol: {nuevo_rol}, Email: {nuevo_email})")
            return redirect(url_for('gestion_usuarios'))
        except Exception as e:
            conn.rollback()
            print(f"Error al crear usuario: {e}")

    busqueda = request.args.get('q', '').strip().lower()
    try:
        if busqueda:
            q_search = "SELECT id, username, email, rol FROM usuarios WHERE LOWER(username) LIKE %s OR LOWER(email) LIKE %s ORDER BY id ASC" if db_type == 'postgres' else "SELECT id, username, email, rol FROM usuarios WHERE LOWER(username) LIKE ? OR LOWER(email) LIKE ? ORDER BY id ASC"
            cursor.execute(q_search, (f"%{busqueda}%", f"%{busqueda}%"))
        else:
            cursor.execute("SELECT id, username, email, rol FROM usuarios ORDER BY id ASC")

        lista_usuarios = cursor.fetchall()
    except Exception as e:
        conn.rollback()
        lista_usuarios = []

    conn.close()
    return render_template('usuarios.html', usuarios=lista_usuarios, busqueda=busqueda)

@app.route('/editar_usuario/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def editar_usuario(user_id):
    nuevo_user = request.form.get('username')
    nuevo_email = request.form.get('email')
    nueva_pass = request.form.get('password')
    nuevo_rol = request.form.get('rol')

    conn, db_type = get_db()
    cursor = conn.cursor()

    try:
        q_sel = "SELECT username, email, rol FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT username, email, rol FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (user_id,))
        anterior = cursor.fetchone()

        if anterior:
            user_ant, email_ant, rol_ant = anterior[0], anterior[1], anterior[2]
            
            if nueva_pass and nueva_pass.strip():
                q_upd = "UPDATE usuarios SET username = %s, email = %s, password = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET username = ?, email = ?, password = ?, rol = ? WHERE id = ?"
                cursor.execute(q_upd, (nuevo_user, nuevo_email, nueva_pass, nuevo_rol, user_id))
            else:
                q_upd = "UPDATE usuarios SET username = %s, email = %s, rol = %s WHERE id = %s" if db_type == 'postgres' else "UPDATE usuarios SET username = ?, email = ?, password = ?, rol = ? WHERE id = ?"
                cursor.execute(q_upd, (nuevo_user, nuevo_email, nuevo_rol, user_id))

            conn.commit()

            cambios = []
            if user_ant != nuevo_user:
                cambios.append(f"Usuario: '{user_ant}' ➔ '{nuevo_user}'")
            if email_ant != nuevo_email:
                cambios.append(f"Email: '{email_ant}' ➔ '{nuevo_email}'")
            if rol_ant != nuevo_rol:
                cambios.append(f"Rol: '{rol_ant}' ➔ '{nuevo_rol}'")
            if nueva_pass and nueva_pass.strip():
                cambios.append("Contraseña actualizada")

            detalle_log = " | ".join(cambios) if cambios else "Sin cambios de datos"
            registrar_log(session['username'], "Modificación de Usuario", f"Usuario ID {user_id}: {detalle_log}")

    except Exception as e:
        conn.rollback()
        print(f"Error al editar usuario: {e}")

    conn.close()
    return redirect(url_for('gestion_usuarios'))

@app.route('/eliminar_usuario/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(user_id):
    conn, db_type = get_db()
    cursor = conn.cursor()
    try:
        q_sel = "SELECT username FROM usuarios WHERE id = %s" if db_type == 'postgres' else "SELECT username FROM usuarios WHERE id = ?"
        cursor.execute(q_sel, (user_id,))
        target_user = cursor.fetchone()

        if target_user and target_user[0] != 'admin':
            q_del = "DELETE FROM usuarios WHERE id = %s" if db_type == 'postgres' else "DELETE FROM usuarios WHERE id = ?"
            cursor.execute(q_del, (user_id,))
            conn.commit()
            registrar_log(session['username'], "Eliminación de Usuario", f"Se eliminó permanentemente al usuario: '{target_user[0]}'")
    except Exception as e:
        conn.rollback()
        print(f"Error al eliminar usuario: {e}")

    conn.close()
    return redirect(url_for('gestion_usuarios'))

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

@app.route('/uploads/<filename>')
@login_required
def ver_archivo(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
