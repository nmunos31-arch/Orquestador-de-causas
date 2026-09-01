# Contexto de corrida y fases paralelas (2026-09-01)

Ver contexto general en
`Actualizador de informes/docs/2026-08-27-orquestador-gestion-causas-design.md` y las dos
optimizaciones hermanas ya implementadas:
`2026-08-28-goteo-incremental-y-acuerdo-pago-design.md` y
`2026-08-28-cache-calendario-por-corrida-design.md`. Este spec cubre una idea que planteó
Nico el 2026-09-01: agregar una fase previa que recopile la información común a todas las
fases, y a partir de ahí dejar correr en paralelo a las que puedan.

## Motivación

El orquestador despacha 4 subagentes estrictamente en serie
(`calendario → smu → goteo → agenda`), y cada uno **redescubre por su cuenta** información
que es idéntica para toda la corrida:

- **La fecha de hoy.** `calendario.md` paso 0 la calcula para saber si es lunes; `goteo.md`
  paso 2 la calcula para `fecha_corte` y `goteo_ultima_revision`; `agenda.md` la usa para
  comparar contra los hitos de 14 días corridos y 4 días hábiles. Una corrida que cruza la
  medianoche puede terminar con dos fases usando fechas distintas — lo que ensucia
  `goteo_ultima_revision`, que es justamente el campo del que depende el filtro incremental
  de la corrida siguiente.
- **El calendario.** El cache de eventos lo genera `goteo` en su paso 1 y lo consume
  `agenda` con un fallback explícito "por si goteo falló antes de llegar a ese paso". Es un
  acoplamiento frágil: `agenda` depende de un **efecto secundario** de `goteo`. Además
  `calendario` (Fase 0) hacía su propia llamada a la API (`eventos-calendario
  --dias-adelante 90`) sobre un rango que ya está contenido en el cache de 200 días.
- **El estado de los tokens.** Los 4 subagentes tienen un "paso 0" que explica qué hacer si
  un comando se queda esperando un login interactivo. El problema real es que
  `obtener_credenciales()` llama a `flow.run_local_server(port=0)`, que en una tarea
  desatendida **no vuelve nunca**: con un token vencido, la corrida podía colgarse cuatro
  veces seguidas antes de llegar al panel.

## Diseño

Orden nuevo de una corrida:

```
contexto → calendario → smu → (goteo ‖ agenda) → panel
```

### Nuevo comando CLI: `contexto-corrida`

```
python -m gestion_causas.cli contexto-corrida --salida "gestion_causas/_contexto_corrida.json"
```

Resuelve, en una sola invocación:

1. `fecha_hoy`, `dia_semana` y `es_lunes`.
2. El estado de los 3 tokens (`gmail_trabajo`, `calendar`, `personal`), cada uno como
   `{ok, email, error}`, validando además que el token esté atado a la cuenta esperada
   (`nmunoz@gomezyriesco.cl` los dos primeros, `nmunos31@gmail.com` el tercero).
3. El cache de eventos de calendario (200 días), si el token de Calendar sirve.

Escribe `_contexto_corrida.json` y lo imprime a stdout. **Código de salida `1`** si Gmail de
trabajo o Calendar no están disponibles — el orquestador aborta la corrida y manda el panel
avisando, en vez de despachar 4 subagentes que van a fallar uno por uno. Un fallo del token
personal **no** da salida `1`: solo afecta el envío del panel al final.

### Diagnóstico no interactivo

`obtener_credenciales()` (y `construir_servicio()` / `diagnostico()`) de los tres clientes
gana `permitir_login: bool = True`. Con `permitir_login=False`, cuando el token no existe o
no se puede refrescar, **levanta `RuntimeError`** en vez de abrir el navegador. El default
`True` deja intacto el uso interactivo de siempre (`diagnostico`, `diagnostico-calendario`,
`diagnostico-personal` corridos a mano por Nico para autorizar un token).

Efecto lateral útil: como el contexto hace una llamada real a la API al principio, deja los
tokens refrescados antes de que `goteo` y `agenda` arranquen en paralelo — se evita que dos
procesos intenten refrescar y reescribir el mismo `token_*.json` a la vez.

