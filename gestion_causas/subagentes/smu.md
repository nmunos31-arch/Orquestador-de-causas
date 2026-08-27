# Subagente "smu" (Fases 1-2) del orquestador gestion-causas-orquestador

Fases 1 y 2 del proyecto "Gestión automática de causas nuevas desde la casilla del
trabajo" — ver el diseño completo en
`C:\Users\usuario\.claude\plans\1-contrato-de-trabajo-streamed-pizza.md` y en
`Actualizador de informes\docs\2026-08-27-orquestador-gestion-causas-design.md`. Este
archivo es el prompt que el orquestador (`gestion-causas-orquestador`) despacha como
subagente en la Fase "smu" de cada corrida, siempre después de "calendario" y antes de
"goteo".

Objetivo de esta corrida: por cada correo nuevo de una demanda contra Rendic Hermanos,
Alvi, Super 10, Servicios Logísticos Santiago, Preunic o Salcobrand que llegue a
`nmunoz@gomezyriesco.cl`, registrar la causa (registro local siempre; Excel solo para las
4 primeras — ver paso 2i), crear su carpeta en Minutas, guardar la demanda adjunta, dejar
un borrador con los documentos de prueba a solicitar, y etiquetar la cadena con el color
de la empresa. **Nunca** envía correos ni borra nada (ni correos ni archivos), y no toca
el calendario.

**Regla de origen de la cadena** (acordada con el usuario): solo se procesan como causa
nueva las cadenas cuyo **primer mensaje** fue enviado por alguien de dominio `@smu.cl` o
`@sb.cl` — son los dos dominios desde los que las empresas mandantes derivan sus causas.
Las cadenas cuyo primer mensaje es de `@gomezyriesco.cl` son **internas** (Nico
discutiendo la causa con Román y el equipo) y **no se procesan aquí** — ver paso 2b. Esas
cadenas internas sí importan para el proyecto, pero las usa la tarea `gestion-causas-agenda`
(ahí es donde va el borrador con los montos demandados, respondiendo dentro de esa misma
cadena en vez de crear una nueva).

**Excepción (acordada con el usuario el 2026-08-17):** a veces la persona de la empresa
mandante le manda el cuadro-resumen **solo a Román** y no copia a Nico, así que lo primero
que aparece en la casilla de Nico es la respuesta de Román (dominio `@gomezyriesco.cl`)
con el cuadro-resumen de smu.cl/sb.cl citado adentro. Eso **no** es una cadena interna, es
el mismo tipo de intake normal — ver el detalle de cómo reconocerlo en el paso 2b.

Toda la parte mecánica se hace con el CLI `gestion_causas.cli` (paquete en
`Actualizador de informes\gestion_causas`), corrido con Bash/PowerShell desde
`Actualizador de informes` como directorio de trabajo:
`python -m gestion_causas.cli <subcomando> ...` — cada llamada imprime JSON a stdout.
Usa `python -m gestion_causas.cli --help` si necesitas recordar los argumentos exactos
de un subcomando.

## 0. Prerrequisito: token autorizado con la cuenta del trabajo

Este paso **no lo hace la tarea programada** — requiere un login interactivo en el
navegador que solo puede hacer un humano. Si en cualquier paso de abajo un comando del
CLI se queda esperando sin responder o falla porque no puede abrir un navegador,
significa que el token todavía no fue autorizado: **detente de inmediato, no reintentes,
y deja como resumen final** "La tarea no pudo autenticarse contra
nmunoz@gomezyriesco.cl — falta correr `python -m gestion_causas.cli diagnostico` una
vez de forma interactiva para autorizar el token." No hagas nada más en esa corrida.

Si el diagnóstico responde, valida que el JSON tenga
`"email": "nmunoz@gomezyriesco.cl"`. Si dice otra cuenta, detente igual y avisa — nunca
sigas operando sobre la cuenta equivocada.

## 0b. Avisar sobre borradores sin enviar de corridas anteriores

Esta tarea nunca envía correos — cada borrador de documentos que crea (paso 2k.5) queda
esperando a que Nico lo revise y lo envíe a mano. Como es fácil que se acumulen sin que
Nico se dé cuenta, **antes de buscar correos nuevos** corre:
```
python -m gestion_causas.cli verificar-borradores-pendientes
```
Esto revisa, para cada causa del registro que tiene un `borrador_documentos_draft_id`
guardado (ver paso 2k.5), si ese borrador todavía existe en Gmail. Devuelve:
- `pendientes`: causas cuyo borrador sigue ahí sin enviar — **guarda esta lista**, va en el
  resumen final (paso 3) como aviso explícito, con RIT, empresa y demandante de cada una.
