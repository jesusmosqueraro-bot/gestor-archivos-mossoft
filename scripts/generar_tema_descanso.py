#!/usr/bin/env python3
"""Genera static/css/tema-descanso.css a partir de static/css/tema-claro.css.

Idea: el tema "Descansar la vista" es una variante SEPIA/cálida del tema claro (mismo patrón
de selectores, mismas reglas) — como el modo "Sepia" de un e-reader: reduce el brillo/contraste
y le quita la luz azul al blanco puro del tema claro, sin llegar a ser tan oscuro como el tema
oscuro. En vez de mantener a mano una segunda hoja de 200+ reglas en paralelo (con el riesgo de
que se desincronicen), este script relee tema-claro.css línea por línea y aplica un "filtro de
temperatura cálida" a cada color: lo mezcla con un tono sepia (distinto para texto/fondo/borde)
y baja levemente el brillo. Así cualquier clase nueva que se agregue a tema-claro.css primero,
al volver a correr este script, aparece automáticamente también en tema-descanso.css.

Uso: python3 scripts/generar_tema_descanso.py
"""
import re
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ORIGEN = os.path.join(BASE_DIR, 'static', 'css', 'tema-claro.css')
DESTINO = os.path.join(BASE_DIR, 'static', 'css', 'tema-descanso.css')

# 🎨 Tonos sepia de referencia hacia los que se "mezcla" cada color, según qué propiedad CSS
# está coloreando (texto / fondo / borde). Elegidos para que el resultado final se sienta como
# papel envejecido tenue: fondos color crema/tostado, texto café oscuro, bordes tostado medio.
SEPIA_TEXTO = (0x5C, 0x3D, 0x1F)    # café oscuro cálido, bien saturado
SEPIA_FONDO = (0xEF, 0xE3, 0xC7)    # crema/parchment
SEPIA_BORDE = (0xD8, 0xC4, 0x93)    # tostado medio

PESO_TEXTO = 0.45
PESO_FONDO = 0.55
PESO_BORDE = 0.42
FACTOR_BRILLO_FONDO = 0.97  # un pelín más tenue/opaco que el tema claro puro

HEX_RE = re.compile(r'#([0-9a-fA-F]{6})')


def _mezclar(rgb_original, rgb_sepia, peso):
    return tuple(round(o * (1 - peso) + s * peso) for o, s in zip(rgb_original, rgb_sepia))


def _hex_a_rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_a_hex(rgb):
    return '#' + ''.join(f'{max(0, min(255, round(c))):02x}' for c in rgb)


def _propiedad_de_linea(linea):
    if 'background-color:' in linea or 'background-image:' in linea:
        return 'fondo'
    if 'border-color:' in linea:
        return 'borde'
    if 'color:' in linea:  # después de los dos anteriores: 'color:' solo (texto)
        return 'texto'
    return None


def _transformar_linea(linea):
    # El data-theme se cambia SIEMPRE que aparezca, incluso en líneas de selector "sueltas"
    # (selectores multilínea que terminan en coma, sin declaración de color propia) — si no,
    # un grupo como ".pagina-acento-cyan .bg-slate-800\/60,\n.../\/40,\n.../\/30,\n.../\/80 { ... }"
    # quedaría con las primeras líneas en data-theme="claro" y solo la última en "descanso".
    nueva = linea.replace('data-theme="claro"', 'data-theme="descanso"')

    prop = _propiedad_de_linea(nueva)
    if prop is None:
        return nueva

    sepia, peso = {
        'texto': (SEPIA_TEXTO, PESO_TEXTO),
        'fondo': (SEPIA_FONDO, PESO_FONDO),
        'borde': (SEPIA_BORDE, PESO_BORDE),
    }[prop]

    def reemplazar(m):
        rgb = _hex_a_rgb(m.group(1))
        mezclado = _mezclar(rgb, sepia, peso)
        if prop == 'fondo':
            mezclado = tuple(c * FACTOR_BRILLO_FONDO for c in mezclado)
        return _rgb_a_hex(mezclado)

    nueva = HEX_RE.sub(reemplazar, nueva)

    # rgba(r,g,b,a) — mismo tratamiento sobre el canal RGB, alpha intacto.
    def reemplazar_rgba(m):
        r, g, b, a = m.group(1), m.group(2), m.group(3), m.group(4)
        rgb = (int(r), int(g), int(b))
        mezclado = _mezclar(rgb, sepia, peso)
        if prop == 'fondo':
            mezclado = tuple(c * FACTOR_BRILLO_FONDO for c in mezclado)
        return f"rgba({round(mezclado[0])},{round(mezclado[1])},{round(mezclado[2])},{a})"

    nueva = re.sub(r'rgba\((\d+),\s*(\d+),\s*(\d+),\s*([0-9.]+)\)', reemplazar_rgba, nueva)
    return nueva


def _quitar_comentarios(texto):
    """Quita todos los comentarios /* ... */ (incluso multilínea) del CSS de origen, para no
    tener que rastrear un estado 'dentro/fuera de comentario' línea por línea — así una línea
    de continuación de comentario (que no empieza con '/*' ni '*') no se cuela como si fuera
    una regla real."""
    return re.sub(r'/\*.*?\*/', '', texto, flags=re.DOTALL)


def main():
    with open(ORIGEN, 'r', encoding='utf-8') as f:
        contenido = f.read()

    contenido_sin_comentarios = _quitar_comentarios(contenido)

    salida = [
        '/* =========================================================================\n',
        '   TEMA "DESCANSAR LA VISTA" DE ARKIV — generado por scripts/generar_tema_descanso.py\n',
        '   a partir de tema-claro.css (variante sepia/cálida, más tenue que el tema claro).\n',
        '   No editar a mano: agrega la clase nueva a tema-claro.css y vuelve a correr el\n',
        '   script — así las dos hojas de tema claro no se desincronizan entre sí.\n',
        '   ========================================================================= */\n',
        '\n',
    ]
    for linea in contenido_sin_comentarios.splitlines(keepends=True):
        if linea.strip() == '':
            continue
        salida.append(_transformar_linea(linea))

    with open(DESTINO, 'w', encoding='utf-8') as f:
        f.writelines(salida)
    print(f"✅ Generado {DESTINO} ({len(salida)} líneas)")


if __name__ == '__main__':
    main()
