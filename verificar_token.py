"""Comprueba que el ACCESS_TOKEN del .env funciona (sin mostrarlo en pantalla).
Uso:  python3 verificar_token.py
"""
import json
import urllib.error
import urllib.request

import bot  # reutiliza la lectura del .env

if not bot.ACCESS_TOKEN:
    raise SystemExit("❌ No hay ACCESS_TOKEN en el archivo .env")

req = urllib.request.Request(
    f"https://graph.instagram.com/{bot.API_VERSION}/me?fields=user_id,username",
    headers={"Authorization": f"Bearer {bot.ACCESS_TOKEN}"},
)
try:
    with urllib.request.urlopen(req, timeout=15) as r:
        datos = json.loads(r.read())
    print(f"✅ Token OK — conectado a @{datos.get('username')} (id {datos.get('user_id')})")
except urllib.error.HTTPError as e:
    print("❌ El token no funciona:", e.code, e.read().decode("utf-8"))
if not bot.APP_SECRETS:
    print("APP_SECRET: ❌ falta")
for i, clave in enumerate(bot.APP_SECRETS, 1):
    # Una clave secreta de Meta tiene 32 caracteres: números y letras de la a a la f.
    ok = len(clave) == 32 and all(c in "0123456789abcdef" for c in clave)
    print(f"APP_SECRET clave {i}:", "✅ formato correcto" if ok else f"❌ no parece una clave secreta ({len(clave)} caracteres, deberían ser 32)")
