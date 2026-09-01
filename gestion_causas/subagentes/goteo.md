# Subagente "goteo" (Fase 3) del orquestador gestion-causas-orquestador

Fase 3 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "goteo" de cada corrida, siempre después de "smu" (para poder revisar
en el mismo lote las causas recién registradas) y **en paralelo con "agenda"** (desde el
2026-09-01: las dos fases escriben campos distintos del registro y ya no dependen una de la
otra, porque el cache de calendario lo genera el contexto de la corrida y no vos). Depende de que el
subagente "smu" ya haya registrado las causas — este subagente NO descubre causas nuevas,
solo revisa las ya conocidas por si llegaron documentos nuevos en la misma cadena de
correo. **Nunca** envía correos ni borra nada, y no toca el calendario.

Razón de que sea una tarea separada de `gestion-causas-smu`: esa tarea excluye los hilos
ya marcados `Procesado-GestionCausas`, así que nunca volvería a mirarlos — el goteo
necesita justamente lo contrario, revisar hilos ya procesados por si trajeron algo nuevo
después. Por eso esta tarea no busca por query/etiqueta, sino por el RIT de cada causa
(ver paso 2) — no basta con mirar el `thread_id` original que guardó Fase 1, porque los
documentos reales muchas veces llegan en una cadena **distinta**, reenviada ("RV: ...")
por la persona de RR.HH./legal de la empresa, y esa cadena Fase 1 nunca la ve.

**Filtro incremental (2026-08-28, actualizado 2026-08-31 — sin excepción de lunes):**
para no re-escanear correos de causas sin novedades en cada una de las 3 corridas
diarias, el paso 2 usa `goteo_ultima_revision` (fecha `AAAA-MM-DD` guardada en el
registro de cada causa) para acotar la búsqueda a mail nuevo desde la corrida anterior,
**todos los días de la semana por igual** — ya no hay un rescan completo especial los
lunes (se sacó porque duplicaba trabajo sin encontrar nada nuevo: la lógica de "primera
revisión" de abajo ya le da a cada causa su propio escaneo completo la primera vez que
el goteo la mira, y el colchón de 1 día en `fecha_corte` ya cubre el margen de la
búsqueda `after:` de Gmail).

**Búsqueda combinada en vez de una por causa (2026-08-28, misma tarde):** la primera
versión de este filtro seguía haciendo una llamada `buscar-hilos` **por cada causa
activa** (aunque acotada por fecha), así que con 27 causas activas eran 27 búsquedas de
red secuenciales aunque casi todas volvieran vacías — confirmado por Nico el 2026-08-28
tras ver que una corrida sin novedades tardó ~20 minutos igual. Ahora el paso 2 revisa la
bandeja de entrada **una sola vez** (o dos, si hay causas de primera revisión) para toda
la corrida, buscando de una todos los RIT activos a la vez, y solo después separa qué
hilo pertenece a qué causa — ver el paso 2 más abajo.

