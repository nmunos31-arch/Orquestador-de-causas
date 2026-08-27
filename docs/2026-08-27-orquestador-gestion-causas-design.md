# Orquestador único para el ciclo de gestión de causas + panel de estado

## Contexto

Hoy el ciclo de gestión automática de causas nuevas (ver
[docs/superpowers/plans/2026-07-07-informe-juicios-email.md](../../docs/superpowers/plans/2026-07-07-informe-juicios-email.md)
y `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`) vive repartido
en 5 tareas programadas independientes, cada una con su propio `SKILL.md` y su propio
cron:

| Tarea | Fase | Cron actual |
|---|---|---|
| `gestion-causas-calendario` | Fase 0 — alta desde calendario | Lunes 07:07 |
| `gestion-causas-smu` | Fases 1-2 — ingesta de causas nuevas desde Gmail | 09:08 / 14:xx / 18:xx |
| `gestion-causas-goteo` | Fase 3 — documentos nuevos de causas ya conocidas | 11:04 / 17:xx |
| `gestion-causas-agenda` | Fases 4-6 — ofrecimiento y disparo de minuta | 08:04 diario |
| `revision-semanal-calendario-audiencias` | Recordatorios de audiencia | Viernes 16:08 |

Todas comparten la misma librería Python (`gestion_causas/`) y el mismo estado en disco
(`registro_causas.json`, `registro_seguimiento.json`, `bitacora.md`), pero corren en
sesiones de Claude Code separadas y sin ningún punto en común donde ver el ciclo completo
de una causa de un vistazo. Nico tiene que revisar `bitacora.md` o el registro a mano para
saber en qué fase está cada causa.

**Problema a resolver:** falta de visibilidad/control del estado del ciclo completo, no un
problema de coordinación entre fases (el orden actual ya funciona).

## Decisión de arquitectura

Se reemplazan las 5 tareas programadas por **una sola tarea programada**
(`gestion-causas-orquestador`), que corre 3 veces al día (09:00 / 14:00 / 18:00, igual
que hoy `gestion-causas-smu`). Las 5 tareas antiguas se **desactivan, no se borran**
(mismo criterio ya usado con `actualizar-informe-juicios`); sus `SKILL.md` quedan como
referencia histórica de las reglas migradas.

En cada corrida, el orquestador despacha, en este **orden fijo y secuencial** (no en
paralelo), un subagente por fase. El contenido de cada `SKILL.md` actual se migra casi
textual a las instrucciones del subagente correspondiente (reglas de filtro de dominio,
exclusión de `invite.ics`, cadencia de insistencia, etc. no cambian):

1. **`calendario`** (Fase 0) — se autoevalúa: solo actúa si hoy es lunes; si no, informa
   "no me tocaba hoy" y termina sin hacer nada.
2. **`smu`** (Fases 1-2) — ingesta de causas nuevas desde Gmail.
3. **`goteo`** (Fase 3) — documentos nuevos de causas ya conocidas. Corre después de
   `smu` a propósito, para poder revisar en el mismo lote las causas recién registradas.
4. **`agenda`** (Fases 4-6) — ofrecimiento a Román y disparo de `/minuta-laboral`.
5. **`revision-audiencias`** — se autoevalúa: solo actúa si hoy es viernes.

### Por qué secuencial y no paralelo

Las 5 fases comparten `registro_causas.json` y `registro_seguimiento.json`. Si dos
subagentes los escribieran al mismo tiempo, una escritura podría pisar a la otra. Además
`goteo` depende de que `smu` ya haya registrado las causas nuevas de la corrida (Fase 1-2
antes de Fase 3) — sin orden, un subagente podría revisar una causa que otro todavía no
registró. La ejecución secuencial evita ambos problemas sin necesitar locks de archivo.

### Aislamiento de fallas

Cada subagente corre aislado: si uno falla, el orquestador **captura el error, lo anota en
`bitacora.md` y sigue con el siguiente** — un fallo en `goteo` no impide que `agenda` corra
después con los datos que haya, ni cancela el envío del panel al final. Es el mismo
criterio de tolerancia a fallos que ya usa el sistema hoy (ej. Excel abierto en
`gestion-causas-smu`), aplicado ahora también a errores no anticipados de un subagente
completo.

## Panel de estado (HTML por correo)

Al terminar los 5 subagentes (hayan actuado, no actuado, o fallado), el orquestador arma
un correo HTML y lo envía a `nmunoz@gomezyriesco.cl`. Contenido:

