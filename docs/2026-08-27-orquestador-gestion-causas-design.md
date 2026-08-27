# Orquestador único para el ciclo de gestión de causas + panel de estado

## Contexto

Hoy el ciclo de gestión automática de causas nuevas (ver
[docs/superpowers/plans/2026-07-07-informe-juicios-email.md](../../docs/superpowers/plans/2026-07-07-informe-juicios-email.md)
y `C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md`) vive repartido
en 4 tareas programadas independientes, cada una con su propio `SKILL.md` y su propio
cron, todas construidas sobre el mismo CLI y el mismo estado en disco:

| Tarea | Fase | Cron actual |
|---|---|---|
| `gestion-causas-calendario` | Fase 0 — alta desde calendario | Lunes 07:07 |
| `gestion-causas-smu` | Fases 1-2 — ingesta de causas nuevas desde Gmail | 09:08 / 14:xx / 18:xx |
| `gestion-causas-goteo` | Fase 3 — documentos nuevos de causas ya conocidas | 11:04 / 17:xx |
| `gestion-causas-agenda` | Fases 4-6 — ofrecimiento y disparo de minuta | 08:04 diario |

Las 4 comparten la misma librería Python (`gestion_causas/`) y el mismo estado en disco
(`registro_causas.json`, `registro_seguimiento.json`, `bitacora.md`), pero corren en
sesiones de Claude Code separadas y sin ningún punto en común donde ver el ciclo completo
de una causa de un vistazo. Nico tiene que revisar `bitacora.md` o el registro a mano para
saber en qué fase está cada causa.

**Nota sobre `revision-semanal-calendario-audiencias`:** existe una 5ª tarea programada
relacionada por nombre ("calendario", "audiencias"), pero **no forma parte de este
proyecto**: no usa el CLI de `gestion_causas`, no lee/escribe `registro_causas.json`, y su
mecanismo es completamente distinto (exporta el calendario vía automatización de Chrome,
cruza contra un Excel maestro separado "Causas Gomez y Riesco", y su función es programar
recordatorios de audiencia y llevar un informe de causas **penales**, no laborales). Se
deja fuera del orquestador y sigue corriendo exactamente igual que hoy, sin cambios.

**Problema a resolver:** falta de visibilidad/control del estado del ciclo completo, no un
problema de coordinación entre fases (el orden actual ya funciona).

## Decisión de arquitectura

Se reemplazan las 4 tareas programadas por **una sola tarea programada**
(`gestion-causas-orquestador`), que corre 3 veces al día (09:00 / 14:00 / 18:00, igual
que hoy `gestion-causas-smu`). Las 4 tareas antiguas se **desactivan, no se borran**
(mismo criterio ya usado con `actualizar-informe-juicios`); sus `SKILL.md` quedan como
referencia histórica de las reglas migradas. `revision-semanal-calendario-audiencias`
queda fuera de este proyecto y sigue exactamente igual que hoy (ver nota en Contexto).

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

### Por qué secuencial y no paralelo

Las 4 fases comparten `registro_causas.json` y `registro_seguimiento.json`. Si dos
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

Al terminar los 4 subagentes (hayan actuado, no actuado, o fallado), el orquestador arma
un correo HTML y lo envía a `nmunoz@gomezyriesco.cl`. Contenido:

1. **Resumen de la corrida**: qué hizo cada una de las 4 fases esta vez. Ejemplos:
   - "smu: 2 causas nuevas registradas — Pérez con Alvi M-XXX-2026, Soto con Rendic
     M-YYY-2026"
   - "goteo: 3 documentos guardados (2 en Pérez con Alvi, 1 en Soto con Rendic)"
   - "calendario: no correspondía hoy (no es lunes)"
   - Cualquier fallo, con su mensaje de error, en su propia sub-sección.
2. **Estado de cada causa activa**: RIT, empresa, demandante, una fase inferida a partir de
   los campos que **ya existen** en `registro_causas.json` (sin agregar campos nuevos al
   registro), en este orden de prioridad (primera coincidencia gana):
   - `causa_cerrada` → "Cerrada"
   - `minuta_ejecutada` → "Minuta generada"
   - `oferta_borrador_creado` → "Ofrecimiento enviado a Román"
   - `tiene_demanda` → "Demanda guardada, en curso"
   - ninguno de los anteriores → "Recién registrada"

   (Implementado así en `panel.py::_fase_actual` — se descartó una fase intermedia de
   "prueba económica lista" en base a `ceco`/EERR: agregaba una distinción que no se
   traduce en una acción distinta para Nico, y `ceco` puede estar presente sin que eso
   signifique nada sobre el avance del ofrecimiento o la minuta.)
   - Próxima fecha relevante: `fecha_audiencia`.
   - Alerta simple si una causa sigue abierta pero `ultima_actualizacion` lleva varios días
     sin cambios (umbral a definir en la implementación, ej. 7 días corridos).

