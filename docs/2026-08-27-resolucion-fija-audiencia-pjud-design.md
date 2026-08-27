# Descarga de la resolución que fija audiencia (PJUD) — diseño

## Objetivo

Extender la tarea programada `gestion-causas-smu` para que, además de crear la
carpeta de la causa y guardar la demanda adjunta (pasos 2g/2h existentes),
descargue y guarde en esa misma carpeta la resolución que da curso a la causa
y fija la fecha de la audiencia preparatoria/única — y, de paso, registre esa
fecha/hora exacta en el sistema (`fecha_audiencia`), que hoy depende de que el
cuadro-resumen del correo ya la traiga (a veces dice "Pendiente reclamación" o
directamente no la trae).

Alcance: **solo causas nuevas en adelante**. No hay backfill de causas ya
registradas antes de esta funcionalidad.

## Restricción técnica que condiciona el diseño

`oficinajudicialvirtual.pjud.cl` (OJV) está protegido por un WAF con
reCAPTCHA que bloquea cualquier navegador controlado por Chrome DevTools
Protocol (Selenium, Playwright, requests HTTP directos, etc.) — ver
`~/.claude/skills/buscador-causas-pjud/SKILL.md`, que documenta esto en
detalle para el mismo sitio. Lo único que funciona es la extensión
`claude-in-chrome`, que controla el navegador real del usuario vía la API de
extensiones (no CDP).

Esto significa que este paso nuevo **no puede garantizar ejecución
desatendida al 100%**: depende de que, en el momento en que corre
`gestion-causas-smu`, haya una sesión de Chrome con la extensión conectada
(decisión del usuario: "el script corre cuando tengo el computador prendido,
así que no hay problema en eso" — se intenta igual dentro de la tarea
programada, con degradación controlada si no está disponible).

Consecuencias de diseño:
- Si `claude-in-chrome` no está disponible/conectado, el paso se salta
  **completo** para toda la corrida (no bloquea nada más).
- Si aparece un captcha visual del WAF, no se intenta resolver — se detiene
  ese intento puntual y la causa queda pendiente para una corrida futura.
- Nunca se opera como usuario logueado en "Mis Causas" — todo pasa por la
  Consulta Unificada pública (mismo criterio que `buscador-causas-pjud`).

## Mecanismo de descarga (verificado en vivo)

La Consulta Unificada por RIT vive en `oficinajudicialvirtual.pjud.cl` →
botón "Consulta causas" → pestaña "Búsqueda por RIT" (activa por defecto).
Verificado con el caso de ejemplo RIT O-496-2026 (JLT Concepción, GONZÁLEZ/
RENDIC HERMANOS):

