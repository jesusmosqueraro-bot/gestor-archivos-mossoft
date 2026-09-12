#!/usr/bin/env python3
"""Agrega el include de partials/colores_modal_personalizados.html a todas las plantillas que
enlazan marca-institucional.css (pedido por Tomás, 12/09/2026: "un modal de diseño para poder
modificar a gusto los colores de los modales").

El include debe ir SIEMPRE justo después del <link> a marca-institucional.css: como
colores_modal_personalizados.html es un <style> inline que redefine las mismas variables CSS que
esa hoja ya declaró en :root (--marca-*/--modal-*), necesita cargar DESPUÉS para ganar por orden
de cascada (misma especificidad) — ver el comentario al principio de ese partial y de
marca-institucional.css.

Uso: python3 scripts/aplicar_colores_modal_templates.py
"""
import os
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

CSS_LINK = '    <link rel="stylesheet" href="/static/css/marca-institucional.css">'
INCLUDE_NUEVO = "    {% include 'partials/colores_modal_personalizados.html' %}"


def main():
    tocados = 0
    for ruta in sorted(glob.glob(os.path.join(TEMPLATES_DIR, '*.html'))):
        with open(ruta, 'r', encoding='utf-8') as f:
            contenido = f.read()

        if CSS_LINK not in contenido:
            continue
        if 'colores_modal_personalizados.html' in contenido:
            continue  # ya migrada (script idempotente, por si se corre más de una vez)

        nuevo_contenido = contenido.replace(CSS_LINK, CSS_LINK + '\n' + INCLUDE_NUEVO)
        if nuevo_contenido != contenido:
            with open(ruta, 'w', encoding='utf-8') as f:
                f.write(nuevo_contenido)
            tocados += 1
            print(f"✏️  {os.path.relpath(ruta, BASE_DIR)}")

    print(f"\nTotal: {tocados} plantillas con el include de colores de modal agregado.")


if __name__ == '__main__':
    main()
