# Driver Python para el ciclo de gestión de causas (reducir consumo de tokens)

## Contexto

Hoy el ciclo de `gestion_causas` (fases `calendario`, `smu`, `goteo`, `agenda`,
`seguimiento`) corre como 5 subagentes de Claude Code, cada uno leyendo un `.md` de
instrucciones largo (`gestion_causas/subagentes/*.md`) que orquesta el bucle completo:
recorrer causas una por una, llamar al CLI `gestion_causas.cli` paso a paso, y razonar en
cada paso aunque la mayoría de las decisiones ya están mecanizadas en Python (extracción
del mapa de hilos, filtro de reportes consolidados, filtro de dominio, cadencia de
insistencia, etc.). Esto consume tokens de Claude Code en cada corrida programada (3
veces al día para el orquestador, más las corridas de `seguimiento`) aunque casi todo el
trabajo por causa es mecánico.

**Objetivo:** que el flujo corra principalmente con scripts Python, sin que Claude
procese los datos completos ni tenga alta injerencia en el control del flujo. Claude
interviene solo en los puntos puntuales que requieren razonamiento sobre texto libre o
redacción no contemplable con reglas fijas.

## Decisión de arquitectura

Se reemplaza el patrón "Claude Code lee el `.md` y orquesta" por un **driver Python**
(`gestion_causas/orquestador.py`) que controla el flujo completo: recorre las causas
activas en un `for`, llama directo a las funciones ya existentes en `registro.py`,
`carpetas.py`, `gmail_client.py`, `calendar_client.py`, `seguimiento.py` (como librería,
sin pasar por subprocess del propio CLI), y decide con lógica Python normal todo lo que
hoy ya está mecanizado.

La tarea programada (`gestion-causas-orquestador`, 09:00/14:00/18:00) sigue existiendo
con el mismo mecanismo de `scheduled-tasks`, pero la sesión de Claude Code que dispara
ya no lee ningún `.md` de instrucciones — su único trabajo es correr
`python -m gestion_causas.orquestador` y reportar el resultado. Esa sesión top-level casi
no consume tokens.

Los 5 `subagentes/*.md` actuales se migran a módulos Python bajo `gestion_causas/fases/`
(`calendario.py`, `smu.py`, `goteo.py`, `agenda.py`, `seguimiento.py`), cada uno con una
función `correr(contexto_corrida) -> ResumenFase` que reemplaza el `.md` correspondiente.
Los `.md` **no se borran** — quedan como referencia histórica de las reglas migradas
(mismo criterio ya usado con las 4 tareas programadas antiguas antes del orquestador).

## Puntos que se quedan con razonamiento de Claude

Del repaso de `smu.md`, `goteo.md`, `agenda.md` y la corrección pendiente de
`seguimiento.md` (clasificación de pedidos solo-informativos), se descartaron dos
candidatos iniciales por no necesitar razonamiento:

- El **resumen narrativo del panel** (`titular` de cada fase) se arma con f-strings en
  Python a partir de las métricas que la fase ya calculó.
- La **redacción del correo de ofrecimiento** a Román usa una plantilla fija y literal
  (ver memoria `gestion_causas_borrador_ofrecimiento_formato`) — Claude solo extrae los
  montos del PDF; Python rellena la plantilla.

Quedan 6 puntos, cada uno con contexto acotado (nunca el hilo o PDF completo sin filtrar
previamente en Python) y un schema de salida JSON fijo:

1. **`smu` (paso "documentos a solicitar")** — leer `demanda.pdf` y decidir qué
   documentos agregar a la lista base (base de cálculo distinta, descuento indebido,
   horas extra, etc.).
2. **`agenda` (paso "hito de 14 días — ofrecimiento")** — leer `demanda.pdf` y extraer
   los montos exactos (Recargo 30%, AFC, descuento finiquito). Python arma el correo con
   la plantilla fija a partir de esos montos.
3. **`goteo` (paso "detectar acuerdo/pago")** — decidir si un hilo confirma un acuerdo
   **cerrado** (no solo bases propuestas por el tribunal — ver memoria
   `gestion_causas_bases_tribunal_no_es_acuerdo`).
4. **`seguimiento` (paso "clasificar pedido")** — clasificar un pedido pendiente como
   candidato a insistencia, completo, o solo informativo (ver memoria
   `gestion_causas_seguimiento_no_insistir_solo_informativo`).
5. **`smu` (caso borde "origen de la cadena")** — cuando el primer mensaje es de
   `@gomezyriesco.cl`, decidir si es un reenvío citado del cuadro-resumen (cadena válida)
   o una conversación interna.
