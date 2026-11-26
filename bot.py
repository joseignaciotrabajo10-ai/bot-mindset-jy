"""Bot de respuestas automáticas para los DMs y comentarios de Instagram de Jose Ignacio Mindset.

Recibe los avisos (webhooks) que manda Meta cuando alguien escribe por DM,
busca palabras clave definidas en respuestas.json y contesta con texto + imagen.

Solo usa la librería estándar de Python (no hay que instalar nada).
Si no hay ACCESS_TOKEN configurado, funciona en "modo prueba": no envía nada
y solo muestra en pantalla lo que habría respondido.
"""

import hashlib
import hmac
import json
import os
import re
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

CARPETA = os.path.dirname(os.path.abspath(__file__))
CARPETA_IMAGENES = os.path.join(CARPETA, "imagenes")
CARPETA_AUDIOS = os.path.join(CARPETA, "audios")
TIPOS_AUDIO = {".m4a": "audio/mp4", ".mp3": "audio/mpeg", ".aac": "audio/aac", ".wav": "audio/wav"}
ARCHIVO_RESPUESTAS = os.path.join(CARPETA, "respuestas.json")
API_VERSION = "v23.0"


def cargar_env():
    """Lee el archivo .env (si existe) y lo carga como variables de entorno."""
    ruta = os.path.join(CARPETA, ".env")
    if not os.path.exists(ruta):
        return
    with open(ruta, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            os.environ.setdefault(clave.strip(), valor.strip().strip('"').strip("'"))


cargar_env()
ACCESS_TOKEN = os.environ.get("ACCESS_TOKEN", "").strip()
# Meta firma los avisos con la clave secreta de la app; según la configuración
# puede ser la de Instagram o la de Facebook, así que se aceptan varias separadas por coma.
APP_SECRETS = [c.strip() for c in os.environ.get("APP_SECRET", "").split(",") if c.strip()]
APP_SECRET = ",".join(APP_SECRETS)
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
PORT = int(os.environ.get("PORT", "8000"))
MODO_PRUEBA = not ACCESS_TOKEN
# ID de la cuenta de Instagram (joseignacioym). Hace falta con el token de
# "inicio de sesión unificado" (empieza con EAA), que usa la API de Facebook.
IG_ACCOUNT_ID = os.environ.get("IG_ACCOUNT_ID", "").strip()
# Token con inicio de sesión de Instagram (IGAA...): API de Instagram, vence en 60 días.
# Token de usuario del sistema (EAA...): API de Facebook, no vence (no hay que renovarlo).
TOKEN_FACEBOOK = ACCESS_TOKEN.startswith("EAA")
API_BASE = f"https://graph.{'facebook' if TOKEN_FACEBOOK else 'instagram'}.com/{API_VERSION}"
CUENTA = IG_ACCOUNT_ID if TOKEN_FACEBOOK else "me"
# IDs con que Meta identifica a esta cuenta (se completan solos al arrancar).
MIS_IDS = {IG_ACCOUNT_ID} if IG_ACCOUNT_ID else set()
# Para guardar el token renovado en Render (RENDER_SERVICE_ID lo pone Render solo).
RENDER_API_KEY = os.environ.get("RENDER_API_KEY", "").strip()
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "").strip()
DIAS_ENTRE_RENOVACIONES = 3
try:
    ULTIMA_RENOVACION = float(os.environ.get("TOKEN_RENOVADO", "0"))
except ValueError:
    ULTIMA_RENOVACION = 0.0


def log(*partes):
    print(time.strftime("[%H:%M:%S]"), *partes, flush=True)


