# Subagente "calendario" (Fase 0) del orquestador gestion-causas-orquestador

Fase 0 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase 0 de cada corrida.

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

## 0a. Autoevaluación de turno

Esta fase solo actúa **los lunes**, según el campo `es_lunes` del contexto (si no hay
contexto, determina la fecha de hoy en zona horaria de Chile):
- Si **no** es lunes: termina de inmediato. Tu único mensaje final debe ser exactamente
  `{"fase": "calendario", "resultado": "No corresponde hoy (Fase 0 solo corre los lunes).", "error": null}`
  (un único objeto JSON, sin texto antes ni después). No ejecutes ningún comando del CLI.
- Si es lunes: sigue con el resto de este archivo.

**Por qué existe**: `gestion-causas-smu` (Fase 1) detecta causas nuevas por correo, pero
puede fallar — correspondencia anterior a que la automatización empezara a cubrir esa
empresa (ej. Salcobrand/Preunic se agregaron el 13-08-2026), fuera de la ventana de
backlog (`after:2026/07/01`), o correos que nunca calzaron con el patrón esperado. Se
descubrió en real revisando la causa Rebolledo con Salcobrand (M-637-2026): tenía
audiencia única fijada para el 24-08-2026 y no estaba registrada en ningún lado (ni
Excel, ni registro local, ni carpeta, ni etiqueta) porque la demanda llegó en mayo de
2026, antes de que Salcobrand entrara al alcance del proyecto. El calendario es la fuente
de verdad de qué realmente va a audiencia, así que sirve de red de seguridad.

**Restricción dura**: el calendario se usa en modo **SOLO LECTURA** (mismo mecanismo que
`gestion-causas-agenda`, `gestion_causas/calendar_client.py`, autenticado directamente
como `nmunoz@gomezyriesco.cl` con scope `calendar.readonly`). Esta tarea nunca crea,
modifica ni borra eventos. Tampoco envía correos ni borra nada.

Toda la parte mecánica se hace con el CLI `gestion_causas.cli`, corrido con
Bash/PowerShell desde `Actualizador de informes` como directorio de trabajo.

## 1. Trae los eventos candidatos

Usa el cache que ya trajo el contexto de la corrida, en vez de hacer una segunda llamada a
la API por tu cuenta (el rango de 90 días que necesitás está contenido en el del cache):

```
python -m gestion_causas.cli eventos-calendario --dias-adelante 90 --desde-cache "<cache_calendario.ruta del contexto>"
```

Si no hay contexto, o si el comando falla con `--desde-cache` (el cache no existe, está
corrupto, o no cubre el rango pedido), corré el mismo comando **sin** ese flag — cae de
vuelta a la llamada en vivo de siempre y el resultado es idéntico:

```
python -m gestion_causas.cli eventos-calendario --dias-adelante 90
```

Devuelve los eventos de los próximos 90 días cuyo resumen menciona alguna de las 6
empresas de interés (Rendic Hermanos, Alvi, Super 10, Servicios Logísticos Santiago,
Preunic, Salcobrand — detección por alias de texto, no hace falta que el nombre sea
exacto), cada uno con `rit_detectado` (el RIT extraído del título, o `null` si el título
no trae uno reconocible). El comando ya excluye por su cuenta los eventos cuyo RIT
empieza con "I-" (ej. "I-38-2026") — son trámites ante la Inspección del Trabajo, no
causas judiciales laborales, y quedan fuera del alcance de este proceso (instrucción del
usuario, 2026-08-13). Si `total` es 0, termina con resumen "sin eventos nuevos de las
empresas de interés".

## 2. Por cada evento

a. **Si `rit_detectado` es null**, sáltalo — no hay forma confiable de identificar la
   causa a partir del evento. Anótalo en el resumen final (con la fecha y el `resumen`
   completo) para que Nico lo revise a mano; puede ser una audiencia real cuyo título no
   sigue el patrón "... [RIT] ..." esperado.

b. **Verifica si ya está registrada**:
   ```
   python -m gestion_causas.cli causa-ya-registrada --rit "<rit_detectado>"
   ```
   Si `ya_registrada` es true, no hagas nada más con este evento — ya la maneja
   normalmente Fase 1/3/4. (Nota: esto no actualiza `fecha_audiencia` si cambió; eso lo
   hace `gestion-causas-agenda` leyendo el calendario en cada corrida, no esta tarea.)

c. **Si NO está registrada**, determina el **tipo de audiencia** a partir del `resumen`
   (misma lógica que `gestion-causas-agenda`):
   - "audiencia única" (o "aud. única") → Única.
   - "audiencia preparatoria" → Preparatoria.
   - "audiencia de juicio" (o "aud. de juicio") → Juicio.
   - Cualquier otra cosa (vence plazo, reunión preparatoria —que NO es lo mismo que
     audiencia preparatoria—, recurso, sobreseimiento, etc.) → no es una audiencia; sáltalo
     y no sigas con este evento (el barrido es para audiencias, no para cualquier trámite
     con el nombre de la empresa). Anótalo igual en el resumen final por si a Nico le
     interesa saber que existe una causa de estas empresas que no está en el sistema,
     aunque no toque crear nada todavía.

