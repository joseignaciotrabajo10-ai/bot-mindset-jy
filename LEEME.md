# Bot de respuestas automáticas — Instagram Jose Ignacio Mindset (@joseignacioym)

> Copia del bot de Iron Element, adaptada. Diferencia clave: funciona con el token **EAA…** (usuario del sistema, app *Bot MINDSET JY*), que usa la API de Facebook y **no vence**, así que no necesita `RENDER_API_KEY` ni renovación. Requiere `IG_ACCOUNT_ID=17841400050626344` en el `.env` / Render. Con un token **IGAA…** funciona igual que el de Iron Element.


Cuando alguien escribe por DM con palabras como *precio, planes, valores, cuánto sale…* o *horario, a qué hora abren…*, el bot responde al tiro con un **texto de bienvenida + una imagen**.

## Archivos

| Archivo | Para qué sirve |
|---|---|
| `respuestas.json` | **Lo que vas a editar**: palabras clave, textos e imágenes de cada respuesta |
| `imagenes/` | Aquí van `planes.jpg` y `horarios.jpg` (o los nombres que pongas en el JSON) |
| `bot.py` | El servidor (no hace falta tocarlo) |
| `probar.py` | Simula un DM para probar sin Instagram |
| `.env.example` | Plantilla de las claves de Meta → se copia como `.env` |

## Editar respuestas

En `respuestas.json`:
- `palabras_clave`: da lo mismo si van con mayúsculas o tildes ("Precíos" = "precios").
- `respuesta`: lista de mensajes que se mandan en orden (`texto` y/o `imagen`). En el texto, `{nombre}` se reemplaza por el primer nombre de quien escribe (si Instagram no lo entrega, queda solo "¡Hola!").
- `respuesta` también acepta `{"audio": "archivo.m4a"}` (archivos en la carpeta `audios/`: .m4a, .mp3, .aac o .wav, menos de 25 MB). Se manda por DM y en respuestas a historias; no en el DM que sale de un comentario (Meta solo permite texto ahí). Hoy: `iron-element.m4a` en planes y `recurrente.m4a` en pago recurrente.
- `excepto` (opcional): palabras que anulan la regla. Por ejemplo, "planes" tiene `pase`, para que *"cuánto sale el pase diario"* responda solo lo del pase.
- Para revisar todas las respuestas en formato fácil de leer: `python3 generar_catalogo.py` genera `CATALOGO.md`.
- Si un mensaje activa varias reglas (ej. "valores y horarios"), se manda un solo saludo y cada imagen una sola vez.
- `horas_pausa_si_responde_equipo`: si alguien del gym escribe a mano en una conversación (desde la app de Instagram o Meta Business Suite), el bot deja de responderle a esa persona por estas horas (hoy: 3), para no pisarse con el equipo. En los logs aparece `El equipo le respondió a ...`. Si el equipo responde dentro de los 30 segundos siguientes a una respuesta del bot, no se detecta (se confunde con el bot).
- `seguimiento`: si la persona no vuelve a escribir en `minutos` (10) después de recibir alguna de las respuestas de `despues_de` (hoy: planes), el bot le manda `texto` preguntando si le interesó algún plan. Máximo una vez al día por persona, y no se envía si el equipo ya respondió a mano. Para apagarlo: `"activo": false`. Para usarlo también después de otro tema, agrega su nombre a `despues_de` (ej. `"pase diario"`).
- `comentarios`: si alguien comenta un post o reel con una palabra clave, el bot le manda un DM (respuesta privada) con el tema que corresponde y responde el comentario con `respuesta_publica`. Meta permite **un solo mensaje de texto** por comentario, por eso las reglas con imagen tienen `texto_comentario` (ej. planes invita a responder "SÍ"; cuando la persona contesta "sí" por DM, le llega la respuesta completa con la imagen). Para apagarlo: `"activo": false`.
- `minutos_entre_respuestas`: para no repetirle lo mismo a la misma persona (hoy: 180 min = 3 horas).
- `bienvenida`: respuesta para mensajes **sin** palabra clave. Está apagada (`"activa": false`) para que el bot no conteste cuando te escriben otras cosas.