def normalizar(texto):
    """Minúsculas y sin tildes: 'Precíos' -> 'precios'."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def cargar_respuestas():
    with open(ARCHIVO_RESPUESTAS, encoding="utf-8") as f:
        return json.load(f)


def contiene(texto, palabras):
    return any(re.search(r"\b" + re.escape(normalizar(p)) + r"\b", texto) for p in palabras)


def buscar_reglas(texto, config):
    """Devuelve todas las reglas con alguna palabra clave en el texto
    (si preguntan precios y horarios a la vez, se responden ambos).
    Una regla no aplica si el texto trae alguna de sus palabras "excepto"
    (ej. "cuánto sale el pase diario" no debe responder con los planes).
    Una regla con "patron" se activa por una expresión regular (ej. un número de
    teléfono); si es "exclusiva", cuando aplica se responde solo esa."""
    normal = normalizar(texto)
    encontradas = []
    for regla in config["reglas"]:
        if contiene(normal, regla.get("excepto", [])):
            continue
        if contiene(normal, regla.get("palabras_clave", [])) or (
            regla.get("patron") and re.search(regla["patron"], texto)
        ):
            encontradas.append(regla)
    exclusivas = [r for r in encontradas if r.get("exclusiva")]
    return exclusivas or encontradas


# Para no contestar lo mismo varias veces seguidas a la misma persona.
_ultima_respuesta = {}
_candado = threading.Lock()


def puede_responder(usuario, nombre_regla, minutos):
    ahora = time.time()
    clave = (usuario, nombre_regla)
    with _candado:
        anterior = _ultima_respuesta.get(clave)
        if anterior and ahora - anterior < minutos * 60:
            return False
        _ultima_respuesta[clave] = ahora
        return True


# Para saber si un mensaje que salió de la cuenta lo mandó el bot o una
# persona del equipo: Meta avisa de ambos como "eco" (is_echo), así que se guardan
# los ids de los mensajes del bot y la hora del último envío a cada persona.
SEGUNDOS_ECO = 30  # un eco que llega hasta 30 s después de un envío del bot es del bot
_ids_del_bot = {}
_ultimo_envio_bot = {}
_pausados = {}


def marcar_envio_bot(destinatario, mid=None):
    ahora = time.time()
    with _candado:
        _ultimo_envio_bot[destinatario] = ahora
        if mid:
            _ids_del_bot[mid] = ahora
        for viejo in [m for m, t in _ids_del_bot.items() if ahora - t > 3600]:
            del _ids_del_bot[viejo]


def es_eco_del_bot(destinatario, mid):
    with _candado:
        return mid in _ids_del_bot or time.time() - _ultimo_envio_bot.get(destinatario, 0) < SEGUNDOS_ECO


def pausar(usuario, horas):
    with _candado:
        _pausados[usuario] = time.time() + horas * 3600


def en_pausa(usuario):
    with _candado:
        return time.time() < _pausados.get(usuario, 0)


def enviar(destinatario, mensaje, recipient=None):
    """Envía un mensaje por la API de Instagram. Con recipient={"comment_id": ...}
    es una "respuesta privada" a un comentario (un solo mensaje, solo texto)."""
    cuerpo = {"recipient": recipient or {"id": destinatario}, "message": mensaje}
    marcar_envio_bot(destinatario)  # antes de enviar: el eco puede llegar antes que la respuesta
    if MODO_PRUEBA:
        log("  [modo prueba] enviaría:", json.dumps(mensaje, ensure_ascii=False))
        return
    req = urllib.request.Request(
        f"{API_BASE}/{CUENTA}/messages",
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {ACCESS_TOKEN}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            respuesta = r.read().decode("utf-8")
        log("  enviado OK:", respuesta)
        try:
            marcar_envio_bot(destinatario, json.loads(respuesta).get("message_id"))
        except ValueError:
            pass
    except urllib.error.HTTPError as e:
        log("  ERROR al enviar:", e.code, e.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log("  ERROR de conexión:", e.reason)


def nombre_de_usuario(usuario_id):
    """Pide a Instagram el nombre de quien escribe (solo el primer nombre)."""
    if MODO_PRUEBA:
        return "Prueba"
    req = urllib.request.Request(
        f"{API_BASE}/{usuario_id}?fields=name,username",
        headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            datos = json.loads(r.read())
    except (urllib.error.URLError, ValueError) as e:
        log("  no se pudo obtener el nombre:", e)
        return ""
    return limpiar_nombre(datos.get("name") or "")


def limpiar_nombre(nombre):
    """Primer nombre sin signos pegados ("Constanza." -> "Constanza").
    Si el nombre no tiene letras (ej. solo un emoji), devuelve "" y se saluda sin nombre."""
    partes = nombre.split()
    if not partes:
        return ""
    primero = re.sub(r"^[\W_]+|[\W_]+$", "", partes[0])
    if primero.isupper() and len(primero) > 1:
        primero = primero.capitalize()  # "PESTAÑAS" -> "Pestañas"
    return primero if any(c.isalpha() for c in primero) else ""


def con_nombre(texto, nombre):
    """Reemplaza {nombre}; si no hay nombre, queda "¡Hola!" en vez de "¡Hola !"."""
    return texto.replace(" {nombre}", f" {nombre}" if nombre else "").replace("{nombre}", nombre)


def sin_saludo(texto):
    """Quita el primer párrafo (el saludo) para no saludar dos veces."""
    partes = texto.split("\n\n", 1)
    return partes[1] if len(partes) == 2 else texto


def poner_cierre(texto, incluir):
    """Reemplaza {cierre} por el cierre de venta de respuestas.json, o lo quita
    (cuando se juntan varias respuestas, el cierre va solo en la última)."""
    cierre = cargar_respuestas().get("cierre", "")
    if incluir and cierre:
        return texto.replace("{cierre}", cierre)
    return texto.replace("\n\n{cierre}", "").replace("{cierre}", "")


def texto_unido(reglas, nombre, campo="texto"):
    """Junta los textos de varias reglas en un solo mensaje (un solo saludo).
    Si la regla tiene "texto_comentario", se usa ese en vez del normal."""
    # Las que invitan a responder "sí" van al final, para que la pregunta cierre el mensaje.
    reglas = sorted(reglas, key=lambda r: bool(r.get(campo)))
    textos = [regla.get(campo) or next((p["texto"] for p in regla["respuesta"] if p.get("texto")), "")
              for regla in reglas]
    textos = [t for t in textos if t]
    partes = []
    for i, texto in enumerate(textos):
        if i > 0:
            texto = sin_saludo(texto)
        if i < len(textos) - 1:
            texto = sin_cierre(poner_cierre(texto, False))
        else:
            texto = poner_cierre(texto, True)
        partes.append(texto)
    return con_nombre("\n\n".join(partes), nombre)


def sin_cierre(texto):
    """Quita el último párrafo si es la despedida ("¿Tienes alguna otra pregunta?..."),
    para no repetirla cuando se juntan varias respuestas."""
    partes = texto.rsplit("\n\n", 1)
    if len(partes) == 2 and ("otra pregunta" in partes[1] or "Cualquier duda" in partes[1]):
        return partes[0]
    return texto


def responder(destinatario, reglas, nombre):
    """Manda las partes de cada regla en su orden (texto, imagen, texto...).
    Si son varias reglas, se saluda una sola vez, cada imagen se manda una vez
    y el cierre de venta ({cierre}) va solo en el último texto que lo tenga."""
    partes = []
    for i, regla in enumerate(reglas):
        for parte in regla["respuesta"]:
            if parte.get("texto"):
                partes.append(("texto", parte["texto"] if i == 0 else sin_saludo(parte["texto"])))
            for tipo in ("imagen", "audio"):
                if parte.get(tipo) and (tipo, parte[tipo]) not in partes:
                    partes.append((tipo, parte[tipo]))
    ultimo_cierre = max((j for j, (tipo, valor) in enumerate(partes) if tipo == "texto" and "{cierre}" in valor),
                        default=-1)
    for j, (tipo, valor) in enumerate(partes):
        if tipo == "texto":
            texto = poner_cierre(valor, j == ultimo_cierre)
            if texto.strip():
                enviar(destinatario, {"text": con_nombre(texto, nombre)})
        else:
            carpeta = "imagenes" if tipo == "imagen" else "audios"
            url = f"{PUBLIC_URL}/{carpeta}/{valor}"
            tipo_api = "image" if tipo == "imagen" else "audio"
            enviar(destinatario, {"attachment": {"type": tipo_api, "payload": {"url": url}}})


def procesar_evento(datos):
    if datos.get("object") != "instagram":
        return
    config = cargar_respuestas()  # se relee cada vez: puedes editar el JSON sin reiniciar
    for entrada in datos.get("entry", []):
        mi_id = str(entrada.get("id", ""))
        # Los avisos llegan reenviados desde el bot de Iron Element; si en el mismo
        # aviso viene algo de otra cuenta (ej. el gym), no es para este bot.
        if MIS_IDS and mi_id and mi_id not in MIS_IDS:
            log(f"  aviso para otra cuenta (ID {mi_id}), se ignora")
            continue
        for cambio in entrada.get("changes", []):
            if cambio.get("field") == "comments":
                procesar_comentario(cambio.get("value") or {}, mi_id, config)
        for evento in entrada.get("messaging", []):
            mensaje = evento.get("message") or {}
            remitente = str(evento.get("sender", {}).get("id", ""))
            texto = mensaje.get("text")
            if mensaje.get("is_echo"):
                # Mensaje que salió de la cuenta del gym: si no lo mandó el bot, lo
                # escribió alguien del equipo y el bot se calla con esa persona.
                destinatario = str(evento.get("recipient", {}).get("id", ""))
                if destinatario and not es_eco_del_bot(destinatario, mensaje.get("mid")):
                    horas = config.get("horas_pausa_si_responde_equipo", 12)
                    pausar(destinatario, horas)
                    log(f"El equipo le respondió a {destinatario}: bot en pausa {horas} h con esa persona")
                continue
            if remitente and remitente != mi_id:
                with _candado:
                    _ultimo_dm[remitente] = time.time()
            # Ignorar mensajes borrados o sin texto (stickers, audios...)
            if not texto or mensaje.get("is_deleted") or remitente == mi_id:
                continue
            log(f"DM de {remitente}: {texto!r}")
            if en_pausa(remitente):
                log("  el equipo está atendiendo esta conversación, el bot no responde")
                continue
            reglas = buscar_reglas(texto, config)
            for regla in reglas_pendientes_por_si(remitente, texto, config):
                if regla not in reglas:
                    reglas.insert(0, regla)
            if not reglas:
                bienvenida = config.get("bienvenida") or {}
                if not bienvenida.get("activa"):
                    log("  sin palabra clave, no se responde")
                    continue
                reglas = [dict(bienvenida, nombre="bienvenida")]
            minutos = config.get("minutos_entre_respuestas", 30)
            pendientes = []
            for regla in reglas:
                if puede_responder(remitente, regla["nombre"], minutos):
                    pendientes.append(regla)
                else:
                    log(f"  ya se le respondió '{regla['nombre']}' hace poco, se omite")
            if pendientes:
                log("  reglas:", ", ".join(r["nombre"] for r in pendientes))
                nombre = nombre_de_usuario(remitente)
                responder(remitente, pendientes, nombre)
                seguimiento = config.get("seguimiento") or {}
                if seguimiento.get("activo") and any(
                    r["nombre"] in seguimiento.get("despues_de", []) for r in pendientes
                ):
                    programar_seguimiento(remitente, nombre, seguimiento)


# Comentarios en posts y reels: si traen palabra clave, el bot responde por DM
# (respuesta privada) y deja un comentario público. Meta permite un solo mensaje
# de texto por comentario; si la respuesta tenía imagen (ej. planes), el DM invita
# a responder "sí" y la imagen se manda cuando la persona contesta.
AFIRMATIVOS = ["si", "sii", "siii", "dale", "ok", "okay", "bueno", "ya", "claro", "porfa",
               "por favor", "quiero", "me interesa", "enviala", "mandala", "envia", "manda"]
_espera_si = {}


def comentar_publico(comment_id, texto):
    if MODO_PRUEBA:
        log("  [modo prueba] comentaría:", texto)
        return
    req = urllib.request.Request(
        f"{API_BASE}/{comment_id}/replies",
        data=json.dumps({"message": texto}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {ACCESS_TOKEN}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            log("  comentario público OK")
    except urllib.error.HTTPError as e:
        log("  ERROR al comentar:", e.code, e.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log("  ERROR de conexión:", e.reason)


def procesar_comentario(valor, mi_id, config):
    opciones = config.get("comentarios") or {}
    if not opciones.get("activo"):
        return
    texto = valor.get("text") or ""
    autor = str((valor.get("from") or {}).get("id", ""))
    comment_id = valor.get("id")
    publica = opciones.get("respuesta_publica", "")
    # Ignorar comentarios de la propia cuenta (incluidas las respuestas públicas del
    # bot, que traen la palabra "info" y harían un bucle).
    if not comment_id or not autor or autor == mi_id or (publica and texto.strip() == publica.strip()):
        return
    log(f"Comentario de {autor}: {texto!r}")
    reglas = buscar_reglas(texto, config)
    if not reglas:
        log("  sin palabra clave, no se responde")
        return
    minutos = config.get("minutos_entre_respuestas", 180)
    reglas = [r for r in reglas if puede_responder(autor, "comentario:" + r["nombre"], minutos)]
    if not reglas:
        log("  ya se le respondió hace poco por un comentario, se omite")
        return
    log("  reglas:", ", ".join(r["nombre"] for r in reglas))
    nombre = nombre_de_usuario(autor)
    enviar(autor, {"text": texto_unido(reglas, nombre, "texto_comentario")}, {"comment_id": comment_id})
    # Qué mandar si responde "sí": la misma regla, o la que indique "si_envia"
    # (ej. "recurrente" explica el pago y con el "sí" se mandan los planes con imagen).
    con_imagen = []
    for r in reglas:
        if r.get("texto_comentario") and r.get("si_envia", r["nombre"]) not in con_imagen:
            con_imagen.append(r.get("si_envia", r["nombre"]))
    if con_imagen:
        with _candado:
            _espera_si[autor] = (time.time(), con_imagen)
    if publica:
        comentar_publico(comment_id, publica)


def reglas_pendientes_por_si(remitente, texto, config):
    """Si la persona respondió "sí" al DM que salió de un comentario, devuelve las
    reglas completas (con imagen) que quedaron pendientes."""
    with _candado:
        pendiente = _espera_si.get(remitente)
        if not pendiente or time.time() - pendiente[0] > 7 * 86400:
            return []
        if not contiene(normalizar(texto), AFIRMATIVOS):
            return []
        del _espera_si[remitente]
    return [r for r in config["reglas"] if r["nombre"] in pendiente[1]]


# Mensaje de seguimiento: si la persona no vuelve a escribir X minutos después
# de recibir ciertas respuestas (ej. los planes), el bot le pregunta si le interesó.
_ultimo_dm = {}
_seguimientos = {}
_seguimiento_enviado = {}


def programar_seguimiento(usuario, nombre, seguimiento):
    minutos = seguimiento.get("minutos", 10)
    with _candado:
        if time.time() - _seguimiento_enviado.get(usuario, 0) < 24 * 3600:
            return  # como mucho un seguimiento al día por persona
        anterior = _seguimientos.pop(usuario, None)
        if anterior:
            anterior.cancel()
        timer = threading.Timer(minutos * 60, enviar_seguimiento, args=(usuario, nombre, time.time()))
        timer.daemon = True
        _seguimientos[usuario] = timer
    timer.start()
    log(f"  seguimiento programado en {minutos} min")


def enviar_seguimiento(usuario, nombre, programado):
    try:
        with _candado:
            _seguimientos.pop(usuario, None)
            volvio_a_escribir = _ultimo_dm.get(usuario, 0) > programado
        if volvio_a_escribir:
            return  # la conversación siguió sola, no hace falta insistir
        if en_pausa(usuario):
            return  # el equipo está atendiendo
        seguimiento = cargar_respuestas().get("seguimiento") or {}
        if not seguimiento.get("activo"):
            return
        with _candado:
            _seguimiento_enviado[usuario] = time.time()
        log(f"Seguimiento a {usuario} (no respondió en {seguimiento.get('minutos', 10)} min)")
        enviar(usuario, {"text": con_nombre(poner_cierre(seguimiento["texto"], True), nombre)})
    except Exception as e:  # el timer corre aparte: que un error no pase inadvertido
        log("ERROR en seguimiento:", repr(e))


def obtener_mis_ids(token):
    """Pregunta a Instagram los números con que Meta identifica a ESTA cuenta.
    Con inicio de sesión de Instagram, el aviso puede traer "id" o "user_id"."""
    req = urllib.request.Request(
        f"https://graph.instagram.com/{API_VERSION}/me?fields=id,user_id,username",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            datos = json.loads(r.read())
    except (urllib.error.URLError, ValueError, OSError) as e:
        log("AVISO: no se pudo saber el ID de la cuenta:", e)
        return set()
    ids = {str(datos[c]) for c in ("id", "user_id") if datos.get(c)}
    log(f"Cuenta de Instagram: @{datos.get('username')} (IDs {', '.join(sorted(ids))})")
    return ids


def firma_valida(cuerpo, firma):
    if not APP_SECRETS:
        return True  # sin APP_SECRET no se verifica (solo para pruebas locales)
    for secreto in APP_SECRETS:
        esperada = "sha256=" + hmac.new(secreto.encode(), cuerpo, hashlib.sha256).hexdigest()
        if hmac.compare_digest(esperada, firma or ""):
            return True
    return False


def renovar_token():
    """Pide a Instagram un token nuevo de 60 días y lo guarda en Render.
    El token de Instagram vence a los 60 días; renovándolo seguido no vence nunca."""
    global ACCESS_TOKEN, ULTIMA_RENOVACION
    req = urllib.request.Request(
        "https://graph.instagram.com/refresh_access_token"
        f"?grant_type=ig_refresh_token&access_token={quote(ACCESS_TOKEN)}"
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            datos = json.loads(r.read())
    except urllib.error.HTTPError as e:
        log("ERROR al renovar el token:", e.code, e.read().decode("utf-8"))
        return
    except (urllib.error.URLError, ValueError) as e:
        log("ERROR al renovar el token:", e)
        return
    ACCESS_TOKEN = datos["access_token"]
    ULTIMA_RENOVACION = time.time()
    dias = int(datos.get("expires_in", 0)) // 86400
    log(f"Token renovado: vence en {dias} días")
    if not (RENDER_API_KEY and RENDER_SERVICE_ID):
        log("  AVISO: falta RENDER_API_KEY; el token nuevo no quedó guardado en Render")
        return
    if guardar_en_render("ACCESS_TOKEN", ACCESS_TOKEN):
        guardar_en_render("TOKEN_RENOVADO", str(int(ULTIMA_RENOVACION)))
        log("  token nuevo guardado en Render")


def guardar_en_render(variable, valor):
    """Actualiza una variable de entorno en Render, para que siga ahí cuando
    el servicio se reinicie."""
    req = urllib.request.Request(
        f"https://api.render.com/v1/services/{RENDER_SERVICE_ID}/env-vars/{variable}",
        data=json.dumps({"value": valor}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RENDER_API_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="PUT",
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            return True
    except urllib.error.HTTPError as e:
        log(f"  ERROR al guardar {variable} en Render:", e.code, e.read().decode("utf-8"))
    except urllib.error.URLError as e:
        log("  ERROR de conexión con Render:", e.reason)
    return False


def ciclo_renovacion():
    periodo = DIAS_ENTRE_RENOVACIONES * 86400
    while True:
        # Si ya se renovó hace poco (por ejemplo, antes de un reinicio), espera lo que falta.
        espera = max(60, ULTIMA_RENOVACION + periodo - time.time())
        time.sleep(espera)
        try:
            renovar_token()
        except Exception as e:  # que un error no detenga las renovaciones futuras
            log("ERROR inesperado al renovar el token:", repr(e))
        if time.time() - ULTIMA_RENOVACION > 3600:
            time.sleep(6 * 3600)  # falló: reintentar en 6 horas


class Manejador(BaseHTTPRequestHandler):
    def _responder(self, codigo, cuerpo=b"", tipo="text/plain; charset=utf-8"):
        self.send_response(codigo)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/webhook":
            # Meta verifica el webhook con este GET una sola vez al conectarlo.
            q = parse_qs(url.query)
            if q.get("hub.mode") == ["subscribe"] and q.get("hub.verify_token") == [VERIFY_TOKEN] and VERIFY_TOKEN:
                log("Webhook verificado por Meta")
                return self._responder(200, q.get("hub.challenge", [""])[0].encode())
            return self._responder(403, b"token incorrecto")
        if url.path.startswith("/imagenes/"):
            nombre = os.path.basename(url.path)
            ruta = os.path.join(CARPETA_IMAGENES, nombre)
            if nombre and os.path.isfile(ruta):
                tipo = "image/png" if nombre.lower().endswith(".png") else "image/jpeg"
                with open(ruta, "rb") as f:
                    return self._responder(200, f.read(), tipo)
            return self._responder(404, b"no existe")
        if url.path.startswith("/audios/"):
            nombre = os.path.basename(url.path)
            ruta = os.path.join(CARPETA_AUDIOS, nombre)
            tipo = TIPOS_AUDIO.get(os.path.splitext(nombre)[1].lower())
            if nombre and tipo and os.path.isfile(ruta):
                with open(ruta, "rb") as f:
                    return self._responder(200, f.read(), tipo)
            return self._responder(404, b"no existe")
        if url.path == "/privacidad":
            # Meta pide un link a la política de privacidad para publicar la app.
            with open(os.path.join(CARPETA, "privacidad.html"), "rb") as f:
                return self._responder(200, f.read(), "text/html; charset=utf-8")
        return self._responder(200, b"Bot Mindset JY funcionando")

    def do_POST(self):
        if urlparse(self.path).path != "/webhook":
            return self._responder(404)
        cuerpo = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if not firma_valida(cuerpo, self.headers.get("X-Hub-Signature-256")):
            log("Firma inválida, se ignora el aviso")
            return self._responder(403)
        # Meta exige contestar rápido: respondemos 200 y procesamos aparte.
        self._responder(200, b"EVENT_RECEIVED")
        try:
            datos = json.loads(cuerpo)
        except ValueError:
            return
        # Resumen de cada aviso que llega (para diagnosticar qué manda Meta).
        try:
            tipos = []
            for e in datos.get("entry", []):
                for clave in ("messaging", "standby"):
                    if e.get(clave):
                        tipos.append(f"{clave}x{len(e[clave])}")
                tipos += [f"changes:{c.get('field')}" for c in e.get("changes", [])]
            log(f"Aviso de Meta ({datos.get('object')}): {', '.join(tipos) or 'vacío'}")
        except Exception:
            pass
        threading.Thread(target=self._procesar_seguro, args=(datos,), daemon=True).start()

    @staticmethod
    def _procesar_seguro(datos):
        try:
            procesar_evento(datos)
        except Exception as e:  # que un error no tumbe el servidor
            log("ERROR procesando evento:", repr(e))

    def log_message(self, *args):
        pass  # silenciar el log por defecto de cada petición


if __name__ == "__main__":
    cargar_respuestas()  # falla al tiro si el JSON tiene un error
    log(f"Bot escuchando en el puerto {PORT}" + ("  (MODO PRUEBA: no envía nada)" if MODO_PRUEBA else ""))
    if TOKEN_FACEBOOK and not IG_ACCOUNT_ID:
        raise SystemExit("Falta IG_ACCOUNT_ID en el .env (el ID de la cuenta de Instagram)")
    if not MODO_PRUEBA and not TOKEN_FACEBOOK:
        MIS_IDS.update(obtener_mis_ids(ACCESS_TOKEN))
    if not MODO_PRUEBA and not TOKEN_FACEBOOK:
        threading.Thread(target=ciclo_renovacion, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Manejador).serve_forever()
