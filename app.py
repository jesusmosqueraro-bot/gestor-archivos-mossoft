import os
import uuid
import random
import smtplib
import sqlite3
import urllib.request
import urllib.parse
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, session, flash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'clave_secreta_gestor_archivos_ultra_segura'

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'txt', 'docx'}

# --- CONFIGURACIÓN DE CORREO Y RECAPTCHA ---
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = "jesus.mosqueraro@gmail.com"
SMTP_PASSWORD = "gyod xyny fzvw bsxu"

RECAPTCHA_SECRET_KEY = "6Lel3V4tAAAAAAWsc9oCEgoWBN95V2zQZ1E3dx2X"

DB_NAME = "gestor.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
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
    
    # Asegurar la existencia e inicialización del usuario admin con clave '1234'
    cursor.execute("SELECT * FROM usuarios WHERE username = 'admin'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)",
                       ('admin', '1234', 'admin@ejemplo.com', 'admin'))
    else:
        cursor.execute("UPDATE usuarios SET password = '1234' WHERE username = 'admin'")

    conn.commit()
    conn.close()

init_db()

def registrar_log(usuario, accion, detalles=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    fecha_actual = datetime.now().strftime("%d/%m/%Y %I:%M %p")
    cursor.execute("INSERT INTO logs (usuario, accion, detalles, fecha) VALUES (?, ?, ?, ?)",
                   (usuario, accion, detalles, fecha_actual))
    conn.commit()
    conn.close()

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
        username = request.form.get('usuario')
        # CORRECCIÓN: Se recibe 'contrasena' tal como está definido en el input de login.html
        password = request.form.get('contrasena') or request.form.get('password')
        recaptcha_response = request.form.get('g-recaptcha-response')

        if not verificar_recaptcha(recaptcha_response):
            return render_template('login.html', error="Por favor, marca la casilla 'No soy un robot'.")

        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT username, password, rol FROM usuarios WHERE username = ?", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and user[1] == password:
            session['logged_in'] = True
            session['username'] = user[0]
            session['rol'] = user[2]
            registrar_log(user[0], "Inicio de Sesión", "Inicio de sesión exitoso con reCAPTCHA")
            return redirect(url_for('bienvenida'))

        return render_template('login.html', error="Usuario o contraseña incorrectos.")

    return render_template('login.html')

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
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("SELECT username FROM usuarios WHERE email = ?", (email,))
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
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET password = ? WHERE username = ?", (nueva_password, username))
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
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT id, titulo, descripcion, fecha FROM galerias")
    rows = cursor.fetchall()
    
    galerias = []
    fecha_defecto = datetime.now().strftime("%d/%m/%Y %I:%M %p")

    for r in rows:
        galeria_id, titulo, descripcion, fecha = r[0], r[1], r[2], r[3]
        if not fecha:
            fecha = fecha_defecto

        cursor.execute("SELECT filename FROM archivos WHERE galeria_id = ?", (galeria_id,))
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
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO galerias (id, titulo, descripcion, fecha) VALUES (?, ?, ?, ?)",
                       (galeria_id, titulo, descripcion, fecha_actual))
        for fname in archivos_guardados:
            cursor.execute("INSERT INTO archivos (galeria_id, filename) VALUES (?, ?)", (galeria_id, fname))
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
    
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Obtener valores anteriores
    cursor.execute("SELECT titulo, descripcion FROM galerias WHERE id = ?", (galeria_id,))
    anterior = cursor.fetchone()
    
    if anterior:
        titulo_ant, desc_ant = anterior[0], anterior[1]
        cursor.execute("UPDATE galerias SET titulo = ?, descripcion = ? WHERE id = ?", (nuevo_titulo, nueva_desc, galeria_id))
        conn.commit()
        
        # Registrar cambios detallados
        cambios = []
        if titulo_ant != nuevo_titulo:
            cambios.append(f"Título: '{titulo_ant}' ➔ '{nuevo_titulo}'")
        if desc_ant != nueva_desc:
            cambios.append(f"Descripción: '{desc_ant}' ➔ '{nueva_desc}'")
            
        detalle_log = " | ".join(cambios) if cambios else "Sin cambios detectados"
        registrar_log(session['username'], "Edición de Galería", f"Galería ID {galeria_id}: {detalle_log}")

    conn.close()
    return redirect(url_for('index'))