**Filtro de remitente confiable (2026-08-13, actualizado 2026-08-17):** de todos los
adjuntos que aparezcan en cualquier hilo relacionado con la causa, **solo se guardan los
que vienen de un mensaje enviado desde una dirección que termine en**:
`@unimarc.cl`, `@super10.cl`, `@alvi.cl`, `@sb.cl`, `@mayorista10.cl`, `@smu.cl`,
`@divisionlogistica.cl`
(verificado en real con la causa Iturriaga M-643-2026: el contrato, aviso de término,
finiquito y anexo llegaron de `sorostica@unimarc.cl` en una cadena "RV:" aparte; los
propios envíos de Nico desde `@gomezyriesco.cl` NO son documentos de prueba del cliente y
no deben guardarse en el goteo, son sus propias gestiones, no evidencia. `@mayorista10.cl`
se agregó tras confirmar en Palavecino M-40-2026 y Parra M-537-2025 que el personal de
Super 10/Mayorista 10 —Lorena Gomez Peña, Leslie Rosende Adam, Viviana Segura Catalán,
Maria Macarena Antiquera, entre otros— manda contrato/finiquito/EERR desde ese dominio en
vez de o además de `@super10.cl`. `@smu.cl` se agregó el 2026-08-17 por indicación directa
de Nico: aunque `@smu.cl` es también el origen de la demanda (equipo legal corporativo de
SMU), Nico confirmó que también es confiable para descargar documentos de prueba reales
cuando los manda (visto en M-6-2026, Luis Soto: contrato, finiquito y anexos reales
enviados por `dsanchezv@smu.cl`). `@divisionlogistica.cl` se agregó el 2026-08-17 tras
confirmar en Yañez con SSLL (O-348-2026) que Alexis Cubillos Arellano
(`acubillos@divisionlogistica.cl`) manda la documentación real de RR.HH. de Servicios
Logísticos Santiago (liquidaciones, finiquito, contrato, carta de despido, anexos) desde
ese dominio). Esta lista es la observada hasta ahora para Rendic Hermanos (marca Unimarc),
Super 10/Mayorista 10, Alvi, Salcobrand y Servicios Logísticos Santiago; si aparece un
dominio nuevo y evidentemente correspondiente a RR.HH./legal de alguna de las 6 empresas
(incluyendo Preunic, que todavía no tiene dominio confirmado), anótalo en el resumen final
para que Nico decida si agregarlo a la lista — no lo agregues tú mismo silenciosamente.

**Filtro de asunto — descartar hilos de reporte interno (2026-08-14, actualizado
2026-08-17 y 2026-08-24):** el filtro de dominio de remitente por sí solo NO basta, porque
`@sb.cl` / `@smu.cl` (y en general cualquiera de los dominios confiables) también mandan
hilos de **reporte interno** que mencionan muchos RIT a la vez (ej. una planilla contable
mensual con la provisión de todas las demandas laborales vigentes), no prueba de un caso
puntual — el buscar-hilos por RIT los encuentra igual porque el RIT aparece listado
adentro. Confirmado en la corrida del 2026-08-14: el hilo "Provisiones demanda laborales
[mes] [año]" (enviado por `cqueralto@sb.cl` / `jllanos@sb.cl`, reenviado por
`rgomez@gomezyriesco.cl`) coincidió con la búsqueda de al menos 9 RIT distintos
(Salcobrand y Preunic) y su adjunto "Roman Gomez.xlsx" / "Provisiones [mes].xlsx" se
guardó por error en las 9 carpetas — tuvo que revertirse a mano. La corrida del
2026-08-17 confirmó un segundo patrón del mismo tipo: el hilo "INFORME PROVISIÓN [mes]
[año]" (enviado por `dsanchezv@smu.cl`), visto repetidamente cruzando varias causas de
Rendic Hermanos. Un tercer patrón, el hilo **"Risgo causas estado sentencias" / "Riesgo
causas estado sentencias"** (enviado por `cqueralto@sb.cl`, adjuntos `Roman.xlsx` /
`Roman Gomez.xlsx` / `Informe de riesgo Roman Gomez [fecha].xlsx`), se coló por error en
la carpeta de Obreque con Salcobrand (O-809-2026) **tres veces** (2026-08-18, 2026-08-21 y
2026-08-24) antes de agregarse aquí — Nico confirmó que tampoco debe incluirse en esta
automatización.

**Antes de descartar o quedarte con un hilo (paso 2d):**
1. Toma el `subject` de cada mensaje del hilo y quítale primero cualquier prefijo de
   respuesta/reenvío (`RE:`, `RV:`, `FWD:`/`FW:`, `ENV:`, repetido, insensible a
   mayúsculas) — de lo contrario un asunto como `"RE: INFORME PROVISIÓN ABRIL 2026"` o
   `"Re: Risgo causas estado sentencias"` no calza con el patrón (bug de raíz confirmado el
   2026-08-21).
