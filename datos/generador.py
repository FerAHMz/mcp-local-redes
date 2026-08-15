"""Generador del set sintético de telemetría.

Simula 15 vehículos durante 7 días sobre rutas reales del área metropolitana de
Guatemala. Por defecto trabaja sin red, leyendo las polilíneas guardadas en
datos/rutas/. Con GOOGLE_MAPS_API_KEY definida y --regenerar-rutas vuelve a
pedirlas a la Directions API.

Uso:
    python datos/generador.py [--salida datos/flota.db] [--ahora 2026-08-19T15:30] [--semilla 7]
"""

import argparse
import glob
import json
import math
import os
import random
import sqlite3
import sys
from datetime import datetime, timedelta

from geopy.distance import great_circle

AQUI = os.path.dirname(os.path.abspath(__file__))
DIR_RUTAS = os.path.join(AQUI, "rutas")
ESQUEMA = os.path.join(AQUI, "esquema.sql")

INTERVALO_S = 15
DIAS = 7
SIGMA_GPS_M = 5.0
# Por debajo de esto el receptor reporta 0; evita velocidades fantasma por el ruido del GPS.
UMBRAL_VELOCIDAD_KMH = 2.0

VEHICULOS = [
    ("P-123BCD", "camion", "Marvin Castellanos"),
    ("P-456DEF", "panel", "Lucía Ramírez"),
    ("P-789GHJ", "pickup", "Otto Barrientos"),
    ("P-234KLM", "camion", "Ana Lucía Pérez"),
    ("P-567NPQ", "panel", "Byron Ajquejay"),
    ("P-890RST", "microbus", "Karla Estrada"),
    ("P-345VWX", "camion", "Julio Morales"),
    ("P-678YZB", "panel", "Sofía Monterroso"),
    ("P-901CDF", "pickup", "Edgar Tzul"),
    ("P-112GHK", "camion", "Mónica Aguilar"),
    ("P-223LMN", "panel", "Rodrigo Castañeda"),
    ("P-334PQR", "microbus", "Diana Quiñónez"),
    ("P-445STV", "camion", "Héctor Cuxil"),
    ("P-556WXY", "pickup", "Gabriela Solís"),
    ("P-667ZBC", "panel", "Luis Fernando Ordóñez"),
]
# Esta unidad está dada de baja: existe en el catálogo pero no reporta.
PLACA_INACTIVA = "P-667ZBC"


def decodificar_polilinea(codificada):
    """Decodifica una polilínea en el formato de Google (precisión 1e-5) a una lista de (lat, lon)."""
    puntos, indice, lat, lon = [], 0, 0, 0
    while indice < len(codificada):
        for es_lat in (True, False):
            resultado, desplazamiento = 0, 0
            while True:
                b = ord(codificada[indice]) - 63
                indice += 1
                resultado |= (b & 0x1F) << desplazamiento
                desplazamiento += 5
                if b < 0x20:
                    break
            delta = ~(resultado >> 1) if resultado & 1 else resultado >> 1
            if es_lat:
                lat += delta
            else:
                lon += delta
        puntos.append((lat / 1e5, lon / 1e5))
    return puntos


def cargar_rutas():
    rutas = []
    for archivo in sorted(glob.glob(os.path.join(DIR_RUTAS, "*.json"))):
        with open(archivo, encoding="utf-8") as f:
            datos = json.load(f)
        puntos = decodificar_polilinea(datos["polilinea"])
        acumulada = [0.0]
        for a, b in zip(puntos, puntos[1:]):
            acumulada.append(acumulada[-1] + great_circle(a, b).meters)
        # Distancia sobre la polilínea a la que cae cada parada, para saber
        # cuándo la unidad llega a ella durante la simulación.
        paradas = []
        for parada in datos["paradas"][1:-1]:
            objetivo = (parada["lat"], parada["lon"])
            i = min(range(len(puntos)), key=lambda k: great_circle(puntos[k], objetivo).meters)
            paradas.append({"nombre": parada["nombre"], "distancia": acumulada[i]})
        rutas.append({
            "nombre": datos["nombre"],
            "puntos": puntos,
            "acumulada": acumulada,
            "largo": acumulada[-1],
            "paradas": paradas,
            "velocidad_base": datos["distancia_m"] / datos["duracion_s"] * 3.6,
        })
    return rutas