El panel es una vista **calculada al vuelo** sobre datos existentes — no persiste su
propio estado ni duplica el registro.

## Envío del panel: cuenta personal, no la de trabajo

**Corrección de diseño (2026-08-27):** la primera versión de este documento proponía
agregar una excepción acotada de envío directamente a `gmail_client.py` (la cuenta de
trabajo, `nmunoz@gomezyriesco.cl`). Nico corrigió esto: **`nmunoz@gomezyriesco.cl` nunca
envía correo bajo ninguna circunstancia**, ni siquiera un auto-reporte — es una regla sin
excepciones. La única cuenta que Nico autoriza a enviar es la personal,
**`nmunos31@gmail.com`**. `gmail_client.py` queda intacto, sin scope `gmail.send` y sin
ninguna función de envío (se revirtió la excepción que se había agregado por error).

En su lugar, el envío del panel lo hace un módulo nuevo y deliberadamente mínimo,
`gmail_personal_client.py`:

- Autenticado como `nmunos31@gmail.com`, con un token propio
  (`token_gmail_personal.json`) separado del de trabajo, reutilizando el mismo
  `client_secret.json` (proyecto `informe-semanal-501614`) que ya usan `gmail_client.py`
  y `Automatizacion Informe Semanal/generar_informe_semanal.py`.
- **Único scope pedido: `gmail.send`.** No lee correo, no etiqueta, no crea borradores —
  su única razón de existir es enviar el panel.
- Una única función, `enviar_panel_estado(asunto, html)`, que **solo puede enviar a
  `nmunoz@gomezyriesco.cl`** — la dirección va hardcodeada, no como parámetro. No expone
  un `destinatario`/`to` libre.
- El conector de Gmail de Claude para la cuenta personal (ya conectado) se descartó como
  mecanismo de envío: hoy solo expone `create_draft`, no una herramienta de envío — de
  ahí la necesidad de este cliente Python propio, mismo patrón que ya usa `gmail_client.py`
  para el trabajo.
- Tests en `tests/test_gmail_personal_client.py` verifican: el scope es únicamente
  `gmail.send`, no hay funciones de lectura/etiquetado/borrado, `enviar_panel_estado` no
  acepta destinatario arbitrario, y rechaza HTML vacío o solo espacios.
- Requiere un consentimiento OAuth de Nico, una sola vez, con la cuenta personal.

`gestion_causas/cli.py` expone `enviar-panel` (llama a
`gmail_personal_client.enviar_panel_estado`) y `diagnostico-personal` (verifica que el
token esté atado a `nmunos31@gmail.com`, mismo patrón que `diagnostico`/
`diagnostico-calendario`). `panel-html` (arma el HTML, sin tocar Gmail) no cambia.

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

1. Se implementa `gestion-causas-orquestador` y sus 4 subagentes, reutilizando el
   contenido de cada `SKILL.md` actual.
2. Se agrega `enviar_panel_estado` y la función de armado del HTML del panel.
3. Se prueba en paralelo con las tareas antiguas **todavía activas** (para comparar
   resultados) antes de desactivarlas.
4. Una vez validado, se desactivan (`enabled: false`, sin borrar) las 4 tareas antiguas.

## Fuera de alcance

- `revision-semanal-calendario-audiencias` no se toca: no comparte CLI ni registro con
  `gestion_causas` (ver nota en Contexto), sigue como tarea independiente sin cambios.
- `Automatizacion Informe Semanal` (Relok) y las tareas manuales/inactivas
  (`buscador-preunic`, `actualizar-informe-juicios`) no se tocan — son dominios aparte que
  no comparten registro ni CLI con `gestion_causas`.
- No se agregan campos nuevos a `registro_causas.json`; el panel se calcula sobre lo que
  ya existe.
- No se implementa un mecanismo de locks de archivo — la ejecución secuencial lo hace
  innecesario.
