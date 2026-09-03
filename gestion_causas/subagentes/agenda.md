# Subagente "agenda" (Fases 4-6) del orquestador gestion-causas-orquestador

Fase 4 del proyecto "Gestión automática de causas nuevas desde la casilla del trabajo" —
ver el diseño completo en `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`
y en `Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "agenda" de cada corrida, al final: después de "calendario" y "smu", y
**en paralelo con "goteo"** (desde el 2026-09-01 — las dos fases escriben campos distintos
del registro y ya no dependen una de la otra). Depende de que el subagente "smu" ya haya registrado las causas (aplica
a las 6 empresas: Rendic Hermanos, Alvi, Super 10, Servicios Logísticos Santiago, Preunic
y Salcobrand — este subagente no filtra por empresa, trabaja sobre lo que ya está en el
registro local).

El borrador de ofrecimiento (paso 3) va como respuesta dentro de la cadena **interna**
que Nico abre con Román al llegar cada demanda (asunto "Demanda laboral "[Apellido] con
[Empresa]" [RIT]", primer mensaje de `@gomezyriesco.cl`) — esa es justo la cadena que
`gestion-causas-smu` detecta como interna y deja sin procesar (ver su paso 2b). Si esa
cadena todavía no existe para una causa, se crea un correo nuevo como respaldo (ver
paso 3g).

**Restricción dura:** el calendario de `nmunoz@gomezyriesco.cl` se usa en **modo
SOLO LECTURA**. Esta tarea nunca crea, modifica ni borra eventos — solo los lee para
saber la fecha de cada audiencia. Tampoco envía correos (solo deja borradores) ni borra
nada.

**Sobre el acceso al calendario**: el conector de Calendar de Claude está autenticado
como la cuenta personal (`nmunos31@gmail.com`), y el calendario de trabajo le aparece
compartido con permiso `freeBusyReader` — ve cuándo Nico está ocupado, pero no el título
de los eventos, así que **no sirve** para encontrar el RIT ni el tipo de audiencia. En su
lugar, esta tarea usa un cliente propio (`gestion_causas/calendar_client.py`), autenticado
directamente como `nmunoz@gomezyriesco.cl` con scope de solo lectura
(`calendar.readonly`), igual que ya hace `gmail_client.py` para Gmail. No requiere
navegador ni exportar nada — el comando del paso 2 llama a la API en tiempo real.

Toda la parte mecánica de fechas/registro/consulta del calendario se hace con el CLI
`gestion_causas.cli`, corrido con Bash/PowerShell desde `Actualizador de informes` como
directorio de trabajo.

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
- `mapa_audiencias.ruta` — el mapa RIT → audiencia (fecha, resumen, tipo), resuelto una sola
  vez para toda la corrida con el mismo criterio que usa `goteo` — ver el paso 2 más abajo.
  Si en cambio trae `mapa_audiencias.error`, seguí con el fallback en vivo de ese paso.
- `tokens` — el estado de los 3 tokens, ya verificado **sin** abrir ningún login
  interactivo. Si el orquestador te despachó, es porque los tokens de Gmail de trabajo y de
  Calendar están OK; no hace falta que los vuelvas a diagnosticar.

Si el archivo no existe (típicamente porque estás corriendo esta fase suelta a mano, fuera
del orquestador), seguí igual: calculá la fecha de hoy vos mismo y usá las llamadas en vivo
que se indican como fallback más abajo. Si en ese caso algún comando del CLI se queda
esperando un login interactivo, detente de inmediato, no reintentes, y deja como resumen
"La tarea no pudo autenticarse contra nmunoz@gomezyriesco.cl — falta autorizar el token de
forma interactiva."

Si estás corriendo esta fase suelta y necesitás verificar el token de Calendar por separado:
```
python -m gestion_causas.cli diagnostico-calendario
```

## 1. Trae las causas activas

```
python -m gestion_causas.cli causas-activas --dias-ventana 0
```
Con `--dias-ventana 0` quedan las causas sin audiencia pasada: sin fecha registrada
todavía, o con audiencia hoy o en el futuro. Las causas con audiencia ya pasada se
excluyen solas (no hay nada más que agendar). Si `total` es 0, termina con un resumen de
"sin causas activas para revisar agenda".

## 2. Por cada causa activa, busca su audiencia en el calendario

El tipo y fecha de audiencia de cada RIT ya los resolvió el contexto de la corrida (paso 0)
en `mapa_audiencias.ruta` — mismo mapa que usa `gestion-causas-goteo` paso 3a, para que las
dos fases nunca vuelvan a divergir en cómo clasifican Única/Preparatoria/Juicio. Buscá la
entrada de este RIT en `rit_a_audiencia` de ese archivo: trae `{"fecha", "resumen", "tipo"}`
con `tipo` ∈ Única/Preparatoria/Juicio/Ambiguo. **Usa esta fecha como fuente de verdad**, no
el campo `fecha_audiencia` guardado en el registro (que viene del cuadro del correo y puede
quedar desactualizado si se reprogramó).

- Si el RIT no aparece en el mapa: no hay audiencia próxima — sáltala, nada que agendar
  todavía para esa causa.
- Si el `tipo` es **Ambiguo**: sáltate los pasos 3 y 4 para esta causa y anótalo en el
  resumen final para que Nico lo revise (mejor no adivinar el tipo de audiencia).

**Fallback si no hay contexto, o trae `mapa_audiencias.error`** (ej. estás corriendo agenda
de forma suelta fuera del orquestador): resolvé esta causa en vivo con el cache de
calendario del paso 0 (`cache_calendario.ruta`) o, si tampoco existe, con la llamada directa
a la API:

```
python -m gestion_causas.cli buscar-audiencia-por-rit --rit "<rit>" --desde-cache "gestion_causas/cache_eventos_calendario.json"
```
(si el archivo no existe, omití `--desde-cache` y corré el comando tal cual, sin ese
flag — cae de vuelta al comportamiento de siempre)

Si el comando con `--desde-cache` falla por algo que **no** es "no encuentra el
archivo" (por ejemplo un error de formato/JSON), tratalo igual que si el archivo no
existiera: para esa causa puntual, reintenta sin `--desde-cache` (la llamada en vivo de
siempre) y seguí adelante. No hace falta detener la corrida ni avisar a las demás causas —
es un fallback por causa, no un fallo general.

Quédate con el **primero futuro o de hoy** (si todos son pasados, no hay audiencia
próxima — sáltala). Del `resumen` del evento, determina el tipo con el mismo criterio del
mapa: "audiencia única" (o "aud. única") → Única; "audiencia preparatoria" (o "reunión
preparatoria" — así la agenda el tribunal casi siempre en la práctica) → Preparatoria;
"audiencia de juicio" (o "aud. de juicio") → Juicio; si no queda claro, es Ambiguo — sáltate
los pasos 3 y 4 y anótalo en el resumen.

**Causas que no son una demanda laboral contra la empresa** (ej. una demanda de
desafuero, donde la empresa es la demandante y no la demandada — ver
`obtener-causa --rit "<rit>"`, campo `tipo_causa`): los pasos 3 y 4 asumen el flujo
estándar (empresa demandada, "Recargo 30%/AFC" que ofrecer, minuta de prueba armada con
`/minuta-laboral`) y no le sirven a este tipo de causa. Antes de aplicar el paso 3,
revisa si la causa trae `"aplica_ofrecimiento": false` en su registro — si lo trae,
sáltate el paso 3 sin generar el borrador de ofrecimiento. Igual con el paso 4: si trae
`"aplica_minuta_laboral": false`, sáltatelo sin invocar `/minuta-laboral`. Si ninguno de
los dos campos está presente (el caso normal), asume que sí aplican y sigue como
siempre. En cualquier caso, sigue trayendo su fecha de audiencia con
`buscar-audiencia-por-rit` como con cualquier otra causa activa — el objetivo de estos
flags es solo evitar los pasos 3/4, no dejar de trackear la causa.

## 3. Hito de 14 días corridos — borrador de ofrecimiento (solo Única o Juicio)

Aplica **solo** si el tipo de audiencia es Única o Juicio (no Preparatoria — en esa
etapa todavía no corresponde ofrecer nada).

a. Calcula la fecha del hito:
   ```
   python -m gestion_causas.cli dias-corridos-antes --fecha "<fecha audiencia AAAA-MM-DD>" --n 14
   ```
b. Si la `fecha_hoy` del contexto es **anterior** a esa fecha, todavía no toca — sigue con la
   siguiente causa. Si es igual o posterior, y la causa **no tiene ya**
   `oferta_borrador_creado: true` en su registro (revísalo con
   `python -m gestion_causas.cli obtener-causa --rit "<rit>"`), continúa:

c. Abre `demanda.pdf` de la carpeta de la causa y extrae los montos exactos de:
   Recargo legal 30%, AFC (Devolución AFC), y cualquier descuento del finiquito
   mencionado en la demanda. Coteja estos montos contra "Conceptos demandados" del
   registro/cuadro original. Si hay una discrepancia entre lo que dice la demanda y lo
   que se registró del cuadro, usa el monto de la **demanda** (es la fuente legal) y
   anota la discrepancia en el resumen final para que Nico la revise — no la ocultes.

d. Calcula el ofrecimiento: 60% de la suma de (Recargo 30% + AFC), redondeado a un
   número entero de pesos.

e. Redacta el cuerpo EXACTAMENTE con esta plantilla (sin agregar ni quitar nada),
   reemplazando lo que va entre corchetes:
   ```
   Estimado Román:
   En esta causa, que tiene audiencia [única/de juicio] el [fecha en formato dd de mes de aaaa, hora si se conoce], se demanda lo siguiente:

   * Recargo 30%: $[monto]
   * AFC: $[monto]
   * Descuento finiquito: $[monto, o quitar esta línea si la demanda no menciona descuento de finiquito]

   Total: $[suma]
   Las sumas están conformes con el finiquito.
   Por lo anterior, consulto si hago un ofrecimiento por $[60% de Recargo+AFC], que equivale al 60% del recargo y AFC.
   ```
   Si el finiquito no tiene descuento que reclamar, omite esa línea y ajusta el Total
   sumando solo Recargo 30% + AFC.

f. Asunto: `Demanda laboral "[Apellido demandante] con [Empresa]" Rit [Letra]-[Número]-[Año]`
   (usa el nombre de la empresa tal como aparece en el registro local — campo `empresa`
   de `obtener-causa` —, no la abreviatura de carpeta; aplica igual para las 6 empresas,
   Preunic y Salcobrand incluidas, aunque esas dos no tengan fila en el Excel).

g. **Busca si ya existe la cadena interna de esta causa** — Nico tiene la costumbre de
   abrir, apenas llega la demanda, una cadena interna con Román y el equipo con asunto
   "Demanda laboral "[Apellido] con [Empresa]" [RIT]" (dominio `@gomezyriesco.cl` en el
   primer mensaje — es justo el tipo de cadena que `gestion-causas-smu` deja sin tocar).
   Ahí es donde va el borrador, respondiendo, en vez de un correo nuevo:
   ```
   python -m gestion_causas.cli buscar-hilos --query "from:gomezyriesco.cl subject:\"<rit>\""
   ```
   De los resultados, quédate con el hilo cuyo asunto se parezca a "Demanda laboral ...
   [RIT]" (confírmalo con `leer-hilo` si hay dudas: el primer mensaje debe ser de alguien
   `@gomezyriesco.cl`). Si hay más de uno, usa el que tenga el mensaje más reciente.

   **Ojo con causas RIT T- (tutela) u O- (ordinario), sobre todo si van a audiencia de
   juicio:** en esos procedimientos la cadena interna la abre Nico igual, pero su primer
   mensaje **no propone montos** (a diferencia del caso RIT M- ya verificado, donde el
   primer mensaje ya traía "Estimado Román: En esta causa... se demanda lo siguiente").
   No uses "¿el primer mensaje ya tiene montos?" como señal para saber si encontraste la
   cadena correcta — la señal es solo: primer mensaje de `@gomezyriesco.cl` + el RIT en
   el asunto o el cuerpo. Si la búsqueda por `subject:"<rit>"` no encuentra nada para
   estas causas (el asunto podría no seguir el patrón "Demanda laboral..." tan
   estrictamente), reintenta sin restringir el asunto:
   ```
   python -m gestion_causas.cli buscar-hilos --query "from:gomezyriesco.cl <rit>"
   ```
   y confirma con `leer-hilo` que el primer mensaje es de `@gomezyriesco.cl` y menciona
   la causa antes de usarla.

   - **Si encuentras esa cadena**: crea el borrador como respuesta dentro de ella:
     ```
     python -m gestion_causas.cli crear-borrador --destinatario "rgomez@gomezyriesco.cl" --asunto "Re: <asunto de esa cadena>" --cuerpo-archivo "<ruta.txt>" --thread-id <id de esa cadena>
     ```
     El comando ya evita duplicar si esa cadena ya tiene un borrador — revisa `creado`.
   - **Si NO la encuentras** (causa nueva, Nico todavía no abrió la cadena interna):
     crea un correo nuevo con el asunto del paso 3f, como respaldo:
     ```
     python -m gestion_causas.cli crear-borrador --destinatario "rgomez@gomezyriesco.cl" --asunto "<asunto>" --cuerpo-archivo "<ruta.txt>"
     ```
     El comando ya evita duplicar si existe un borrador con ese mismo asunto — revisa
     `creado` en la respuesta.

h. Si `creado` es true, registra que ya se hizo (para no repetirlo en corridas
   futuras):
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"oferta_borrador_creado\": true}>"
   ```
   y anota en la bitácora.

