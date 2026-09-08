"""Autocompletar de persona por cédula o nombre (pedido por Tomás, 08/09/2026): "al ingresar el
número de documento, empiece a buscar y mostrar los similares, algo como autocompletar (...) y
que sea así para todos los campos en los que se pueda filtrar por cédula (...) y lo mismo si se
desea buscar por nombre". Se reutiliza /usuarios/buscar (coincidencia parcial) a través del
helper compartido activarAutocompletarPersona (/static/js/autocompletar_persona.js). Cubre: el
endpoint ahora incluye 'firma' en cada resultado, y las plantillas que necesitan este
autocompletar (Inventario, Altas de Credenciales — alta y edición) cargan el script compartido y
tienen su contenedor de sugerencias; Gestión de Usuarios filtra en vivo por nombre además de
cédula."""


def test_buscar_usuarios_incluye_firma_en_cada_resultado(admin_session, app, crear_usuario):
    usuario = crear_usuario(nombre='Firma Prueba Persona', cedula='1029384756')
    conn, db_type = app.get_db()
    cur = conn.cursor()
    cur.execute("UPDATE usuarios SET firma = ? WHERE usuario = ?",
                ('https://res.cloudinary.com/demo/image/upload/firma_persona.png', usuario))
    conn.commit()
    conn.close()

    r = admin_session.get('/usuarios/buscar?q=Firma Prueba')

    data = r.get_json()
    resultado = next(u for u in data['resultados'] if u['usuario'] == usuario)
    assert resultado['firma'] == 'https://res.cloudinary.com/demo/image/upload/firma_persona.png'


def test_buscar_usuarios_sin_firma_registrada_trae_none(admin_session, crear_usuario):
    crear_usuario(nombre='Sin Firma Persona', cedula='1029384999')

    r = admin_session.get('/usuarios/buscar?q=Sin Firma Persona')

    data = r.get_json()
    resultado = next(u for u in data['resultados'] if u['nombre'] == 'Sin Firma Persona')
    assert resultado['firma'] is None


def test_modal_inventario_incluye_autocompletar_de_cedula(admin_session):
    texto = admin_session.get('/tickets/inventario').get_data(as_text=True)
    assert '/static/js/autocompletar_persona.js' in texto
    assert 'sugerencias-cedula-activo' in texto
    assert 'activarAutocompletarPersona' in texto
    assert 'input-activo-cedula-buscar' in texto
    # El botón "Buscar" (búsqueda exacta) se conserva junto al autocompletar, no se reemplaza.
    assert 'buscarAsignadoPorCedula()' in texto


def test_credenciales_colaboradores_incluye_autocompletar_en_alta_y_edicion(admin_session):
    texto = admin_session.get('/credenciales/colaboradores').get_data(as_text=True)
    assert '/static/js/autocompletar_persona.js' in texto
    assert 'sugerencias-colaborador' in texto
    assert 'sugerencias-colaborador-editar' in texto
    assert texto.count('activarAutocompletarPersona(') == 2


def test_usuarios_filtra_en_vivo_por_nombre_ademas_de_cedula(admin_session, crear_usuario):
    crear_usuario(nombre='Buscable Por Nombre', cedula='1055667788')

    texto = admin_session.get('/usuarios').get_data(as_text=True)

    assert 'data-buscar=' in texto
    assert 'buscable por nombre' in texto.lower()  # el atributo data-buscar incluye el nombre en minúsculas
    assert 'function filtrarUsuarios()' in texto
    assert 'Buscar por cédula o nombre' in texto