Los cambios se aplican sin reiniciar el bot.

## Probar en tu Mac

```bash
python3 bot.py
```
Y en otra terminal:
```bash
python3 probar.py "hola cuánto valen los planes?"
```
Sin `.env`, el bot está en **modo prueba**: no envía nada y solo muestra lo que respondería.

## Conectarlo a Instagram (una sola vez)

1. **Cuenta profesional**: la cuenta de Instagram del gym tiene que ser de *Empresa* o *Creador*.
2. **Permitir el acceso a los mensajes**: en la app de Instagram → Configuración → Mensajes y respuestas a historias → Herramientas conectadas → activar *Permitir acceso a los mensajes*.
3. **Crear la app en Meta**: en developers.facebook.com → *Crear app* → caso de uso **"Administrar mensajes y contenido en Instagram"**. Dentro de la app: *API setup with Instagram login* → agregar la cuenta del gym → **Generar token**. Ese es el `ACCESS_TOKEN`. En esa misma pantalla, la *Clave secreta de la app de Instagram* es el `APP_SECRET` (ojo: no es la de Configuración → Básica).
4. **Subir el bot a internet** (necesita una dirección https pública). Lo más fácil es **Render.com**: subes esta carpeta a GitHub → *New Web Service* → Start command `python3 bot.py` → en *Environment* cargas `ACCESS_TOKEN`, `APP_SECRET`, `VERIFY_TOKEN` (una palabra secreta que inventes) y `PUBLIC_URL` (la dirección que te da Render).
   - El plan gratis de Render se "duerme" cuando no hay movimiento y la primera respuesta puede tardar casi un minuto. Para que conteste siempre al tiro conviene el plan de ~US$7 al mes.
5. **Conectar el webhook**: en la app de Meta → Instagram → Webhooks → URL `https://TU-DIRECCION/webhook` + el mismo `VERIFY_TOKEN` → *Verificar* → suscribirse al campo **`messages`**.
6. **Publicar la app y conectarla al portfolio del gym**: con la app **publicada** y como **propiedad del portfolio "Iron Element Training Puerto Montt"** (el mismo dueño del Instagram), el bot responde a **cualquier persona** con el acceso estándar. Comprobado el 24 oct. 2026 con una cuenta que no era tester. **No hizo falta la revisión de Meta ni registrarse como "Tech Provider"**, que no se puede deshacer, así que no lo hagas a menos que el bot deje de responder a quienes no son testers. Los textos para una eventual revisión quedaron en `REVISION_META.md`.

## Ojo

- Meta solo deja responder a quien escribió primero y dentro de las 24 horas siguientes. El bot cumple eso solo, porque únicamente contesta mensajes que llegan.
- El token de Instagram dura **60 días**, pero el bot lo **renueva solo cada 3 días** y guarda el nuevo en Render (variable `ACCESS_TOKEN`). Para eso, en Render tiene que estar la variable `RENDER_API_KEY` (Render → Account Settings → API Keys). En los logs aparece `Token renovado: vence en 59 días`. Si dice `ERROR al renovar el token`, hay que generar uno nuevo en Meta y pegarlo en Render.
- La variable `TOKEN_RENOVADO` la crea y actualiza el bot solo (fecha de la última renovación); no hay que tocarla.

## Ideas pendientes (conversadas, sin hacer)

- **Avisos por Telegram** (a un grupo del equipo) cuando una conversación quede sin respuesta del bot ni del equipo por 1 hora. Opcional: resumen diario y horario de avisos.
- **Agradecimiento automático** por DM cuando alguien etiqueta al gym en su historia.
- **Repost de historias con aprobación** (vía Telegram). El botón nativo "Agregar a tu historia" no existe en la API; republicar quedaría sin el recuadro del autor.
- **Respuestas con IA** para preguntas sin palabra clave, usando solo la información del gym.