## 4. Hito de 4 días hábiles — /minuta-laboral (solo Única o Preparatoria)

Aplica **solo** si el tipo de audiencia es Única o Preparatoria (no Juicio — la minuta
de juicio tiene su propia lógica y no es parte de este proyecto).

a. Calcula la fecha del hito (saltando sábados, domingos y feriados):
   ```
   python -m gestion_causas.cli dias-habiles-antes --fecha "<fecha audiencia AAAA-MM-DD>" --n 4
   ```
b. Si la `fecha_hoy` del contexto es anterior a esa fecha, sigue con la siguiente causa. Si es
   igual o posterior, y la causa **no tiene ya** `minuta_ejecutada: true` en su
   registro, continúa:

c. Invoca la skill `/minuta-laboral` sobre la carpeta de la causa (la carpeta ya debe
   tener la demanda y los documentos que hayan llegado por Fase 2/3 — la skill se
   encarga del resto: leer la plantilla, la demanda y los documentos, y generar la
   minuta).

d. Registra que ya se ejecutó, para no repetirlo:
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con {\"minuta_ejecutada\": true}>"
   ```
   y anota en la bitácora ("Minuta generada a N días hábiles de la audiencia").

## 5. Resumen final

Tu **último mensaje** de esta ejecución debe ser **un único objeto JSON**, sin texto antes
ni después y sin envolverlo en \`\`\` — el orquestador lo copia tal cual a la sección "Fase
agenda" del panel de estado. Formato:

```json
{
  "fase": "agenda",
  "titular": "<una frase: ej. \"1 borrador de ofrecimiento creado, 2 minutas generadas\">",
  "metricas": [
    {"etiqueta": "Causas revisadas", "valor": N},
    {"etiqueta": "Borradores de ofrecimiento creados", "valor": N},
    {"etiqueta": "Minutas generadas", "valor": N},
    {"etiqueta": "Sin evento de calendario todavía", "valor": N}
  ],
  "items": [
    {"rit": "<rit>", "titulo": "<demandante> con <empresa>",
     "detalle": "Ofrecimiento de $<monto> (Recargo $<x> + AFC $<y>)"}
  ],
  "acciones": [],
  "notas": []
}
```

- `items`: una entrada por cada borrador de ofrecimiento creado o minuta generada en esta
  corrida (`detalle` describe cuál de las dos fue, con los montos si aplica).
- `acciones`: **cualquier discrepancia entre los montos de la demanda y los del cuadro**
  (paso 3c) va acá, siempre — es lo que más necesita que Nico la revise antes de que el
  ofrecimiento salga con un monto equivocado: `{"rit": "<rit>", "que": "Discrepancia:
  demanda dice $<x>, cuadro decía $<y> — se usó el de la demanda", "urgencia": "alta"}`.
- `notas`: causas con tipo de audiencia ambiguo (paso 2, no se pudo determinar Única/
  Preparatoria/Juicio) u otras observaciones de criterio.
- Si no hubo novedades, `titular` puede ser "Sin novedades" con las listas vacías.