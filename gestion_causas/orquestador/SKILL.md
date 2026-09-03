---
name: gestion-causas-orquestador
description: Orquesta las 5 fases del ciclo de gestión de causas (calendario, smu, goteo, agenda, seguimiento) como subagentes, resolviendo primero el contexto común de la corrida, y envía un panel de estado por correo
---

> **Copia versionada:** este archivo vive en dos lugares que deben mantenerse idénticos —
> `C:\Users\usuario\.claude\scheduled-tasks\gestion-causas-orquestador\SKILL.md` (el que lee
> el planificador: la fuente viva) y
> `Actualizador de informes\gestion_causas\orquestador\SKILL.md` (la copia en git, junto a
> los 5 subagentes que este archivo despacha). Si editás uno, copiá el otro; se comparan con
> `diff`.


Tarea programada desatendida (sin usuario presente). Reemplaza a las 6 tareas
`gestion-causas-calendario`, `gestion-causas-smu`, `gestion-causas-goteo`,
`gestion-causas-agenda`, `gestion-causas-sin-respuesta` y
`gestion-causas-documentos-pendientes` (quedan desactivadas o borradas, ver
`Actualizador de informes\docs\2026-09-01-registro-de-pedidos-design.md` para el detalle
de la fusión de las últimas dos en la fase `seguimiento`). Diseño completo en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md` y, para el
paso 1 y el paralelismo del paso 2, en
`Actualizador de informes\docs\2026-09-01-contexto-de-corrida-y-fases-paralelas-design.md`.

Objetivo de esta corrida: resolver una sola vez el contexto común (fecha, tokens,
calendario), ejecutar las 5 fases del ciclo de gestión de causas como subagentes aislados, y
al terminar armar y enviar por correo un panel de estado a nmunoz@gomezyriesco.cl.

Trabaja siempre con `Actualizador de informes` como directorio de trabajo para los
comandos de Bash/PowerShell.

## 1. Contexto de la corrida

Antes de despachar cualquier subagente:

```
python -m gestion_causas.cli contexto-corrida --salida "Actualizador de informes\gestion_causas\_contexto_corrida.json"
```

Esto resuelve de una sola vez lo que las 5 fases comparten: la fecha de hoy y el día de la
semana, si esta es la corrida de la mañana (campo `corrida`, ver paso 2), el estado de los
3 tokens (**sin** abrir un login interactivo, que en una tarea desatendida no vuelve
nunca), el cache de eventos de calendario para toda la corrida, el mapa RIT → hilos con
novedades (`mapa_hilos`, para `goteo`/`seguimiento`) y el mapa RIT → audiencia
(`mapa_audiencias`, para `goteo`/`agenda` — antes cada una clasificaba el tipo de audiencia
por su cuenta con criterios que ya habían divergido).

- **Si el comando sale con código 0**: sigue al paso 2. El campo `tokens.personal` puede
  venir en `false` — eso solo afecta el envío del panel del paso 5, no las 5 fases.
- **Si sale con código 1** (Gmail de trabajo o Calendar no disponibles): **no despaches
  ningún subagente**. Anota el problema en la bitácora
  ```
  python -m gestion_causas.cli bitacora --mensaje "Orquestador: corrida abortada, contexto no listo (<error del token>)"
  ```
  y salta directo al paso 3, poniendo como `resultado` de las 5 fases
  `"ERROR: contexto no listo — <error del token>"`. El panel se arma y se intenta enviar
  igual, para que Nico se entere de que hay un token que reautorizar.

## 2. Despacha los subagentes que correspondan

Para cada fase, usa la herramienta Agent (subagente nuevo, sin contexto previo de esta
conversación) con el siguiente prompt, reemplazando `<ARCHIVO>` por la ruta indicada:

"Leé completo el archivo <ARCHIVO> con la herramienta Read, y seguí sus instrucciones al
pie de la letra como si fueran tu única tarea (incluye su propio manejo de errores y de
autenticación). El contexto de esta corrida ya está resuelto en
`Actualizador de informes\gestion_causas\_contexto_corrida.json` — leelo con Read antes de
nada y usá esos valores (fecha de hoy, ruta del cache de calendario, ruta del mapa de
hilos, ruta del mapa de audiencias, estado de los tokens) en vez de volver a calcularlos.
Tu último mensaje de esta
conversación debe ser exactamente el objeto JSON del "Resumen final" que ese archivo te
pide entregar (`{\"fase\", \"titular\", \"metricas\", \"items\", \"acciones\", \"notas\"}`)
— un único bloque JSON, sin texto antes ni después, sin envolverlo en \`\`\`."

| Orden | Fase | ARCHIVO |
|---|---|---|
| 1 | calendario | Actualizador de informes\gestion_causas\subagentes\calendario.md |
| 2 | smu | Actualizador de informes\gestion_causas\subagentes\smu.md |
| 3a | goteo | Actualizador de informes\gestion_causas\subagentes\goteo.md |
| 3b | agenda | Actualizador de informes\gestion_causas\subagentes\agenda.md |
| 3c | seguimiento | Actualizador de informes\gestion_causas\subagentes\seguimiento.md |

**`calendario` y `seguimiento` solo en la corrida de la mañana:** revisa el campo
`corrida` del contexto del paso 1 (`"manana"` o `"resto"`). Si es `"resto"`, **saltate por
completo la fase `calendario`** (no despaches ese subagente; en el paso 3 deja su entrada
como `{"fase": "calendario", "resultado": "No aplica: solo corre en la corrida de la
mañana.", "error": null}`) y, en el paso de abajo, **no incluyas `seguimiento`** entre las
fases que despachas en paralelo con `goteo`/`agenda` (mismo criterio en el paso 3). Los
umbrales de ambas fases son semanales/en días hábiles con cadencia limitada a 2 avisos —
correrlas 3 veces al día no adelanta nada y solo triplica el barrido de correo.

**Orden y paralelismo:**

- `calendario` (si aplica, ver arriba) y `smu` corren **uno a la vez**, en ese orden,
  esperando a que cada uno termine antes de seguir. No los corras en paralelo entre sí:
  los dos dan de alta causas nuevas, los dos escriben el mismo Excel
  (`actualizar_informe_juicios.py`, que no tolera dos escritores), y los dos podrían
  descubrir la **misma** causa y crear carpeta y fila duplicadas.
- Recién cuando `smu` terminó, despacha `goteo`, `agenda` y (solo en la corrida de la
  mañana) `seguimiento` **en paralelo**: las llamadas a la herramienta Agent en un
  **mismo mensaje**. Las tres trabajan sobre las causas que `calendario` y `smu` ya
  registraron, comparten el cache de calendario que dejó el paso 1, y escriben
  archivos/campos distintos del registro (`goteo`/`agenda` tocan `registro_causas.json`
  en campos distintos; `seguimiento` toca `registro_pedidos.json` y
  `registro_seguimiento.json`, que ninguna de las otras dos toca) — la escritura está
  serializada con un lock por archivo en `registro.py`, así que no se pisan. Espera a que
  **todas las que despachaste** terminen antes de seguir al paso 3.

Si el último mensaje de un subagente no parece un resumen final real (por ejemplo,
contiene frases como "voy a esperar", "en segundo plano", "seré notificado" en vez de
resultados concretos — típicamente porque el subagente lanzó un proceso en background y
suspendió su turno sin terminar la tarea), mandale **un único** mensaje de continuación
(SendMessage al mismo agente) recordándole que complete el resto de su tarea de forma
síncrona, dentro del mismo turno, y que su próximo mensaje debe ser exactamente el objeto
JSON del "Resumen final" que su archivo de instrucciones pide — antes de aceptar esa fase
como terminada.

Si un subagente falla o no responde (error de la herramienta Agent), o si tras ese único
recordatorio su último mensaje sigue sin ser un resumen coherente: no te detengas. Anota
como resultado de esa fase `{"fase": "<fase>", "error": "<descripción breve del fallo>"}`
y sigue con la siguiente fase de la lista. Un fallo de una fase nunca cancela las demás ni
el envío del panel — incluyendo el caso en que falle una de las fases paralelas y las
otras no.

## 3. Arma el JSON de resumen de la corrida

Junta el resultado de cada subagente en una lista de 5 objetos, siempre en este orden
(calendario, smu, goteo, agenda, seguimiento), y escribila con la herramienta Write en un
archivo temporal: `Actualizador de informes\gestion_causas\_panel_resumen_temp.json`. Para
cada fase, el objeto que va en la lista depende de cómo terminó:

- **Corrió y su último mensaje es un objeto JSON válido** (el contrato de "Resumen final"
  de su archivo — `{"fase", "titular", "metricas", "items", "acciones", "notas"}`): usá
  ese objeto tal cual, sin modificarlo.
- **Corrió pero su último mensaje NO es JSON válido** (a pesar del recordatorio del paso
  2): `{"fase": "<fase>", "titular": null, "resultado_crudo": "<el texto tal cual, sin
  recortar>"}`. El panel lo va a mostrar igual, marcado como "formato libre" — nunca se
  pierde la información por un problema de formato.
- **Se saltó por no ser la corrida de la mañana** (`calendario`/`seguimiento` cuando
  `corrida` es `"resto"`, ver paso 2): `{"fase": "<fase>", "resultado": "No aplica: solo
  corre en la corrida de la mañana.", "error": null}`.
- **Falló o no respondió** (ver el punto anterior): `{"fase": "<fase>", "error":
  "<descripción breve del fallo>"}`.
- **La corrida se abortó en el paso 1** (contexto no listo): las 5 fases llevan
  `{"fase": "<fase>", "error": "contexto no listo — <error del token>"}`.

## 4. Genera el HTML del panel

Antes de armar el HTML, revisá si quedaron borradores de documentos sin enviar de
corridas anteriores (esto reemplaza al paso 0b que antes hacía `smu` por su cuenta):
```
python -m gestion_causas.cli verificar-borradores-pendientes
```
Guardá la salida completa (el JSON que imprime) en un archivo temporal con la herramienta
Write: `Actualizador de informes\gestion_causas\_borradores_pendientes_temp.json`. Si el
comando falla (token vencido, etc.), no reintentes — seguí sin `--borradores-json` en el
comando de abajo, la bandeja de acciones simplemente no va a incluir esta fuente en esta
corrida.

```
python -m gestion_causas.cli panel-html --resumen-json "Actualizador de informes\gestion_causas\_panel_resumen_temp.json" --borradores-json "Actualizador de informes\gestion_causas\_borradores_pendientes_temp.json" --salida "Actualizador de informes\gestion_causas\_panel_temp.html"
```

Esto lee registro_causas.json, registro_pedidos.json y registro_seguimiento.json, y
escribe el HTML completo del panel (bandeja de acciones, resumen de fases, pedidos
abiertos, y causas activas por empresa) en el archivo indicado. No requiere red.

## 5. Envía el panel por correo

python -m gestion_causas.cli enviar-panel --html-file "Actualizador de informes\gestion_causas\_panel_temp.html" --asunto "Panel de gestión de causas - <fecha de hoy AAAA-MM-DD>"

(la fecha de hoy sale del campo `fecha_hoy` del contexto del paso 1.)

Esta es la única acción de toda la automatización que envía un correo — se manda desde
la cuenta personal (nmunos31@gmail.com, la única autorizada a enviar) a
nmunoz@gomezyriesco.cl (que nunca envía nada). Si el contexto del paso 1 ya reportó
`tokens.personal.ok = false`, este comando va a fallar: intentalo igual una vez, y si falla
seguí al paso 6. Si el comando falla por cualquier motivo (token vencido, sin red, etc.), no
reintentes en esta corrida: anota el error con

python -m gestion_causas.cli bitacora --mensaje "Orquestador: fallo al enviar el panel de estado (<error>)"

y sigue al paso 6 igual.

## 6. Limpieza y resumen final

Borra los archivos temporales de la corrida si siguen existiendo: `_contexto_corrida.json`,
`_hilos_corrida.json`, `_audiencias_corrida.json`, `_panel_resumen_temp.json`,
`_borradores_pendientes_temp.json` y `_panel_temp.html`.

Entrega un resumen final breve: qué hizo cada una de las 5 fases (el `titular` de cada una,
o su error), y si el panel se envió correctamente o falló.
