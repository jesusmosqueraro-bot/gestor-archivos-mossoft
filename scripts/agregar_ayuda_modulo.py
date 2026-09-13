"""Script de migración (idempotente) — inserta el botón de ayuda contextual
({% include 'partials/ayuda_modulo.html' %}, parametrizado con la clave de módulo correcta)
justo después de {% include 'partials/buscador.html' %} en cada plantilla que ya lo incluye, y
agrega <script src="/static/js/ayuda-modulo.js"> antes de </body> si no está.

Se puede volver a correr sin duplicar nada: si la plantilla ya tiene el include de ayuda_modulo
o el <script> de ayuda-modulo.js, los deja intactos.

Las plantillas SIN buscador.html (admin_boveda_personal, admin_geolocalizacion, chat,
chat_bot, fondo_login, mi_boveda, inventario_certificacion) se editaron a mano, igual que se
hizo para el logo institucional — no las cubre este script.

Pedido por Tomás (13/09/2026): "habilitar un boton de ayuda... manual instructivo de las
funcionalidades de Arkiv"."""
import re

# clave de módulo -> archivo de plantilla (solo las que sí incluyen buscador.html)
PLANTILLAS = {
    'admin_db': 'admin_db',
    'bienvenida': 'bienvenida',
    'comunicados': 'comunicados',
    'comunicados_cumplimiento': 'comunicados_cumplimiento',
    'conocimiento': 'conocimiento',
    'credenciales': 'credenciales',
    'credenciales_auditoria': 'credenciales_auditoria',
    'credenciales_colaboradores': 'credenciales_colaboradores',
    'diseno_modales': 'diseno_modales',
    'historial_sesiones': 'historial_sesiones',
    'archivos': 'index',
    'logs': 'logs',
    'logs_correos': 'logs_correos',
    'mis_tareas': 'mis_tareas',
    'papelera': 'papelera',
    'respaldos': 'respaldos',
    'tablero_ejecutivo': 'tablero_ejecutivo',
    'ticket_detalle': 'ticket_detalle',
    'tickets': 'tickets',
    'tickets_configuracion': 'tickets_configuracion',
    'tickets_indicadores': 'tickets_indicadores',
    'tickets_inicio': 'tickets_inicio',
    'tickets_inventario': 'tickets_inventario',
    'tickets_plantillas': 'tickets_plantillas',
    'usuarios': 'usuarios',
    'vencimientos': 'vencimientos',
    'geolocalizacion': 'admin_geolocalizacion',  # tiene buscador? se valida abajo, ver nota
}

INCLUDE_BUSCADOR = "{% include 'partials/buscador.html' %}"
SCRIPT_TAG = '<script src="/static/js/ayuda-modulo.js"></script>'

modificados = []
omitidos = []

for modulo, archivo in PLANTILLAS.items():
    ruta = f'templates/{archivo}.html'
    try:
        with open(ruta, encoding='utf-8') as f:
            contenido = f.read()
    except FileNotFoundError:
        omitidos.append((archivo, 'no existe'))
        continue

    if INCLUDE_BUSCADOR not in contenido:
        omitidos.append((archivo, 'sin buscador.html, se edita a mano'))
        continue

    cambio = False

    include_ayuda = f"{{% with modulo='{modulo}' %}}{{% include 'partials/ayuda_modulo.html' %}}{{% endwith %}}"
    if include_ayuda not in contenido:
        contenido = contenido.replace(
            INCLUDE_BUSCADOR,
            INCLUDE_BUSCADOR + '\n                ' + include_ayuda,
            1,
        )
        cambio = True

    if SCRIPT_TAG not in contenido:
        contenido = re.sub(r'(\s*)</body>', '\n    ' + SCRIPT_TAG + r'\1</body>', contenido, count=1)
        cambio = True

    if cambio:
        with open(ruta, 'w', encoding='utf-8') as f:
            f.write(contenido)
        modificados.append(archivo)
    else:
        omitidos.append((archivo, 'ya tenía todo'))

print(f"Modificados: {len(modificados)}")
for a in modificados:
    print(f"  - {a}")
print(f"Omitidos: {len(omitidos)}")
for a, motivo in omitidos:
    print(f"  - {a}: {motivo}")
