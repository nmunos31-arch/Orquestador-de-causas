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

## Fuera de alcance

- No se toca el subagente **agenda** — su trabajo (hitos de fecha + consulta de
  calendario) no re-escanea correos, así que no hay redundancia que optimizar ahí.
- No se agrega ningún comando nuevo a `cli.py` — `buscar-hilos --query` ya pasa el string
  tal cual a Gmail, así que el operador `after:` se arma en el subagente sin tocar el CLI.
- No se cierra `causa_cerrada` automáticamente en ningún escenario.
