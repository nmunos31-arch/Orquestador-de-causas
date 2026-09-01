---
name: gestion-causas-orquestador
description: Orquesta las 4 fases del ciclo de gestión de causas (calendario, smu, goteo, agenda) como subagentes, resolviendo primero el contexto común de la corrida, y envía un panel de estado por correo
---

> **Copia versionada:** este archivo vive en dos lugares que deben mantenerse idénticos —
> `C:\Users\usuario\.claude\scheduled-tasks\gestion-causas-orquestador\SKILL.md` (el que lee
> el planificador: la fuente viva) y
> `Actualizador de informes\gestion_causas\orquestador\SKILL.md` (la copia en git, junto a
> los 4 subagentes que este archivo despacha). Si editás uno, copiá el otro; se comparan con
> `diff`.


Tarea programada desatendida (sin usuario presente). Reemplaza a las 4 tareas
`gestion-causas-calendario`, `gestion-causas-smu`, `gestion-causas-goteo` y
`gestion-causas-agenda` (quedan desactivadas, no borradas). Diseño completo en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md` y, para el
paso 1 y el paralelismo del paso 2, en
`Actualizador de informes\docs\2026-09-01-contexto-de-corrida-y-fases-paralelas-design.md`.

Objetivo de esta corrida: resolver una sola vez el contexto común (fecha, tokens,
calendario), ejecutar las 4 fases del ciclo de gestión de causas como subagentes aislados, y
al terminar armar y enviar por correo un panel de estado a nmunoz@gomezyriesco.cl.

Trabaja siempre con `Actualizador de informes` como directorio de trabajo para los
comandos de Bash/PowerShell.

## 1. Contexto de la corrida

Antes de despachar cualquier subagente:

```
python -m gestion_causas.cli contexto-corrida --salida "Actualizador de informes\gestion_causas\_contexto_corrida.json"
```

Esto resuelve de una sola vez lo que las 4 fases comparten: la fecha de hoy y el día de la
semana, el estado de los 3 tokens (**sin** abrir un login interactivo, que en una tarea
desatendida no vuelve nunca), y el cache de eventos de calendario para toda la corrida.

- **Si el comando sale con código 0**: sigue al paso 2. El campo `tokens.personal` puede
  venir en `false` — eso solo afecta el envío del panel del paso 5, no las 4 fases.
- **Si sale con código 1** (Gmail de trabajo o Calendar no disponibles): **no despaches
  ningún subagente**. Anota el problema en la bitácora
  ```
  python -m gestion_causas.cli bitacora --mensaje "Orquestador: corrida abortada, contexto no listo (<error del token>)"
  ```
  y salta directo al paso 3, poniendo como `resultado` de las 4 fases
  `"ERROR: contexto no listo — <error del token>"`. El panel se arma y se intenta enviar
  igual, para que Nico se entere de que hay un token que reautorizar.

## 2. Despacha los 4 subagentes

Para cada fase, usa la herramienta Agent (subagente nuevo, sin contexto previo de esta
conversación) con el siguiente prompt, reemplazando `<ARCHIVO>` por la ruta indicada:

"Leé completo el archivo <ARCHIVO> con la herramienta Read, y seguí sus instrucciones al
pie de la letra como si fueran tu única tarea (incluye su propio manejo de errores y de
autenticación). El contexto de esta corrida ya está resuelto en
`Actualizador de informes\gestion_causas\_contexto_corrida.json` — leelo con Read antes de
nada y usá esos valores (fecha de hoy, ruta del cache de calendario, estado de los tokens)
en vez de volver a calcularlos. Tu último mensaje de esta conversación debe ser exactamente
el resumen final que ese archivo te pide entregar — entre 1 y 5 líneas, sin texto adicional
antes ni después."

| Orden | Fase | ARCHIVO |
|---|---|---|
| 1 | calendario | Actualizador de informes\gestion_causas\subagentes\calendario.md |
| 2 | smu | Actualizador de informes\gestion_causas\subagentes\smu.md |
| 3a | goteo | Actualizador de informes\gestion_causas\subagentes\goteo.md |
| 3b | agenda | Actualizador de informes\gestion_causas\subagentes\agenda.md |

**Orden y paralelismo:**

- `calendario` y `smu` corren **uno a la vez**, en ese orden, esperando a que cada uno
  termine antes de seguir. No los corras en paralelo entre sí: los dos dan de alta causas
  nuevas, los dos escriben el mismo Excel (`actualizar_informe_juicios.py`, que no tolera
  dos escritores), y los dos podrían descubrir la **misma** causa y crear carpeta y fila
  duplicadas.
- Recién cuando `smu` terminó, despacha `goteo` y `agenda` **en paralelo**: las dos llamadas
  a la herramienta Agent en un **mismo mensaje**. Ambas trabajan sobre las causas que
  `calendario` y `smu` ya registraron, comparten el cache de calendario que dejó el paso 1, y
  escriben campos distintos del registro (la escritura está serializada con un lock en
  `registro.py`, así que no se pisan). Espera a que **las dos** terminen antes de seguir al
  paso 3.

Si el último mensaje de un subagente no parece un resumen final real (por ejemplo,
contiene frases como "voy a esperar", "en segundo plano", "seré notificado" en vez de
resultados concretos — típicamente porque el subagente lanzó un proceso en background y
suspendió su turno sin terminar la tarea), mandale **un único** mensaje de continuación
(SendMessage al mismo agente) recordándole que complete el resto de su tarea de forma
síncrona, dentro del mismo turno, y que su próximo mensaje debe ser el resumen final real
que su archivo de instrucciones pide — antes de aceptar esa fase como terminada.

Si un subagente falla o no responde (error de la herramienta Agent), o si tras ese único
recordatorio su último mensaje sigue sin ser un resumen coherente: no te detengas. Anota
como resultado de esa fase el texto "ERROR: <descripción breve del fallo>" y sigue con la
siguiente fase de la lista. Un fallo de una fase nunca cancela las demás ni el envío del
panel — incluyendo el caso en que falle una de las dos fases paralelas y la otra no.

## 3. Arma el JSON de resumen de la corrida

Con el resultado de cada subagente (su último mensaje, o el texto de error del punto
anterior), escribe con la herramienta Write un archivo temporal en
Actualizador de informes\gestion_causas\_panel_resumen_temp.json, con este formato
exacto (un objeto por fase, siempre en este orden):

[
  {"fase": "calendario", "resultado": "<resumen o null>", "error": "<solo si fallo, si no null>"},
  {"fase": "smu", "resultado": "...", "error": null},
  {"fase": "goteo", "resultado": "...", "error": null},
  {"fase": "agenda", "resultado": "...", "error": null}
]

## 4. Genera el HTML del panel

python -m gestion_causas.cli panel-html --resumen-json "Actualizador de informes\gestion_causas\_panel_resumen_temp.json" --salida "Actualizador de informes\gestion_causas\_panel_temp.html"

Esto lee registro_causas.json y escribe el HTML completo del panel en el archivo
indicado. No requiere red ni credenciales.

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

Borra los archivos temporales de la corrida si siguen existiendo:
`_contexto_corrida.json`, `_panel_resumen_temp.json` y `_panel_temp.html`.

Entrega un resumen final breve: qué hizo cada una de las 4 fases (una línea cada una,
tomada de su resultado/error), y si el panel se envió correctamente o falló.
