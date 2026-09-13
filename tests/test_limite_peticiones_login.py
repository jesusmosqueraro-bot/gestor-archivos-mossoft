"""Corrige un hallazgo de los logs de producción en Render (pedido de Tomás, 13/09/2026):
"Flask-Limiter no se dispara: el manejador CSRF (CSRFProtect) está interceptando los POST
inválidos antes de que Flask-Limiter registre el intento" — una ráfaga de 10 POST a /login sin
token CSRF (o con uno vencido) nunca hacía disparar el 429 de "5 per minute".

Causa real (ver el comentario grande en app.py, junto a la construcción de Limiter):
"@limiter.limit(...)" usado como DECORADOR de una vista (como estaba antes en /login) solo
cuenta/aplica ese límite cuando la vista se EJECUTA de verdad — el chequeo vive dentro de la
función que envuelve a la vista, no en el before_request genérico de Flask-Limiter. Si
CSRFProtect corta la petición ANTES (por token CSRF faltante/vencido), la vista de /login nunca
se ejecuta, y ese límite específico nunca se cuenta para esos intentos — esto pasaba sin
importar el orden en que se construyeran Limiter y CSRFProtect.

La corrección (ver app.py) deja de decorar la vista y en su lugar aplica el límite en un
"before_request" explícito ("_limitar_intentos_login") que usa "limiter.limit(...)" como
gestor de contexto ("with ...:"), registrado ANTES que CSRFProtect — así el conteo/bloqueo
ocurre de inmediato para todo POST a /login, se valide o no después el CSRF.

Estas pruebas activan WTF_CSRF_ENABLED a propósito (las demás pruebas de la suite lo dejan
apagado, ver tests/conftest.py) para poder reproducir exactamente el escenario del hallazgo:
una ráfaga de POST a /login sin csrf_token."""


def test_limite_de_peticiones_de_login_se_activa_aunque_falte_el_token_csrf(client, app):
    """Antes de la corrección, esta ráfaga de 10 POST sin csrf_token nunca devolvía 429: CSRF
    cortaba cada petición antes de que Flask-Limiter llegara a contarla."""
    original = app.app.config['WTF_CSRF_ENABLED']
    app.app.config['WTF_CSRF_ENABLED'] = True
    try:
        codigos = []
        for _ in range(10):
            r = client.post('/login', data={'usuario': 'quien-sea', 'password': 'lo-que-sea'})
            codigos.append(r.status_code)
        assert 429 in codigos, (
            f"El límite de 5 peticiones/minuto de /login nunca se disparó en la ráfaga "
            f"(códigos obtenidos: {codigos}) — Flask-Limiter no se está evaluando antes que CSRF."
        )
        # Las primeras peticiones (dentro del tope) deben seguir siendo rechazadas por CSRF, no
        # coladas como si el token faltante no importara.
        assert codigos[0] != 429
    finally:
        app.app.config['WTF_CSRF_ENABLED'] = original


def test_orden_de_registro_limitador_de_login_antes_que_csrf(app):
    """Chequeo estructural, más directo que el anterior: dentro de los before_request globales
    de Flask (app.before_request_funcs[None]), "_limitar_intentos_login" (el before_request
    explícito que aplica el límite de /login como gestor de contexto, ver app.py) debe aparecer
    ANTES que el before_request de Flask-WTF (CSRFProtect) — así es como Flask decide qué
    validación corre primero en cada petición, y es justo lo que hace que el límite se cuente
    aunque el CSRF de esa petición sea inválido o esté ausente."""
    ganchos = app.app.before_request_funcs.get(None, [])
    nombres = [getattr(f, '__qualname__', getattr(f, '__name__', '')) for f in ganchos]
    modulos = [getattr(f, '__module__', '') for f in ganchos]
    indices_login = [i for i, n in enumerate(nombres) if '_limitar_intentos_login' in n]
    indices_csrf = [i for i, m in enumerate(modulos) if m.startswith('flask_wtf')]
    assert indices_login, "No se encontró el before_request '_limitar_intentos_login' — ¿se movió o se renombró?"
    assert indices_csrf, "No se encontró el before_request de Flask-WTF — ¿sigue instalado?"
    assert min(indices_login) < min(indices_csrf), (
        "'_limitar_intentos_login' debe registrarse (y por lo tanto ejecutarse) antes que "
        "CSRFProtect, para que un POST a /login sin token CSRF válido también cuente contra "
        "el límite de 5 por minuto."
    )
