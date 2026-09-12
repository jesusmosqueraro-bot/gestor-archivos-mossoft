"""Migración: quita el residuo muerto de 'Plus Jakarta Sans' en las 10 plantillas que todavía
lo cargaban (Google Fonts <link> + <style> body{font-family...}) de una iteración de diseño
anterior a la adopción de Montserrat como tipografía institucional (pedido por Tomás,
12/09/2026: "cambia el diseño de la letra por MontSerrat para el texto en todo el aplicativo").

Confirmado inofensivo antes de tocar nada: en las 10 plantillas, el <link> de
marca-institucional.css (que fija Montserrat vía `body { font-family: var(--marca-fuente); }`)
carga DESPUÉS del bloque de Plus Jakarta Sans, así que ya ganaba por orden de cascada (misma
especificidad de selector, gana el que carga último) — Plus Jakarta Sans nunca se estaba
renderizando. El `background-color: #0b0f19;` del mismo bloque también es 100% redundante: las
10 plantillas ya traen ese mismo color en la clase `bg-[#0b0f19]` de su <body>.

Qué quita, por archivo:
  1. El par de <link rel="preconnect"> que precede al <link> de Plus Jakarta Sans.
  2. El <link> de Plus Jakarta Sans (Google Fonts).
  3. La línea `body { font-family: 'Plus Jakarta Sans', ... }` dentro del <style> — si ese
     <style> no tiene más reglas, se quita el <style> completo; si tiene otras reglas propias
     de la plantilla (ej. scrollbars, .tab-btn.active), esas se conservan intactas.

Idempotente: si un archivo ya no tiene el patrón, se deja tal cual.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / 'templates'

ARCHIVOS = [
    'bienvenida.html',
    'cambiar_password.html',
    'chat.html',
    'chat_bot.html',
    'inventario_certificacion.html',
    'papelera.html',
    'perfil_2fa.html',
    'perfil_datos.html',
    'recuperar.html',
    'usuarios.html',
]

RE_JAKARTA_LINK = re.compile(r'^\s*<link href="https://fonts\.googleapis\.com/css2\?family=Plus\+Jakarta\+Sans[^"]*" rel="stylesheet">\s*\n', re.MULTILINE)
RE_PRECONNECT_PAR = re.compile(
    r'^\s*<link rel="preconnect" href="https://fonts\.googleapis\.com">\s*\n'
    r'\s*<link rel="preconnect" href="https://fonts\.gstatic\.com"[^>]*>\s*\n',
    re.MULTILINE,
)
# Línea de regla body{font-family: 'Plus Jakarta Sans', ...} ya sea sola en un <style>...</style>
# de una línea, o como una regla más dentro de un <style> multilínea.
RE_STYLE_UNA_LINEA = re.compile(r'^\s*<style>\s*body\s*\{\s*font-family:\s*\'Plus Jakarta Sans\',\s*sans-serif;\s*background-color:\s*#0b0f19;\s*\}\s*</style>\s*\n', re.MULTILINE)
RE_STYLE_REGLA_SUELTA = re.compile(r'^\s*body\s*\{\s*font-family:\s*\'Plus Jakarta Sans\',\s*sans-serif;\s*background-color:\s*#0b0f19;\s*\}\s*\n', re.MULTILINE)


def procesar_archivo(ruta: Path) -> list:
    texto = ruta.read_text(encoding='utf-8')
    original = texto
    hechos = []

    # 1) Quitar SOLO el primer par de preconnect que antecede al link de Jakarta.
    m = RE_JAKARTA_LINK.search(texto)
    if m:
        # Buscar el par de preconnect inmediatamente antes de este link.
        antes = texto[:m.start()]
        m_pre = None
        for m_pre in RE_PRECONNECT_PAR.finditer(antes):
            pass  # nos quedamos con el último match antes del link (el más cercano)
        if m_pre and antes[m_pre.end():].strip() == '':
            texto = texto[:m_pre.start()] + texto[m_pre.end():]
            hechos.append('preconnect x2 (Jakarta)')
            # Recalcular posición del link de Jakarta tras el corte.
            m = RE_JAKARTA_LINK.search(texto)

    # 2) Quitar el link de Jakarta.
    texto, n = RE_JAKARTA_LINK.subn('', texto)
    if n:
        hechos.append(f'link Jakarta x{n}')

    # 3) Quitar la regla/estilo de Jakarta.
    texto, n = RE_STYLE_UNA_LINEA.subn('', texto)
    if n:
        hechos.append('style de una linea')
    else:
        texto, n = RE_STYLE_REGLA_SUELTA.subn('', texto)
        if n:
            hechos.append('regla suelta dentro de <style> multilinea')

    if texto != original:
        ruta.write_text(texto, encoding='utf-8')
    return hechos


def main():
    for nombre in ARCHIVOS:
        ruta = PLANTILLAS / nombre
        hechos = procesar_archivo(ruta)
        print(f"  {nombre}: {', '.join(hechos) if hechos else 'SIN CAMBIOS (revisar manualmente)'}")


if __name__ == '__main__':
    main()
