"""Simula un DM para probar el bot sin Meta.
Uso:  python3 probar.py "hola, cuánto valen los planes?"
(El bot debe estar corriendo en otra terminal: python3 bot.py)
"""
import json, sys, urllib.request

texto = " ".join(sys.argv[1:]) or "Hola! cuáles son los precios?"
evento = {"object": "instagram", "entry": [{"id": "MINDSET_JY", "messaging": [
    {"sender": {"id": "ALUMNO_PRUEBA"}, "recipient": {"id": "MINDSET_JY"},
     "message": {"mid": "x", "text": texto}}]}]}
req = urllib.request.Request("http://localhost:8000/webhook", data=json.dumps(evento).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
print(urllib.request.urlopen(req).read().decode(), "-> mira la terminal del bot")
