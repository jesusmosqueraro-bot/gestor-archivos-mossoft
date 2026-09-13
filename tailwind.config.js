/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  safelist: [
    // 🎨 Clases dinámicas: se arman en las plantillas concatenando un color que viene de
    // Python en tiempo de ejecución (p. ej. "bg-" + "{{ ticket.sla.color }}" + "-400"), así
    // que Tailwind nunca las ve completas al escanear el HTML fuente y las descartaría por
    // "no usadas" si no se listan aquí explícitamente. Colores reales usados hoy:
    //   - SLA de tickets (_estado_sla_ticket en app.py): slate, emerald, rose, cyan
    //     → templates/tickets.html, ticket_detalle.html
    //   - Historial de sesiones (ETIQUETAS_ACCION_HISTORIAL_SESIONES en app.py): emerald,
    //     rose, slate → templates/historial_sesiones.html
    //   - Selector de tema (Diseño de Modales): sky, amber, orange
    //     → templates/diseno_modales.html
    // Si se agrega un color nuevo a cualquiera de esas fuentes, hay que sumarlo aquí (y
    // volver a correr `npm run build:css`) o esa clase quedará sin estilo en producción.
    'bg-cyan-400',
    'bg-cyan-500/10',
    'bg-emerald-400',
    'bg-emerald-500/10',
    'bg-rose-400',
    'bg-rose-500/10',
    'bg-slate-400',
    'bg-slate-500/10',
    'border-cyan-500/20',
    'border-emerald-500/20',
    'border-rose-500/20',
    'border-slate-500/20',
    'text-amber-400',
    'text-cyan-400',
    'text-emerald-400',
    'text-orange-400',
    'text-rose-400',
    'text-sky-400',
    'text-slate-400',
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
