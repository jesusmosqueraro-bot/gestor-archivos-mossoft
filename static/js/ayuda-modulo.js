// ❓ Ayuda contextual por módulo — un botón "?" en cada página que abre un panel con la
// ayuda de ESE módulo puntual: qué es, para quién, cómo usarlo paso a paso y preguntas
// frecuentes. A diferencia del buscador global (que busca contenido dentro de los módulos) o
// de un manual único y centralizado, este es ayuda específica de la página en la que está el
// usuario — pedido por Tomás (13/09/2026): "habilitar un boton de ayuda... manual instructivo
// de las funcionalidades de Arkiv".
//
// Cada plantilla incluye templates/partials/ayuda_modulo.html pasando su propia clave de
// módulo (ver ese parcial). Como cada plantilla solo es alcanzable por quien ya tiene permiso
// de ver ese módulo (la ruta de Flask ya lo exige), el botón siempre queda ajustado al rol de
// quien lo ve, sin lógica de permisos adicional aquí — simplemente no llegan a ver un botón de
// un módulo al que no tienen acceso, porque nunca llegan a esa página.
//
// El contenido de cada módulo se investigó leyendo su ruta real en app.py (decorador de
// permisos, comportamiento) y su plantilla (botones/campos reales) — no es contenido genérico
// ni inventado.

