"""Genera CATALOGO.md: todas las respuestas del bot en formato fácil de leer.
Se arma desde respuestas.json, así que siempre calza con lo que responde el bot.
Uso:  python3 generar_catalogo.py
"""
import json
import os
import time

CARPETA = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(CARPETA, "respuestas.json"), encoding="utf-8") as f:
    config = json.load(f)


def cita(texto):
    """Muestra el mensaje como le llega a la persona (cada línea como cita)."""
    texto = texto.replace("{nombre}", "*(nombre)*").replace("{cierre}", config.get("cierre", ""))
    # Los dos espacios al final fuerzan el salto de línea en GitHub.
    return "\n".join("> " + linea + "  " if linea else ">" for linea in texto.split("\n"))


lineas = [
    "# Catálogo de respuestas — Bot Instagram Iron Element",
    "",
    f"Generado el {time.strftime('%d-%m-%Y %H:%M')} desde `respuestas.json`. "
    "No editar este archivo a mano: los cambios se hacen en `respuestas.json` "
    "y después se vuelve a correr `python3 generar_catalogo.py`.",
    "",
    f"- No se repite la misma respuesta a la misma persona antes de **{config.get('minutos_entre_respuestas', 30)} minutos**.",
    f"- Si alguien del equipo responde a mano en una conversación, el bot se calla con esa persona por **{config.get('horas_pausa_si_responde_equipo', 12)} horas**.",
    "- Si un mensaje activa varios temas, se saluda una sola vez y se mandan todas las respuestas.",
    "- *(nombre)* se reemplaza por el primer nombre de quien escribe.",
    "",
    "## Índice",
    "",
]
for i, regla in enumerate(config["reglas"], 1):
    lineas.append(f"{i}. {regla['nombre'].capitalize()}")
lineas.append("")

for i, regla in enumerate(config["reglas"], 1):
    lineas += [f"## {i}. {regla['nombre'].capitalize()}", ""]
    if regla.get("patron"):
        lineas.append("**Se activa con:** un número de celular chileno en el mensaje (ej. `+56 9 1234 5678` o `912345678`)"
                      + (". Cuando aparece, se responde solo esto." if regla.get("exclusiva") else ""))
    else:
        lineas.append("**Se activa con:** " + ", ".join(f"`{p}`" for p in regla["palabras_clave"]))
    if regla.get("excepto"):
        lineas.append("")
        lineas.append("**No se activa si el mensaje trae:** " + ", ".join(f"`{p}`" for p in regla["excepto"]))
    lineas += ["", "**Respuesta:**", ""]
    for parte in regla["respuesta"]:
        if parte.get("texto"):
            lineas += [cita(parte["texto"]), ""]
        if parte.get("imagen"):
            lineas += [f"🖼️ Imagen: `imagenes/{parte['imagen']}`", ""]
            lineas += [f"![{parte['imagen']}](imagenes/{parte['imagen']})", ""]
        if parte.get("audio"):
            lineas += [f"🔊 Audio: [`audios/{parte['audio']}`](audios/{parte['audio']})", ""]
    if regla.get("texto_comentario"):
        lineas += ["**Si la pregunta viene de un comentario** (Meta solo permite un mensaje de texto, sin imagen):", "",
                   cita(regla["texto_comentario"]), "",
                   ("Si la persona responde \"sí\" por DM, le llega la respuesta de *" + regla["si_envia"] + "* con la imagen."
                    if regla.get("si_envia") else
                    "Si la persona responde \"sí\" por DM, le llega la respuesta completa de arriba con la imagen."), ""]
    lineas += ["---", ""]

comentarios = config.get("comentarios") or {}
lineas += [
    "## Comentarios en posts y reels",
    "",
    "**Estado:** " + ("✅ activo" if comentarios.get("activo") else "⏸️ apagado"),
    "",
    "Si alguien comenta cualquier post o reel con una palabra clave, el bot le responde por DM "
    "con el tema que corresponde (los mismos textos de arriba, todo en un solo mensaje).",
    "",
]
if comentarios.get("respuesta_publica"):
    lineas += [f"Además responde el comentario públicamente con: **{comentarios['respuesta_publica']}**", ""]
lineas += ["---", ""]

seguimiento = config.get("seguimiento") or {}
lineas += [
    "## Mensaje de seguimiento",
    "",
    "**Estado:** " + ("✅ activo" if seguimiento.get("activo") else "⏸️ apagado"),
    "",
    f"Si la persona no vuelve a escribir **{seguimiento.get('minutos', 10)} minutos** después de recibir "
    + ", ".join(f"*{n}*" for n in seguimiento.get("despues_de", []))
    + ", el bot le manda esto (máximo una vez al día por persona, y nunca si el equipo ya le respondió a mano):",
    "",
]
if seguimiento.get("texto"):
    lineas += [cita(seguimiento["texto"]), "", "---", ""]

bienvenida = config.get("bienvenida") or {}
lineas += [
    "## Mensaje sin palabra clave",
    "",
    "**Estado:** " + ("✅ activo" if bienvenida.get("activa") else "⏸️ apagado (el bot no responde mensajes sin palabra clave)"),
    "",
]
for parte in bienvenida.get("respuesta", []):
    if parte.get("texto"):
        lineas += [cita(parte["texto"]), ""]

with open(os.path.join(CARPETA, "CATALOGO.md"), "w", encoding="utf-8") as f:
    f.write("\n".join(lineas))
print(f"✅ CATALOGO.md generado con {len(config['reglas'])} temas")
