"""Chance (%) de chuva e rajada em Chapecó, pelas previsões de conjunto.

Cada modelo roda várias vezes com pequenas mudanças (GEFS 31, ECMWF 51, ICON 40 versões).
Chance = quantas versões passam do limite, dividido pelo total. Só o ponto de Chapecó,
para caber no limite grátis da Open-Meteo.
Saída: dados/conjunto.json
"""
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
MODELOS = {"gfs025": "GEFS", "ecmwf_ifs025": "ECMWF ENS", "icon_global": "ICON EPS"}
LIMITES = {
    "chuva_1": ("precipitation", 1),      # mm/h
    "chuva_5": ("precipitation", 5),
    "chuva_10": ("precipitation", 10),
    "rajada_60": ("wind_gusts_10m", 60),  # km/h
    "rajada_80": ("wind_gusts_10m", 80),
    "cape_1000": ("cape", 1000),          # J/kg: energia para tempestade forte
}


def calcular():
    q = urllib.parse.urlencode({
        "latitude": config.CENTRO[0], "longitude": config.CENTRO[1],
        "hourly": "precipitation,wind_gusts_10m,cape", "models": ",".join(MODELOS),
        "forecast_hours": config.HORAS, "timezone": config.TZ,
    })
    with urllib.request.urlopen(f"https://ensemble-api.open-meteo.com/v1/ensemble?{q}", timeout=60) as r:
        h = json.load(r)["hourly"]
    horas = h["time"]
    saida = {"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "horas": horas, "chance": {}, "versoes": {}}
    for nome, (var, lim) in LIMITES.items():
        series = [v for k, v in h.items() if k.startswith(var + "_")]
        chance = []
        for t in range(len(horas)):
            vals = [s[t] for s in series if s[t] is not None]
            chance.append(round(100 * sum(v >= lim for v in vals) / len(vals)) if vals else None)
        saida["chance"][nome] = chance
    sufixo = {"gfs025": "ncep_gefs025", "ecmwf_ifs025": "ecmwf_ifs025_ensemble", "icon_global": "icon_global_eps"}
    for m, rotulo in MODELOS.items():
        saida["versoes"][rotulo] = sum(1 for k in h if k.startswith("precipitation_") and k.endswith(sufixo[m]))
    json.dump(saida, open(os.path.join(AQUI, "dados", "conjunto.json"), "w"), ensure_ascii=False)
    return saida


if __name__ == "__main__":
    c = calcular()
    print("versões:", c["versoes"])
    for k, v in c["chance"].items():
        print(f"{k:10}", "máx", max(x or 0 for x in v), "%", v[:24])
