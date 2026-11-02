import csv
import io
import json
import zipfile
from datetime import datetime, timedelta

import httpx

ZIP_URL = "https://ssl.renfe.com/gtransit/Fichero_AV_LD/google_transit.zip"
TU_URL = "https://gtfsrt.renfe.com/trip_updates_LD.json"
VP_URL = "https://gtfsrt.renfe.com/vehicle_positions_LD.json"


def leer(z, nombre):
    with z.open(nombre) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")))


def a_hora(texto):
    # Las horas del horario vienen como "HH:MM:SS", a veces con horas >= 24
    h, m, s = (int(x) for x in texto.split(":"))
    return h * 3600 + m * 60 + s


def hora_texto(segundos_desde_medianoche):
    h = int(segundos_desde_medianoche // 3600) % 24
    m = int(segundos_desde_medianoche % 3600 // 60)
    return f"{h:02d}:{m:02d}"


print("Descargando horarios (puede tardar)...")
r = httpx.get(ZIP_URL, timeout=120, follow_redirects=True)
r.raise_for_status()
z = zipfile.ZipFile(io.BytesIO(r.content))

nombres = {s["stop_id"]: s["stop_name"] for s in leer(z, "stops.txt")}

# Primera y última parada de cada viaje, con su hora programada
primera, ultima = {}, {}
for st in leer(z, "stop_times.txt"):
    tid, seq = st["trip_id"], int(st["stop_sequence"])
    hora = a_hora(st["departure_time"] or st["arrival_time"])
    llegada = a_hora(st["arrival_time"] or st["departure_time"])
    if tid not in primera or seq < primera[tid]["seq"]:
        primera[tid] = {"seq": seq, "parada": st["stop_id"], "salida": hora}
    if tid not in ultima or seq > ultima[tid]["seq"]:
        ultima[tid] = {"seq": seq, "parada": st["stop_id"], "llegada": llegada}

# Retrasos en tiempo real (en segundos, por viaje)
tu = httpx.get(TU_URL, timeout=30).json()
retraso = {}
for e in tu["entity"]:
    if "tripUpdate" in e:
        t = e["tripUpdate"]
        retraso[t["trip"]["tripId"]] = t.get("delay")

# Posiciones en tiempo real
vp = httpx.get(VP_URL, timeout=30).json()
trenes = []
for e in vp["entity"]:
    if "vehicle" not in e:
        continue
    v = e["vehicle"]
    tid = v["trip"]["tripId"]
    seg = retraso.get(tid) or 0
    p, u = primera.get(tid), ultima.get(tid)
    trenes.append({
        "tren": v["vehicle"]["label"],
        "viaje": tid,
        "lat": v["position"]["latitude"],
        "lon": v["position"]["longitude"],
        "estado": v.get("currentStatus", ""),
        "origen": nombres.get(p["parada"], "") if p else "",
        "destino": nombres.get(u["parada"], "") if u else "",
        "salida_prevista": hora_texto(p["salida"]) if p else "",
        "llegada_prevista": hora_texto(u["llegada"]) if u else "",
        "salida_estimada": hora_texto(p["salida"] + seg) if p else "",
        "llegada_estimada": hora_texto(u["llegada"] + seg) if u else "",
        "retraso_min": round(seg / 60, 1),
    })

con_retraso = [t for t in trenes if t["retraso_min"] > 0]
print(f"\nTrenes en el mapa: {len(trenes)}")
if trenes:
    pct = 100 * len(con_retraso) / len(trenes)
    print(f"Trenes con retraso: {len(con_retraso)} ({pct:.1f} %)")

with open("trenes.json", "w", encoding="utf-8") as f:
    json.dump(trenes, f, ensure_ascii=False, indent=2)
print("Guardado en trenes.json")