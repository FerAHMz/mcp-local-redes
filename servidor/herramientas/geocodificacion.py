"""Conversión de coordenadas a dirección legible, con tres niveles de respaldo.

1. Geocoding API de Google Maps si GOOGLE_MAPS_API_KEY está definida.
2. Nominatim de OpenStreetMap si hay red.
3. La geocerca más cercana como referencia, si no hay red.

El servidor nunca debe fallar por falta de conectividad, así que cualquier
excepción de red termina en el siguiente nivel. Uso urllib y no requests para
no sumar dependencias al servidor.
"""

import json
import logging
import os
import urllib.parse
import urllib.request

from servidor.herramientas import comun

log = logging.getLogger("mcp")

TIMEOUT_S = 4
# Nominatim exige identificar la aplicación en el User-Agent.
USER_AGENT = "mcp-flota-gt/1.0 (proyecto universitario CC3067)"

_cache = {}


def _obtener_json(url, cabeceras=None):
    peticion = urllib.request.Request(url, headers=cabeceras or {})
    with urllib.request.urlopen(peticion, timeout=TIMEOUT_S) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def _google(lat, lon, llave):
    consulta = urllib.parse.urlencode({"latlng": f"{lat},{lon}", "key": llave, "language": "es"})
    datos = _obtener_json(f"https://maps.googleapis.com/maps/api/geocode/json?{consulta}")
    if datos.get("status") == "OK" and datos["results"]:
        return datos["results"][0]["formatted_address"]
    return None


def _nominatim(lat, lon):
    consulta = urllib.parse.urlencode({"lat": lat, "lon": lon, "format": "jsonv2", "accept-language": "es", "zoom": 17})
    datos = _obtener_json(f"https://nominatim.openstreetmap.org/reverse?{consulta}", {"User-Agent": USER_AGENT})
    return datos.get("display_name") or None


def direccion(db, lat, lon):
    """Dirección legible para el punto, o la referencia a la geocerca más cercana si no hay red."""
    # Redondeo a ~10 m para que reportes consecutivos de una unidad detenida no repitan la consulta.
    clave = (round(lat, 4), round(lon, 4))
    if clave in _cache:
        return _cache[clave]

    resultado = None
    llave = os.environ.get("GOOGLE_MAPS_API_KEY")
    if llave:
        try:
            resultado = _google(lat, lon, llave)
        except Exception as e:
            log.warning("geocoding de Google falló: %s", e)
    if resultado is None:
        try:
            resultado = _nominatim(lat, lon)
        except Exception as e:
            log.warning("Nominatim no disponible: %s", e)
    if resultado is None:
        resultado = comun.referencia_cercana(db, lat, lon)

    _cache[clave] = resultado
    return resultado