### `eventos-calendario` gana `--desde-cache`

Mismo patrón que ya tenía `buscar-audiencia-por-rit`. El filtro por empresa/RIT se factorizó
a `calendar_client.filtrar_empresas_interes(eventos)`, que ahora usan tanto la variante que
llama a la API como `eventos_empresas_interes_desde_cache()` — mismo criterio, sin duplicar.

Para que el consumidor pueda saber si el cache le sirve, `guardar_cache_eventos()` ahora
graba también `desde` y `hasta`. Si el rango pedido no está contenido en el del cache (ej.
`--dias-atras > 0`, o un `--dias-adelante` mayor), el comando **falla con error claro** en
vez de devolver un resultado parcial en silencio; el llamador decide si cae de vuelta a la
API.

### Escritura serializada del registro

Era el único bloqueo real que quedaba para el paralelismo: `registrar_causa()` hacía
lectura del archivo completo → merge → reescritura completa, sin lock. Con `goteo` y
`agenda` corriendo a la vez, una escritura pisa a la otra **aunque toquen causas distintas**
(verificado: sin lock, de dos escrituras simultáneas sobrevive una sola).

`registro.py` gana un contextmanager `_lock(ruta)` sin dependencias nuevas: archivo
centinela `<ruta>.lock` creado con `O_CREAT | O_EXCL`, reintento cada 50 ms hasta 30 s, y
expiración por antigüedad (un `.lock` de más de 120 s se considera huérfano de un proceso
que murió sin liberarlo, y se borra). Envuelve los tres ciclos leer-modificar-escribir del
módulo: `registrar_causa`, `registrar_eerr_recibido` y `registrar_aviso`. Además `_guardar`
pasa a ser atómico (`.tmp` + `os.replace`), para que un corte a mitad no deje el registro
truncado.

`bitacora.registrar()` queda como está: abre en modo `"a"` y escribe una línea corta desde
un proceso efímero.

## Qué se paraleliza y qué no

**`goteo ‖ agenda`: sí.** No tienen dependencia de datos entre sí una vez que el contexto
está resuelto — `goteo` escribe `goteo_ultima_revision` y `estado_acuerdo`; `agenda` escribe
`oferta_borrador_creado` y `minuta_ejecutada`, y ninguno lee los campos del otro. Se
descartó la objeción de que la minuta de `agenda` necesitara los documentos que `goteo` baja
esa misma mañana: la minuta se dispara 4 días hábiles antes de la audiencia, no el día en
que llega un documento (criterio confirmado por Nico el 2026-09-01).

**`calendario ‖ smu`: no.** Los dos dan de alta causas nuevas y los dos escriben el Informe
de Juicios Vigentes vía `actualizar_informe_juicios.py` (un `.xlsx` que no tolera dos
escritores), y los dos pueden descubrir la **misma** causa — uno por el calendario y el otro
por correo — creando carpeta y fila duplicadas. Siguen en serie, y antes de las otras dos
porque `goteo` y `agenda` trabajan sobre las causas que ellos registran.

## Por qué un comando CLI y no un 5º subagente

La fase de contexto es puramente mecánica: 4 llamadas determinísticas y un JSON. Un
subagente pagaría un contexto de modelo completo para eso y agregaría una superficie más
donde algo puede desviarse del guion. El orquestador lo invoca directo, igual que ya invoca
`panel-html` y `enviar-panel`.

## Fuera de alcance

- No cambia la lógica de negocio de ninguna fase: mismos filtros de dominio y de asunto,
  mismos criterios de tipo de audiencia, misma cadencia de hitos, mismo formato del panel.
- No se agregan campos a `registro_causas.json`.
- No se agregan dependencias de terceros (el lock es stdlib).
- No se cachea entre corridas: el contexto se regenera desde cero en cada una, igual que ya
  hacía el cache de calendario.
- `agenda` **conserva** su fallback a la llamada en vivo cuando no hay cache — sigue
  sirviendo para correrla suelta, a mano, fuera del orquestador.