var AYUDA_MODULOS = {
  "bienvenida": {
      "titulo": "Panel Principal",
      "descripcion": "Es la pantalla de inicio tras iniciar sesión: muestra el comunicado oficial fijado (si hay uno) y tarjetas de acceso a cada módulo de Arkiv. Disponible para cualquier usuario autenticado, pero las tarjetas que ves cambian según tu rol (Estándar, Gestión Humana, Agente o Administrador).",
      "pasos": [
          "Haz clic en la tarjeta del módulo al que quieras entrar (por ejemplo \"Instructivos y Archivos\", \"Muro de Comunicados\" o \"Soporte TI\").",
          "Si tu cuenta es Administrador, usa la tarjeta \"Geolocalización de Accesos\" para abrir la vista rápida (métricas + mapa embebido) sin salir de esta pantalla.",
          "Dentro de esa vista rápida, pulsa \"Ver mapa completo, filtros y gráficas\" para ir a la página completa de Geolocalización.",
          "Usa el botón redondo de la esquina inferior derecha para alternar entre tema oscuro, claro y \"Descansar la vista\".",
          "Pulsa \"Salir\" en la barra superior para cerrar tu sesión."
      ],
      "preguntas": [
          {
              "q": "¿Por qué no veo las mismas tarjetas que un compañero?",
              "a": "Las tarjetas se muestran según tu rol: Estándar ve el menor número de módulos, y tarjetas como Tablero Ejecutivo, Gestión de Usuarios, Geolocalización, Gestor de Base de Datos, Respaldos y Diseño de Modales son exclusivas de Administrador (las tres últimas, además, solo las ve la cuenta super-admin)."
          },
          {
              "q": "¿Qué significa el punto rojo sobre la tarjeta de Chat Interno?",
              "a": "Indica que tienes mensajes directos o del Canal General sin leer. Esta tarjeta solo aparece para cuentas Admin/Agente."
          },
          {
              "q": "¿El tema que elijo se guarda para la próxima vez?",
              "a": "Sí, la preferencia de tema queda asociada a tu cuenta y te sigue a cualquier dispositivo desde el que inicies sesión."
          }
      ]
  },
  "usuarios": {
      "titulo": "Gestión de Usuarios",
      "descripcion": "Módulo de altas, edición y control de cuentas de Arkiv. La vista general y el cambio de rol/estado están disponibles para cuentas con rol Agente o Administrador; el alta manual completa (\"Nuevo Usuario\", con rol elegible libremente) y la edición completa de una cuenta son exclusivas de Administrador. Solo la cuenta super-admin ('admin') puede editar a otro admin/agente, asignar el rol Administrador o auditar la Bóveda Personal de alguien.",
      "pasos": [
          "Usa el campo \"Buscar por cédula o nombre...\" y los filtros de especialidad, rol y estado para localizar una cuenta; \"Limpiar filtros\" los reinicia.",
          "(Solo Administrador) Pulsa \"Nuevo Usuario\" y completa el formulario para dar de alta una cuenta con el rol que corresponda.",
          "Pulsa \"Carga masiva\" para subir un archivo .xlsx con la plantilla descargable y crear varias cuentas de una vez (siempre en rol Estándar).",
          "En la fila del usuario, usa el ícono de lápiz (Administrador) o el selector de rol junto al botón de check (Agente, solo para cuentas Estándar/Gestión Humana) para ajustar el rol.",
          "Administra el catálogo de especialidades desde el botón \"Especialidades\" (o \"+ Administrar\" dentro de los formularios).",
          "Usa el ícono de documento para registrar certificados, cursos o exámenes de un colaborador desde \"Documentos y vencimientos\"."
      ],
      "preguntas": [
          {
              "q": "Tengo rol Agente, ¿por qué no puedo editar el correo o la contraseña de un usuario?",
              "a": "Un agente solo puede cambiar el rol de cuentas Estándar o Gestión Humana; el resto del formulario de edición (correo, teléfono, contraseña, firma) queda exclusivo de un Administrador."
          },
          {
              "q": "¿Quién puede crear una cuenta con rol Administrador?",
              "a": "Solo la cuenta super-admin ('admin') ve esa opción en el formulario; el resto de administradores no puede asignar ese rol."
          },
          {
              "q": "¿Por qué veo un candado en vez de botones en algunas filas?",
              "a": "Es una cuenta protegida: solo el super-admin puede modificar a otro administrador o agente, o es tu propia fila (no puedes cambiar tu propio rol ni bloquearte a ti mismo)."
          }
      ]
  },
  "geolocalizacion": {
      "titulo": "Geolocalización de Accesos",
      "descripcion": "Mapa (Leaflet) y métricas/gráficas de dónde ocurrieron los inicios de sesión, comparados contra el catálogo real de Sedes autorizadas (con su radio en metros) configurado en Soporte TI. Exclusivo de cuentas con rol Administrador.",
      "pasos": [
          "Filtra por \"Usuario\" y por rango de fechas (\"Desde\"/\"Hasta\") y pulsa \"Filtrar\"; usa \"Limpiar\" para quitar los filtros.",
          "Revisa las tarjetas de \"Accesos registrados\", \"Usuarios únicos\", \"Dentro de sede\" y \"Fuera de sede\".",
          "Consulta las gráficas \"Dentro vs. fuera de sede\" y \"Accesos por usuario (top 10)\".",
          "Explora el mapa: los círculos marcan las sedes autorizadas y su radio; los puntos verdes/rojos son accesos dentro o fuera de sede.",
          "Revisa la tabla debajo del mapa como respaldo de los mismos datos en formato tabla."
      ],
      "preguntas": [
          {
              "q": "¿De dónde salen las sedes que aparecen en el mapa?",
              "a": "Del catálogo real de Sedes configurado en Soporte TI (con su latitud, longitud y radio en metros); una sede sin coordenadas cargadas ahí no aparece en el mapa."
          },
          {
              "q": "¿Por qué un acceso aparece \"Sin ubicación\"?",
              "a": "El navegador de esa persona no entregó (o no autorizó) la geolocalización al iniciar sesión, así que ese registro quedó sin latitud/longitud."
          },
          {
              "q": "¿Puedo ver esto sin salir del Panel Principal?",
              "a": "Sí, hay una vista rápida con las mismas métricas y un mapa embebido, accesible desde la tarjeta \"Geolocalización de Accesos\" de la Bienvenida."
          }
      ]
  },
  "papelera": {
      "titulo": "Papelera de Reciclaje",
      "descripcion": "Guarda los instructivos, credenciales y comunicados eliminados para poder restaurarlos o borrarlos en forma definitiva. Disponible para cuentas con rol Agente o Administrador.",
      "pasos": [
          "Cambia entre las pestañas \"Instructivos\", \"Credenciales\" y \"Comunicados\" (cada una muestra su conteo).",
          "Pulsa \"Restaurar\" para devolver el elemento a su módulo original.",
          "Pulsa \"Destruir\" para eliminarlo definitivamente; se pide confirmación y la acción no se puede deshacer."
      ],
      "preguntas": [
          {
              "q": "¿Qué diferencia hay entre \"Restaurar\" y \"Destruir\"?",
              "a": "\"Restaurar\" regresa el elemento a su listado normal (instructivos, credenciales o comunicados). \"Destruir\" lo borra para siempre de la base de datos, sin posibilidad de recuperarlo."
          },
          {
              "q": "Envié un comunicado a la papelera, ¿por qué no lo veo de inmediato?",
              "a": "Si llegaste desde esa acción, la Papelera abre directamente en la pestaña \"Comunicados\"; si entraste por tu cuenta, haz clic manualmente en esa pestaña."
          }
      ]
  },
  "logs": {
      "titulo": "Bitácora de Auditoría",
      "descripcion": "Registro cronológico de las acciones realizadas en Arkiv: quién, qué acción y cuándo. Disponible para cuentas con rol Agente o Administrador.",
      "pasos": [
          "Filtra por \"Filtrar por Usuario\" o \"Filtrar por Acción\" (el filtro se aplica al elegir la opción).",
          "Escribe en \"Buscar por nombre, cédula, usuario, detalle o fecha\" y presiona Enter.",
          "Usa \"Anterior\"/\"Siguiente\" para moverte entre páginas de 50 registros.",
          "Pulsa \"Exportar a Excel (CSV)\" para descargar los registros que coinciden con el filtro actual.",
          "Pulsa \"Log de Correos\" para ir a la bitácora de correos enviados por la app."
      ],
      "preguntas": [
          {
              "q": "¿Hasta cuándo llega este historial?",
              "a": "No tiene límite de tiempo: cada acción registrada por el sistema queda aquí, paginada de 50 en 50; usa los filtros para acotar la búsqueda."
          },
          {
              "q": "¿El CSV exportado respeta los filtros que apliqué?",
              "a": "Sí, \"Exportar a Excel (CSV)\" usa exactamente el mismo usuario, acción y texto de búsqueda que tengas aplicados en pantalla."
          }
      ]
  },
  "logs_correos": {
      "titulo": "Log de Correos Enviados",
      "descripcion": "Bitácora de los correos que envía la app (notificaciones de tickets y códigos de recuperación de clave), con destinatario, asunto, tipo y si el envío tuvo éxito. Disponible para cuentas con rol Agente o Administrador. Por seguridad, nunca muestra el contenido del correo ni los códigos de verificación.",
      "pasos": [
          "Filtra por \"Destinatario\", \"Tipo de correo\" (Ticket / Recuperación de clave) o \"Estado del envío\" (Enviado/Error).",
          "Escribe en \"Buscar en destinatario / asunto\" y presiona Enter.",
          "Pulsa \"Exportar a Excel (CSV)\" para descargar el resultado filtrado.",
          "Pulsa \"Ver Auditoría\" para ir a la bitácora general de logs."
      ],
      "preguntas": [
          {
              "q": "¿Por qué un correo aparece marcado como \"Error\"?",
              "a": "El envío falló (por ejemplo, un problema de red o del proveedor de correo); la columna \"Detalle del error\" muestra el mensaje de la excepción."
          },
          {
              "q": "¿Puedo ver aquí el código de recuperación de alguien?",
              "a": "No. Este registro solo guarda destinatario, asunto, tipo y estado; el código y el cuerpo del correo nunca se almacenan."
          },
          {
              "q": "¿Hay un límite de correos mostrados?",
              "a": "Sí, se muestran los 500 correos más recientes que coincidan con el filtro; usa los filtros para acotar si necesitas algo más puntual."
          }
      ]
  },
  "admin_db": {
      "titulo": "Gestor de Base de Datos",
      "descripcion": "Visor genérico de las tablas de la base de datos con una consola para ejecutar SQL libre. Todo el módulo, incluida la sola visualización de tablas, es exclusivo de la cuenta super-admin ('admin'); ningún otro administrador ni agente puede entrar.",
      "pasos": [
          "Haz clic en el nombre de una tabla (usuarios, logs, tickets, credenciales, etc.) en la barra superior para ver sus primeros 100 registros.",
          "Escribe una sentencia en el campo \"Ejecutar Consulta SQL Personalizada\" (SELECT, UPDATE, DELETE, INSERT) y pulsa \"Ejecutar SQL\"; confirma el cuadro de diálogo de advertencia.",
          "Revisa el mensaje de éxito o de error que aparece después de ejecutar la consulta.",
          "Usa el control de columnas de la tabla de resultados para reordenar u ocultar columnas (la preferencia se guarda por tabla)."
      ],
      "preguntas": [
          {
              "q": "¿Cualquier administrador puede entrar aquí y ejecutar SQL?",
              "a": "No. Tanto el acceso a esta página como la consola SQL están restringidos a la cuenta super-admin ('admin'); ningún otro admin ni agente la ve."
          },
          {
              "q": "¿Qué pasa si mi consulta SQL falla?",
              "a": "Se revierte la transacción (rollback), el intento queda registrado en la Bitácora de Auditoría junto con el error, y ves el mensaje de error en pantalla."
          },
          {
              "q": "¿Se registra lo que consulto o ejecuto aquí?",
              "a": "Sí, cada sentencia SQL manual —éxito o error, incluyendo simples SELECT— queda registrada en la Bitácora de Auditoría."
          }
      ]
  },
  "respaldos": {
      "titulo": "Respaldos de Base de Datos",
      "descripcion": "Genera, descarga y administra respaldos (.json) de todas las tablas de la base de datos, y configura la frecuencia del respaldo automático. Exclusivo de la cuenta super-admin ('admin').",
      "pasos": [
          "Pulsa \"Generar y descargar ahora\" para crear un respaldo manual de inmediato.",
          "Configura la frecuencia en los campos \"Cada\" y \"Unidad\" (Día(s) u Hora(s)) y, si es en días, la hora en \"A las\"; pulsa \"Guardar\".",
          "Descarga un respaldo existente con el ícono de descarga, o bórralo con el ícono de basura (pide confirmación).",
          "Revisa la columna \"Copia externa\" para confirmar si el respaldo ya se subió a Cloudinary."
      ],
      "preguntas": [
          {
              "q": "¿Los respaldos incluyen los archivos adjuntos (imágenes, PDFs)?",
              "a": "No, solo incluyen las tablas de la base de datos; los archivos adjuntos ya viven aparte, en Cloudinary."
          },
          {
              "q": "¿Qué hago si \"Copia externa\" muestra \"Pendiente\"?",
              "a": "La subida a Cloudinary toma unos segundos después de generarse el respaldo; espera un momento y recarga la página. Si sigue pendiente, esa subida puntual pudo haber fallado."
          },
          {
              "q": "¿Se eliminan solos los respaldos viejos?",
              "a": "Los automáticos con más de 30 días se eliminan solos; los manuales se conservan hasta que los borres tú."
          }
      ]
  },
  "diseno_modales": {
      "titulo": "Diseño de Modales",
      "descripcion": "Personaliza los colores de marca y de los modales de toda la plataforma (fondo, borde, texto) para cada uno de los 3 temas (oscuro, claro, descansar la vista). Exclusivo de la cuenta super-admin ('admin'), porque el cambio se aplica de inmediato a todos los usuarios de Arkiv.",
      "pasos": [
          "Ajusta los \"Colores de marca\" (azul primario, azul secundario, cian, naranja) con el selector de color o escribiendo el código hexadecimal.",
          "Ajusta fondo, borde, texto y texto secundario para cada tema y revisa la \"Vista previa\" en vivo de cada bloque.",
          "Pulsa \"Guardar colores\" para aplicar los cambios a todas las personas que usan Arkiv.",
          "Pulsa \"Restablecer a los colores originales\" si necesitas volver a los valores de fábrica (pide confirmación)."
      ],
      "preguntas": [
          {
              "q": "¿A quién afectan estos cambios?",
              "a": "A todos los usuarios de Arkiv, de inmediato al guardar — no solo a tu propia cuenta."
          },
          {
              "q": "¿Los \"Colores de marca\" solo se usan en los modales?",
              "a": "No, también se usan en la pantalla de inicio de sesión y en el selector de color del Muro de Comunicados."
          },
          {
              "q": "¿Puedo deshacer un cambio si me equivoco?",
              "a": "Sí, usa \"Restablecer a los colores originales\" para volver a los valores de fábrica de Arkiv; se pierde cualquier personalización guardada."
          }
      ]
  },
  "fondo_login": {
      "titulo": "Fondo de Login",
      "descripcion": "Administra las imágenes o videos cortos que se muestran en un panel junto al formulario de inicio de sesión, rotando automáticamente si hay más de uno activo. Vive dentro de Novedades y Comunicados y está disponible para cuentas con rol Agente o Administrador.",
      "pasos": [
          "Selecciona un archivo (imagen JPG/PNG/GIF/WEBP o video MP4/MOV/WEBM, máximo 60 MB) y pulsa \"Agregar al fondo\".",
          "Usa las flechas de subir/bajar para cambiar el orden de rotación de un archivo.",
          "Pulsa el ícono de pausa/reproducir para pausar o reactivar un archivo sin borrarlo.",
          "Pulsa el ícono de basura para eliminarlo definitivamente (también se borra de Cloudinary; pide confirmación)."
      ],
      "preguntas": [
          {
              "q": "¿Este panel se ve en el celular?",
              "a": "No, solo se muestra en pantallas grandes; en celular se oculta para que el inicio de sesión cargue rápido y liviano."
          },
          {
              "q": "¿Qué pasa si no subo ningún archivo?",
              "a": "El login se ve igual que siempre, sin el panel adicional."
          },
          {
              "q": "¿Qué tamaño de imagen conviene usar?",
              "a": "Una imagen cercana a cuadrada (por ejemplo 1200×1200 px), porque el archivo se muestra completo, sin recortar."
          }
      ]
  },
  "historial_sesiones": {
      "titulo": "Historial de Sesiones",
      "descripcion": "Muestra los inicios y cierres de sesión de tu propia cuenta (fecha, dirección IP y dispositivo). Disponible para cualquier usuario autenticado; las cuentas con rol Administrador además pueden consultar el historial de cualquier otra cuenta desde un selector.",
      "pasos": [
          "Revisa la tabla de eventos (Inicio de Sesión, Cierre de Sesión, Cuenta Bloqueada por Intentos, Desbloqueo por Intentos Fallidos, etc.) con fecha, IP y dispositivo.",
          "(Solo Administrador) Usa el selector \"Ver historial de:\" para consultar el historial de otra cuenta.",
          "(Solo Administrador) Pulsa \"Mapa de accesos\" para ir a Geolocalización de Accesos.",
          "Si ves un acceso que no reconoces, entra a \"tu perfil\" para cambiar tu contraseña y considera activar la \"verificación en dos pasos\"."
      ],
      "preguntas": [
          {
              "q": "¿Puedo ver el historial de otra persona?",
              "a": "Solo si tu cuenta tiene rol Administrador; el resto de usuarios únicamente ve su propio historial."
          },
          {
              "q": "Veo un acceso que no reconozco, ¿qué hago?",
              "a": "Cambia tu contraseña de inmediato desde tu perfil, avisa a un administrador y considera activar la verificación en dos pasos (2FA)."
          }
      ]
  },
  "tablero_ejecutivo": {
      "titulo": "Tablero Ejecutivo",
      "descripcion": "Panorama agregado de las métricas de Arkiv (solicitudes de soporte, usuarios, instructivos, inventario, vencimientos, comunicados, etc.) en una sola pantalla, con acceso directo a cada módulo. Exclusivo de cuentas con rol Administrador.",
      "pasos": [
          "Filtra por \"Mes\", rango de fechas (\"Desde\"/\"Hasta\") o \"Analista\" y pulsa \"Filtrar\" (afecta las tarjetas y la tendencia de Solicitudes de Soporte); usa \"Limpiar\" para quitar los filtros.",
          "Revisa las tarjetas KPI: Solicitudes abiertas, SLA vencidos, Satisfacción promedio, Usuarios activos, Tiempo promedio de resolución y la variación de solicitudes frente al período anterior.",
          "Consulta la gráfica de tendencia de \"Solicitudes de Soporte creadas\".",
          "Revisa la tabla \"Uso por módulo\" y pulsa \"Ver\" en cualquier fila para ir directo a ese módulo.",
          "Pulsa el enlace a \"Indicadores de Soporte TI\" para el detalle completo de tickets con gráficos y exportación a PDF/Excel."
      ],
      "preguntas": [
          {
              "q": "¿Los filtros de arriba afectan todas las tarjetas?",
              "a": "No, solo las relacionadas con Solicitudes de Soporte (tickets); el resto de módulos (usuarios, inventario, comunicados, etc.) no cambia con ese filtro."
          },
          {
              "q": "¿Dónde exporto esta información a PDF o Excel?",
              "a": "Desde \"Indicadores de Soporte TI\" (enlace en la parte superior del tablero), que tiene el detalle completo de tickets con gráficos y exportación."
          }
      ]
  },
  "archivos": {
      "titulo": "Gestor de Instructivos",
      "descripcion": "Es el repositorio central de instructivos, manuales, guías rápidas y políticas de la empresa, organizados por categoría, tipo de documento y formato adjunto (imagen, video, PDF u otros). Cualquier cuenta con sesión iniciada puede ver y buscar el material disponible; solo los roles Admin y Agente pueden publicar, editar o eliminar instructivos, y también pueden marcar un instructivo como visible 'Solo Administradores / Agentes' para ocultarlo del resto de usuarios.",
      "pasos": [
          "Usa los filtros de 'Búsqueda por Texto', 'Categoría', 'Tipo de Documento' y 'Formato Adjunto' para encontrar un instructivo.",
          "Haz clic en el ícono de archivo para previsualizarlo o en el ícono de descarga para bajarlo directamente.",
          "(Admin/Agente) Haz clic en 'Nuevo Instructivo' para abrir el formulario de carga.",
          "Completa Título, Categoría, Tipo, Descripción y adjunta uno o varios archivos; elige si será visible para 'Todos' o solo para 'Solo Administradores / Agentes', y opcionalmente una fecha de vencimiento.",
          "Pulsa 'Subir Material' para publicarlo; los demás usuarios reciben una notificación de campanita según la visibilidad elegida.",
          "(Admin/Agente) Usa el lápiz para 'Editar' o el ícono de papelera para enviar el instructivo o un archivo suelto a la papelera."
      ],
      "preguntas": [
          {
              "q": "¿Cualquier usuario puede subir un instructivo?",
              "a": "No. Ver y descargar instructivos está disponible para cualquier cuenta con sesión iniciada, pero subir, editar o eliminar material (y el botón 'Nuevo Instructivo') solo aparece para los roles Admin y Agente."
          },
          {
              "q": "¿Qué tipos de archivo y qué tamaño máximo admite?",
              "a": "Se aceptan imágenes (png, jpg, jpeg, gif, webp), documentos (pdf, txt, docx, xlsx, pptx), video (mp4, mov, webm, avi) y comprimidos (zip, rar, 7z, tar, gz), hasta 500 MB por archivo. Arkiv también valida que el contenido real del archivo coincida con su extensión, no solo el nombre."
          },
          {
              "q": "¿Qué significa marcar un instructivo como 'Solo Administradores / Agentes'?",
              "a": "Ese instructivo queda oculto del listado y de las sugerencias de búsqueda para cualquier usuario con rol Estándar; solo las cuentas Admin y Agente lo verán, igual que ocurre con el material marcado 'admin' en el módulo."
          },
          {
              "q": "¿Puedo ver quién ha visto o descargado un instructivo?",
              "a": "Sí, pero solo si tu rol es Admin o Agente: el ícono junto al contador de vistas abre un modal con el listado de usuarios que lo han visto y la fecha de su primera vista."
          }
      ]
  },
  "comunicados": {
      "titulo": "Muro de Comunicados",
      "descripcion": "Es el tablón de novedades institucionales de Preventiva IPS: mantenimientos, cambios de proceso y alertas, con nivel de prioridad (Informativo, Importante o Urgente). Cualquier cuenta con sesión iniciada puede ver los comunicados activos y el histórico; publicar, editar, archivar o eliminar comunicados, así como usar 'Cumplimiento' y 'Fondo de Login', está reservado a los roles Admin y Agente.",
      "pasos": [
          "Cambia entre las pestañas 'Novedades Activas' e 'Histórico' para ver los comunicados vigentes o los archivados.",
          "Usa el buscador para filtrar por palabras del título, contenido o autor.",
          "(Admin/Agente) Haz clic en 'Publicar Comunicado' para abrir el formulario.",
          "Escribe el Título y el Detalle/Mensaje (editor de texto enriquecido), elige el 'Nivel de Prioridad', adjunta una imagen opcional, define '¿Quién puede verlo?' (Todos o Solo Administradores/Agentes) y, si quieres, un color de tarjeta.",
          "Pulsa 'Publicar' para que el comunicado aparezca en el muro y se notifique a los destinatarios correspondientes.",
          "(Admin/Agente) Usa los íconos de la tarjeta para editar, archivar/reactivar o enviar el comunicado a la papelera."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede publicar un comunicado?",
              "a": "Solo las cuentas con rol Admin o Agente ven el botón 'Publicar Comunicado' y pueden crear, editar, archivar o eliminar comunicados; un usuario Estándar solo puede leerlos y buscarlos."
          },
          {
              "q": "¿Qué pasa cuando abro el Muro de Comunicados?",
              "a": "Al entrar en la pestaña 'Novedades Activas', Arkiv marca automáticamente como leídos, para tu cuenta, todos los comunicados activos que ves en pantalla (los archivados no cuentan como pendientes de lectura)."
          },
          {
              "q": "¿Se puede restringir un comunicado a solo Admin/Agente?",
              "a": "Sí, con la opción '¿Quién puede verlo?' al crear o editar el comunicado, seleccionando 'Solo Administradores / Agentes'; en ese caso el resto de usuarios ni siquiera se entera de que existe."
          },
          {
              "q": "¿Cómo sé si un comunicado ya lo leyó todo el mundo?",
              "a": "Si tu rol es Admin o Agente, cada tarjeta del muro muestra cuántos usuarios activos ya lo leyeron, y el botón 'Ver quién lo ha leído' abre el detalle; para una vista consolidada de todos los comunicados usa el botón 'Cumplimiento'."
          }
      ]
  },
  "comunicados_cumplimiento": {
      "titulo": "Cumplimiento de Lectura",
      "descripcion": "Es el panel de seguimiento de lectura de los comunicados vigentes (no archivados): muestra, para cada uno, qué porcentaje de las cuentas activas ya lo leyó y quién falta. Esta página está restringida por completo a los roles Admin y Agente; se accede desde el botón 'Cumplimiento' del Muro de Comunicados.",
      "pasos": [
          "Entra desde el Muro de Comunicados con el botón 'Cumplimiento'.",
          "Revisa el porcentaje y el conteo '(leídos)/(total)' de cada comunicado activo.",
          "Haz clic en 'Falta por leer (N)' para desplegar la lista de usuarios que aún no lo han leído.",
          "Si hace falta insistir, pulsa 'Enviar recordatorio' y confirma para notificar por correo a quienes faltan por leerlo."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede entrar a este panel?",
              "a": "Solo Admin y Agente: la ruta está protegida y cualquier otro rol es redirigido automáticamente al Gestor de Instructivos si intenta acceder."
          },
          {
              "q": "¿Arkiv envía recordatorios de lectura automáticamente?",
              "a": "Sí. Si un comunicado lleva más de 48 horas publicado y todavía le falta gente por leer, Arkiv ya le envía un recordatorio automático por correo y campanita; el botón 'Enviar recordatorio' permite mandarlo también de forma manual en cualquier momento."
          },
          {
              "q": "¿Los comunicados archivados aparecen aquí?",
              "a": "No, el panel solo muestra comunicados vigentes (no archivados); si no hay ninguno activo, la página indica 'No hay comunicados activos'."
          }
      ]
  },
  "conocimiento": {
      "titulo": "Base de Conocimiento",
      "descripcion": "Es la biblioteca de artículos de referencia dentro del módulo de Soporte TI, cada uno con título, descripción y un documento adjunto (PDF, Word, Excel u otro). Cualquier cuenta con sesión iniciada puede buscar y abrir los artículos; crear, editar o eliminar artículos solo está disponible para los roles Admin y Agente.",
      "pasos": [
          "Usa el buscador de artículos para filtrar por palabras del título o la descripción.",
          "Haz clic en 'Abrir documento' para ver o descargar el archivo del artículo.",
          "(Admin/Agente) Haz clic en 'Nuevo Artículo' para abrir el formulario.",
          "Completa el Título (obligatorio) y la Descripción, y adjunta el Documento de referencia.",
          "Pulsa 'Guardar' para publicar el artículo en la Base de Conocimiento.",
          "(Admin/Agente) Usa el ícono de lápiz para editarlo o el de papelera para eliminarlo (pide confirmación)."
      ],
      "preguntas": [
          {
              "q": "¿Cualquiera puede crear un artículo?",
              "a": "No. Solo los roles Admin y Agente ven el botón 'Nuevo Artículo' y los íconos de editar/eliminar; cualquier otro usuario logueado solo puede buscar y abrir los artículos existentes."
          },
          {
              "q": "¿Qué documentos se pueden adjuntar?",
              "a": "El campo 'Documento' acepta PDF, Word, Excel u otro documento de referencia, dentro de los mismos formatos permitidos en el resto de Arkiv (imágenes, pdf/txt/docx/xlsx/pptx, video y comprimidos), con un tope de 500 MB por archivo."
          },
          {
              "q": "¿Se puede editar un artículo sin reemplazar el documento?",
              "a": "Sí, al editar puedes dejar el campo de documento vacío y Arkiv conserva el archivo que ya estaba adjunto, actualizando solo el título y la descripción."
          },
          {
              "q": "¿Arkiv registra cuántas veces se abre un artículo?",
              "a": "Sí, cada vez que alguien pulsa 'Abrir documento' se suma una vista al contador que se muestra en la tarjeta del artículo."
          }
      ]
  },
  "chat": {
      "titulo": "Chat Interno",
      "descripcion": "Chat interno en tiempo real, exclusivo para usuarios con rol admin o agente. Incluye un \"Canal General\" compartido por todo el equipo con acceso operativo y conversaciones directas (persona a persona) con cualquier otro admin/agente activo. Los usuarios con rol estándar no tienen acceso a este módulo; para ellos la ruta /chat muestra en su lugar el Asistente de Chat.",
      "pasos": [
          "Haz clic en \"Canal General\" en la barra lateral para ver y enviar mensajes al equipo completo de admin/agente.",
          "Haz clic en un contacto de la lista para abrir una conversación directa 1 a 1 con esa persona.",
          "Usa el buscador \"Buscar por nombre o usuario...\" para filtrar la lista de contactos, y los botones \"Todos / En línea / Desc.\" para filtrar por estado de conexión.",
          "Escribe el mensaje en el cuadro de texto (Enter para enviar, Shift+Enter para salto de línea) y presiona el botón de enviar (icono de avión de papel).",
          "Usa el icono del clip para adjuntar un archivo, o pega una imagen copiada directo en el cuadro de texto.",
          "Marca un contacto con la estrella (favorito) o el pin (anclar arriba) para organizarlo en tu propia lista; estas marcas son personales y no afectan lo que ven los demás."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede usar el Chat Interno?",
              "a": "Solo usuarios con rol admin o agente. Los usuarios con rol estándar no ven este chat; en su lugar acceden al Asistente de Chat (IA/menú guiado)."
          },
          {
              "q": "¿Quién ve mis mensajes directos?",
              "a": "Un mensaje directo solo lo ven tú y la persona con la que conversas. El Canal General, en cambio, lo ve todo el equipo con acceso operativo (admin/agente)."
          },
          {
              "q": "¿Puedo saber si un contacto está conectado?",
              "a": "Sí, cada contacto muestra un punto verde (en línea) o rojo (desconectado) según su actividad reciente, y puedes filtrar la lista con los botones En línea/Desconectados."
          },
          {
              "q": "¿Qué es el botón \"Asistente para estándar\" que ve un admin?",
              "a": "Es el interruptor general que un administrador usa para habilitar o deshabilitar, para todas las cuentas con rol estándar a la vez, el acceso al Asistente de Chat guiado por menú. No afecta al Chat Interno."
          }
      ]
  },
  "chat_bot": {
      "titulo": "Asistente de Chat",
      "descripcion": "Módulo disponible para usuarios con rol estándar en la ruta /chat. No es una conversación con una persona real ni un chat libre: es un asistente automático que avanza por un menú de opciones fijas (crear una solicitud de soporte, consultar tus solicitudes, ver preguntas frecuentes, o pedir hablar con un agente humano). Un administrador debe habilitarlo primero para todo el rol estándar; si está deshabilitado, la pantalla lo indica y ofrece crear la solicitud o consultar la Base de Conocimiento por otra vía.",
      "pasos": [
          "Responde escribiendo el número de la opción que quieres, o el texto de la opción, en el cuadro de mensaje.",
          "Elige \"Crear una solicitud de soporte\" y sigue las preguntas del asistente (categoría, título y descripción) para registrar un ticket.",
          "Elige \"Consultar mis solicitudes\" para ver tus últimas solicitudes registradas y su estado.",
          "Elige \"Preguntas frecuentes\" para ver los artículos publicados en la Base de Conocimiento.",
          "Elige \"Hablar con un agente humano\" para escalar tu caso: se crea una solicitud de prioridad alta y, cuando un agente responda, la conversación continúa en esta misma pantalla.",
          "Escribe la palabra 'volver' en cualquier momento para regresar al menú principal, o usa el botón \"Reiniciar conversación\" para empezar de nuevo."
      ],
      "preguntas": [
          {
              "q": "¿Puedo hablar con una persona real desde el asistente de chat?",
              "a": "No directamente en una conversación libre, pero sí puedes escalar tu caso eligiendo \"Hablar con un agente humano\": esto crea una solicitud de soporte y, en cuanto un agente te responda, esa respuesta aparece en esta misma ventana como continuación de la conversación. La propia pantalla lo aclara: \"Este es un asistente automático — no es una conversación con una persona\"."
          },
          {
              "q": "¿Por qué no veo el Asistente de Chat o me dice que no está disponible?",
              "a": "Porque un administrador debe habilitar esta función para los usuarios estándar (interruptor general en el Chat Interno). Mientras esté deshabilitada, puedes crear tu solicitud o consultar la Base de Conocimiento desde el menú principal del sistema."
          },
          {
              "q": "¿Qué pasa si dejo de responder al asistente?",
              "a": "Si pasan un par de minutos sin respuesta, el asistente envía un recordatorio; si sigues sin responder después de varios recordatorios, cierra la conversación automáticamente (puedes escribir de nuevo cuando quieras para reabrirla). Esto no aplica mientras estás esperando la respuesta de un agente humano."
          },
          {
              "q": "¿Es este asistente una inteligencia artificial que entiende cualquier pregunta?",
              "a": "No. Es un menú guiado de opciones fijas controlado por el sistema (similar a un bot de opciones de WhatsApp), no un modelo de IA de conversación libre. Reconoce el número de la opción, el texto exacto o parcial de la opción, y la palabra 'volver'."
          }
      ]
  },
  "credenciales": {
      "titulo": "Bóveda de Accesos",
      "descripcion": "Bóveda institucional de credenciales y notas seguras (servidores, aplicativos, cuentas de servicio), exclusiva para roles admin y agente. Cada ítem puede marcarse como 'Equipo' (visible para todo admin/agente, el comportamiento de siempre) o 'Personal' (solo lo ve su dueño, con quien se comparta puntualmente, o un admin en auditoría). No debe confundirse con Mi Bóveda Personal: esta última la puede usar cualquier rol y solo muestra las entradas personales de quien entra, mientras que la Bóveda de Accesos además reúne los ítems 'Equipo' de toda la organización.",
      "pasos": [
          "Haz clic en 'Nueva Credencial' para abrir el formulario.",
          "Elige el tipo de ítem: 'Credencial' o 'Nota segura', y la visibilidad: 'Equipo' o 'Personal'.",
          "Completa Nombre del Aplicativo/Servicio, usuario y contraseña (puedes usar el botón de generar contraseña) o el contenido de la nota.",
          "Opcional: define una política de rotación en días, etiquetas y campos personalizados.",
          "Guarda con 'Guardar Acceso'; usa los íconos de ojo/copiar para revelar la clave a demanda, 'Historial' para ver claves anteriores, y 'Compartir puntualmente' (solo en ítems personales) para dar acceso de solo consulta a otro colaborador.",
          "Entra a 'Auditoría' (arriba a la derecha) para revisar seguridad de contraseñas, rotación e historial de consultas."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede entrar a la Bóveda de Accesos?",
              "a": "Solo usuarios con rol admin o agente. El rol estándar no tiene acceso a esta página en absoluto."
          },
          {
              "q": "¿En qué se diferencia de Mi Bóveda Personal?",
              "a": "Mi Bóveda Personal es accesible para cualquier rol y solo muestra tus propias entradas 'Personal'. La Bóveda de Accesos, además de los ítems 'Equipo' institucionales, permite a un admin/agente crear también ítems 'Personal' desde el mismo lugar; esos ítems personales son los mismos que después ve esa persona en Mi Bóveda Personal."
          },
          {
              "q": "¿Cómo comparto un acceso con un colaborador?",
              "a": "Solo los ítems marcados 'Personal' se pueden compartir puntualmente con el botón de compartir: el colaborador podrá ver y copiar el ítem, pero no editarlo, eliminarlo ni volver a compartirlo. Los ítems 'Equipo' ya son visibles por defecto para todo admin/agente, no hace falta compartirlos."
          },
          {
              "q": "¿Por qué no veo la contraseña apenas abro la página?",
              "a": "Por seguridad ninguna clave se envía junto con la página: se descifra solo al pulsar 'ver clave' o 'copiar clave', y cada consulta queda registrada en la Auditoría de Credenciales."
          }
      ]
  },
  "credenciales_auditoria": {
      "titulo": "Auditoría de Credenciales",
      "descripcion": "Panel de solo consulta (admin/agente) con tres secciones: seguridad de contraseñas (débiles o repetidas), estado de rotación de contraseñas según la política opcional de cada credencial, e historial reciente de quién consultó o copió cada clave. El análisis de seguridad y de rotación revisa todas las credenciales activas guardadas en la tabla, tanto las institucionales ('Equipo') como las 'Personal' de cualquier usuario, no solo las de la Bóveda de Accesos que ese admin/agente ve normalmente.",
      "pasos": [
          "Entra desde el botón 'Auditoría' en la Bóveda de Accesos.",
          "Revisa 'Seguridad de contraseñas': ítems marcados 'Débil' (muy corta o de uso común) o 'Repetida' (la misma clave usada en más de un ítem).",
          "Revisa 'Estado de rotación de contraseñas': etiquetas 'Vencida', 'Al día' o 'Sin política', según los días transcurridos frente a la política configurada.",
          "Revisa 'Historial de consultas recientes' para ver quién vio o copió qué clave y cuándo (últimas 200 consultas).",
          "Para resolver una alerta, ve a la Bóveda de Accesos y edita esa credencial cambiando la contraseña; eso cuenta como una rotación y limpia el aviso pendiente."
      ],
      "preguntas": [
          {
              "q": "¿Cómo se detectan contraseñas débiles o repetidas?",
              "a": "El análisis ocurre dentro del servidor: una contraseña muy corta (menos de 8 caracteres) o que coincide con una lista de contraseñas comunes se marca 'Débil'; si la misma clave se usa en más de un ítem activo, se marca 'Repetida'. Ninguna contraseña sale de Arkiv ni se consulta contra servicios externos de filtraciones."
          },
          {
              "q": "¿Qué credenciales entran en este análisis?",
              "a": "Todas las credenciales activas de tipo 'credencial' (las notas seguras no tienen clave real y se excluyen), tanto institucionales como personales de cualquier usuario; la auditoría no filtra por visibilidad ni propietario."
          },
          {
              "q": "¿Qué significa que una credencial esté 'Vencida'?",
              "a": "Que ya pasaron más días que los definidos en su política de rotación desde el último cambio de esa contraseña. 'Sin política' significa que esa credencial no tiene configurados días de rotación, así que no se le hace seguimiento."
          },
          {
              "q": "¿Puedo cambiar algo desde este panel?",
              "a": "No, es de solo consulta. Cualquier cambio (editar, cambiar contraseña) se hace desde la Bóveda de Accesos."
          }
      ]
  },
  "credenciales_colaboradores": {
      "titulo": "Altas de Credenciales",
      "descripcion": "Registro (admin/agente) de los accesos entregados a colaboradores en cada aplicativo de la organización (por ejemplo SAMI, correo, Wolkvox), con su propio historial de quién lo solicitó (número de PQRS), qué analista lo gestionó, quién capacitó a la persona y por qué medio se envió la credencial. Usa una tabla independiente (credenciales_colaboradores), distinta de la Bóveda de Accesos: esta última guarda credenciales de servicios/infraestructura de la organización, mientras que Altas de Credenciales lleva la trazabilidad de accesos entregados a personas puntuales.",
      "pasos": [
          "Haz clic en 'Nueva Alta' para abrir el formulario.",
          "Escribe o selecciona el 'Colaborador' (autocompleta con nombres ya registrados o con Gestión de Usuarios).",
          "Marca uno o varios 'Aplicativo(s)'; si conoces el usuario/ID propio de ese aplicativo o necesita una contraseña distinta, diligencia esos campos debajo de la casilla marcada.",
          "Escribe la 'Contraseña asignada' (se usa para todos los aplicativos marcados, salvo que hayas indicado una distinta para alguno).",
          "Opcional: fecha de solicitud/creación, 'Solicitado por (PQRS)', 'Analista que gestiona', 'Capacitado por' y 'Credenciales enviadas vía'.",
          "Guarda con 'Guardar Alta'; luego usa los íconos de ojo/copiar para ver la clave, 'Editar', 'Deshabilitar'/'Reactivar', o el ícono de papelera para eliminar un registro de forma permanente."
      ],
      "preguntas": [
          {
              "q": "¿En qué se diferencia de la Bóveda de Accesos?",
              "a": "La Bóveda de Accesos guarda credenciales de servicios e infraestructura de la organización; Altas de Credenciales registra los accesos entregados a colaboradores en cada aplicativo, con historial de solicitud (PQRS), analista y medio de envío. Son tablas distintas."
          },
          {
              "q": "¿Qué diferencia hay entre 'Deshabilitar' y eliminar un registro?",
              "a": "Deshabilitar marca el registro como 'Deshabilitado' (con fecha y quién lo hizo) pero lo conserva y se puede 'Reactivar' después. Eliminar borra el registro de forma permanente y no se puede deshacer."
          },
          {
              "q": "¿Puedo dar de alta el mismo colaborador en varios aplicativos a la vez?",
              "a": "Sí, puedes marcar varios aplicativos en el mismo formulario: se crea un registro por cada uno con la misma contraseña asignada, salvo que indiques una contraseña distinta para alguno en particular."
          },
          {
              "q": "¿Quién puede ver y usar este módulo?",
              "a": "Solo usuarios con rol admin o agente."
          }
      ]
  },
  "mi_boveda": {
      "titulo": "Mi Bóveda Personal",
      "descripcion": "Bóveda privada disponible para cualquier usuario que inicie sesión (incluido el rol estándar, que no puede entrar a la Bóveda de Accesos), para guardar sus propias contraseñas o notas seguras personales. Usa la misma tabla que la Bóveda de Accesos institucional, pero filtrada para mostrar únicamente tus propias entradas marcadas como 'Personal'; nunca muestra los ítems 'Equipo' de la organización ni las entradas personales de otras personas.",
      "pasos": [
          "Haz clic en 'Nueva entrada'.",
          "Escribe el nombre del servicio, usuario y contraseña, o cambia a nota segura para guardar texto sensible sin usuario ni clave.",
          "Opcional: agrega notas, etiquetas y la URL del sitio (habilita el botón 'Ir al sitio').",
          "Guarda la entrada; usa el ícono de ojo para ver la clave o el de copiar para copiarla al portapapeles.",
          "Usa 'Historial' para ver versiones anteriores, 'Editar' para modificarla, o 'Eliminar' para enviarla a la papelera."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver mis contraseñas personales?",
              "a": "Solo tú, y un super-admin con fines de auditoría (por ejemplo offboarding urgente o una investigación de seguridad) desde el panel Auditoría de Bóveda Personal. Ni siquiera un agente puede verlas."
          },
          {
              "q": "¿Es lo mismo que la Bóveda de Accesos?",
              "a": "No. La Bóveda de Accesos institucional es exclusiva de admin/agente y guarda credenciales del equipo; Mi Bóveda Personal la puede usar cualquier rol y solo guarda tus propias entradas privadas."
          },
          {
              "q": "¿Puedo compartir una entrada de Mi Bóveda con un compañero?",
              "a": "Desde esta página no hay opción de compartir. El botón para compartir puntualmente un ítem personal solo existe en la Bóveda de Accesos institucional, a la que únicamente entran admin y agente."
          },
          {
              "q": "¿Queda registro si alguien consulta una entrada mía?",
              "a": "Sí, toda consulta o revelación (tuya, o de un super-admin en auditoría) queda registrada con el usuario y la fecha en el log del sistema."
          }
      ]
  },
  "admin_boveda_personal": {
      "titulo": "Auditoría de Bóveda Personal",
      "descripcion": "Panel exclusivo de la cuenta super-admin literal 'admin' (ni siquiera otros usuarios con rol admin pueden entrar) para buscar a cualquier persona y consultar o revelar lo que tenga guardado en su Mi Bóveda Personal, pensado para casos de prioridad como un offboarding urgente o una investigación de seguridad. Es de solo lectura: no permite crear, editar ni eliminar entradas de la bóveda de otra persona; se diferencia de la Bóveda de Accesos y de Mi Bóveda Personal en que no es un espacio de trabajo propio, sino una herramienta puntual de auditoría sobre la bóveda de otros.",
      "pasos": [
          "Escribe un nombre, usuario o cédula en 'Buscar usuario' y elige a la persona entre las sugerencias.",
          "Revisa las entradas (credenciales y notas seguras) de la bóveda personal de esa persona.",
          "Usa el ícono de ojo o 'Copiar' para revelar una clave, o 'Ver contenido' para leer una nota segura.",
          "Usa 'Historial' para ver versiones anteriores de una entrada puntual."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede usar este panel?",
              "a": "Únicamente la cuenta literal 'admin' (super-admin), el mismo candado que protege el Gestor de Base de Datos y los Respaldos; ni siquiera otras cuentas con rol admin pueden entrar."
          },
          {
              "q": "¿Puedo editar o eliminar algo desde aquí?",
              "a": "No, el panel es de solo consulta (ver/revelar). Crear, editar o eliminar una entrada solo lo puede hacer el propio dueño desde su Mi Bóveda Personal."
          },
          {
              "q": "¿Queda constancia de que consulté la bóveda de alguien más?",
              "a": "Sí, cada consulta o revelación se registra en el log de auditoría como 'Auditoría de Bóveda Personal', junto con tu usuario y el de la persona dueña de la entrada."
          }
      ]
  },
  "tickets_configuracion": {
      "titulo": "Configuración de Áreas, Sedes, Categorías y Proveedores",
      "descripcion": "Catálogo maestro que usan los Tickets/Soporte TI: aquí se definen las Áreas, Sedes, Categorías y Proveedores que luego aparecen como opciones al crear una solicitud, además del responsable de cada una (para la asignación automática de tickets). Es exclusivo del equipo de soporte: solo lo ven usuarios con rol admin o agente.",
      "pasos": [
          "Ubica la sección correspondiente (Áreas, Sedes, Categorías o Proveedores) y usa el formulario de arriba para escribir el nombre y pulsar 'Agregar área' / 'Agregar sede' / 'Agregar categoría' / 'Agregar proveedor'.",
          "Para Sedes y Áreas, completa también la dirección física y elige un responsable del listado desplegable; para Sedes puedes además indicar latitud, longitud y radio en metros.",
          "Para Proveedores, registra NIT y razón social en lugar de dirección/responsable.",
          "Para editar un registro existente, haz clic sobre él para desplegarlo, cambia los campos y pulsa el ícono de guardar (disquete).",
          "Usa el buscador de cada lista ('Buscar área/sede/categoría por nombre...' o 'Buscar por nombre o NIT...') para localizar un registro rápido antes de editarlo.",
          "Para dar de baja un registro, despliégalo y pulsa 'Eliminar área' / 'Eliminar sede' / 'Eliminar categoría' / 'Eliminar proveedor' (no se borra físicamente: queda marcado como eliminado)."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede entrar a esta pantalla?",
              "a": "Solo usuarios con rol admin o agente (equipo de Soporte TI). Cualquier otro rol es redirigido al ver intentar acceder a la URL."
          },
          {
              "q": "¿Para qué sirve el campo 'Responsable' en Áreas, Sedes y Categorías?",
              "a": "Se usa para la asignación automática de los tickets que caen en esa área/sede/categoría; se elige de un listado de usuarios activos del sistema, no como texto libre."
          },
          {
              "q": "¿Qué pasa si elimino una Sede o Categoría que ya está en uso?",
              "a": "El registro se marca como eliminado (estado = 'eliminado') y deja de aparecer como opción en los formularios nuevos, pero no borra los tickets o activos que ya la tenían asignada."
          },
          {
              "q": "¿Latitud, longitud y radio para qué se usan?",
              "a": "Son exclusivos de Sedes y sirven para validar la ubicación (geocerca) al registrar asistencia u otras validaciones por cercanía a la sede."
          }
      ]
  },
  "tickets_plantillas": {
      "titulo": "Plantillas de Solicitud",
      "descripcion": "Permite al equipo de Soporte TI (admin/agente) crear y administrar plantillas para acelerar la creación de tickets recurrentes (por ejemplo 'Solicitud de acceso a Kubapp' o 'Instalación de impresora nueva'). Cualquier usuario logueado puede luego elegir una de estas plantillas al crear una nueva solicitud: el sistema prellena tipo, título, categoría, prioridad, área, sede y descripción, y todo sigue siendo editable antes de enviar.",
      "pasos": [
          "Pulsa el botón 'Nueva plantilla' para abrir el formulario de creación.",
          "Completa el nombre de la plantilla, tipo, prioridad, categoría, área, sede, título y descripción sugeridos.",
          "Pulsa 'Guardar plantilla' para dejarla disponible en el formulario de 'Nueva Solicitud' de Tickets.",
          "Para modificar una plantilla existente, pulsa el ícono de lápiz ('Editar') sobre su tarjeta.",
          "Para retirarla, pulsa el ícono de papelera sobre la tarjeta; el sistema pide confirmación antes de eliminarla."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede crear o editar plantillas?",
              "a": "Solo admin/agente (equipo de Soporte TI) puede entrar a esta pantalla de administración. Sin embargo, cualquier usuario con sesión iniciada puede usar las plantillas ya creadas al abrir una nueva solicitud de ticket."
          },
          {
              "q": "Si uso una plantilla al crear un ticket, ¿los datos quedan fijos?",
              "a": "No. La plantilla solo prellena tipo, título, categoría, prioridad, área, sede y descripción; el usuario puede editar cualquiera de esos campos antes de enviar la solicitud."
          },
          {
              "q": "¿Al eliminar una plantilla se pierden los tickets ya creados con ella?",
              "a": "No, la plantilla se marca como inactiva (estado != 'activo') y deja de listarse; los tickets que ya se crearon usándola no se ven afectados."
          }
      ]
  },
  "tickets_indicadores": {
      "titulo": "Indicadores de Tickets",
      "descripcion": "Tablero de métricas de Soporte TI: totales por cumplimiento de SLA (vigente/próximo a vencer/vencido), satisfacción promedio, tiempo promedio de resolución, tendencia de solicitudes creadas y gráficos por categoría/agente/sede. Es exclusivo de admin/agente y permite filtrar por mes, rango de fechas y agente, además de exportar el reporte.",
      "pasos": [
          "Usa los filtros 'Mes' (o rango de fechas) y 'Agente' en la parte superior y pulsa el botón de aplicar (ícono de filtro) para acotar los indicadores; usa 'Quitar filtros' para volver a ver todo el histórico.",
          "Revisa las tarjetas KPI (Total Solicitudes, Vigentes, Próx. a vencer, Vencidos, Satisfacción promedio, Tiempo prom. de resolución): cada una de las cuatro primeras es clicable y lleva al listado de tickets ya filtrado por ese estado de cumplimiento.",
          "Explora los gráficos (tendencia de solicitudes, distribución por categoría/prioridad/agente/sede) que ya reflejan los filtros aplicados.",
          "Pulsa 'Exportar a Excel' para descargar el reporte de indicadores (resumen + detalle) en un libro de Excel.",
          "Pulsa el botón de exportar a PDF para obtener el mismo reporte listo para imprimir o enviar a gerencia.",
          "Pulsa el botón de exportar a CSV para descargar el listado completo de tickets filtrados, útil para analizarlo aparte en Excel."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver este tablero?",
              "a": "Solo usuarios con rol admin o agente; el resto de roles no tiene acceso a esta URL."
          },
          {
              "q": "¿Los gráficos y exportaciones respetan los filtros de mes/fecha/agente que elegí?",
              "a": "Sí, tanto las tarjetas y gráficos en pantalla como las tres exportaciones (CSV, Excel, PDF) usan el mismo filtro de fecha inicio/fin y agente que se haya aplicado."
          },
          {
              "q": "¿Qué diferencia hay entre las tres exportaciones?",
              "a": "El CSV entrega el listado plano de tickets (código, tipo, título, categoría, área, sede, prioridad, estado, fechas y calificación) para analizar en una hoja de cálculo; el Excel entrega un reporte con resumen y detalle; el PDF entrega el mismo contenido del tablero (incluyendo gráficos) listo para imprimir o enviar a gerencia."
          },
          {
              "q": "¿Qué significa 'Próx. a vencer' y 'Vencido'?",
              "a": "Reflejan el cumplimiento del SLA de cada ticket: 'Vigente' aún tiene margen, 'Próx. a vencer' está cerca del límite y 'Vencido' ya superó el tiempo de atención acordado; el sistema revisa y avisa (campanita/correo) automáticamente estos cambios de estado al entrar a este panel."
          }
      ]
  },
  "tickets_inventario": {
      "titulo": "Inventario de Activos",
      "descripcion": "Módulo de Soporte TI (admin/agente) para administrar el inventario de equipos: alta y edición de activos con placa, tipo, marca, modelo, número de serie, estado, asignación a un colaborador, sede, área y proveedor; también soporta reemplazo de equipos con trazabilidad, actas de asignación/recibido en PDF, adjuntos y carga/descarga masiva por Excel.",
      "pasos": [
          "Pulsa 'Nuevo Activo' para registrar un equipo (placa/nombre, tipo, marca, modelo, número de serie, estado, sede, área, proveedor, costo de compra o alquiler, y a quién se asigna).",
          "Usa los filtros de estado, tipo, sede, área y proveedor, o el buscador (que también encuentra por cédula del colaborador asignado), para acotar la tabla de activos.",
          "Para modificar un activo, ábrelo desde la tabla y edita sus datos; puedes marcar 'Generar acta de asignación (PDF)' para dejar constancia firmada de la entrega.",
          "Usa el ícono de 'Reemplazar activo' cuando un equipo se sustituye por otro, indicando motivo y el activo de reemplazo, para conservar la trazabilidad entre ambos.",
          "Pulsa 'Tipos de activo' para administrar el catálogo de tipos de equipo (crear, eliminar y reordenar).",
          "Pulsa 'Importar / Exportar' para descargar la plantilla de carga masiva en Excel, subir un archivo con varios activos a la vez, o exportar el inventario filtrado a CSV, Excel o PDF."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede administrar el Inventario?",
              "a": "Solo usuarios con rol admin o agente (equipo de Soporte TI)."
          },
          {
              "q": "¿Las tarjetas de conteo (Disponibles, Asignados, En mantenimiento, etc.) y de costos responden a los filtros que aplico?",
              "a": "Sí. Responden a la sede, tipo, área, proveedor y búsqueda ya elegidos, pero no al filtro de estado en sí, para poder seguir comparando los distintos estados entre ellos aunque estés viendo, por ejemplo, solo una sede."
          },
          {
              "q": "¿Qué pasa con un activo después de certificar su devolución?",
              "a": "Ya no pasa a 'Disponible' de inmediato: queda en estado 'Devolución', bloqueado, hasta que un admin/agente lo revise desde este módulo y le asigne su siguiente estado (Disponible, Mantenimiento, Baja, etc.)."
          },
          {
              "q": "¿Cómo veo el historial de un activo (a quién se asignó antes, si fue reemplazado, o qué tickets tiene asociados)?",
              "a": "Cada activo guarda su trazabilidad de reemplazos (como saliente o entrante), sus adjuntos y el historial de tickets de soporte donde se marcó ese equipo como 'Activo relacionado'."
          },
          {
              "q": "¿Se puede cargar el inventario de forma masiva?",
              "a": "Sí, desde 'Importar / Exportar' se descarga primero una plantilla .xlsx con las columnas exactas (Placa, Tipo de activo, Marca, Modelo, Número de serie, Estado, Asignado a, Sede, Área, Proveedor, Tipo de costo, Costo de compra, Costo de alquiler mensual, Observaciones) y luego se sube el archivo diligenciado."
          }
      ]
  },
  "certificacion_devoluciones": {
      "titulo": "Certificación de Devolución de Activos",
      "descripcion": "Permite confirmar que un colaborador efectivamente devolvió un equipo del Inventario antes de que se pueda dar de baja su cuenta. Accesible para admin, agente y también para el rol acotado 'Gestión Humana' (que no tiene el resto de permisos de Soporte TI, solo esta certificación).",
      "pasos": [
          "En 'Pendientes de devolución' busca al colaborador o el activo con el buscador ('Buscar por colaborador, cédula o activo...').",
          "Marca qué accesorios entregados sí regresaron (vienen premarcados; desmarca solo los que no volvieron) y, si aplica, escribe el detalle del accesorio 'Otro'.",
          "Agrega observaciones si es necesario y, si el equipo es biomédico entregado a domicilio, registra el nombre y la firma del familiar/cuidador responsable (dibujada o subida como imagen).",
          "Marca la casilla 'Generar acta (PDF)' si necesitas que quede un acta descargable de la devolución.",
          "Pulsa 'Confirmar devolución'; el sistema pide confirmación antes de registrar el cambio.",
          "Consulta el historial en 'Certificados de devolución' y descarga el acta en PDF de cada registro (columna 'Acta'), o pulsa 'Exportar a CSV' para bajar todo el historial."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede certificar una devolución?",
              "a": "Usuarios con rol admin, agente o gestión humana. Este último rol es exclusivo para esta certificación y no da acceso al resto de Soporte TI (Tickets, Bóveda de Accesos, Papelera, Auditoría, etc.)."
          },
          {
              "q": "¿Qué pasa si el activo figura como 'Asignado' pero sin colaborador definido ('Sin asignar')?",
              "a": "No se puede certificar la devolución en ese estado: el sistema pide primero ir a Inventario, editar el activo y definir a quién estaba asignado (o cambiarlo a 'Disponible' si en realidad no está asignado a nadie)."
          },
          {
              "q": "¿El colaborador recibe algo por correo al certificar su devolución?",
              "a": "Sí, se le envía automáticamente el certificado de devolución en PDF por correo, independientemente de si se marcó la casilla 'Generar acta' (esa casilla solo controla si el acta queda disponible para descarga bajo demanda en el historial)."
          },
          {
              "q": "¿En qué estado queda el activo después de certificar la devolución?",
              "a": "Pasa a estado 'Devolución' (bloqueado) y no vuelve a 'Disponible' automáticamente; un administrador o agente debe revisarlo desde Inventario y decidir su siguiente estado."
          }
      ]
  },
  "vencimientos": {
      "titulo": "Vencimiento de Documentos",
      "descripcion": "Panel consolidado, solo para admin/agente, que reúne en una sola vista los instructivos institucionales y los documentos de empleado (cédula, contrato, etc.) que tienen fecha de vencimiento, clasificándolos como vigente, próximo a vencer o vencido.",
      "pasos": [
          "Revisa las tarjetas de resumen 'Documentos vencidos' y 'Próximos a vencer (30 días)' para un vistazo rápido.",
          "Filtra por 'Origen' (Instructivos institucionales o Documentos de empleado) y por 'Estado' (Vencido, Próximo a vencer, Vigente) usando los desplegables de la barra de filtros.",
          "Revisa la tabla con Origen, Documento, Detalle, fecha de Vencimiento y Estado de cada elemento.",
          "Pulsa el ícono 'Ir al módulo' en la fila de un documento para abrir la pantalla donde se administra (Instructivos o Gestión de Usuarios) y renovarlo o corregir su fecha.",
          "Usa los accesos directos 'Instructivos' y 'Usuarios' en la parte superior para ir directamente a esos módulos."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver este panel?",
              "a": "Solo usuarios con rol admin o agente."
          },
          {
              "q": "¿Desde aquí puedo renovar o cambiar la fecha de vencimiento de un documento?",
              "a": "No directamente: este panel es de solo consulta y filtrado. El ícono 'Ir al módulo' de cada fila lleva a Instructivos (documentos institucionales) o a Gestión de Usuarios (documentos de empleado), que es donde se edita el documento y su fecha."
          },
          {
              "q": "¿Qué significa 'Próximo a vencer'?",
              "a": "El documento aún no ha vencido pero está dentro del umbral de días definido por el sistema (mostrado en pantalla como 'Próximos a vencer (30 días)'); al superarlo pasa a 'Vencido'."
          },
          {
              "q": "¿Se avisa a alguien cuando un documento cambia de estado?",
              "a": "Sí, el sistema revisa automáticamente los vencimientos al visitar este panel (o el listado de Instructivos) y notifica por campanita y correo la primera vez que un documento entra en 'Próximo a vencer' o escala a 'Vencido'."
          }
      ]
  },
  "tickets": {
      "titulo": "Solicitudes de Soporte TI",
      "descripcion": "Es la lista de solicitudes (incidentes y requerimientos) del módulo de Soporte TI. Un usuario con rol 'estándar' solo ve las solicitudes que él mismo creó (el título de la página dice 'Mis Solicitudes de Soporte'), mientras que un 'agente' o 'admin' del equipo de soporte ve todas las solicitudes de todos los usuarios ('Soporte TI — Todas las Solicitudes') y además puede filtrar por más criterios y ver quién creó y quién tiene asignado cada caso.",
      "pasos": [
          "Haz clic en \"Nueva Solicitud\" para abrir el formulario y crear un caso (elige Incidente o Requerimiento, escribe un título y una descripción, y opcionalmente categoría, prioridad, área, sede, un activo del inventario relacionado, un ticket relacionado ya cerrado y adjuntos).",
          "Usa las pestañas superiores (Activos, Vigentes, Próximos a vencer, Vencidos, Cerrados / historial) para filtrar por el cumplimiento del SLA.",
          "Usa la barra de filtros (Tipo, Estado, Prioridad, Categoría, Área, Sede, Buscar) para acotar la lista; el campo Buscar encuentra por título, descripción, o nombre/cédula/usuario del solicitante o del agente asignado.",
          "Haz clic en cualquier fila de la tabla para abrir el detalle de esa solicitud.",
          "Si el equipo de soporte configuró plantillas, puedes elegir una en \"Usar una plantilla\" dentro del formulario de Nueva Solicitud para prellenar los campos.",
          "Si está disponible la IA de clasificación, puedes usar el botón \"Clasificar con IA\" dentro del formulario para que sugiera Tipo, Categoría y Prioridad a partir de lo que ya escribiste."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver una solicitud que yo creé?",
              "a": "Solo tú (quien la creó) y cualquier cuenta con rol agente o admin (equipo de soporte TI). Otros usuarios estándar no pueden verla."
          },
          {
              "q": "¿Por qué no veo las solicitudes de mis compañeros?",
              "a": "Porque tu rol es 'estándar': esta vista solo te muestra las solicitudes que tú mismo creaste. Solo agentes y administradores ven todas las solicitudes de la organización."
          },
          {
              "q": "¿Puedo adjuntar archivos al crear una solicitud?",
              "a": "Sí, en el campo 'Evidencias' del formulario de Nueva Solicitud puedes adjuntar imágenes, PDFs, documentos ofimáticos, comprimidos o videos (máximo 5 archivos)."
          },
          {
              "q": "¿Qué significan las pestañas Vigentes, Próximos a vencer y Vencidos?",
              "a": "Reflejan el cumplimiento del SLA de resolución de cada solicitud abierta: 'Vigentes' tiene margen de tiempo, 'Próximos a vencer' está por agotarse y 'Vencidos' ya pasó la fecha límite de solución. 'Cerrados / historial' agrupa las ya Resueltas, Cerradas o Canceladas."
          }
      ]
  },
  "tickets_inicio": {
      "titulo": "Inicio de Soporte TI",
      "descripcion": "Es la página de aterrizaje propia del módulo Solicitudes TI (distinta de la Bienvenida general de Arkiv): muestra un resumen rápido de números y las solicitudes más recientes. El contenido cambia según el rol: un agente/admin ve 'Asignados a mí (abiertos)', 'Sin asignar' y 'Resueltos por mí' (y, si es admin, cuántas solicitudes están escaladas por SLA vencido); un usuario estándar ve 'Mis abiertos', 'Resueltos' y 'Total' de sus propias solicitudes.",
      "pasos": [
          "Haz clic en \"Crear una nueva solicitud\" para abrir directamente el formulario de Nueva Solicitud (te lleva a /tickets con el modal ya abierto).",
          "Haz clic en cualquiera de las tarjetas de resumen (por ejemplo 'Sin asignar' o 'Asignados a mí') para ir a la lista de solicitudes filtrada según ese número.",
          "Si eres administrador y hay solicitudes escaladas por SLA vencido, haz clic en el aviso rojo para revisarlas directamente.",
          "Revisa la sección \"Tickets recientes\" (o \"Mis solicitudes recientes\") para ver los últimos 5 casos, o haz clic en \"Ver todas\" para ir a la lista completa."
      ],
      "preguntas": [
          {
              "q": "¿Qué es 'Escalados' que veo en esta pantalla?",
              "a": "Solo lo ve el rol admin: cuenta las solicitudes asignadas a un agente que ya superaron su fecha límite de SLA de resolución sin resolverse, es decir, casos que ya requieren intervención de un supervisor."
          },
          {
              "q": "¿Por qué mi resumen se ve distinto al de un compañero de soporte TI?",
              "a": "Porque el resumen depende del rol: los agentes y administradores ven indicadores operativos del equipo (asignados, sin asignar, resueltos), mientras que un usuario estándar solo ve el estado de sus propias solicitudes."
          },
          {
              "q": "¿Desde aquí puedo ver el detalle de una solicitud?",
              "a": "Sí, haciendo clic en cualquier fila de 'Tickets recientes' vas directo al detalle de esa solicitud."
          }
      ]
  },
  "ticket_detalle": {
      "titulo": "Detalle de la Solicitud",
      "descripcion": "Muestra toda la información de una solicitud individual: datos del solicitante, estado del SLA, calificación de satisfacción (una vez resuelta/cerrada) y el hilo de Seguimiento (comentarios y adjuntos). El panel 'Gestionar Solicitud' y la sección de Tareas internas solo se muestran a agentes/admin; un usuario estándar solo ve la información del caso, puede comentar (mientras el ticket no esté Cerrado/Cancelado) y, si es el beneficiario del caso, calificar el servicio una vez resuelto o cerrado. Solo puede ver el detalle quien creó la solicitud o una cuenta con rol agente/admin.",
      "pasos": [
          "Usa el editor de \"Seguimiento\" al final de la página y el botón \"Enviar\" para agregar un comentario (puedes adjuntar archivos); si eres agente/admin puedes marcar la casilla \"Nota interna (solo la ve el equipo de soporte)\" para que el solicitante no la vea.",
          "Si eres agente/admin, usa el panel \"Gestionar Solicitud\" para cambiar Estado, Prioridad y \"Asignar a\", y pulsa \"Guardar\".",
          "Si el caso está \"Sin asignar\", haz clic en \"Tomar este caso\" para asignártelo con un solo clic.",
          "Haz clic en \"Duplicar\" para abrir el formulario de Nueva Solicitud prellenado con los datos de este ticket, como caso nuevo e independiente.",
          "Si eres agente/admin y aparece el botón \"WhatsApp\", haz clic para abrir WhatsApp Web/Desktop con un mensaje ya redactado para el solicitante (Arkiv no lo envía por ti).",
          "Si eres agente/admin y el ticket tiene modificaciones de SLA disponibles, haz clic en \"Modificar fecha\" para correr la fecha límite de solución indicando una categoría de motivo y el detalle.",
          "Si el ticket ya está Resuelto o Cerrado y tú eres el beneficiario de la solicitud, califica el servicio con las estrellas y pulsa \"Enviar\" (solo se puede calificar una vez)."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver el detalle de mi solicitud?",
              "a": "Solo tú (quien la creó) y cualquier cuenta con rol agente o admin."
          },
          {
              "q": "¿Cómo cambio el estado de un ticket?",
              "a": "Solo agentes/admin pueden hacerlo, desde el panel 'Gestionar Solicitud'. El sistema no permite saltar directo a 'Resuelto' sin pasar antes por 'En Proceso', ni a 'Cerrado' sin pasar antes por 'Resuelto'; una vez 'Cerrado' el estado queda bloqueado. Tampoco se puede pasar a Resuelto/Cerrado si el ticket todavía tiene tareas internas sin completar o cancelar."
          },
          {
              "q": "¿Puedo adjuntar archivos en un comentario?",
              "a": "Sí, junto al editor de Seguimiento hay un campo para adjuntar archivos (imágenes, documentos, comprimidos, videos)."
          },
          {
              "q": "¿Quién puede calificar el servicio?",
              "a": "El beneficiario real de la solicitud: normalmente quien la creó, salvo que un agente la haya subido a nombre de otra persona, en cuyo caso es esa persona quien califica. Solo se puede calificar una vez, y únicamente cuando el ticket ya está Resuelto o Cerrado."
          },
          {
              "q": "¿Qué es una 'Nota interna'?",
              "a": "Un comentario que solo ve el equipo de soporte (agentes/admin), no el solicitante. Solo agentes/admin pueden marcarla al comentar."
          }
      ]
  },
  "mis_tareas": {
      "titulo": "Mis Tareas",
      "descripcion": "Es la cola de trabajo personal del agente: reúne todas las subtareas internas que le asignaron dentro de cualquier ticket de Soporte TI, sin tener que entrar caso por caso. Es exclusiva del equipo de soporte (roles agente/admin); un usuario estándar no tiene acceso a esta página ni ve las tareas internas de un ticket.",
      "pasos": [
          "Por defecto la página muestra solo las tareas activas (pendiente/en progreso); haz clic en \"Ver completadas y canceladas\" para ver también las que ya terminaron (o \"Ver solo activas\" para volver).",
          "Haz clic en el código del ticket (por ejemplo su código) para ir al detalle completo de esa solicitud.",
          "Escribe una nota o avance en el campo de texto de cada tarea y pulsa el ícono de enviar para agregarla al historial de Seguimiento de esa tarea.",
          "Cambia el estado de una tarea (Pendiente, En progreso, Completada, Cancelada) desde el desplegable de estado; no se puede pasar a Completada o Cancelada sin haber pasado antes por 'En progreso', y una vez Completada/Cancelada queda bloqueada.",
          "Haz clic en el ícono de lápiz para editar el asunto, el responsable o la fecha límite de la tarea sin cambiar su estado."
      ],
      "preguntas": [
          {
              "q": "¿Quién puede ver esta página?",
              "a": "Solo agentes y administradores; un usuario con rol estándar no tiene acceso a 'Mis Tareas' ni a las tareas internas de un ticket."
          },
          {
              "q": "¿Qué tareas aparecen aquí?",
              "a": "Todas las tareas asignadas a ti (como responsable) en cualquier ticket, sin importar en qué caso estén."
          },
          {
              "q": "¿Puedo marcar una tarea como completada directamente?",
              "a": "No si sigue en 'pendiente': primero debe pasar por 'En progreso' antes de poder marcarse como 'Completada' o 'Cancelada'."
          },
          {
              "q": "¿Editar una tarea desde aquí me saca de esta página?",
              "a": "No, tanto agregar una nota como cambiar el estado o editar una tarea desde 'Mis Tareas' te devuelve a esta misma vista en vez de llevarte al detalle del ticket."
          }
      ]
  }
};