- `limpiados`: causas cuyo borrador ya no existe (Nico lo envió o lo borró) — el comando ya
  limpió el campo solo, no hace falta hacer nada con esto salvo mencionarlo si es útil.

## 1. Buscar correos candidatos

Ejecuta:
```
python -m gestion_causas.cli buscar-hilos --query "from:(smu.cl OR sb.cl OR gomezyriesco.cl) subject:DEMANDA after:2026/07/01 -label:\"Procesado-GestionCausas\"" --max-resultados 50
```
Se incluye `gomezyriesco.cl` en la búsqueda a propósito, aunque esas cadenas no se
procesan (ver paso 2b) — es la única forma de que la etiqueta `Procesado-GestionCausas`
también las alcance y no las siga trayendo en cada corrida. El filtrado real de si una
cadena es válida (smu.cl/sb.cl) o interna (gomezyriesco.cl) se hace por hilo, no en esta
búsqueda.

El `after:2026/07/01` es un límite acordado con el usuario: no procesar correspondencia
anterior a julio de 2026. Razón: causas de meses anteriores que ya se resolvieron y se
sacaron del Excel no se detectarían como duplicado (el chequeo de duplicado del paso 2i
solo mira lo que hoy está en el Excel), así que revisarlas podría crear una fila y una
carpeta nuevas para una causa que en realidad ya está cerrada. Para causas viejas que
siguen vivas, no hace falta ir a buscarlas: en algún momento llega correspondencia nueva
en esa cadena (dentro de la ventana de fecha) y ahí se revisa con el chequeo normal de
duplicado. No cambies esta fecha sin que el usuario lo pida.

Si `total` es 0, termina la corrida y entrega un resumen de "sin correos nuevos". El
volumen de correspondencia de julio-agosto es grande (puede rondar el límite de 50) — no
esperes vaciarlo en una sola corrida. El límite de 50 por corrida y la etiqueta de
control aseguran que cada corrida avance sin reprocesar lo ya visto; a las causas que ya
están registradas les basta con etiquetarlas y marcarlas procesadas (pasos 2e, 2l-2n),
sin recrear carpeta ni fila.

## 2. Por cada hilo encontrado

a. Trae todos los mensajes del hilo:
   ```
   python -m gestion_causas.cli leer-hilo --thread-id <id>
   ```
   Usa siempre el **primer mensaje del hilo** (el reenvío original con el cuadro
   resumen) para extraer los datos de la causa — los mensajes siguientes del mismo
   hilo suelen ser el CECO, documentos, o idas y vueltas.

b. **Determina el origen de la cadena.** Mira el campo `sender` del primer mensaje
   (paso 2a) y extrae el dominio (lo que sigue después de `@`):
   - Si es `smu.cl` o `sb.cl` → cadena válida, sigue con el paso 2c.
   - Si es `gomezyriesco.cl` → **antes de concluir que es interna**, revisa el cuerpo
     de ese primer mensaje: a veces la persona de la empresa mandante le escribe el
     cuadro-resumen **solo a Román** (sin copiar a Nico), y lo que Nico ve como
     "primer mensaje" del hilo es en realidad la respuesta de Román a esa persona
     (ej. "Estimada Daniela, acusamos recibo...") con el correo original y su cuadro
     resumen completo citado/anidado abajo (formato `> El ... escribió:` o similar).
     En ese caso la cadena **sí es válida** — trátala igual que si el primer mensaje
     fuera de smu.cl/sb.cl y sigue con el paso 2c, extrayendo el cuadro resumen del
     texto citado. La señal para reconocer este caso: el cuerpo del primer mensaje de
     Román es corto (acuse de recibo, "reclamaremos", etc.) y contiene, citado, un
     cuadro resumen completo (Rit, Tribunal, Demandante, etc.) firmado por alguien de
     dominio `@smu.cl` o `@sb.cl`.
     Si en cambio el primer mensaje de `gomezyriesco.cl` es Nico o Román **iniciando**
     una conversación (sin nada de smu.cl/sb.cl citado) — típicamente Nico
     preguntándole a Román sobre estrategia de una causa que ya está registrada
     (ofrecimientos, cómo contestar, etc.) — ahí sí es cadena **interna**. Marca el
     hilo como procesado (paso 2n) y sigue con el siguiente hilo, sin hacer nada más
     aquí — esta cadena la usa `gestion-causas-agenda`, no esta tarea.
   - Cualquier otro dominio → no es una demanda-notificación válida. Marca como
     procesado (paso 2n) y sigue con el siguiente, sin hacer nada más.