d. **Busca el hilo original de la demanda** para poder etiquetar y sacar los datos de la
   causa:
   ```
   python -m gestion_causas.cli buscar-hilos --query "<rit_detectado>"
   ```
   Lee cada hilo candidato (`leer-hilo`) y quédate con el que tenga el **mensaje más
   antiguo** cuyo remitente sea de dominio `@smu.cl` o `@sb.cl` (mismo criterio de origen
   que usa `gestion-causas-smu` para causas nuevas) — ese es el hilo/mensaje de origen. Si
   no encuentras ningún hilo con esas condiciones, registra la causa igual con lo que
   tengas del evento (paso 2e) pero sin `thread_id` ni demanda, y anótalo en el resumen
   final para que Nico lo revise a mano — no te detengas por esto.

   Del mensaje de origen (si lo encontraste) extrae lo que puedas: demandante (apellido,
   para el nombre de carpeta), CECO y fecha de despido si el cuadro resumen los trae. No
   pasa nada si faltan — se registra igual, mismo criterio que Fase 1.

e. **Registra la causa**:
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con empresa (=empresa_detectada del evento), demandante, thread_id (si lo encontraste), ceco (si hay), fecha_despido (si hay), fecha_audiencia (=fecha del evento, AAAA-MM-DD), tiene_demanda (true/false según si vas a guardarla en 2g), aplica_excel (true para Rendic Hermanos/Alvi/Super 10/Servicios Logísticos Santiago, false para Preunic/Salcobrand)>"
   ```

f. **Si encontraste el hilo de origen**, etiqueta el hilo con el color de la empresa:
   ```
   python -m gestion_causas.cli etiquetar-empresa --thread-id "<id>" --empresa "<empresa_detectada>"
   ```

g. **Solo si el tipo de audiencia (paso 2c) es Única o Preparatoria** (no Juicio — para
   cuando una causa llega a audiencia de juicio ya debería tener carpeta de una etapa
   anterior; si no la tiene, es un caso raro que conviene que Nico revise a mano en vez de
   crear algo automáticamente a esta altura del proceso):

   1. Crea la carpeta:
      ```
      python -m gestion_causas.cli crear-carpeta --apellido "<apellido demandante>" --empresa "<empresa_detectada>" --rit "<rit>"
      ```
      (el comando ya busca y reusa una carpeta existente por RIT si Nico ya tenía una
      armada a mano — revisa `reusada`).
   2. Si encontraste el mensaje de origen con un adjunto que parezca la demanda (PDF
      grande, no firma/logo — el comando ya filtra firmas automáticamente), guárdalo:
      ```
      python -m gestion_causas.cli guardar-adjunto --message-id "<id>" --attachment-id "<id>" --carpeta "<carpeta>" --nombre-archivo demanda.pdf
      ```
      Si no hay demanda disponible, sigue sin ella y anótalo en el resumen final.

h. **Si la empresa es Rendic Hermanos, Alvi, Super 10 o Servicios Logísticos Santiago**
   (NO Preunic ni Salcobrand) **y lograste datos suficientes** (juzgado, materia, cuantía
   — lo que hayas podido extraer del correo de origen o de la demanda si la guardaste),
   agrega la fila al Informe de Juicios Vigentes, igual que hace `gestion-causas-smu`:
   ```
   python "..\actualizar_informe_juicios.py" --json-file "<ruta a un JSON con juzgado, materia, causa, cuantia, resumen>"
   ```
   Código de salida 0 o 3 (duplicado) → sigue. Código 1 (Excel bloqueado o datos
   incompletos) → no es motivo para detener el resto de la corrida, solo anótalo en el
   resumen final para que Nico agregue esa fila a mano. Si no lograste datos suficientes
   para la Plantilla del Resumen (ver `docs\2026-07-07-informe-juicios-email-design.md`),
   sáltate este paso igual y anótalo — mejor no escribir una fila con datos incompletos o
   inventados.

i. **Anota en la bitácora**:
   ```
   python -m gestion_causas.cli bitacora --rit "<rit>" --mensaje "Fase 0 (barrido de calendario): causa detectada por audiencia del <fecha>, no estaba registrada. <qué se hizo: carpeta creada/reusada, demanda guardada o faltante, Excel actualizado o no aplica/pendiente>"
   ```

## 3. Resumen final

Tu **último mensaje** de esta ejecución debe ser **un único objeto JSON**, sin texto antes
ni después y sin envolverlo en \`\`\` — el orquestador lo copia tal cual a la sección "Fase
calendario" del panel de estado. Formato:

```json
{
  "fase": "calendario",
  "titular": "<una frase: ej. \"1 causa nueva detectada por calendario (Rebolledo con Salcobrand)\">",
  "metricas": [
    {"etiqueta": "Eventos revisados", "valor": N},
    {"etiqueta": "Causas nuevas dadas de alta", "valor": N},
    {"etiqueta": "Eventos sin RIT reconocible", "valor": N}
  ],
  "items": [
    {"rit": "<rit>", "titulo": "<demandante> con <empresa>",
     "detalle": "Audiencia <tipo> el <fecha>; demanda guardada/falta; Excel actualizado/no aplica"}
  ],
  "acciones": [],
  "notas": []
}
```

- `items`: una entrada por cada causa nueva dada de alta en esta corrida.
- `notas`: eventos que se saltaron por no traer un RIT reconocible en el título (fecha +
  texto del evento, para que Nico los revise a mano si le interesa) — no son urgentes,
  van como nota, no como acción.
- Si no es lunes, usá el mensaje del paso 0a en vez de este formato. Si hubo problema de
  autenticación en el paso 0, en cambio: `{"fase": "calendario", "error": "<el error tal
  cual>"}`.