1. **Resumen de la corrida**: qué hizo cada una de las 5 fases esta vez. Ejemplos:
   - "smu: 2 causas nuevas registradas — Pérez con Alvi M-XXX-2026, Soto con Rendic
     M-YYY-2026"
   - "goteo: 3 documentos guardados (2 en Pérez con Alvi, 1 en Soto con Rendic)"
   - "calendario: no correspondía hoy (no es lunes)"
   - Cualquier fallo, con su mensaje de error, en su propia sub-sección.
2. **Estado de cada causa activa**: RIT, empresa, demandante, una fase inferida a partir de
   los campos que **ya existen** en `registro_causas.json` (sin agregar campos nuevos al
   registro):
   - `tiene_demanda` → demanda guardada
   - `ceco` presente / EERR reusado o registrado → prueba económica lista
   - `aplica_ofrecimiento` → borrador de ofrecimiento dejado
   - `aplica_minuta_laboral` → minuta generada
   - `causa_cerrada` → cierre
   - Próxima fecha relevante: `fecha_audiencia`.
   - Alerta simple si una causa sigue abierta pero `ultima_actualizacion` lleva varios días
     sin cambios (umbral a definir en la implementación, ej. 7 días corridos).

El panel es una vista **calculada al vuelo** sobre datos existentes — no persiste su
propio estado ni duplica el registro.

## Excepción puntual a "nunca envía correos"

La automatización tiene como regla dura no enviar correos, solo dejar borradores. Se
agrega una **excepción acotada y explícita** solo para este panel:

- Nueva función en `gmail_client.py`, ej. `enviar_panel_estado(html: str)`, que **solo
  puede enviar a `nmunoz@gomezyriesco.cl`** — la dirección va hardcodeada en la función,
  no como parámetro. No existe una función de envío genérica con destinatario libre.
- Requiere sumar el scope `gmail.send` al token de trabajo (`token_gmail_trabajo.json`) —
  nuevo consentimiento OAuth de Nico, una sola vez.
- El resto de la automatización (borrador de ofrecimiento a Román, avisos de insistencia)
  sigue sin poder enviar nada — la excepción es únicamente este correo de auto-reporte a
  sí mismo.
- El test existente que verifica que `gmail_client.py` no implementa envío se actualiza
  para permitir explícitamente esta única función acotada, y se agrega un test que
  confirma que no acepta un destinatario distinto de `nmunoz@gomezyriesco.cl`.

## Manejo de errores

- Fallo de un subagente → no cancela los siguientes ni el envío del panel; queda anotado
  en `bitacora.md` y en la sección de resumen del correo.
- Fallo al enviar el correo del panel (red, token vencido, etc.) → se anota en
  `bitacora.md`, no se reintenta en la misma corrida; se resuelve solo en la corrida
  siguiente (3 veces al día es margen suficiente).
- Se mantienen sin cambios todos los manejos de error específicos ya documentados por fase
  (ej. Excel abierto en `smu`, borrador ya existente en `agenda`).

## Pruebas

- Tests nuevos para `enviar_panel_estado`: solo permite el destinatario fijo, no expone
  parámetro `to` arbitrario, no se puede llamar con contenido vacío.
- Test para la función que arma el HTML del panel: dado un `registro_causas.json` de
  ejemplo (fixture), valida que el HTML generado contiene los campos esperados por causa y
  la sección de alertas.
- Se reutilizan los tests existentes de cada módulo (`registro.py`, `carpetas.py`,
  `agenda.py`, `gmail_client.py`) sin cambios — la lógica interna de cada fase no se
  reescribe, solo se migra su punto de entrada de "tarea programada independiente" a
  "subagente despachado por el orquestador".

## Migración

1. Se implementa `gestion-causas-orquestador` y sus 5 subagentes, reutilizando el
   contenido de cada `SKILL.md` actual.
2. Se agrega `enviar_panel_estado` y la función de armado del HTML del panel.
3. Se prueba en paralelo con las tareas antiguas **todavía activas** (para comparar
   resultados) antes de desactivarlas.
4. Una vez validado, se desactivan (`enabled: false`, sin borrar) las 5 tareas antiguas.

## Fuera de alcance

- `Automatizacion Informe Semanal` (Relok) y las tareas manuales/inactivas
  (`buscador-preunic`, `actualizar-informe-juicios`) no se tocan — son dominios aparte que
  no comparten registro ni CLI con `gestion_causas`.
- No se agregan campos nuevos a `registro_causas.json`; el panel se calcula sobre lo que
  ya existe.
- No se implementa un mecanismo de locks de archivo — la ejecución secuencial lo hace
  innecesario.