function abrirAyudaModulo(clave) {
    var datos = AYUDA_MODULOS[clave];
    var modal = document.getElementById('modal-ayuda-modulo');
    var tituloEl = document.getElementById('ayuda-modulo-titulo');
    var contenidoEl = document.getElementById('ayuda-modulo-contenido');
    if (!modal || !tituloEl || !contenidoEl) return;

    if (!datos) {
        tituloEl.textContent = 'Ayuda no disponible';
        contenidoEl.innerHTML = '<p class="text-slate-400">Todavía no hay contenido de ayuda para este módulo.</p>';
        modal.classList.remove('hidden');
        return;
    }

    tituloEl.textContent = datos.titulo;

    var html = '<p class="text-slate-300 leading-relaxed">' + _escapeHtmlAyuda(datos.descripcion) + '</p>';

    if (datos.pasos && datos.pasos.length) {
        html += '<div class="mt-4"><h3 class="text-[11px] font-bold text-emerald-400 uppercase tracking-wider mb-2"><i class="fa-solid fa-list-ol mr-1.5"></i>Cómo hacerlo</h3><ol class="list-decimal list-inside space-y-1.5 text-slate-300">';
        datos.pasos.forEach(function (paso) {
            html += '<li>' + _escapeHtmlAyuda(paso) + '</li>';
        });
        html += '</ol></div>';
    }

    if (datos.preguntas && datos.preguntas.length) {
        html += '<div class="mt-4"><h3 class="text-[11px] font-bold text-sky-400 uppercase tracking-wider mb-2"><i class="fa-solid fa-circle-question mr-1.5"></i>Preguntas frecuentes</h3><div class="space-y-3">';
        datos.preguntas.forEach(function (item) {
            html += '<div><p class="font-semibold text-slate-200">' + _escapeHtmlAyuda(item.q) + '</p><p class="text-slate-400 mt-0.5">' + _escapeHtmlAyuda(item.a) + '</p></div>';
        });
        html += '</div></div>';
    }

    contenidoEl.innerHTML = html;
    modal.classList.remove('hidden');
}

function cerrarAyudaModulo() {
    var modal = document.getElementById('modal-ayuda-modulo');
    if (!modal) return;
    modal.classList.add('hidden');
}

function _escapeHtmlAyuda(texto) {
    var div = document.createElement('div');
    div.textContent = texto || '';
    return div.innerHTML;
}