2. Descarta el hilo completo si el subject resultante (de **cualquiera** de sus mensajes)
   empieza con "Provisiones demanda laborales", "Informe de provisión" / "INFORME
   PROVISIÓN", o "Risgo causas estado sentencias" / "Riesgo causas estado sentencias"
   (sin distinguir mayúsculas/minúsculas), o sea evidentemente un reporte/consolidado
   interno que menciona la causa de pasada en vez de tratarse específicamente de ella
   (mismo criterio de "usa criterio, no proceses todo a ciegas" ya mencionado abajo, pero
   ahora con estos tres patrones conocidos como casos confirmados). Si aparece un patrón
   de asunto nuevo con la misma pinta (reporte consolidado, no documento de un caso
   puntual), anótalo en el resumen final para que Nico lo agregue a esta lista.

**Adjunto a excluir siempre, sin importar el remitente:** `invite.ics` (adjunto estándar
de una invitación/respuesta de Calendar, ej. "Aceptado: Reunión preparatoria...",
"Invitación: Audiencia única..."). No es un reporte pero tampoco es prueba del caso — solo
el evento de calendario. Se coló por error en Cuevas con Alvi (M-393-2026) dos veces
(2026-08-21 y 2026-08-24) antes de agregarse aquí.

Toda la parte mecánica se hace con el CLI `gestion_causas.cli`, corrido con
Bash/PowerShell desde `Actualizador de informes` como directorio de trabajo:
`python -m gestion_causas.cli <subcomando> ...`.

**Regla de ejecución obligatoria — nada de scripts propios ni procesos en background.**
Procesa las causas activas **una por una, dentro de tu propio turno**, con llamadas
directas y de corta duración al CLI (`python -m gestion_causas.cli <subcomando> ...`,
cada una termina y devuelve su resultado al toque) — exactamente como hacen
`gestion-causas-smu` y `gestion-causas-agenda`, que no tienen este problema. **No**
escribas un script Python (u otro) que reimplemente este loop, **no** lo lances con
`Bash run_in_background`, y **no** uses `Monitor` para esperarlo. Confirmado en la
corrida del 2026-08-27: un runner casero lanzado así se cortó dos veces sin terminar
ninguna causa, porque el proceso en background no sobrevive a la frontera en que tu
turno se suspende (p. ej. mientras esperás una notificación) — el orquestador cree que
terminaste y sigue adelante, y el proceso queda huérfano y se mata. Si 27+ causas activas
parecen demasiado para un turno, no importa: se procesan igual, una por una — nunca con
un proceso de fondo que quede corriendo para consultarlo después.

## 0. Contexto de la corrida

El orquestador ya resolvió, antes de despacharte, lo que las 4 fases comparten. Leelo con
Read una sola vez, al empezar:
`Actualizador de informes\gestion_causas\_contexto_corrida.json`

De ahí sacás:
- `fecha_hoy` (AAAA-MM-DD), `dia_semana` y `es_lunes` — usá **esa** fecha en todo este
  archivo y no vuelvas a calcularla: si la corrida cruza la medianoche, dos fases podrían
  quedar con fechas distintas.
- `cache_calendario.ruta` — los eventos del calendario, traídos una sola vez para toda la
  corrida.
- `tokens` — el estado de los 3 tokens, ya verificado **sin** abrir ningún login
  interactivo. Si el orquestador te despachó, es porque los tokens de Gmail de trabajo y de
  Calendar están OK; no hace falta que los vuelvas a diagnosticar.

Si el archivo no existe (típicamente porque estás corriendo esta fase suelta a mano, fuera
del orquestador), seguí igual: calculá la fecha de hoy vos mismo y usá las llamadas en vivo
que se indican como fallback más abajo. Si en ese caso algún comando del CLI se queda
esperando un login interactivo, detente de inmediato, no reintentes, y deja como resumen
"La tarea no pudo autenticarse contra nmunoz@gomezyriesco.cl — falta autorizar el token de
forma interactiva."

## 1. Trae las causas activas

```
python -m gestion_causas.cli causas-activas --dias-ventana 60
```
Esto devuelve las causas sin fecha de audiencia registrada, o con audiencia en el futuro,
o cuya audiencia fue hace 60 días o menos (la prueba puede seguir llegando un tiempo
después de la audiencia, ej. por reprogramación). Si `total` es 0, termina con un resumen
de "sin causas activas para revisar".

