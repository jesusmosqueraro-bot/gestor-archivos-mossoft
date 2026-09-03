"""Fixtures compartidas para las pruebas de Arkiv.

Todas las pruebas corren contra una base de datos sqlite local y descartable (nunca contra
Postgres/producción). Cada prueba arranca con las tablas recién creadas y vacías —salvo la
cuenta 'admin' que init_db() siembra siempre— para que el orden de ejecución no importe y no
queden datos de una prueba filtrando a otra.
"""
import os
import sys

# 🧵 Evita que cada importación de app.py dispare el hilo de respaldo automático diario
# (threading.Thread(..., daemon=True).start() a nivel de módulo) — no aporta nada a las
# pruebas y, si algo llegara a reimportar el módulo más de una vez, dejaría hilos sueltos.
os.environ.setdefault('DESHABILITAR_RESPALDO_AUTOMATICO', '1')

# 🔑 app.py lee ENCRYPTION_KEY al importarse (para cifrar/descifrar credenciales guardadas,
# ver encriptar_texto/desencriptar_texto) y sin ella cualquier prueba que dé de alta una
# credencial falla con "ENCRYPTION_KEY no configurada". Esta clave es SOLO para pruebas —nunca
# se usa en producción, donde la real vive en las variables de entorno de Render— y debe fijarse
# ANTES de "import app", porque _fernet se construye una sola vez a nivel de módulo.
os.environ.setdefault('ENCRYPTION_KEY', 'zH1Yv3E4v5b6c7d8e9f0AbCdEfGhIjKlMnOpQrStUvw=')

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, 'gestor.db')

# Se importa UNA sola vez por sesión de pytest (no por prueba): reimportar el módulo completo
# en cada prueba sería lento y volvería a registrar el hilo de arriba si alguna vez se habilita.
if os.path.exists(DB_PATH):
    os.remove(DB_PATH)
import app as arkiv  # noqa: E402

arkiv.app.config['TESTING'] = True
arkiv.app.config['WTF_CSRF_ENABLED'] = False

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _sin_correos_reales(monkeypatch):
    """Se aplica a TODAS las pruebas automáticamente: ninguna prueba debe disparar un envío de
    correo real (bienvenida, recuperación de clave, notificaciones de tickets, respaldos). Dos
    motivos, no solo uno:
      1) Nunca deben salir correos reales a bandejas reales solo por correr las pruebas.
      2) El envío real ocurre en un hilo aparte (threading.Thread) que puede seguir vivo
         después de que termina la prueba que lo disparó. Sin este mock, se vio ese hilo
         intentando escribir en 'correos_log' justo cuando la prueba SIGUIENTE ya había
         borrado y estaba recreando el archivo sqlite — una condición de carrera real que
         hacía fallar pruebas al azar (sqlite3.OperationalError: disk I/O error)."""
    monkeypatch.setattr(arkiv, 'enviar_correo_recuperacion', lambda *a, **k: None)
    monkeypatch.setattr(arkiv, 'enviar_correo_bienvenida', lambda *a, **k: None)
    monkeypatch.setattr(arkiv, 'enviar_correo_ticket', lambda *a, **k: None)
    monkeypatch.setattr(arkiv, '_enviar_respaldo_por_correo', lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _base_de_datos_limpia():
    """Se aplica a TODAS las pruebas automáticamente (autouse): borra el archivo sqlite y
    vuelve a crear el esquema desde cero antes de cada prueba, y limpia los contadores del
    limitador de peticiones (Flask-Limiter) para que el límite de una prueba no contamine la
    siguiente cuando varias pruebas golpean la misma ruta limitada (p. ej. /login)."""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    arkiv.init_db()
    try:
        arkiv.limiter.reset()
    except Exception:
        pass  # El limiter "dummy" (sin Flask-Limiter instalado) no tiene reset().
    yield
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)


@pytest.fixture
def app():
    """El módulo de la app ya importado (para acceder a helpers, constantes, get_db(), etc.
    directamente desde una prueba sin tener que volver a importar)."""
    return arkiv


@pytest.fixture
def client(app):
    """Cliente de pruebas de Flask, ya con TESTING/CSRF configurados.

    Nota de nombres: el módulo se llama 'app' (app.py) y DENTRO de él también hay una
    variable 'app' que es la instancia de Flask (app = Flask(__name__)) — por eso
    'app.app.test_client()' y no 'app.test_client()'."""
    return app.app.test_client()


def _crear_sesion(client, arkiv_app, usuario, rol):
    with client.session_transaction() as sess:
        sess['logged_in'] = True
        sess['username'] = usuario
        sess['rol'] = rol
        sess['instance_id'] = arkiv_app.SERVER_INSTANCE_ID
        sess['debe_cambiar_password'] = False
        sess['debe_activar_2fa'] = False
    return client


@pytest.fixture
def admin_session(client, app):
    """Sesión autenticada como la cuenta super-admin ('admin', sembrada por init_db()).
    Bypasea login/recaptcha/2FA a propósito: estas pruebas verifican lo que pasa DESPUÉS de
    haber iniciado sesión, no el mecanismo de login en sí (ver tests/test_login.py para eso)."""
    return _crear_sesion(client, app, 'admin', 'admin')


@pytest.fixture
def crear_usuario(app):
    """Inserta un usuario de prueba directo en la BD y devuelve su 'usuario'. Evita pasar por
    el alta desde /usuarios (que ya tiene sus propias pruebas de validación aparte)."""
    contador = {'n': 0}

    def _crear(usuario=None, password_hash='x', correo=None, rol='estandar', nombre='Persona de Prueba', telefono=None, cedula=None):
        contador['n'] += 1
        usuario = usuario or f"usuarioprueba{contador['n']}"
        correo = correo or f"{usuario}@preventivaips.com.co"
        conn, db_type = app.get_db()
        cur = conn.cursor()
        q = ("INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre, telefono, cedula) VALUES (%s, %s, %s, %s, %s, %s, %s)"
             if db_type == 'postgres' else
             "INSERT INTO usuarios (usuario, password_hash, correo, rol, nombre, telefono, cedula) VALUES (?, ?, ?, ?, ?, ?, ?)")
        cur.execute(q, (usuario, password_hash, correo, rol, nombre, telefono, cedula))
        conn.commit()
        conn.close()
        return usuario

    return _crear


@pytest.fixture
def sesion_usuario(client, app, crear_usuario):
    """Crea un usuario 'estandar' de prueba y devuelve el cliente con su sesión ya activa."""
    usuario = crear_usuario(rol='estandar')
    return _crear_sesion(client, app, usuario, 'estandar')