6. Los puntos 1 y 5 pueden resolverse en un único llamado a Claude por causa dentro de
   `smu` (lee la demanda/hilo una sola vez y devuelve ambas decisiones en el mismo JSON)
   — se define en el plan de implementación, para no leer el PDF dos veces.

Todo lo demás (extracción del cuadro-resumen vía "Mapeo de columnas", filtro de
dominio/empresa, de-dupe, carpeta destino según tipo de audiencia, etiquetado, cadencia
de insistencia, armado del mapa de hilos y del mapa de audiencias, cálculo de fechas,
reuso de EERR) ya está o queda 100% en Python puro, sin llamada a Claude.

## Invocación a Claude — `reasoning.py`

Módulo nuevo y angosto: `gestion_causas/reasoning.py` con una función:

```python
def preguntar(tarea: str, contexto: dict, schema: dict) -> dict:
    ...
```

- Arma un prompt corto: la instrucción puntual (`tarea`) + el `contexto` mínimo necesario
  serializado a JSON (nunca el `.md` completo ni todo el hilo/PDF sin filtrar) + "responde
  solo con JSON válido según este schema: `<schema>`".
- Corre `claude -p "<prompt>"` como subprocess (headless, misma suscripción de Claude
  Code que ya usa el resto del sistema — sin API key nueva).
- Parsea la respuesta como JSON. Si falla el parseo, reintenta **una vez** con un prompt
  que incluye el error de parseo. Si vuelve a fallar, devuelve
  `{"error": "<detalle>"}` en vez de lanzar una excepción.
- La fase que llamó a `preguntar` decide qué hacer con `{"error": ...}`: normalmente
  anotarlo en `acciones` del resumen final (para que Nico lo revise a mano) y seguir con
  la siguiente causa, sin detener la corrida completa — mismo criterio de aislamiento de
  fallas que ya usa el sistema hoy.

## Manejo de errores y panel

Sin cambios respecto al diseño actual del orquestador: cada fase corre aislada (el driver
Python envuelve cada `fases.<nombre>.correr(...)` en `try/except`), un fallo no cancela
las siguientes ni el envío del panel, y queda anotado en `bitacora.md` y en la sección de
resumen del correo. El armado del HTML del panel (`panel.py`) no cambia — sigue siendo
cálculo puro sobre `registro_causas.json`, sin llamar a Claude.

## Testing

Cada fase migrada es una función Python normal, testeable con pytest:

- Se mockea `reasoning.preguntar` para los 6 puntos de razonamiento (no se llama a Claude
  de verdad en los tests) y se reutilizan las fixtures de registro/Gmail que ya usan los
  tests actuales (`tests/test_registro.py`, `tests/test_seguimiento.py`, etc.).
- Test nuevo para `reasoning.preguntar`: reintenta una vez y devuelve `{"error": ...}`
  sin lanzar excepción si Claude devuelve JSON inválido dos veces seguidas.
- Test nuevo para el driver `orquestador.py`: un fallo en una fase no impide que las
  demás corran ni que se arme/envíe el panel.

## Migración

Se migra fase por fase, no todas de una vez:

1. **`goteo`** primero, como piloto — es la fase con más causas por corrida y la que ya
   tiene más lógica mecanizada en Python de base (mapa de hilos, filtro de reportes
   consolidados). Corre en paralelo con el subagente `.md` viejo (comparando resultados)
   antes de desactivarlo — mismo criterio que usó la migración al orquestador
   (`2026-08-27-orquestador-gestion-causas-design.md`, sección "Migración").
2. Una vez validado el patrón de `reasoning.py` y el driver, se migran `smu`, `agenda` y
   `seguimiento` con el mismo patrón.
3. `calendario` se migra al final — es la más simple y probablemente no necesita ningún
   punto de razonamiento (a confirmar al implementarla).
4. Cada `.md` viejo se conserva sin borrar tras migrar su fase, como referencia
   histórica.

## Fuera de alcance

- `revision-semanal-calendario-audiencias` no se toca (no comparte CLI ni registro con
  `gestion_causas`, ver `2026-08-27-orquestador-gestion-causas-design.md`).
- No se cambia el formato de `registro_causas.json`, `registro_seguimiento.json` ni
  `bitacora.md` — el driver Python lee y escribe los mismos campos que ya usan las fases
  actuales.
- No se introduce una API key de Anthropic ni facturación aparte — la invocación a Claude
  sigue siendo vía Claude Code headless (`claude -p`), dentro de la suscripción actual.
- La skill `/minuta-laboral` (invocada hoy desde `agenda` paso 4) no se toca — sigue
  siendo una skill de Claude Code aparte, fuera de este rediseño.
