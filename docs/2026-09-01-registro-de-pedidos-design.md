# Registro de pedidos y restauración del seguimiento (2026-09-01)

Ver contexto general en
`Actualizador de informes/docs/2026-08-27-orquestador-gestion-causas-design.md` y
`2026-09-01-contexto-de-corrida-y-fases-paralelas-design.md` (paralelismo de
`goteo`/`agenda`, que este spec extiende a `seguimiento`). Este spec cubre una revisión de
estructura pedida por Nico el 2026-09-01: el correo diario se lee mal (prosa libre por
fase) y las tareas de insistencia (documentos pedidos y propuestas de acuerdo sin
respuesta) llevaban semanas sin correr.

## Motivación

**La insistencia dejó de funcionar.** `gestion-causas-sin-respuesta` y
`gestion-causas-documentos-pendientes` (Fases 5 y 6 del proyecto original) tenían su
SKILL.md en `.claude/scheduled-tasks/`, pero nunca quedaron registradas en el
planificador — no aparecían ni siquiera como tarea deshabilitada — y el orquestador no
las despachaba. Quedaron huérfanas cuando el orquestador absorbió a las otras 4 fases.
Evidencia: `registro_seguimiento.json` no tenía ningún aviso posterior al 2026-08-24 (un
barrido manual), con los otros 12 avisos del 2026-08-19.

**El diseño de esas dos fases además era caro.** Para saber qué estaba esperando
respuesta, la Fase 6 abría el hilo de cada una de las ~27 causas activas más una búsqueda
por RIT (2 llamadas de red por causa), y le pedía al modelo que reconstruyera "el último
mensaje de Nico pidiendo documentos" leyendo la cadena entera — cada corrida. La Fase 5
buscaba por texto (`"Estimada Daniela" newer_than:30d`), con ruido reconocido en su propio
SKILL. Todo ese trabajo existía porque **el sistema no anotaba cuándo se pidió algo**: de
43 causas, solo 4 tenían `borrador_documentos_draft_id`, y ninguna guardaba qué se pidió
ni cuándo se envió. Peor: `verificar-borradores-pendientes` ya detectaba que un borrador
había desaparecido de Gmail (o sea, que Nico lo envió) y tiraba esa señal — limpiaba el
campo y lo olvidaba.

## Diseño: el sistema recuerda, no busca

`registro_pedidos.json` — un archivo nuevo junto a los otros tres registros
(`registro_causas.json`, `registro_ceco.json`, `registro_seguimiento.json`), mismas
convenciones de `registro.py` (lock por archivo, escritura atómica). Una entrada por
**pedido de Nico que espera respuesta**: `rit`, `tipo` (`documentos`|`acuerdo`),
`thread_id`, `fecha_envio`, `destinatario`, `items_pedidos`, `items_recibidos`, `estado`
(`esperando`|`parcial`|`completo`|`gestion_manual`|`pendiente_envio`), `origen`.

Tres vías de alta, ninguna requiere buscar por texto:

1. **Automática, desde el borrador que se envió.** `verificar-borradores-pendientes`
   (`cli.py`) cambió de comportamiento: cuando un `borrador_documentos_draft_id` ya no
   existe en Gmail, en vez de limpiar el campo y olvidarlo, busca el último mensaje propio
   en ese `thread_id` — si existe, es que se envió, y da de alta el pedido (con los
   `documentos_solicitados` que la Fase 2 de `smu` ahora guarda al crear el borrador); si
   no existe ningún mensaje propio nuevo, es que Nico lo borró sin enviar, y no se registra
   nada. Cero búsquedas nuevas: el hilo ya se conocía.
2. **Etiqueta de Gmail, para lo que se manda a mano.** Nico etiqueta el correo que envía
   con `Esperando-Respuesta`. El comando `pedidos-desde-etiqueta` hace **una sola**
   búsqueda `label:Esperando-Respuesta` por corrida y da de alta lo nuevo. Al cerrar el
   pedido, se le quita la etiqueta — así la bandeja etiquetada en Gmail siempre refleja
   exactamente lo que sigue abierto.
3. **Comando manual** `registrar-pedido`, para un alta puntual sin pasar por Gmail.

**Bootstrap, una sola vez.** `migrar-pedidos-bootstrap` siembra el registro nuevo con el
backlog que existía antes de este cambio: las 13 entradas de `registro_seguimiento.json`
(con su historial de avisos intacto, para que la cadencia siga contando desde donde iba) y
las causas con `borrador_documentos_draft_id` vigente. Es idempotente — no duplica si se
corre más de una vez. `registro_seguimiento.json` no se elimina: sigue siendo el registro
de *cadencia* (`puede_insistir`/`registrar_aviso`); el registro nuevo guarda *qué* se
pidió.

## El subagente `seguimiento`

Reemplaza a las dos fases huérfanas, fusionadas, como quinta fase del orquestador
(`subagentes/seguimiento.md`). Su lógica ya no es buscar, es recorrer:

1. Da de alta lo nuevo (`verificar-borradores-pendientes` + `pedidos-desde-etiqueta`).
2. Trae `pedidos-abiertos` — el universo a revisar, sin tocar Gmail todavía.
3. Por cada pedido abierto, trae su hilo (`leer-hilo`, una llamada), hace el cruce por RIT
   si corresponde (mismo criterio de descarte de reportes consolidados que usa `goteo`), y
   clasifica: completo, parcial (recordatorio de faltantes), sin respuesta ≥4 días hábiles
   (documentos) o ≥24 h (acuerdo) → insistencia, con la misma cadencia de 2 avisos que ya
   usaban las fases viejas (`puede-insistir`/`registrar-aviso`, sin cambios).

Se despacha **en paralelo con `goteo` y `agenda`** (escribe archivos/campos distintos,
mismo criterio que ya justificó el paralelismo de esas dos — ver el spec hermano de
contexto de corrida) y **solo en la corrida de la mañana**: sus umbrales son en días
hábiles y la cadencia limita a 2 avisos, así que correrla 3 veces al día no adelanta
ningún aviso. `contexto-corrida` agrega un campo `corrida` (`"manana"`/`"resto"`, según la
hora) para que el orquestador no tenga que interpretar relojes; `calendario` (Fase 0) usa
el mismo campo, porque además estaba duplicada con la tarea suelta
`gestion-causas-calendario` (deshabilitada como parte de este cambio).

## Costo aceptado

Un correo que Nico manda a mano y no etiqueta con `Esperando-Respuesta` no se sigue. La
mitigación queda para la Etapa 3 (correo estructurado): una sección "Pedidos abiertos" en
el panel diario, que además de informar sirve de control de calidad del propio
registro — si Nico está esperando algo y no aparece ahí, es señal de que falta
etiquetarlo.

## Qué queda para después (Etapas 2-4, no implementadas en este cambio)

- **Barrido de Gmail combinado en Python** (`mapa-hilos-por-rit`): mecanizar lo que hoy es
  prosa en `goteo.md` paso 2 (unión de RITs, detección de truncamiento, filtro de reportes
  consolidados), para que `goteo` y `seguimiento` no vuelvan a barrer la bandeja cada uno
  por su cuenta.
- **Correo estructurado**: contrato JSON por fase en vez de prosa libre, con una bandeja
  de acciones consolidada arriba del correo y la tabla de "Pedidos abiertos".
- **Mapa RIT → audiencia centralizado**: `goteo` y `agenda` hoy resuelven el tipo de
  audiencia cada uno por su cuenta, con criterios ya divergentes.