def regenerar_rutas(llave):
    """Vuelve a pedir cada ruta a la Directions API conservando las paradas del archivo."""
    import requests

    for archivo in sorted(glob.glob(os.path.join(DIR_RUTAS, "*.json"))):
        with open(archivo, encoding="utf-8") as f:
            datos = json.load(f)
        paradas = datos["paradas"]
        respuesta = requests.get(
            "https://maps.googleapis.com/maps/api/directions/json",
            params={
                "origin": f"{paradas[0]['lat']},{paradas[0]['lon']}",
                "destination": f"{paradas[-1]['lat']},{paradas[-1]['lon']}",
                "waypoints": "|".join(f"{p['lat']},{p['lon']}" for p in paradas[1:-1]),
                "key": llave,
            },
            timeout=30,
        ).json()
        if respuesta.get("status") != "OK":
            print(f"{datos['nombre']}: {respuesta.get('status')} {respuesta.get('error_message', '')}", file=sys.stderr)
            continue
        ruta = respuesta["routes"][0]
        datos["polilinea"] = ruta["overview_polyline"]["points"]
        datos["distancia_m"] = sum(t["distance"]["value"] for t in ruta["legs"])
        datos["duracion_s"] = sum(t["duration"]["value"] for t in ruta["legs"])
        datos["fuente"] = "google_directions"
        with open(archivo, "w", encoding="utf-8") as f:
            json.dump(datos, f, indent=2, ensure_ascii=False)
        print(f"{datos['nombre']}: {datos['distancia_m']} m", file=sys.stderr)


def posicion_en(ruta, distancia):
    """Interpola la coordenada que está a `distancia` metros del inicio de la ruta."""
    acumulada, puntos = ruta["acumulada"], ruta["puntos"]
    if distancia >= ruta["largo"]:
        return puntos[-1]
    # Búsqueda binaria del segmento; la lista tiene cientos de puntos y se consulta miles de veces.
    lo, hi = 0, len(acumulada) - 1
    while hi - lo > 1:
        medio = (lo + hi) // 2
        if acumulada[medio] <= distancia:
            lo = medio
        else:
            hi = medio
    largo_seg = acumulada[hi] - acumulada[lo]
    f = 0.0 if largo_seg == 0 else (distancia - acumulada[lo]) / largo_seg
    return (
        puntos[lo][0] + (puntos[hi][0] - puntos[lo][0]) * f,
        puntos[lo][1] + (puntos[hi][1] - puntos[lo][1]) * f,
    )


def rumbo(a, b):
    """Bearing inicial en grados (0 = norte, sentido horario) entre dos coordenadas."""
    lat1, lat2 = math.radians(a[0]), math.radians(b[0])
    dlon = math.radians(b[1] - a[1])
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def con_ruido(punto, rng):
    dlat = rng.gauss(0, SIGMA_GPS_M) / 111_320
    dlon = rng.gauss(0, SIGMA_GPS_M) / (111_320 * math.cos(math.radians(punto[0])))
    return (punto[0] + dlat, punto[1] + dlon)


class Simulador:
    """Recorre una ruta paso a paso produciendo la trayectoria de un vehículo en un día."""

    def __init__(self, ruta, rng):
        self.ruta = ruta
        self.rng = rng
        self.puntos = []  # (datetime, (lat, lon), ignicion)

    def detenido(self, inicio, duracion_s, coordenada, ignicion=1):
        t = inicio
        while t < inicio + timedelta(seconds=duracion_s):
            self.puntos.append((t, coordenada, ignicion))
            t += timedelta(seconds=INTERVALO_S)
        return t

    def recorrer(self, inicio, minutos_parada):
        """Una vuelta completa con parada en cada punto intermedio. Devuelve la hora de llegada."""
        ruta, rng = self.ruta, self.rng
        base = ruta["velocidad_base"]
        t, distancia, velocidad = inicio, 0.0, 0.0
        pendientes = list(ruta["paradas"])

        while distancia < ruta["largo"]:
            self.puntos.append((t, posicion_en(ruta, distancia), 1))
            t += timedelta(seconds=INTERVALO_S)

            # Velocidad objetivo con un paseo aleatorio acotado, más frenadas por
            # tráfico y semáforos. Cerca de una parada el objetivo baja a cero.
            objetivo = base * rng.uniform(0.55, 1.25)
            if pendientes and pendientes[0]["distancia"] - distancia < 150:
                objetivo = 0.0
            if rng.random() < 0.04:
                objetivo = 0.0
            velocidad += (objetivo - velocidad) * 0.35
            velocidad = max(0.0, min(velocidad, 72.0))
            distancia += velocidad / 3.6 * INTERVALO_S

            if pendientes and distancia >= pendientes[0]["distancia"]:
                parada = pendientes.pop(0)
                distancia = parada["distancia"]
                duracion = 60 * rng.uniform(minutos_parada * 0.6, minutos_parada * 1.4)
                t = self.detenido(t, duracion, posicion_en(ruta, distancia))
                velocidad = 0.0
        return t


def plan_del_dia(indice_vehiculo, fecha, rng):
    """Decide si la unidad opera ese día y con qué horario y número de vueltas."""
    dia_semana = fecha.weekday()
    if dia_semana == 6 and indice_vehiculo % 3 != 0:
        return None
    inicio = datetime.combine(fecha, datetime.min.time()) + timedelta(
        hours=6, minutes=rng.randint(20, 140)
    )
    horas_jornada = 4.5 if dia_semana >= 5 else rng.uniform(7.5, 9.5)
    return {"inicio": inicio, "fin_jornada": inicio + timedelta(hours=horas_jornada)}


