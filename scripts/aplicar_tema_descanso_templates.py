#!/usr/bin/env python3
"""Aplica el tercer tema 'Descansar la vista' a todos los templates que ya soportan claro/oscuro:
1) el atributo data-theme del <html> pasa a reconocer 'claro'/'oscuro'/'descanso' (antes solo
   distinguía claro vs. todo lo demás = oscuro);
2) se agrega el <link> a tema-descanso.css junto al de tema-claro.css;
3) el botón flotante de alternar tema pasa de un ciclo de 2 (claro/oscuro) a uno de 3
   (claro → oscuro → descanso → claro), con un ícono propio para 'descanso'.

Uso: python3 scripts/aplicar_tema_descanso_templates.py
"""
import os
import glob

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES_DIR = os.path.join(BASE_DIR, 'templates')

DATA_THEME_VIEJO = '<html lang="es" data-theme="{{ \'claro\' if session.get(\'tema\') == \'claro\' else \'oscuro\' }}">'
DATA_THEME_NUEVO = '<html lang="es" data-theme="{{ session.get(\'tema\') if session.get(\'tema\') in (\'claro\', \'descanso\') else \'oscuro\' }}">'

CSS_LINK_VIEJO = '    <link rel="stylesheet" href="/static/css/tema-claro.css">'
CSS_LINK_NUEVO = (
    '    <link rel="stylesheet" href="/static/css/tema-claro.css">\n'
    '    <link rel="stylesheet" href="/static/css/tema-descanso.css">'
)

BOTON_VIEJO = (
    '        <input type="hidden" name="tema" value="{{ \'oscuro\' if session.get(\'tema\') == \'claro\' else \'claro\' }}">\n'
    '        <button type="submit" title="Cambiar a tema {{ \'oscuro\' if session.get(\'tema\') == \'claro\' else \'claro\' }}" class="w-11 h-11 rounded-full bg-slate-800/90 hover:bg-slate-700 border border-slate-700/60 text-slate-200 shadow-lg shadow-slate-950/40 flex items-center justify-center transition-all active:scale-95">\n'
    '            <i class="fa-solid {{ \'fa-sun\' if session.get(\'tema\') == \'claro\' else \'fa-moon\' }}"></i>\n'
    '        </button>'
)
BOTON_NUEVO = (
    '        {% set tema_actual = session.get(\'tema\') or \'oscuro\' %}\n'
    '        {% set tema_siguiente = \'oscuro\' if tema_actual == \'claro\' else (\'descanso\' if tema_actual == \'oscuro\' else \'claro\') %}\n'
    '        <input type="hidden" name="tema" value="{{ tema_siguiente }}">\n'
    '        <button type="submit" title="Cambiar a tema {{ tema_siguiente }}" class="w-11 h-11 rounded-full bg-slate-800/90 hover:bg-slate-700 border border-slate-700/60 text-slate-200 shadow-lg shadow-slate-950/40 flex items-center justify-center transition-all active:scale-95">\n'
    '            <i class="fa-solid {{ \'fa-sun\' if tema_actual == \'claro\' else (\'fa-mug-hot\' if tema_actual == \'descanso\' else \'fa-moon\') }}"></i>\n'
    '        </button>'
)


def main():
    tocados_theme, tocados_css, tocados_boton = 0, 0, 0
    for ruta in sorted(glob.glob(os.path.join(TEMPLATES_DIR, '*.html'))):
        with open(ruta, 'r', encoding='utf-8') as f:
            contenido = f.read()
        original = contenido

        if DATA_THEME_VIEJO in contenido:
            contenido = contenido.replace(DATA_THEME_VIEJO, DATA_THEME_NUEVO)
            tocados_theme += 1

        if CSS_LINK_VIEJO in contenido and 'tema-descanso.css' not in contenido:
            contenido = contenido.replace(CSS_LINK_VIEJO, CSS_LINK_NUEVO)
            tocados_css += 1

        if BOTON_VIEJO in contenido:
            contenido = contenido.replace(BOTON_VIEJO, BOTON_NUEVO)
            tocados_boton += 1

        if contenido != original:
            with open(ruta, 'w', encoding='utf-8') as f:
                f.write(contenido)
            print(f"✏️  {os.path.relpath(ruta, BASE_DIR)}")

    print(f"\nTotal: {tocados_theme} con data-theme actualizado, {tocados_css} con el link de CSS agregado, {tocados_boton} con el botón de 3 vías.")


if __name__ == '__main__':
    main()