@app.route('/eliminar_galeria/<galeria_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_galeria(galeria_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT titulo FROM galerias WHERE id = ?", (galeria_id,))
    galeria = cursor.fetchone()
    nombre_galeria = galeria[0] if galeria else galeria_id

    cursor.execute("DELETE FROM galerias WHERE id = ?", (galeria_id,))
    cursor.execute("DELETE FROM archivos WHERE galeria_id = ?", (galeria_id,))
    conn.commit()
    conn.close()
    registrar_log(session['username'], "Eliminación de Galería", f"Se eliminó la galería completa: '{nombre_galeria}'")
    return redirect(url_for('index'))

@app.route('/eliminar_imagen/<galeria_id>/<filename>', methods=['POST'])
@login_required
@admin_required
def eliminar_imagen(galeria_id, filename):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM archivos WHERE galeria_id = ? AND filename = ?", (galeria_id, filename))
    conn.commit()
    conn.close()
    registrar_log(session['username'], "Eliminación de Imagen", f"Se eliminó el archivo: '{filename}' (Galería ID: {galeria_id})")
    return redirect(url_for('index'))

@app.route('/usuarios', methods=['GET', 'POST'])
@login_required
@admin_required
def gestion_usuarios():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    if request.method == 'POST':
        nuevo_user = request.form.get('username')
        nuevo_pass = request.form.get('password')
        nuevo_email = request.form.get('email')
        nuevo_rol = request.form.get('rol', 'estandar')

        try:
            cursor.execute("INSERT INTO usuarios (username, password, email, rol) VALUES (?, ?, ?, ?)",
                           (nuevo_user, nuevo_pass, nuevo_email, nuevo_rol))
            conn.commit()
            registrar_log(session['username'], "Creación de Usuario", f"Nuevo usuario: '{nuevo_user}' (Rol: {nuevo_rol}, Email: {nuevo_email})")
        except sqlite3.IntegrityError:
            pass

    busqueda = request.args.get('q', '').strip().lower()
    if busqueda:
        cursor.execute("SELECT id, username, email, rol FROM usuarios WHERE LOWER(username) LIKE ? OR LOWER(email) LIKE ?",
                       (f"%{busqueda}%", f"%{busqueda}%"))
    else:
        cursor.execute("SELECT id, username, email, rol FROM usuarios")

    lista_usuarios = cursor.fetchall()
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

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    # Obtener valores anteriores
    cursor.execute("SELECT username, email, rol FROM usuarios WHERE id = ?", (user_id,))
    anterior = cursor.fetchone()

    if anterior:
        user_ant, email_ant, rol_ant = anterior[0], anterior[1], anterior[2]
        
        if nueva_pass and nueva_pass.strip():
            cursor.execute("UPDATE usuarios SET username = ?, email = ?, password = ?, rol = ? WHERE id = ?",
                           (nuevo_user, nuevo_email, nueva_pass, nuevo_rol, user_id))
        else:
            cursor.execute("UPDATE usuarios SET username = ?, email = ?, rol = ? WHERE id = ?",
                           (nuevo_user, nuevo_email, nuevo_rol, user_id))

        conn.commit()

        # Auditoría detallada
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

    conn.close()
    return redirect(url_for('gestion_usuarios'))

@app.route('/eliminar_usuario/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def eliminar_usuario(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM usuarios WHERE id = ?", (user_id,))
    target_user = cursor.fetchone()

    if target_user and target_user[0] != 'admin':
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (user_id,))
        conn.commit()
        registrar_log(session['username'], "Eliminación de Usuario", f"Se eliminó permanentemente al usuario: '{target_user[0]}'")

    conn.close()
    return redirect(url_for('gestion_usuarios'))

@app.route('/logs')
@login_required
@admin_required
def ver_logs():
    conn = sqlite3.connect(DB_NAME)
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