El calendario **no** lo traés vos: el contexto de la corrida (paso 0) ya lo trajo una sola
vez para todas las fases, en `cache_calendario.ruta`. Esa es la ruta que vas a pasar como
`--desde-cache <ruta>` en el paso 3a de **todas** las causas de esta corrida (por defecto
`gestion_causas/cache_eventos_calendario.json`).

Si no hay contexto (estás corriendo esta fase suelta, a mano), traelo vos una sola vez con
`python -m gestion_causas.cli cache-eventos-calendario` y usá la `ruta` que devuelve. Si ese
comando falla (error de red, cuota, etc.), no reintentes ni improvises un fallback: detén la
corrida en este punto y reporta el error tal cual en el resumen final.

**Recordatorio antes de empezar este paso:** los comandos de acá abajo (`buscar-hilos`,
`leer-hilo`) son llamadas síncronas al CLI — cada una devuelve su resultado al toque, sin
importar cuántas causas o hilos haya. **Nunca** hace falta lanzarlas en segundo plano ni
"esperar" nada. Si sentís que esto va a tardar, igual se hace secuencial, una llamada
después de la otra, dentro de tu propio turno (ver la regla completa más arriba,
"Regla de ejecución obligatoria").

## 2. Trae de una sola vez los hilos con novedades

La fecha de hoy que vas a usar en el paso 2b y en el paso 3h de cada causa es la
`fecha_hoy` del contexto (paso 0) — no la recalcules.

En vez de preguntarle a Gmail causa por causa, arma un mapa `RIT -> [hilos]` con como
máximo dos búsquedas para toda la corrida:

