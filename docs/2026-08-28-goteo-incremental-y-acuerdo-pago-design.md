# Goteo incremental + seguimiento de acuerdo/pago (2026-08-28)

Ver contexto general del proyecto en
`Actualizador de informes/docs/2026-08-27-orquestador-gestion-causas-design.md` y en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`. Este spec cubre
dos mejoras independientes al subagente **goteo** (Fase 3 del orquestador
`gestion-causas-orquestador`), pedidas por Nico el 2026-08-28.

## Motivación

El goteo corre 3 veces al día. Hoy, en cada corrida, para **cada** causa activa vuelve a
hacer `buscar-hilos` + `leer-hilo` completo sin importar si hubo novedades desde la
corrida anterior — trabajo redundante que crece con el número de causas activas. Además,
hoy no existe ningún estado formal para "se llegó a un acuerdo, falta que paguen" — solo
queda anotado como texto libre en la bitácora (ver `bitacora.md`, entradas del
2026-08-13, 2026-08-20 y 2026-08-21 sobre avenimientos/conciliaciones), y el cierre de la
causa (`causa_cerrada: true`) se hace siempre a mano.

## Parte 1 — Filtro incremental

**Nota:** la mecánica de búsqueda descrita en esta Parte 1 (una `buscar-hilos` por RIT)
quedó superada por la Parte 3 más abajo (búsqueda combinada), agregada la misma tarde. El
campo `goteo_ultima_revision` y la red de seguridad de los lunes siguen funcionando igual;
lo que cambió es cuántas llamadas de red hacen falta para aplicarlos.

### Modelo de datos

Nuevo campo en cada entrada de `registro_causas.json` (vía el mismo mecanismo de
`registrar_causa`, que ya hace merge superficial): `goteo_ultima_revision` (string
`AAAA-MM-DD`). Se actualiza al terminar de procesar cada causa en el paso 2 de goteo,
haya encontrado documentos nuevos o no.

### Lógica de la búsqueda (paso 2b de `subagentes/goteo.md`)

- **Causa sin `goteo_ultima_revision` registrada** (primera vez que la ve el goteo) o
  **hoy es lunes** (rescan completo semanal, ver más abajo): comportamiento actual sin
  cambios — `buscar-hilos --query "<rit>"` sin filtro de fecha, e incluir siempre el
  `thread_id` original del registro aunque no aparezca en la búsqueda.
- **Cualquier otro día**, con `goteo_ultima_revision` ya registrada: calcular
  `fecha_desde = goteo_ultima_revision - 1 día` (colchón de un día porque el operador
  `after:` de Gmail filtra por día completo, no por hora, y para no perder nada que haya
  llegado el mismo día de la corrida anterior después de que goteo ya pasó). Buscar con
  `buscar-hilos --query "<rit> after:<fecha_desde en formato AAAA/MM/DD>"`. **No** se
  fuerza además la inclusión del `thread_id` original — si llegó mail nuevo ahí, el mismo
  filtro `after:` ya lo encuentra (el RIT queda en el asunto de todos los mensajes de esa
  cadena, réplicas incluidas).
- El resto del paso 2 (2c en adelante: leer cada hilo relevante, listar carpeta, filtrar
  por dominio/asunto/adjunto-a-excluir, guardar, detectar EERR) no cambia.

### Red de seguridad — rescan semanal

Los lunes, las 3 corridas del día (no solo la primera) hacen el escaneo completo de
siempre, sin el filtro `after:`, para **todas** las causas activas — corrige en un plazo
máximo de una semana cualquier caso raro que el filtro incremental se haya podido saltar
(ej. un RIT que por algún motivo no se repite en el asunto de una respuesta). No hace
falta detectar "primera corrida del día" ni guardar ningún estado adicional para esto —
alcanza con mirar el día de la semana de hoy.

### `causas_para_goteo` (registro.py)

Sin cambios en esta parte — la ventana de 60 días post-audiencia sigue igual (el ajuste
de ventana para causas con acuerdo pendiente de pago se describe en la Parte 2).

## Parte 2 — Estado de acuerdo pendiente de pago

### Modelo de datos

Nuevo campo `estado_acuerdo` en cada entrada de `registro_causas.json`, con estos
valores posibles:

- Ausente (default): sin acuerdo detectado, comportamiento normal.
- `"pendiente_pago"`: se detectó que la causa **llegó y se aprobó** un
  avenimiento/conciliación/acuerdo (no una negociación en curso ni una oferta — hace
  falta confirmación de que el acuerdo ya se cerró). Señales típicas en el texto del
  hilo: "acta de conciliación", "avenimiento aprobado", "se aprobó el acuerdo por $X",
  "conciliación total".
- `"pago_recibido_pendiente_confirmar"`: estando ya en `pendiente_pago`, se detectó
  (en el mismo hilo u otro) un comprobante de pago/transferencia asociado a ese acuerdo.

`causa_cerrada` **no se toca automáticamente en ningún caso** — sigue siendo una decisión
manual de Nico, como hoy.

### Detección (nuevo sub-paso en el paso 2 de `subagentes/goteo.md`, junto con la
lectura de hilos que el goteo ya hace)

Mientras el goteo lee los mensajes de cada hilo relevante (paso 2c, ya existente — no es
una lectura adicional, es criterio aplicado sobre lo que ya lee):

1. Si la causa **no** tiene todavía `estado_acuerdo` y el contenido del hilo confirma que
   se alcanzó y aprobó un acuerdo (no una propuesta/negociación en curso — usar criterio,
   igual que ya lo hace hoy para decidir qué anotar en la bitácora): registrar
   `estado_acuerdo: "pendiente_pago"` vía `registrar-causa`, anotarlo en la bitácora, y
   mencionarlo en el resumen final.
2. Si la causa **ya** tiene `estado_acuerdo: "pendiente_pago"` y el hilo (mismo u otro)
   trae un comprobante de pago/transferencia asociado a ese acuerdo: guardarlo como
   adjunto (mismas reglas de dominio confiable y de-dupe de siempre — nada nuevo ahí),
   registrar `estado_acuerdo: "pago_recibido_pendiente_confirmar"` vía `registrar-causa`,
   anotarlo en la bitácora, y destacarlo en el resumen final para que Nico lo confirme y
   cierre a mano.

Esta detección aplica tanto en corridas incrementales como en el rescan semanal completo
— no depende de la Parte 1, solo de qué hilos termina leyendo el goteo en cada corrida
(que si llegó un mensaje nuevo con el acuerdo o el comprobante, el filtro incremental ya
lo captura, y si no, el rescan de los lunes es la red de seguridad).

### Ajuste a `causas_para_goteo` (registro.py)

Una causa con `estado_acuerdo` en `"pendiente_pago"` o
`"pago_recibido_pendiente_confirmar"` se sigue incluyendo en `causas_para_goteo`
**aunque su audiencia haya sido hace más de `dias_ventana_post_audiencia` días** (el pago
de un acuerdo puede demorar meses) — la única condición para excluirla sigue siendo
`causa_cerrada: true`.

### Panel (`panel.py`)

Dos badges nuevos en `_fase_actual` / `_COLOR_FASE_CAUSA`, evaluados antes que "Recien
registrada" pero después de "Cerrada"/"Minuta generada"/"Ofrecimiento enviado a Roman"
(mismo orden de prioridad que ya usa `_fase_actual`, agregando los dos casos nuevos justo
después de `causa_cerrada`):
- `estado_acuerdo == "pago_recibido_pendiente_confirmar"` → "Pago recibido, pendiente
  confirmar cierre".
- `estado_acuerdo == "pendiente_pago"` → "Acuerdo pendiente de pago".

Así ambos estados saltan a la vista en el correo del panel sin abrir el registro.

## Parte 3 — Búsqueda combinada en una sola llamada (misma tarde, actualización)

### Motivación

La Parte 1 acota **cuánto mail se lee por causa** (con `after:`), pero seguía disparando
una llamada `buscar-hilos` **por cada una de las causas activas**, una por una — con 27
causas activas son 27 búsquedas de red secuenciales aunque casi todas vuelvan vacías.
Nico confirmó el 2026-08-28 que una corrida sin ninguna novedad real igual tardó ~20
minutos por este motivo, y pidió que el goteo revise la bandeja de entrada **una sola
vez** por corrida y ahí busque cuáles de las causas activas tuvieron correo nuevo, en vez
de preguntarle a Gmail causa por causa.

### Mecanismo (nuevo paso 2 de `subagentes/goteo.md`, antes del loop por causa)

- Se arma un único operador `OR` de Gmail con el RIT de **todas** las causas activas
  (cada RIT entre comillas, para que Gmail no interprete el guion como exclusión).
- **Lunes:** una sola búsqueda `buscar-hilos --query "(<OR de todos los RIT>)"` sin
  filtro de fecha (reemplaza el rescan completo semanal que antes eran 27 búsquedas).
- **Resto de la semana:** las causas activas se separan en dos grupos según si ya tienen
  `goteo_ultima_revision` registrada:
  - "ya revisadas": una sola búsqueda con `after:<fecha más antigua del grupo, menos 1
    día> (<OR de los RIT del grupo>)`.
  - "primera revisión" (si no está vacío): una búsqueda aparte sin filtro de fecha, solo
    con los RIT de ese grupo.
- Los `thread_id` que devuelven esas 1-2 búsquedas se leen con `leer-hilo` (una llamada
  por hilo, pero ahora solo para hilos con actividad real) y se agrupan por RIT según el
  `subject` de sus mensajes, armando un mapa `RIT -> [hilos]` que el loop por causa (ahora
  paso 3) consume directamente en vez de volver a buscar.
- Para las causas de "primera revisión" se sigue agregando también su `thread_id`
  original guardado en el registro al mapa, por si no aparece en la búsqueda (mismo
  colchón que existía antes por causa).

Esto baja el número de llamadas de red de "una búsqueda por causa" (27) a "una o dos
búsquedas por corrida", independiente de cuántas causas activas haya.

### Por qué esta búsqueda no se restringe a los dominios de confianza

La detección de acuerdo/pago (Parte 2) necesita leer avisos y comprobantes de **cualquier**
remitente, no solo de los 7 dominios de confianza de RR.HH./legal — confirmado el
2026-08-28 con M-637-2026 (`jualmosa@gmail.com`) y M-643-2026 (`cajbiobio.cl`), ninguno de
los dos en la lista de dominios confiables. Restringir la búsqueda combinada por dominio
haría que el goteo dejara de ver esos avisos, así que la búsqueda sigue siendo
mailbox-wide (sin `from:`), y el filtro de dominio se sigue aplicando solo al guardar
adjuntos (paso 3e), como ya hacía antes.

### Riesgos conocidos de la búsqueda combinada

- **Truncamiento silencioso por `--max-resultados` (detectado y corregido el
  2026-08-28):** `buscar_hilos` (`gmail_client.py`) corta la paginación exactamente en el
  `max_resultados` pedido y el CLI no informa si había más resultados disponibles. La
  búsqueda sin filtro de fecha de las 27 causas activas de ese día tenía **236 hilos
  reales**; con el tope inicial de 200 que se dejó en `subagentes/goteo.md`, 36 quedaban
  cortados sin ningún aviso — justo en el rescan de los lunes, que es la red de seguridad
  pensada para cubrir lo que el filtro incremental se salte. Corregido subiendo el tope
  inicial a 500 y agregando una instrucción explícita en el paso 2a de `goteo.md`: si el
  `total` devuelto es igual al `--max-resultados` pedido, repetir la búsqueda duplicando
  el tope (hasta 3 intentos) antes de darla por completa. Este riesgo crece con el tiempo
  a medida que se acumula correspondencia histórica de las causas activas, así que puede
  volver a aparecer más adelante si el negocio crece — el mecanismo de reintento con tope
  creciente está pensado para no necesitar ajustar el número a mano cada vez.
- **RIT que no se repite textualmente en una respuesta:** tanto la búsqueda combinada como
  la anterior por-RIT dependen de que el RIT aparezca como texto en el asunto o cuerpo del
  mensaje — si una respuesta puntual no lo repite, ninguna de las dos lo encuentra. Mismo
  riesgo de siempre, cubierto por el rescan completo de los lunes (sin cambios).
- **Longitud de la query:** con 27 RIT el `OR` combinado tiene ~500 caracteres, sin
  problema. Si el número de causas activas creciera mucho más (varios cientos), convendría
  revisar si Gmail sigue aceptando la query combinada o si hay que partirla en lotes — no
  es un problema hoy.

## Fuera de alcance

- No se toca el subagente **agenda** — su trabajo (hitos de fecha + consulta de
  calendario) no re-escanea correos, así que no hay redundancia que optimizar ahí.
- No se agrega ningún comando nuevo a `cli.py` — `buscar-hilos --query` ya pasa el string
  tal cual a Gmail, así que el operador `after:` se arma en el subagente sin tocar el CLI.
- No se cierra `causa_cerrada` automáticamente en ningún escenario.
