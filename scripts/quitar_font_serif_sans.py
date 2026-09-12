"""Migración: quita las clases Tailwind 'font-serif' y 'font-sans' que compiten en
especificidad con la regla global `body { font-family: var(--marca-fuente); }` de
marca-institucional.css (pedido por Tomás, 12/09/2026: "cambia el diseño de la letra por
MontSerrat para el texto en todo el aplicativo").

Una clase Tailwind como '.font-serif' o '.font-sans' (selector de clase, especificidad 0,1,0)
siempre le gana a la regla `body { ... }` (selector de elemento, especificidad 0,0,1) sin
importar el orden de las hojas de estilo. Por eso Montserrat no se veía en los <h1> de las
cabeceras de página (27 plantillas con 'font-serif') ni en el texto de varias páginas completas
(las mismas 27 plantillas tienen 'font-sans' en su <body>, más un <td> suelto en admin_db.html).

Quita solo el token de clase 'font-serif'/'font-sans' (con el espacio que lo separa), dejando
intacto el resto de la lista de clases. Idempotente: si ya no queda el token, no toca la línea.
"""
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PLANTILLAS = RAIZ / 'templates'

# (patrón a buscar, reemplazo) — el espacio antes de la clase se quita junto con ella.
REEMPLAZOS = [
    (re.compile(r' font-serif(?=[ "])'), ''),
    (re.compile(r' font-sans(?=[ "])'), ''),
]


def procesar_archivo(ruta: Path) -> int:
    texto = ruta.read_text(encoding='utf-8')
    original = texto
    cambios = 0
    for patron, reemplazo in REEMPLAZOS:
        texto, n = patron.subn(reemplazo, texto)
        cambios += n
    if texto != original:
        ruta.write_text(texto, encoding='utf-8')
    return cambios


def main():
    total = 0
    archivos_tocados = 0
    for ruta in sorted(PLANTILLAS.glob('*.html')):
        n = procesar_archivo(ruta)
        if n:
            archivos_tocados += 1
            total += n
            print(f"  {ruta.relative_to(RAIZ)}: {n} clase(s) quitada(s)")
    print(f"\nTotal: {total} clases quitadas en {archivos_tocados} archivo(s).")


if __name__ == '__main__':
    main()
