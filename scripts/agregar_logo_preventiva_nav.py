"""Migración mecánica (13/09/2026): agrega {% include 'partials/logo_preventiva_nav.html' %}
justo antes de {% include 'partials/buscador.html' %} en cada plantilla que ya incluye el
buscador global, replicando la indentación exacta de esa línea. Idempotente: si una plantilla ya
tiene el include del logo, se salta sin duplicar.

Pedido por Tomás (13/09/2026): "Incluye el logo de preventiva en uno de esos recuadros, que se
visualice en los modulos que no tienen el logo de preventiva" — ver templates/bienvenida.html
(los dos recuadros vacíos de la barra superior, señalados en la captura).
"""
import os

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVO_LOGO = "{% include 'partials/logo_preventiva_nav.html' %}"
ARCHIVO_BUSCADOR = "{% include 'partials/buscador.html' %}"

PLANTILLAS = [
    "admin_db.html", "comunicados.html", "comunicados_cumplimiento.html", "conocimiento.html",
    "credenciales.html", "credenciales_auditoria.html", "credenciales_colaboradores.html",
    "diseno_modales.html", "historial_sesiones.html", "index.html", "logs.html",
    "logs_correos.html", "mis_tareas.html", "respaldos.html", "tablero_ejecutivo.html",
    "ticket_detalle.html", "tickets.html", "tickets_configuracion.html",
    "tickets_indicadores.html", "tickets_inicio.html", "tickets_inventario.html",
    "tickets_plantillas.html", "vencimientos.html", "bienvenida.html",
]

modificados, saltados = [], []

for nombre in PLANTILLAS:
    ruta = os.path.join(RAIZ, "templates", nombre)
    with open(ruta, "r", encoding="utf-8") as f:
        lineas = f.readlines()

    if any(ARCHIVO_LOGO in l for l in lineas):
        saltados.append(nombre)
        continue

    nuevas = []
    insertado = False
    for linea in lineas:
        if not insertado and ARCHIVO_BUSCADOR in linea:
            indent = linea[:len(linea) - len(linea.lstrip())]
            nuevas.append(f"{indent}{ARCHIVO_LOGO}\n")
            insertado = True
        nuevas.append(linea)

    if not insertado:
        raise SystemExit(f"No se encontró el include del buscador en {nombre}")

    with open(ruta, "w", encoding="utf-8") as f:
        f.writelines(nuevas)
    modificados.append(nombre)

print(f"Modificados ({len(modificados)}): {modificados}")
print(f"Saltados, ya tenían el include ({len(saltados)}): {saltados}")