def simular_vehiculo(indice, ruta, fechas, ahora, rng):
    """Genera la trayectoria de una unidad en todos los días. Devuelve lista de (ts, (lat, lon), ignicion)."""
    trayectoria = []
    for fecha in fechas:
        plan = plan_del_dia(indice, fecha, rng)
        if plan is None:
            continue
        sim = Simulador(ruta, rng)
        t = sim.detenido(plan["inicio"], 60 * rng.uniform(3, 8), ruta["puntos"][0])
        while True:
            t = sim.recorrer(t, minutos_parada=rng.uniform(10, 20))
            if t + timedelta(seconds=ruta["largo"] / (ruta["velocidad_base"] / 3.6) * 1.4) > plan["fin_jornada"]:
                break
            t = sim.detenido(t, 60 * rng.uniform(15, 40), ruta["puntos"][-1])
        # Al cerrar la jornada la unidad queda unos minutos con motor apagado y deja de reportar.
        sim.detenido(t, 60 * 3, ruta["puntos"][-1], ignicion=0)
        trayectoria.extend(p for p in sim.puntos if p[0] <= ahora)
    return trayectoria


def a_filas(vehiculo_id, trayectoria, odometro_inicial, rng):
    """Convierte la trayectoria en filas de `posiciones` con ruido, velocidad, rumbo y odómetro."""
    filas = []
    odometro = odometro_inicial
    anterior = None
    for ts, punto, ignicion in trayectoria:
        medido = con_ruido(punto, rng)
        velocidad, direccion = 0.0, 0.0
        if anterior is not None:
            dt = (ts - anterior[0]).total_seconds()
            # Tras un hueco o un cambio de día no tiene sentido derivar velocidad.
            if 0 < dt <= INTERVALO_S * 2:
                metros = great_circle(anterior[1], medido).meters
                velocidad = metros / dt * 3.6
                if velocidad < UMBRAL_VELOCIDAD_KMH:
                    velocidad = 0.0
                else:
                    direccion = rumbo(anterior[1], medido)
                    odometro += metros / 1000
            if velocidad == 0.0 and anterior is not None:
                direccion = anterior[2]
        filas.append((vehiculo_id, ts.strftime("%Y-%m-%d %H:%M:%S"), round(medido[0], 6), round(medido[1], 6),
                      round(velocidad, 1), round(direccion, 1), ignicion, round(odometro, 2)))
        anterior = (ts, medido, direccion)
    return filas


def crear_base(ruta_db):
    if os.path.exists(ruta_db):
        os.remove(ruta_db)
    db = sqlite3.connect(ruta_db)
    with open(ESQUEMA, encoding="utf-8") as f:
        db.executescript(f.read())
    return db


def generar(ruta_db, ahora, semilla):
    rng = random.Random(semilla)
    rutas = cargar_rutas()
    fechas = [(ahora - timedelta(days=DIAS - 1 - i)).date() for i in range(DIAS)]

    db = crear_base(ruta_db)
    db.executemany(
        "INSERT INTO vehiculos(id, placa, tipo, conductor, activo) VALUES (?, ?, ?, ?, ?)",
        [(i + 1, placa, tipo, conductor, int(placa != PLACA_INACTIVA))
         for i, (placa, tipo, conductor) in enumerate(VEHICULOS)],
    )

    total = 0
    for i, (placa, _, _) in enumerate(VEHICULOS):
        if placa == PLACA_INACTIVA:
            continue
        ruta = rutas[i % len(rutas)]
        trayectoria = simular_vehiculo(i, ruta, fechas, ahora, rng)
        filas = a_filas(i + 1, trayectoria, odometro_inicial=rng.uniform(20_000, 180_000), rng=rng)
        db.executemany(
            "INSERT INTO posiciones(vehiculo_id, ts, lat, lon, velocidad, rumbo, ignicion, odometro) VALUES (?,?,?,?,?,?,?,?)",
            filas,
        )
        total += len(filas)
        print(f"{placa}: {ruta['nombre']}, {len(filas)} posiciones", file=sys.stderr)

    db.commit()
    db.close()
    print(f"{total} posiciones en {ruta_db}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--salida", default=os.path.join(AQUI, "flota.db"))
    parser.add_argument("--ahora", help="Instante final del set (ISO). Por defecto, el momento actual.")
    parser.add_argument("--semilla", type=int, default=7)
    parser.add_argument("--regenerar-rutas", action="store_true",
                        help="Pide las rutas a la Directions API (requiere GOOGLE_MAPS_API_KEY)")
    args = parser.parse_args()

    if args.regenerar_rutas:
        llave = os.environ.get("GOOGLE_MAPS_API_KEY")
        if not llave:
            sys.exit("Falta GOOGLE_MAPS_API_KEY para regenerar rutas")
        regenerar_rutas(llave)

    ahora = datetime.fromisoformat(args.ahora) if args.ahora else datetime.now().replace(second=0, microsecond=0)
    generar(args.salida, ahora, args.semilla)


if __name__ == "__main__":
    main()