1. Completar el formulario:
   - **Competencia**: "Laboral" (`value="4"` del combo `#nomCompetencia`) —
     siempre, para este proyecto.
   - **Corte**: mapeo del nombre de Corte del cuadro-resumen del correo (ej.
     "Corte Concepción") a la opción del combo de 17 cortes — reusar la
     tabla ya documentada en `buscador-causas-pjud/SKILL.md`.
   - **Tribunal**: texto del cuadro-resumen (ej. "Juzgado de letras del
     Trabajo de Concepción"), comparado sin tildes/mayúsculas contra las
     opciones del combo, que se repuebla vía AJAX al fijar Corte (esperar
     ~2-3s).
   - **Libro/Tipo**: la letra del RIT (O, T, M, E, S, U, V, I).
   - **Rol**: el número del RIT. **Año**: el año del RIT.
2. Clic en "Buscar". Si "Total de registros" es 0 → causa aún no indexada en
   el PJUD (frecuente si el ingreso es muy reciente) → tratar como
   `pendiente` (ver más abajo), no es un error.
3. Clic en el ícono de lupa de la fila (debería ser una sola fila, dado que
   se buscó por RIT exacto) → abre el modal "Detalle Causa Laboral", pestaña
   "Movimientos" (activa por defecto).
4. En la tabla de movimientos, ubicar la fila con **Etapa = "Ingreso"** y
   **Trámite = "Resolución"**. La descripción del trámite (columna "Desc.
   Trámite") varía según el caso — "Da curso/Exhorto/Poder", "Da curso",
   etc. — por eso **no se filtra por ese texto exacto**, solo por
   Etapa+Trámite. Si hay más de una fila así, usar la de folio más bajo (la
   primera cronológicamente). Si todavía no existe ninguna fila así → tratar
   como `pendiente`.
5. Clic en el ícono PDF de esa fila. Esto abre una **pestaña nueva** con una
   URL firmada tipo:
   `https://oficinajudicialvirtual.pjud.cl/ADIR_871/laboral/documentos/docReformadoLaboral.php?valorRef=<JWT>`
   Esa pestaña usa el visor nativo de PDF de Chrome, que **no se puede
   controlar** con `read_page`/`javascript_tool`/`computer` (el intento de
   adjuntar falla con "Cannot attach to this target"). Por eso el
   procedimiento es:
   a. Capturar esa URL desde el contexto de pestañas (`tabs_context_mcp`)
      justo después del clic.
   b. Cerrar esa pestaña nueva.
   c. Volver a la pestaña principal de OJV (mismo origen, sesión ya
      autenticada) y ejecutar con `javascript_tool`:
      ```js
      const res = await fetch(URL, {credentials: 'include'});
      const blob = await res.blob();
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'pjud_tmp_<RIT-normalizado>.pdf';
      document.body.appendChild(a); a.click(); a.remove();
      ```
      Esto dispara una descarga real de Chrome a la carpeta de Descargas del
      usuario. **Probado en vivo**: devuelve 200, `content-type:
      application/pdf`, y el archivo llega íntegro a Descargas (451 KB en la
      prueba). Un `fetch` directo por `curl`/Bash a la misma URL (sin pasar
      por el navegador real) da 403 — confirma que el WAF exige que la
      petición se origine en el navegador real, no alcanza con tener la
      cookie de sesión.
   d. Intentar extraer directamente el `href`/`onclick` del ícono sin abrir
      pestaña (para ahorrar el paso a/b) es una optimización posible para la
      fase de implementación, pero no es necesaria — el flujo con
      abrir-cerrar pestaña ya es confiable.
6. Un subcomando nuevo del CLI, `mover-descarga`, mueve el archivo recién
   bajado desde la carpeta de Descargas de Windows a la carpeta de la causa,
   con el nombre fijo `Resolución fija audiencia.pdf`. Mismo criterio de no
   pisar que el resto del sistema (`guardar_adjunto`/`copiar_archivo_local`
   en `carpetas.py`): si ya existe un archivo con ese nombre, no lo
   sobrescribe.
7. Se lee el texto del PDF recién guardado (la skill ya tiene acceso de
   lectura de PDF) para extraer fecha y hora de la audiencia citada (patrón
   tipo "para el día DD de MES de AAAA a las HH:MM horas") y actualizar
   `fecha_audiencia` (formato AAAA-MM-DD) en el registro de la causa vía
   `registrar-causa`.
8. Se marca `resolucion_audiencia_estado: "guardada"` en el registro de la
   causa y se anota en la bitácora ("resolución que fija audiencia guardada,
   audiencia AAAA-MM-DD HH:MM").

## Integración en `gestion-causas-smu`

### Paso 2h.5 (nuevo, después de 2h "guardar la demanda")

Por cada causa que se acaba de registrar en esta corrida (no aplica a causas
ya registradas que solo se etiquetan/marcan procesadas en 2e):

- Si es la primera causa de la corrida que necesita este paso, abrir una
  pestaña en OJV y navegar a "Consulta causas" (reusar esa misma pestaña
  para el resto de causas de la corrida, recargando `indexN.php` entre cada
  una — mismo criterio que `buscador-causas-pjud` usa entre cortes).
- Ejecutar el procedimiento de la sección anterior.
- Si no hay Chrome conectado (falla la primera llamada a una herramienta
  `claude-in-chrome`): abortar el paso completo para el resto de la corrida
  (no solo para esta causa), dejar todas las causas nuevas de esta corrida
  con `resolucion_audiencia_estado: "pendiente"`, y anotar **una sola vez**
  en el resumen final que no se pudo intentar por falta de Chrome.
- Si aparece un captcha visual del WAF en algún punto: detener ese intento
  puntual, dejar esa causa `pendiente`, anotar en el resumen final, y seguir
  con la siguiente causa (no se aborta toda la corrida por esto, a
  diferencia del caso "sin Chrome").

### Paso 0c (nuevo, antes del paso 1 "buscar correos candidatos")

Antes de buscar correos nuevos, recorrer el registro de causas
(`registro_causas.json`) buscando las que tengan
`resolucion_audiencia_estado: "pendiente"` y reintentar el procedimiento
completo (sección "Mecanismo de descarga") para cada una. Mismo patrón que
el paso 0b existente para borradores de documentos sin enviar. Si no hay
Chrome conectado, saltar este paso igual que 2h.5 y anotarlo una sola vez.

### Ajuste al resumen final (paso 3 existente)

Agregar:
- Cuántas causas nuevas de esta corrida quedaron con la resolución guardada.
- Cuántas quedaron `pendiente` (sin indexar aún en el PJUD, sin la fila de
  resolución todavía, o por captcha) — con RIT de cada una.
- Cuántas causas pendientes de corridas anteriores se reintentaron en el
  paso 0c y con qué resultado.
- Si el paso completo se saltó esta corrida por falta de Chrome conectado.

## Qué NO cambia

- Creación de carpeta y guardado de la demanda (pasos 2g/2h) siguen igual.
- El borrador de documentos a solicitar (Fase 2, paso 2k) no depende de este
  paso nuevo — se redacta igual, tenga o no tenga ya la resolución.
- No hay backfill de causas registradas antes de esta funcionalidad.
- No se toca el calendario ni se envían correos (misma regla que el resto de
  `gestion-causas-smu`).

## Testing

- Tests unitarios de Python para: `mover-descarga` (mueve y renombra sin
  pisar, igual suite de casos que `copiar_archivo_local`/`guardar_adjunto`
  ya cubren en `tests/test_carpetas.py`), y para el parser de fecha/hora de
  audiencia a partir del texto de la resolución (casos: fecha simple, fecha
  con hora, texto sin fecha reconocible → no debe fallar, debe devolver
  `None`).
- La parte de navegación/descarga en el navegador real (`claude-in-chrome`)
  no es testeable con pytest — se verifica manualmente, como ya ocurre con
  `buscador-causas-pjud`. El diseño ya fue validado en vivo con un caso real
  (RIT O-496-2026) durante esta sesión de brainstorming.