c. **Extrae el cuadro resumen** (Rit, Tribunal, Demandante, Rut, Fecha audiencia,
   Demandada, Cuantía, Conceptos demandados, Materia, Fecha de ingreso al Pjud, Hechos)
   aplicando exactamente las reglas de
   `Actualizador de informes\docs\2026-07-07-informe-juicios-email-design.md`
   (secciones "Mapeo de columnas" y "Plantilla del Resumen"). El asunto puede no
   coincidir con el RIT real del cuerpo — usa siempre el RIT del cuadro.

d. **Filtra por empresa.** La Demandada debe ser una de estas 6 (compara sin
   importar mayúsculas/tildes/razón social completa tipo "S.A."):
   - Rendic Hermanos
   - Alvi
   - Super 10
   - Servicios Logísticos Santiago
   - Preunic
   - Salcobrand

   Si la Demandada es otra empresa, marca el hilo como procesado (paso 2n) y sigue con
   el siguiente, sin hacer nada más. **Recuerda para el paso 2i:** Preunic y Salcobrand
   pasan por todas las fases igual que las otras 4, pero **nunca** se escriben en el
   Informe de Juicios Vigentes (ese Excel es solo del negocio de SMU).

e. **Verifica si ya está registrada:**
   ```
   python -m gestion_causas.cli causa-ya-registrada --rit "<rit>"
   ```
   Si `ya_registrada` es true, salta directo al paso 2l (etiquetar) y 2n (marcar
   procesado) — no dupliques carpeta, fila ni borrador de documentos. (El script del
   Excel igual detecta el duplicado, pero evitamos trabajo de más.)

f. **Busca el CECO.** Puede venir en el primer mensaje ("nos confirme el CECO
   [código]") o puede faltar. Si falta, revisa los demás mensajes del mismo hilo (ya
   los tienes de 2a) por si alguien ya lo contestó. Si de verdad no está en ningún
   mensaje, sigue igual — el CECO se completa en una corrida futura cuando llegue.

g. **Crea la carpeta de la causa** (apellido del demandante principal, sin el RUT):
   ```
   python -m gestion_causas.cli crear-carpeta --apellido "<apellido>" --empresa "<demandada>" --rit "<rit>"
   ```
   El comando primero busca si ya existe una carpeta en Minutas para este RIT (mira
   tanto el nombre de la carpeta como el nombre de los archivos que ya tiene adentro
   — causas que Nico ya armó a mano antes de esta automatización casi siempre traen el
   RIT en el nombre de la minuta o del "E-Acompaña documentos...", aunque la carpeta
   misma se llame solo "Apellido con Empresa") y la reusa en vez de crear una
   duplicada — revisa el campo `reusada` de la respuesta. **Ojo:** en el caso raro de
   que la carpeta vieja no tenga el RIT en ningún archivo (carpeta casi vacía, o
   documentos sin el RIT en el nombre), no la va a encontrar y va a crear una carpeta
   nueva al lado — si notas que el comando creó una carpeta que no esperabas para esa
   causa, detente, no sigas guardando documentos ahí, y anótalo en el resumen final
   para que Nico lo revise a mano.
   Usa la ruta devuelta (`carpeta`) para el paso siguiente.

h. **Guarda la demanda adjunta.** De los `adjuntos` del primer mensaje (paso 2a),
   identifica el PDF de la demanda (normalmente el único PDF grande adjunto al
   reenvío; ignora imágenes de firma, el CLI ya las filtra automáticamente) y
   guárdalo como `demanda.pdf`:
   ```
   python -m gestion_causas.cli guardar-adjunto --message-id <id-del-mensaje> --attachment-id <id> --carpeta "<carpeta>" --nombre-archivo demanda.pdf
   ```
   Si `guardado` es false porque "parece firma/logo" y en realidad sí era la demanda
   (raro, pero puede pasar con adjuntos chicos), repite el comando agregando
   `--forzar`. Si no hay ningún adjunto que parezca la demanda, sigue sin ella —
   anótalo en el resumen final para que Nico la suba a mano.

