# Subagente "seguimiento" (Fase 3c) del orquestador gestion-causas-orquestador

Fase 5+6 (fusionadas) del proyecto "Gestión automática de causas nuevas desde la casilla
del trabajo" — ver el diseño completo en
`Actualizador de informes\docs\2026-08-19-seguimiento-sin-respuesta-design.md` y el plan
maestro en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`. Este
archivo reemplaza a las dos tareas sueltas `gestion-causas-sin-respuesta` y
`gestion-causas-documentos-pendientes`, que quedaron huérfanas del planificador (no
estaban registradas como tarea programada) y por eso dejaron de correr desde el
2026-08-24. **Nunca** envía correos ni borra nada — solo deja borradores para que Nico
los revise y envíe a mano.

Este archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "seguimiento" de cada corrida, después de "smu" y **en paralelo con
"goteo" y "agenda"**: las tres fases escriben campos/registros distintos y no dependen una
de la otra dentro de la misma corrida (`seguimiento` escribe en `registro_pedidos.json` y
`registro_seguimiento.json`, archivos que ni `goteo` ni `agenda` tocan). Solo se despacha
en la **corrida de la mañana** — ver el paso 2 del orquestador — porque sus umbrales son
en días hábiles y la cadencia no adelanta sola: correrla 3 veces al día no adelanta
ningún aviso.

**Diferencia de fondo con las dos tareas viejas: esto ya NO busca, recuerda.** Las
versiones anteriores salían a buscar en Gmail qué podía estar sin respuesta (por texto,
"Estimada Daniela" newer_than:30d, o abriendo el hilo de cada una de las ~27 causas
activas). Ahora el sistema **anota cuándo se pidió algo** — en `registro_pedidos.json`,
alimentado automáticamente cuando un borrador de documentos desaparece de Gmail (Nico lo
envió) o cuando Nico etiqueta a mano un correo con `Esperando-Respuesta` — y esta fase se
limita a recorrer esa lista, abriendo un hilo solo cuando de verdad puede haber novedad.

Toda la parte mecánica se hace con el CLI `gestion_causas.cli`, corrido con
Bash/PowerShell desde `Actualizador de informes` como directorio de trabajo:
`python -m gestion_causas.cli <subcomando> ...` — cada llamada imprime JSON a stdout.

## 0. Contexto de la corrida

El orquestador ya resolvió, antes de despacharte, lo que las fases comparten. Leelo con
Read una sola vez, al empezar:
`Actualizador de informes\gestion_causas\_contexto_corrida.json`

De ahí sacás:
- `fecha_hoy` (AAAA-MM-DD) — usá **esa** fecha en todo este archivo y no vuelvas a
  calcularla.
- `mapa_hilos.ruta` — el barrido combinado de Gmail para toda la corrida (mapa RIT →
  hilos con novedades, ya con los reportes/consolidados internos descartados). Se usa en
  el paso 3b para el cruce por RIT sin tener que volver a golpear Gmail. Si en cambio trae
  `mapa_hilos.error`, no hay mapa — el paso 3b tiene su propio fallback en vivo.
- `tokens` — el estado de los 3 tokens, ya verificado **sin** abrir ningún login
  interactivo. Si el orquestador te despachó, es porque el token de Gmail de trabajo está
  OK; no hace falta que lo vuelvas a diagnosticar.

Si el archivo no existe (típicamente porque estás corriendo esta fase suelta a mano, fuera
del orquestador), seguí igual: calculá la fecha de hoy vos mismo y corré
`python -m gestion_causas.cli diagnostico` para confirmar que el token responde como
nmunoz@gomezyriesco.cl. Si algún comando del CLI se queda esperando un login interactivo,
detente de inmediato, no reintentes, y deja como resumen "La tarea no pudo autenticarse
contra nmunoz@gomezyriesco.cl — falta autorizar el token de forma interactiva."

## 1. Da de alta los pedidos nuevos de esta corrida

Dos fuentes, ambas obligatorias en cada corrida — cada una es una sola llamada al CLI, no
un barrido por causa:

a. **Borradores de documentos que Nico ya envió** (Fase 2 de `smu` los deja con
   `borrador_documentos_draft_id`; cuando ese borrador desaparece de Gmail es porque se
   envió, no porque se borró — el comando ya distingue los dos casos):
   ```
   python -m gestion_causas.cli verificar-borradores-pendientes
   ```
   Devuelve `pendientes` (borradores que siguen sin enviar — anótalos para el resumen
   final, punto 5), `enviados` (el comando ya los dio de alta como pedido nuevo en
   `registro_pedidos.json`, no hace falta hacer nada más) y `descartados` (borrador
   borrado sin enviar, nada que seguir).

b. **Pedidos y propuestas que Nico mandó a mano**, marcados con la etiqueta de Gmail
   `Esperando-Respuesta` (Nico se la pone él mismo al correo que envía):
   ```
   python -m gestion_causas.cli pedidos-desde-etiqueta
   ```
   Da de alta en `registro_pedidos.json` los hilos etiquetados que todavía no estaban
   registrados (`creados`), clasificando automáticamente `tipo` (`documentos` si el
   cuerpo trae una lista numerada, si no `acuerdo`) y tomando el destinatario del último
   mensaje propio del hilo. Los que ya estaban (`ya_registrados`) no se tocan. Si
   `creados` trae algún pedido con `rit: null` (no se pudo extraer el RIT del asunto ni
   del cuerpo), anótalo en el resumen final para que Nico lo revise — igual se sigue,
   solo que no vas a poder hacer el cruce por RIT del paso 3b para ese pedido.

## 2. Trae los pedidos abiertos

```
python -m gestion_causas.cli pedidos-abiertos
```
Devuelve todos los pedidos en estado `esperando`, `parcial` o `gestion_manual` (los
`completo` y `pendiente_envio` no se revisan), excluyendo los que correspondan a un RIT con
`causa_cerrada: true` en `registro_causas.json` — no hace falta revisar a mano si una causa
en la lista ya está cerrada, el comando ya la filtra. Si la lista viene vacía, termina con un
resumen de "sin pedidos abiertos para revisar".

## 3. Por cada pedido abierto

a. **Trae el hilo original**, tal cual está ahora:
   ```
   python -m gestion_causas.cli leer-hilo --thread-id <thread_id del pedido>
   ```
   Mira los mensajes con fecha **posterior** a `fecha_envio` del pedido — esos son la
   posible respuesta.

b. **Cruce por RIT, si el pedido tiene uno** (si `rit` es null, saltea este paso: no hay
   forma de cruzar). Gmail agrupa visualmente por asunto, pero el sistema de correo de la
   empresa contraria a veces no encadena por los headers reales — la respuesta puede
   llegar en un hilo que parece "separado" aunque el pedido esté en otro (confirmado por
   Nico en Tiznado/Salcobrand M-744-2026).

   Si tenés `mapa_hilos.ruta` (paso 0), este cruce sale gratis: buscá el `rit` del pedido
   en `rit_a_hilos` del mapa — ya trae los hilos con novedades para ese RIT en esta
   corrida, con los reportes/consolidados internos ya descartados, y sus mensajes ya
   leídos en `hilos[thread_id]` (no vuelvas a llamar `leer-hilo` para esos). Quédate con
   los `thread_id` **distintos** al del pedido que tengan actividad posterior a
   `fecha_envio`.

   Si no hay mapa (`mapa_hilos.error`, o estás corriendo esta fase suelta), hacé el
   fallback en vivo:
   ```
   python -m gestion_causas.cli buscar-hilos --query "<rit>"
   ```
   De los resultados, revisa (con `leer-hilo` si hace falta) los hilos **distintos** al
   `thread_id` original con actividad posterior a `fecha_envio` que claramente
   correspondan a esta causa — usa el mismo criterio de descarte que `goteo`: ignora
   "Provisiones demanda laborales...", "Informe de provisión..." / "INFORME PROVISIÓN...",
   "Risgo"/"Riesgo causas estado sentencias" y cualquier reporte consolidado que solo
   mencione el RIT de pasada (ver `subagentes/goteo.md` para el detalle completo de estos
   patrones y cómo quitar primero los prefijos RE:/RV:/FWD:/FW: del asunto antes de
   compararlo).

c. **Descarte de acuses de recibo**: antes de tratar cualquier mensaje posterior como
   "respuesta real", revisa si es un acuse de recibo/cierre corto ("Acuso recibo",
   "Muchas gracias", "Lo tenemos presente", "Saludos cordiales" sin ningún documento ni
   pedido explícito adjunto) — eso no cuenta como respuesta al pedido, es solo cortesía.

d. **Clasifica el pedido**, según `tipo`:

   - **`documentos`**: compara los mensajes posteriores (adjuntos + texto explícito) con
     `items_pedidos` del pedido. Un ítem "llegó" si hay un adjunto o una respuesta
     explícita que lo cubre — no cuentes acuses de recibo. Tres ramas:
     - **Todo entregado**: pasa a `completo` (paso 3f). No anotes en bitácora (evita
       ruido), pero sí en el resumen final (cuenta, no detalle).
     - **Ninguna respuesta** y ya pasaron **4 o más días hábiles** desde `fecha_envio`
       (usa `python -m gestion_causas.cli dias-habiles-entre --desde "<fecha_envio>" --hasta "<fecha_hoy>"`):
       candidato a **insistencia** (texto A, paso 3e).
     - **Respuesta parcial** (llegó al menos un ítem, falta alguno — sin importar los
       días hábiles, cualquier parcial detectado es candidato): candidato a
       **recordatorio de faltantes** (texto B, paso 3e).
     - Si no se cumple ninguna de las tres (sin respuesta pero todavía no llegan los 4
       días hábiles): no hagas nada, sigue con el siguiente pedido (se revisará solo en
       una corrida futura).

   - **`acuerdo`**: sin lista de ítems, se sigue solo por "contestó o no contestó". Si hay
     **algún** mensaje posterior de la contraparte (no un acuse de recibo): pasa a
     `completo`. Si no hay ninguno y pasaron **24 horas o más** desde `fecha_envio`:
     candidato a insistencia (texto A). Menos de 24 h: nada, sigue con el siguiente.

e. **Para cada candidato** (insistencia o recordatorio), verifica la cadencia — usa el
   `thread_id` del pedido como clave, igual que siempre:
   ```
   python -m gestion_causas.cli puede-insistir --thread-id <thread_id>
   ```
   - `puede` false con motivo "no tiene audiencia agendada" → no crear borrador; el
     pedido pasa a `gestion_manual` (paso 3f) y se destaca en el resumen final (punto 5)
     — es lo más importante de todo el resumen.
   - `puede` false por no cumplirse aún el umbral de días hábiles desde el último aviso
     (ya sea el 2do aviso o uno posterior, cuyo umbral cambia solo según cuán cerca esté
     la audiencia) → saltar este pedido en esta corrida, sin mencionarlo en el resumen.
   - `puede` true → continúa. Ya no hay tope de avisos: mientras la causa tenga
     `fecha_audiencia` registrada, la cadencia se ajusta sola (más espaciada si falta
     mucho para la audiencia, diaria si está encima) en vez de detenerse a los 2 avisos.

   Arma los destinatarios: **Para** = `destinatario` del pedido (o, si viene vacío, el
   `to` del último mensaje propio del hilo); **CC** = el resto de los participantes del
   hilo, sin incluir a Nico.

   Escribe el cuerpo a un archivo temporal:

   **Texto A — insistencia (ninguna respuesta):**
   ```
   Estimado/a [Nombre]:

   Junto con saludar, ruego tener presente [los documentos solicitados|el correo anterior].

   Atentamente,
   ```
   ("los documentos solicitados" para `tipo: documentos`, "el correo anterior" para
   `tipo: acuerdo`). Créalo sin `--lista-archivo`:
   ```
   python -m gestion_causas.cli crear-borrador --destinatario "<para>" --cc "<cc separado por coma>" --asunto "Re: <asunto original>" --cuerpo-archivo "<ruta.txt>" --thread-id <thread_id>
   ```

   **Texto B — recordatorio de faltantes (solo `documentos`, respuesta parcial):**
   ```
   Estimado/a [Nombre]:

   Junto con saludar, ruego tener presente que se encuentran pendiente los siguientes documentos:

   [[LISTA]]

   Atentamente,
   ```
   Escribe además un segundo archivo temporal con **solo los ítems pendientes**, uno por
   línea. Créalo así:
   ```
   python -m gestion_causas.cli crear-borrador --destinatario "<para>" --cc "<cc separado por coma>" --asunto "Re: <asunto original>" --cuerpo-archivo "<ruta cuerpo.txt>" --lista-archivo "<ruta faltantes.txt>" --thread-id <thread_id>
   ```

   En ambos casos el comando ya evita duplicar si la cadena tiene otro borrador sin enviar
   — revisa `creado` en la respuesta.

   Si `creado` es true, registra el aviso (para que la cadencia funcione en la próxima
   corrida):
   ```
   python -m gestion_causas.cli registrar-aviso --thread-id <thread_id> --tipo <acuerdo-daniela|causa-laboral|documentos> --rit "<rit si se detectó>" --draft-id <draft_id>
   ```
   (usa `acuerdo-daniela` si el pedido es de tipo `acuerdo` y el destinatario es
   `dsanchezv@smu.cl`; `causa-laboral` para cualquier otro `acuerdo`; `documentos` para
   `tipo: documentos` — son solo informativos, no cambian la cadencia).

f. **Actualiza el pedido** según lo que pasó en este paso:
   - Todo entregado o hubo respuesta de acuerdo → cierra el pedido (esto además le quita
     la etiqueta `Esperando-Respuesta` en Gmail si el pedido vino por esa vía):
     ```
     python -m gestion_causas.cli cerrar-pedido --thread-id <thread_id> --estado completo
     ```
   - `puede-insistir` reportó "no tiene audiencia agendada" (paso 3e) → márcalo `gestion_manual`:
     ```
     python -m gestion_causas.cli cerrar-pedido --thread-id <thread_id> --estado gestion_manual
     ```
   - Respuesta parcial (quedó con recordatorio o esperando el próximo umbral) → actualiza
     `items_recibidos` y el estado:
     ```
     python -m gestion_causas.cli registrar-pedido --thread-id <thread_id> --estado parcial --items-json "<ruta json con la lista de items YA recibidos>"
     ```
   - Sin novedades (nada de lo anterior aplicó) → igual toca el pedido para dejar
     constancia de que se revisó esta corrida:
     ```
     python -m gestion_causas.cli registrar-pedido --thread-id <thread_id>
     ```
     (sin más campos que el `--thread-id`, el comando solo actualiza `ultima_revision`).

g. **Anota en la bitácora** cualquier cambio de estado real (insistencia creada, pedido
   completado, pedido a gestión manual) — no anotes las corridas sin novedades, para no
   generar ruido:
   ```
   python -m gestion_causas.cli bitacora --rit "<rit si se detectó>" --mensaje "Seguimiento: <qué pasó>"
   ```

## 4. Bootstrap del registro de pedidos (solo la primera vez que corre esta fase)

Antes de la **primera** corrida de esta fase (o si `registro_pedidos.json` todavía no
existe), corre una vez:
```
python -m gestion_causas.cli migrar-pedidos-bootstrap
```
Siembra el registro con el backlog de `registro_seguimiento.json` (13 hilos con avisos
vivos al momento de este rediseño) y de las causas con borrador de documentos vigente. El
comando es idempotente (no duplica si ya se corrió) — si en una corrida futura no estás
seguro de si ya se sembró, corrélo igual, no hace daño.

## 5. Resumen final

Tu **último mensaje** de esta ejecución debe ser **un único objeto JSON**, sin texto antes
ni después y sin envolverlo en \`\`\` — el orquestador lo copia tal cual a la sección "Fase
seguimiento" del panel de estado. Formato:

```json
{
  "fase": "seguimiento",
  "titular": "<una frase: ej. \"2 insistencias creadas, 1 pedido requiere gestión manual\">",
  "metricas": [
    {"etiqueta": "Pedidos nuevos dados de alta", "valor": N},
    {"etiqueta": "Pedidos abiertos revisados", "valor": N},
    {"etiqueta": "Completados", "valor": N},
    {"etiqueta": "Insistencias creadas", "valor": N},
    {"etiqueta": "Recordatorios de faltantes creados", "valor": N}
  ],
  "items": [
    {"rit": "<rit>", "titulo": "<destinatario>",
     "detalle": "<1er/2do aviso de insistencia, o recordatorio de faltantes: qué faltaba>"}
  ],
  "acciones": [],
  "notas": []
}
```

- `items`: una entrada por cada pedido en el que creaste un borrador (insistencia o
  recordatorio) en esta corrida.
- `acciones`: los pedidos que pasaron a `gestion_manual` en esta corrida (causa sin
  audiencia agendada) van **acá**, son lo más importante de todo el resumen: `{"rit":
  "<rit o null>", "que": "Causa sin audiencia agendada, sin respuesta (<tipo>) —
  requiere gestión manual", "urgencia": "alta"}`. Los borradores de documentos todavía
  sin enviar (paso 1a, `pendientes`) **no** van acá — el orquestador ya los junta por su
  cuenta en el paso 4, no los dupliques.
- `notas`: pedidos dados de alta sin RIT detectado (paso 1b), u otras observaciones de
  criterio.
- Si no hubo novedades en ningún bloque, `titular` puede ser "Sin novedades" con las
  listas vacías.
