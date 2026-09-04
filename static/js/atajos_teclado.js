// ⌨️ Atajo global de teclado: la tecla Esc sirve para "salir" de donde esté el usuario dentro
// de un módulo, en este orden de prioridad:
//   1) Si hay algún modal de Arkiv abierto (modal de Nuevo/Editar Activo, Adjuntos, Historial,
//      Trazabilidad, Reemplazar, el buscador global, etc. — todos comparten la misma
//      convención: id que empieza con "modal-" y se ocultan con la clase "hidden"), Esc lo
//      cierra, sin importar en qué campo del modal esté escribiendo el usuario.
//   2) Si no hay ningún modal abierto pero el foco está en un campo de texto/búsqueda con
//      contenido (por ejemplo un filtro a medio escribir), la primera vez Esc solo le quita
//      el foco al campo — para no perder de golpe lo que se estaba filtrando ni salir del
//      módulo sin querer por apretar Esc una sola vez.
//   3) En cualquier otro caso, Esc navega a la página anterior del historial del navegador
//      (equivalente a pulsar "Atrás"), que es como se sale de un módulo hacia el que lo
//      contiene. Si esta es la primera página de la pestaña (no hay a dónde volver), no hace
//      nada — así Esc nunca deja a alguien fuera de Arkiv sin querer.
// No se aplica en login/recuperación de clave/cambio de clave obligatorio: ahí Esc no debe
// sacar a nadie del flujo de autenticación a medias.
document.addEventListener('keydown', function (evento) {
    if (evento.key !== 'Escape') return;

    var modalesAbiertos = document.querySelectorAll('[id^="modal-"]:not(.hidden)');
    if (modalesAbiertos.length) {
        modalesAbiertos.forEach(function (modal) { modal.classList.add('hidden'); });
        return;
    }

    var elementoActivo = document.activeElement;
    var esCampoDeTexto = elementoActivo && (elementoActivo.tagName === 'INPUT' || elementoActivo.tagName === 'TEXTAREA');
    if (esCampoDeTexto && elementoActivo.value) {
        elementoActivo.blur();
        return;
    }

    if (window.history.length > 1) {
        window.history.back();
    }
});
