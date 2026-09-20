# WhatsApp para avisos de turno (Cuadro de Turnos)

Qué es esto: cuando se publica una semana en el Cuadro de Turnos (`/turnos/cuadro`), Arkiv le
avisa a cada colaborador su turno por dos canales: correo (ya funciona, usa el mismo webhook de
Apps Script del resto de la app) y **WhatsApp**. El código de WhatsApp ya está completo y
integrado — ver `_enviar_whatsapp_turno`/`notificar_turno` en `app.py` — pero se queda inactivo
hasta que se configuren las credenciales de una cuenta de **WhatsApp Cloud API (Meta)**. Mientras
tanto, cada intento de envío por WhatsApp queda registrado como `error` (con el motivo "WhatsApp
no está configurado todavía") en la bitácora de notificaciones, sin afectar el correo ni la
asignación del turno.

Esta guía es para quien tenga acceso a Facebook Business Manager y a la cuenta de Render
(Tomás, o quien administre esas cuentas) — Claude no puede crear la cuenta de Meta ni cargar los
secrets por ustedes, porque eso implica una verificación de identidad/negocio y credenciales que
solo el dueño de la cuenta debe manejar.

## 1. Crear la app de Meta y activar WhatsApp Cloud API

1. Entrar a https://developers.facebook.com/ con la cuenta de Facebook de Preventiva Salud IPS
   (o crear una si no existe) y hacer clic en **"Mis apps" → "Crear app"**.
2. Elegir el tipo de app **"Negocios"** (Business), asociarla a un Business Manager de Preventiva
   (o crear uno nuevo en el mismo paso).
3. Dentro del panel de la app, en "Agregar productos", buscar **WhatsApp** y hacer clic en
   **"Configurar"**. Esto crea automáticamente un número de prueba de WhatsApp gratuito, útil para
   probar antes de usar el número real de la IPS.
4. En **WhatsApp → Configuración de la API**, se ve el **número de teléfono de prueba** con su
   `Phone number ID` y un **token de acceso temporal** (dura 24 horas) — sirve para probar el
   paso 4 de esta guía, pero para producción se necesita un token permanente (paso 2).

## 2. Conseguir un token permanente y el número de teléfono real

1. En el Business Manager, ir a **"Configuración del negocio" → "Usuarios del sistema"** y crear
   un usuario de sistema (por ejemplo `arkiv-notificaciones`) con rol **Administrador**.
2. Asignarle la app de WhatsApp creada en el paso 1, con permiso de administrar la app.
3. Generar un **token de acceso del usuario de sistema**, marcando el permiso
   `whatsapp_business_messaging` (y `whatsapp_business_management` si se va a administrar el
   número desde ahí). A diferencia del token temporal del paso 1, este **no expira** mientras el
   usuario de sistema exista — es el que se guarda en Render (`WHATSAPP_CLOUD_API_TOKEN`).
4. Para usar el número de WhatsApp real de la IPS (en vez del número de prueba): en
   **WhatsApp → Configuración de la API → Agregar número de teléfono**, seguir el asistente de
   Meta para verificar el número por SMS o llamada. El número de prueba deja de servir para
   colaboradores reales (Meta no permite enviarles mensajes a números ajenos al equipo de
   desarrollo), así que este paso es obligatorio antes de anunciar el módulo al personal.
5. Anotar el **`Phone number ID`** del número ya verificado (no el número telefónico en sí, sino
   el ID que Meta le asigna) → `WHATSAPP_CLOUD_API_PHONE_ID`.

## 3. Plantilla de mensaje (si Meta la exige)

Meta exige una **plantilla aprobada** para el PRIMER mensaje de una conversación cuando han
pasado más de 24 horas desde el último mensaje del colaborador a ese número (política de
"ventana de 24 horas" de WhatsApp Business). El aviso de turno de Arkiv se envía como mensaje de
texto libre (`_mensaje_turno_texto`), que solo se entrega sin plantilla si el colaborador ya le
escribió antes a ese número dentro de las últimas 24 horas. Si Meta empieza a rechazar los envíos
por ventana cerrada, la solución es crear una plantilla de utilidad (por ejemplo
"Notificación de turno") en **WhatsApp → Plantillas de mensajes**, esperar su aprobación (suele
tardar minutos a horas) y avisar para adaptar `_enviar_whatsapp_turno` a enviarla como plantilla
en vez de texto libre.

## 4. Agregar las variables de entorno en Render

En el servicio `arkiv-preventivaips` → **Environment**, agregar:

| Variable | Valor |
|---|---|
| `WHATSAPP_CLOUD_API_TOKEN` | El token permanente del usuario de sistema (paso 2.3) |
| `WHATSAPP_CLOUD_API_PHONE_ID` | El `Phone number ID` del número verificado (paso 2.5) |
| `WHATSAPP_CLOUD_API_VERSION` | Opcional; si no se configura, se usa `v20.0` |

Al guardar, Render reinicia el servicio solo. Desde ese momento, `_whatsapp_turno_configurado()`
devuelve `True` y los avisos de turno empiezan a intentarse por WhatsApp de verdad.

## 5. Formato del teléfono del colaborador

Arkiv toma el campo **Teléfono** ya guardado en la cuenta del colaborador (Gestión de Usuarios),
le quita cualquier caracter que no sea dígito, y si no empieza por `57` (Colombia) se lo agrega
automáticamente antes de enviarlo a Meta — así que basta con que el teléfono esté guardado como
un celular colombiano normal (con o sin el `57` adelante, con o sin espacios/guiones); no hace
falta reformatearlo a mano. Un colaborador sin teléfono registrado simplemente queda con su
intento de WhatsApp marcado como `error` ("El colaborador no tiene teléfono registrado"), sin
afectar el aviso por correo.

## 6. Probar que funciona

1. Con las 3 variables ya configuradas en Render, entrar a `/turnos/cuadro` como admin/agente (o
   con el permiso extra "Cuadro de Turnos"), asignar un turno de prueba a una cuenta con tu
   propio teléfono, y pulsar **"Publicar semana"**.
2. Revisar en `logs` (Bitácora de Auditoría) que aparezca "Cuadro de Turnos Publicado", y en la
   tabla `notificaciones_turnos` (o directamente el WhatsApp del celular de prueba) que el canal
   `WHATSAPP` haya quedado en `enviado`. Si quedó en `error`, la columna `error` de esa fila
   explica el motivo exacto (credenciales, plantilla, teléfono, etc.) — son los mismos mensajes
   que devuelve la API de Meta.
3. Si se usó el número de prueba del paso 1, recordar que solo llega a números que el propio
   panel de Meta tenga agregados como "destinatarios de prueba" — con el número real verificado
   (paso 2.4) ese límite desaparece.