a. Junta el RIT de **todas** las causas activas del paso 1 en un solo operador `OR` de
   Gmail, con cada RIT entre comillas (evita que Gmail interprete el guion del RIT como
   operador de exclusión), ej. `("M-1321-2026" OR "M-164-2026" OR "M-26-2026" OR ...)`.

   **Importante — detecta truncamiento:** el CLI corta los resultados exactamente en el
   `--max-resultados` que le pases, sin avisar que había más (confirmado el 2026-08-28:
   la búsqueda sin filtro de fecha de las 27 causas activas de ese día tenía 236 hilos
   reales, y con `--max-resultados 200` se cortaban 36 en silencio). Por eso, en **cada
   una** de las dos búsquedas del paso b de abajo (grupo "ya revisadas" y grupo "primera
   revisión"): si el `total` que devuelve el CLI es **igual** al
   `--max-resultados` que pediste, no asumas que ya tenés todos los resultados — repite la
   misma búsqueda duplicando `--max-resultados` (500 → 1000 → 2000) hasta que el `total`
   devuelto sea **estrictamente menor** al pedido. Si después de 3 intentos sigue
   exactamente en el tope, detente ahí, no seas más agresivo, y anota en el resumen final
   que esa búsqueda quedó sin confirmar completa (con el `total` y el tope alcanzado) para
   que Nico decida si hay que investigar.

b. Para cada causa activa, revisa con `obtener-causa --rit "<rit>"` si ya tiene
   `goteo_ultima_revision` registrada, y separa en dos grupos (esto se hace **todos los
   días de la semana por igual**, incluidos los lunes — no hay rescan completo especial):

   - **Grupo "ya revisadas"** (con `goteo_ultima_revision`): calcula `fecha_corte` = la
     fecha `goteo_ultima_revision` **más antigua** de este grupo, menos 1 día de colchón
     (el operador `after:` de Gmail filtra por día completo, no por hora, así que sin el
     colchón se podría perder algo llegado el mismo día después de que goteo ya pasó en
     una corrida anterior). Una sola búsqueda para todo el grupo:
     ```
     python -m gestion_causas.cli buscar-hilos --query "after:<fecha_corte AAAA/MM/DD> (<OR de los RIT de este grupo>)" --max-resultados 500
     ```
   - **Grupo "primera revisión"** (sin `goteo_ultima_revision` — primera vez que el goteo
     la revisa; si el grupo no está vacío): una búsqueda aparte, sin filtro de fecha, solo
     con los RIT de este grupo (mismo criterio de "escaneo completo, igual que siempre"
     que tenía antes cada causa nueva):
     ```
     python -m gestion_causas.cli buscar-hilos --query "(<OR de los RIT de este grupo>)" --max-resultados 500
     ```

c. Junta los `thread_id` de la(s) búsqueda(s) anteriores (sin duplicados) y trae los
   mensajes de cada uno — esto sigue siendo una llamada por hilo, pero ahora solo para los
   hilos que de verdad tuvieron actividad, no una búsqueda vacía repetida por cada causa
   sin novedades:
   ```
   python -m gestion_causas.cli leer-hilo --thread-id <thread_id>
   ```

d. Para cada hilo leído, revisa el `subject` de sus mensajes (quitándole primero
   cualquier prefijo `RE:`/`RV:`/`FWD:`/`FW:`/`ENV:`, igual que siempre) para determinar a
   qué RIT(s) corresponde — el RIT queda en el asunto de toda la cadena, incluidas las
   respuestas. Arma con esto el mapa `RIT -> [hilos]` que vas a usar en el paso 3. Si un
   hilo encontrado claramente no tiene que ver con ninguna causa (coincidencia de texto
   casual), descártalo del mapa — usa criterio, no lo proceses a ciegas. Esto incluye los
   hilos "Provisiones demanda laborales [mes]", "Informe de provisión [mes]" / "INFORME
   PROVISIÓN [mes]" y "Risgo causas estado sentencias" / "Riesgo causas estado sentencias"
   (ver nota de filtro de asunto más arriba) y cualquier otro reporte/consolidado interno
   que solo mencione el RIT de pasada.

e. Para las causas del grupo "primera revisión" (paso b), agrega también su `thread_id`
   original guardado en el registro al mapa del RIT correspondiente, aunque no haya
   aparecido en la búsqueda (mismo colchón de seguridad que tenía antes cada causa nueva,
   por si el `thread_id` guardado por Fase 1 no calza con el `OR` de este paso).

Si alguna de las búsquedas de este paso falla (error de red, cuota, límite de longitud de
`query`, etc.), no reintentes ni improvises un fallback: detén la corrida en este punto y
reporta el error tal cual en el resumen final (mismo criterio que la sección 0 y que el
cache de calendario del paso 1).

**Por qué esta búsqueda NO se restringe a los 7 dominios de confianza:** aunque los
documentos de prueba solo se guardan si vienen de esos dominios (paso 3e), la detección de
acuerdo/pago (paso 3c2) necesita leer avisos y comprobantes que pueden llegar de
**cualquier** remitente — confirmado el 2026-08-28 con M-637-2026 (`jualmosa@gmail.com`) y
M-643-2026 (`cajbiobio.cl`), ninguno de los dos en la lista de dominios confiables.
Restringir esta búsqueda por dominio haría que el goteo dejara de detectar esos avisos.

## 3. Por cada causa activa

a. **Determina la carpeta destino de los documentos**, según el tipo de la próxima
   audiencia (mismo mecanismo que usa `gestion-causas-agenda` paso 2 — calendario de
   `nmunoz@gomezyriesco.cl` en solo lectura), usando el cache que ya trajiste en el paso 1
   (no vuelvas a llamar a la API por cada causa):
   ```
   python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>" --desde-cache "<ruta del cache del paso 1>"
   ```
   Quédate con el primer evento futuro o de hoy. Del `resumen` del evento, determina el
   tipo:
   - "audiencia de juicio" (o "aud. de juicio") → **Juicio**.
   - "audiencia única" / "audiencia preparatoria", sin evento, o resumen ambiguo →
     tipo normal (no adivines "Juicio" sin que el título del evento lo diga
     explícitamente).

   - Si el tipo es **Juicio**: la carpeta destino es la subcarpeta **"Exhibición de
     documentos"** dentro de la carpeta de la causa (ej. `<carpeta de la causa>\Exhibición
     de documentos`). No hace falta crearla a mano — `guardar-adjunto` la crea sola si no
     existe. Anota en el resumen final qué causas tuvieron documentos guardados ahí, para
     que Nico sepa por qué no quedaron sueltos en la carpeta principal.
   - En cualquier otro caso: la carpeta destino es la carpeta de la causa directamente
     (comportamiento de siempre).

   Usa esta carpeta destino (llámala `<carpeta destino>` de aquí en adelante) en los
   pasos d y e.

b. **Toma del mapa armado en el paso 2** los hilos que correspondan al RIT de esta causa
   (puede ser una lista vacía si no hubo novedades — en ese caso salta directo al paso h).

c. Ya tenés los mensajes de cada hilo relevante (los trajiste en el paso 2c) — no vuelvas
   a llamar a `leer-hilo`.

c2. **Detecta acuerdo alcanzado y pago recibido**, con el mismo contenido que ya
    trajiste en el paso 2c (no es una lectura adicional, es criterio sobre lo que ya
    leíste):

    - Si la causa **no** tiene todavía `estado_acuerdo` en su registro (revísalo con
      `obtener-causa --rit "<rit>"`) y el contenido de algún hilo confirma que se
      **alcanzó y aprobó** un avenimiento/conciliación/acuerdo — no una negociación en
      curso ni una oferta, hace falta confirmación de que el acuerdo ya se cerró (ej.
      "acta de conciliación", "avenimiento aprobado", "se aprobó el acuerdo por $X",
      "conciliación total"):
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"estado_acuerdo\": \"pendiente_pago\"}>"
      ```
      Anota en la bitácora ("Acuerdo alcanzado, pendiente de pago") y menciónalo en el
      resumen final.

    - Si la causa **ya** tiene `estado_acuerdo: "pendiente_pago"` y algún hilo (el mismo
      u otro) trae un comprobante de pago/transferencia asociado a ese acuerdo, primero
      revisa si el remitente de ese mensaje puntual es un dominio de la lista de
      confianza (`@unimarc.cl`, `@super10.cl`, `@alvi.cl`, `@sb.cl`, `@mayorista10.cl`,
      `@smu.cl`, `@divisionlogistica.cl` — ver nota de dominios más arriba). Esa lista se
      armó para documentos de prueba de RR.HH./legal, así que un comprobante de pago
      puede llegar perfectamente de un dominio distinto (tesorería/finanzas, el banco,
      etc.) — no asumas que siempre calza:
      - **Si el remitente SÍ es de un dominio de confianza:** guárdalo como cualquier
        adjunto de este paso (mismas reglas de de-dupe del paso e más abajo — no hace
        falta un mecanismo nuevo).
      - **Si el remitente NO es de un dominio de confianza:** el comprobante se detectó
        pero el adjunto **no** se guarda automáticamente (queda fuera de la lista de
        confianza) — anótalo igual en el resumen final (ej. "comprobante de pago visto en
        el hilo pero no descargado automáticamente por venir de un dominio no confiable
        `<dominio>` — revisar a mano y guardar si corresponde"), para que Nico no asuma
        que ya quedó guardado.

      En **ambos** casos (se haya podido guardar el adjunto o no), lo relevante es que el
      pago se confirmó, así que igual actualiza el estado:
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"estado_acuerdo\": \"pago_recibido_pendiente_confirmar\"}>"
      ```
      Anota en la bitácora ("Comprobante de pago recibido, pendiente que Nico confirme
      el cierre" — si no se pudo guardar el adjunto, dilo también en la bitácora) y
      destácalo en el resumen final — **no** marques `causa_cerrada`, eso lo decide Nico
      a mano.

d. Lista lo que ya está guardado en la carpeta destino:
   ```
   python -m gestion_causas.cli listar-carpeta --carpeta "<carpeta destino>"
   ```

e. Para cada adjunto de cada mensaje de cada hilo (de **todos** los mensajes, no solo el
   primero — el goteo llega en mensajes posteriores) que cumpla **todas** estas
   condiciones:
   - el remitente (`sender`/`from` de ESE mensaje puntual, no el del hilo en general) es
     una dirección que termina en `@unimarc.cl`, `@super10.cl`, `@alvi.cl`, `@sb.cl`,
     `@mayorista10.cl`, `@smu.cl` o `@divisionlogistica.cl` (ver nota de dominios más
     arriba);
   - su nombre (una vez saneado — mismo criterio que usa el comando: sin caracteres
     `\ / : * ? " < > |`, espacios colapsados) **no** está ya en la lista del paso 3d;
   - su nombre saneado **no** es exactamente `invite.ics` (ver nota más arriba — es solo
     el evento de Calendar, nunca prueba del caso);

   guárdalo en la carpeta destino **siempre con su nombre de archivo original** (el
   `filename` que trae el adjunto — nunca lo edites, acortes ni le pongas un nombre "más
   lindo": ese nombre es lo que permite reconocer en la próxima corrida que ese documento
   específico ya se guardó):
   ```
   python -m gestion_causas.cli guardar-adjunto --message-id <id> --attachment-id <id> --carpeta "<carpeta destino>" --nombre-archivo "<nombre original del adjunto>"
   ```
   (el comando filtra firmas/logos automáticamente, no pisa nada, y además detecta
   duplicados por tamaño de bytes aunque el nombre no coincida exactamente — por ejemplo,
   la demanda se guarda como "demanda.pdf" en Fase 1/0, y como `@sb.cl` es a la vez el
   origen de la demanda de Salcobrand y un dominio de confianza del goteo, ese mismo
   adjunto podría reaparecer aquí con su nombre original; el comando lo reconoce por
   tamaño y no lo duplica. Aun así, hacer el diff del paso 3d primero evita descargas de
   más).

f. Para cada documento que **sí** se guardó en este paso (campo `guardado: true`),
   revisa si parece el Estado de Resultados del local:
   ```
   python -m gestion_causas.cli parece-eerr --nombre-archivo "<nombre>"
   ```
   Si `parece_eerr` es true y la causa tiene CECO y fecha de despido, regístralo para
   que la Fase 2 de futuras causas del mismo local lo pueda reusar:
   ```
   python -m gestion_causas.cli registrar-eerr --ceco "<ceco de la causa>" --fecha-despido "<fecha_despido de la causa>" --rit "<rit>"
   ```
   (el registro guarda el RIT, no la ruta — el reuso de Fase 2 sigue funcionando igual
   aunque el EERR se haya guardado dentro de "Exhibición de documentos").

g. Si guardaste al menos un documento nuevo, anota en la bitácora (menciona si fue en
   la subcarpeta "Exhibición de documentos"):
   ```
   python -m gestion_causas.cli bitacora --rit "<rit>" --mensaje "Goteo: se guardaron N documentos nuevos (<lista de nombres>)[, en Exhibición de documentos por audiencia de juicio]"
   ```
   Si no había nada nuevo, no hace falta anotar nada para esa causa (evita ruido en la
   bitácora en cada corrida sin novedades).

h. **Guarda la fecha de esta revisión**, siempre (haya habido novedades o no, incluso si
   el paso 3b te dio una lista vacía) — es lo que permite que la próxima corrida calcule
   bien `fecha_corte` en el paso 2b:
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"goteo_ultima_revision\": \"<fecha de hoy AAAA-MM-DD>\"}>"
   ```

## 4. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase goteo" del panel de estado. Entrega un resumen breve: cuántas
causas se revisaron (indicando cuántas fueron "primera revisión", sin
`goteo_ultima_revision` previo, y cuántas incrementales desde la última corrida),
cuántas tenían documentos nuevos (con el RIT y los nombres de los documentos, indicando
cuáles se guardaron en la subcarpeta "Exhibición de documentos" por tener audiencia de
juicio próxima), cuántos de esos documentos se identificaron como EERR y quedaron
disponibles para reuso futuro, cuántas causas pasaron a "acuerdo pendiente de pago" y
cuántas a "pago recibido, pendiente confirmar cierre" (con su RIT, para que Nico las
revise). Si no hubo novedades en ninguna causa, dilo en una sola línea.