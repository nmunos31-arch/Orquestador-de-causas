# Cache de calendario por corrida (2026-08-28)

Ver contexto general en
`Actualizador de informes/docs/2026-08-27-orquestador-gestion-causas-design.md` y en
`Actualizador de informes/docs/2026-08-28-goteo-incremental-y-acuerdo-pago-design.md`
(optimización hermana, ya implementada). Este spec cubre un hallazgo hecho al revisar
oportunidades adicionales de optimización pedidas por Nico el 2026-08-28.

## Motivación

`calendar_client.buscar_audiencia_por_rit(rit)` — usado por el comando CLI
`buscar-audiencia-por-rit`, que llaman tanto `goteo` (paso 2a) como `agenda` (paso 2) por
**cada** causa activa, en **cada** corrida — no filtra por RIT del lado de la API: llama
`listar_eventos(hoy, hoy+200 días)`, que trae **todos** los eventos del calendario de
`nmunoz@gomezyriesco.cl` en ese rango (paginado), y recién después filtra por RIT en
memoria con `buscar_eventos_por_rit` (substring match sobre el resumen normalizado).

Con N causas activas, una corrida hace hasta 2×N llamadas a la API de Calendar que traen
exactamente el mismo rango de eventos cada vez — el único trabajo que cambia entre
llamadas es el filtro final en memoria. Con ~27 causas activas eso son ~54 fetches
idénticos del mismo rango de 200 días por corrida, cuando **una sola** llamada alcanza
para responder todas.

## Diseño

### Nuevo comando CLI: `cache-eventos-calendario`

Trae todos los eventos del calendario primario en el rango de 200 días hacia adelante
desde hoy (misma lógica que hoy usa `calendar_client.buscar_audiencia_por_rit`
internamente: `listar_eventos(hoy, hoy + 200 días)`, sin filtrar por empresa ni por RIT —
eso queda para el filtro posterior) y los guarda en un archivo JSON en disco:
`gestion_causas/cache_eventos_calendario.json`.

Contenido del archivo: lista de eventos `{"fecha": "AAAA-MM-DD", "resumen": str}`, más un
campo `generado_en` (timestamp ISO de cuándo se generó, informativo — ningún consumidor
depende de su frescura automáticamente, ver más abajo por qué).

Este archivo se agrega a `.gitignore` del repo raíz (`Actualizador de informes/gestion_causas/cache_eventos_calendario.json`)
— es estado efímero de una corrida, se sobrescribe en cada una, no es dato a versionar.

### `buscar-audiencia-por-rit` gana un flag opcional `--desde-cache <ruta>`

- **Sin el flag** (comportamiento actual, sin cambios): llama a
  `calendar_client.buscar_audiencia_por_rit(rit)`, que hace la llamada en vivo a la API
  (trae todo el rango de 200 días y filtra en memoria). No rompe ningún uso existente
  (`calendario.md` u otros).
- **Con el flag**: lee el JSON de `<ruta>`, corre el mismo filtro `buscar_eventos_por_rit`
  sobre esa lista ya en memoria (sin tocar la API), y devuelve el mismo formato de salida
  de siempre (`{"rit", "eventos", "total"}`). Si `<ruta>` no existe o no es JSON válido,
  el comando termina con error claro (no falla en silencio ni cae de vuelta a la API por
  su cuenta — la decisión de si usar cache o ir en vivo es del subagente que lo llama, ver
  abajo).

### `goteo.md` — nuevo "paso 0"

Al empezar la corrida, antes de procesar la primera causa activa: llama una vez a
`cache-eventos-calendario` (guarda el archivo en la ruta fija de siempre). Usa esa ruta
en **todas** las llamadas a `buscar-audiencia-por-rit --desde-cache` del paso 2a de esa
corrida, para todas las causas.

No hace falta lógica de expiración/frescura: el archivo se regenera desde cero al
principio de cada corrida de goteo (goteo corre 3 veces al día, siempre antes que
agenda en el orden fijo del orquestador), así que dentro de una misma corrida el
contenido es por definición actual.

### `agenda.md` — reusa el mismo archivo, con fallback

Agenda corre después de goteo en el orden fijo del orquestador (mismo motivo que ya hace
que goteo dependa de que `smu` haya corrido antes), así que el archivo que goteo generó
en el paso 0 de esa misma corrida sigue siendo válido cuando le toca a agenda.

- **Si el archivo existe**: usa `buscar-audiencia-por-rit --desde-cache <ruta>` para
  todas las causas, igual que goteo.
- **Si el archivo no existe** (ej. goteo falló antes de llegar al paso 0, o alguien corre
  agenda de forma suelta/manual fuera del orquestador): cae de vuelta a la llamada en vivo
  de siempre (`buscar-audiencia-por-rit` sin el flag), causa por causa — mismo
  comportamiento que agenda tiene hoy, sin quedar bloqueada por la ausencia del cache.

### Impacto esperado

Una corrida normal (goteo + agenda, ~27 causas activas) pasa de hasta ~54 llamadas a la
API de Calendar a **1 sola** (el `cache-eventos-calendario` de goteo; agenda no vuelve a
tocar la API si el cache está disponible). Ningún criterio de negocio cambia — mismo
filtro por RIT, mismo formato de salida, mismo fallback a comportamiento actual cuando
falta el cache.

## Fuera de alcance

- No se toca `calendario.md` (Fase 0, solo corre los lunes) — ya hace una sola llamada
  por corrida (`eventos-calendario`, filtrada por alias de empresa, no por RIT), no tiene
  el problema de N llamadas repetidas.
- No se cachea entre corridas — cada corrida de goteo regenera el archivo desde cero, sin
  intentar reusar el de una corrida anterior (evita cualquier problema de frescura: un
  evento nuevo agendado hace 5 minutos siempre aparece en la próxima corrida).
- No se cambia el formato de salida de `buscar-audiencia-por-rit` ni el criterio de
  filtrado por RIT (`buscar_eventos_por_rit`, substring sobre RIT normalizado) — el cache
  es puramente una fuente de datos alternativa para el mismo filtro que ya existe.