i. **Escribe la fila en el Informe de Juicios Vigentes — solo si la Demandada es
   Rendic Hermanos, Alvi, Super 10 o Servicios Logísticos Santiago.** Si es Preunic o
   Salcobrand, **sáltate este paso por completo** (no ejecutes el script) y sigue
   directo al 2j; anota en el resumen final que esa causa no aplica a Excel.

   Para las 4 empresas de SMU: arma el JSON con
   `{"juzgado", "materia", "causa", "cuantia", "resumen"}` (mismas reglas de la
   Plantilla del Resumen), guárdalo en un archivo temporal, y corre:
   ```
   python "..\actualizar_informe_juicios.py" --json-file "<ruta_al_json>"
   ```
   (ruta relativa desde `gestion_causas`, o usa la ruta absoluta de
   `Actualizador de informes\actualizar_informe_juicios.py`). Código de salida 0 o 3
   (duplicado) → continúa. Código 1 (Excel abierto/bloqueado, o datos incompletos) →
   **no marques el hilo como procesado**, anota el error en el resumen final, y sigue
   con el siguiente hilo.

j. **Registra la causa** en el estado local (para reuso del EERR y para
   `causa-ya-registrada` de corridas futuras). Incluye `fecha_audiencia` si el cuadro la
   trae (la usa la Fase 4 más abajo) en formato AAAA-MM-DD — si dice "Pendiente
   reclamación" o algo no-fecha, omite el campo. Incluye también `"aplica_excel": false`
   si la empresa es Preunic o Salcobrand (o `true` para las otras 4, por claridad):
   ```
   python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con empresa, ceco (si hay), demandante, carpeta, fecha_despido, fecha_audiencia (si hay), thread_id, tiene_demanda, aplica_excel>"
   ```

k. **Redacta el borrador de documentos a solicitar (Fase 2)** — solo si guardaste la
   demanda en el paso 2h (sin demanda no hay de dónde sacar qué se demanda además del
   cuadro; si no hay demanda, sáltate este paso y anótalo en el resumen final). Aplica
   igual para las 6 empresas, incluidas Preunic y Salcobrand.

   1. Lee el PDF de la demanda que acabas de guardar para entender qué se demanda,
      más allá de lo que ya viene resumido en "Conceptos demandados" del cuadro.
   2. Parte de esta lista base, en este orden exacto:
      ```
      1. Contrato de trabajo y anexos
      2. Carta de despido
      3. Finiquito
      4. EERR del local de los años 2024, 2025 y 2026
      5. Comparativa de dotación del local antes y después del despido
      6. Testigos
      7. Absolvente
      ```
   3. **Reuso del EERR**: si tienes CECO y fecha de despido, corre
      ```
      python -m gestion_causas.cli buscar-eerr-reusable --ceco "<ceco>" --fecha-despido "<AAAA-MM-DD>"
      ```
      Si `reusable` no es null: **quita el punto 4** de la lista, y copia el EERR de la
      causa anterior a esta carpeta (busca su carpeta y el nombre del archivo con
      `python -m gestion_causas.cli obtener-causa --rit "<reusable.rit_causa>"`, mira su
      campo `carpeta`, y lista sus archivos con `listar-carpeta` para identificar cuál
      parece el EERR):
      ```
      python -m gestion_causas.cli copiar-archivo --origen "<carpeta de esa causa>\<archivo EERR>" --carpeta-destino "<carpeta de esta causa>" --nombre-archivo "<mismo nombre>"
      ```
      Anota en el resumen final "EERR reusado del CECO X (causa <rit_causa>)".
   4. **Ajustes según lo demandado** (compara contra "Conceptos demandados" del cuadro
      y lo que leíste en la demanda):
      - Si se demanda **diferencia en la base de cálculo** de la indemnización por
        años de servicio o de la sustitutiva de aviso previo: agrega
        *"Últimas 6 liquidaciones de remuneraciones"* como punto nuevo, **antes** de
        Testigos y Absolvente.
      - Si se demanda cualquier otra cosa además de lo típico (ej. un descuento
        indebido en el finiquito por un préstamo, una diferencia por horas
        extraordinarias, etc.): agrega, en el mismo estilo escueto (solo el nombre del
        documento, sin explicar por qué), el antecedente que permita desvirtuarlo o
        estudiar su procedencia — ej. "Antecedentes de la procedencia del préstamo" —
        también antes de Testigos y Absolvente.
   5. Redacta el borrador **como respuesta dentro de la misma cadena**, dirigido a
      quien corresponda en el hilo (normalmente la persona de SMU/sb.cl que envió la
      demanda, o quien aparezca en copia pidiendo que le ayuden con los antecedentes —
      usa el criterio del hilo). El cuerpo del borrador es **únicamente la lista
      numerada de documentos**, sin saludo, sin explicación, sin firma — nada más que
      la lista. Escribe el cuerpo a un archivo temporal, una línea por documento (con o
      sin numeración manual, da igual), y crea el borrador con `--lista` para que Gmail
      la reciba como lista numerada nativa (`<ol>`) — así Nico puede insertar o quitar
      un documento en el medio sin tener que renumerar el resto a mano:
      ```
      python -m gestion_causas.cli crear-borrador --destinatario "<correo>" --asunto "Re: <asunto original>" --cuerpo-archivo "<ruta.txt>" --thread-id <id> --lista
      ```
      El comando ya evita duplicar el borrador si la cadena ya tiene uno — no te
      preocupes por eso, pero revisa `creado` en la respuesta para el resumen final.
      Si `creado` es true, guarda el `draft_id` devuelto en el registro de la causa (para
      que la próxima corrida pueda avisar si Nico todavía no lo envió — ver paso 0b):
      ```
      python -m gestion_causas.cli registrar-causa --rit "<rit>" --datos-json "<json con solo {\"borrador_documentos_draft_id\": \"<draft_id>\"}>"
      ```

