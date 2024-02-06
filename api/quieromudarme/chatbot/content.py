"""Static content for the chatbot, such as long help messages."""
# ruff: noqa: E501

from typing import Final

MSG_SEPARATOR: Final = "----------"

HELP = f"""
🏠 **QuieroMudarme** te ayuda a encontrar tu próximo hogar!
{MSG_SEPARATOR}
🔎 Este bot es perfecto si ya venís buscando y querés que te avisemos **cuando haya algo nuevo o baje de precio**, y solo necesitás el link 🔗 que está en la barrita del navegador.

Lo único que tenés que hacer es copiar tu búsqueda acá y listo! 🎉 Es bien fácil, paso por paso:
 1. Entrá **desde la compu** a [ZonaProp](zonaprop.com.ar) y/o [MercadoLibre](inmuebles.mercadolibre.com.ar) y buscá con los filtros que tenés en mente.
 2. Asegurate de que la búsqueda sea específica: si tiene más de 500 resultados es mucho!
 3. Copiá toda la dirección de la barrita del navegador (el link 🔗, o sea, eso que empieza con "https://...").
 4. Pegá el link 🔗 en este chat. Listo! 🚀

💡 Por ejemplo, si estabas buscando alquilar un 3 ambientes en Palermo a menos de 600 dólares, al poner estos filtros en ZonaProp el link 🔗 va a ser algo así:
`https://www.zonaprop.com.ar/departamentos-alquiler-palermo-3-ambientes-menos-600-dolar.html` (y esto es lo que copiás y me mandás acá!).
{MSG_SEPARATOR}
=====================
Algunos detalles: 🤓
👉 Desde las apps no podés copiar el link 🔗, así que __solo al crear las búsquedas__ necesitás una compu.
👉 Si hacés una búsqueda en una moneda (ejemplo pesos) también te van a aparecer los resultados en la otra moneda (dólares); para esto por el momento se toma el cambio oficial.
👉 Por último, casi siempre lo __bueno, bonito y barato__ se va rápido, así que no te duermas!
=====================
{MSG_SEPARATOR}
**El bot es muy nuevo, nos sirven tus /sugerencias! Y si conocés a alguien buscando su próximo hogar, pasale este bot para hacerle la vida más fácil!** 📢

**Usá el botón de abajo ↙️ para encontrar todos los comandos.** Suerte! 🏡
"""
HELP_MSGS = [msg.strip() for msg in HELP.split(MSG_SEPARATOR)]