l. **Etiqueta el hilo con el color de la empresa:**
   ```
   python -m gestion_causas.cli etiquetar-empresa --thread-id <id> --empresa "<una de las 6 exactas: Rendic Hermanos | Alvi | Super 10 | Servicios Logísticos Santiago | Preunic | Salcobrand>"
   ```
   Las etiquetas "Preunic" y "Salcobrand" ya existían en la casilla antes de esta
   automatización — el comando las reusa tal cual (con su color actual), no las
   recrea.

m. **Anota en la bitácora** cada acción relevante que tomaste para esta causa (fila
   agregada/duplicada/no-aplica-Excel, carpeta creada, demanda guardada o faltante,
   CECO pendiente, borrador de documentos creado o no):
   ```
   python -m gestion_causas.cli bitacora --rit "<rit>" --mensaje "<qué se hizo>"
   ```

n. **Marca el hilo como procesado** — solo si no hubo error de Excel bloqueado en 2i:
   ```
   python -m gestion_causas.cli marcar-procesado --thread-id <id>
   ```

## 3. Resumen final

Tu **último mensaje** de esta ejecución es el resumen que el orquestador va a copiar tal
cual a la sección "Fase smu" del panel de estado — que sea breve y legible, con:
- **Primero, si el paso 0b encontró `pendientes`:** avisa explícitamente cuáles borradores
  de documentos siguen sin enviar de corridas anteriores (RIT, empresa, demandante) — esto
  va destacado, no mezclado con el resto, porque es lo que más fácil se le puede pasar a
  Nico.
- Cuántas causas nuevas se registraron (RIT, empresa, si la demanda se guardó o
  falta, si el CECO se guardó o falta, si aplicaba o no al Excel).
- Cuántos borradores de documentos se crearon (Fase 2), cuántos se saltaron por no
  tener demanda, y en cuántos se reusó el EERR de una causa anterior (con el RIT de
  esa causa).
- Cuántas cadenas internas (`@gomezyriesco.cl`) se encontraron y se dejaron sin
  procesar (solo el conteo, no hace falta detallarlas — las usa `gestion-causas-agenda`).
- Cuántos hilos eran de otra empresa (fuera del filtro de 6) y se ignoraron.
- Cuántos eran RIT duplicado.
- Cuántos quedaron pendientes por error (Excel bloqueado) — se reintentan solos en
  la próxima corrida.
- Si hubo el problema de autenticación del paso 0, dilo primero y no sigas.

No hace falta ser extenso si no hubo novedades.