"""Previsão diária de Chapecó para 15 dias (painel: abas 3, 7, 10 e 15 dias).

Duas buscas na Open-Meteo, só o ponto de Chapecó:
  1. modelos ECMWF, GFS e ICON: máxima, mínima, chuva do dia e rajada -> mediana dos que têm o dia
     (ICON só vai até ~7 dias; GFS até 16; ECMWF até 15)
  2. conjunto (GEFS e ECMWF ENS, ~80 versões): chance de chuva = versões com >= 1 mm e >= 10 mm no dia
     (GEFS 0,25° só vai até ~10 dias; depois disso a chance é só do ECMWF ENS)

Confiança (regras simples, em código):
  dias 1-3  alta   | dias 4-7  média | dias 8-15 baixa ("tendência")
  cai um nível se os modelos discordam: máximas com diferença > 4 °C, ou chuva com um
  modelo seco (< 1 mm) e outro molhado (>= 10 mm)
Saída: dados/longo.json
"""
import json
import os
import statistics
import urllib.parse
import urllib.request
from datetime import datetime

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "dados", "longo.json")
DIAS = 15
MODELOS = ["ecmwf_ifs025", "gfs_seamless", "icon_seamless"]
CONJUNTO = ["gfs025", "ecmwf_ifs025"]
CHUVA_ALGUMA, CHUVA_FORTE = 1, 10      # mm no dia
DIF_TEMP = 4                           # °C entre máximas dos modelos
NIVEIS = ["baixa", "média", "alta"]


def _get(url, params):
    q = urllib.parse.urlencode(params, safe=",")
    with urllib.request.urlopen(f"{url}?{q}", timeout=60) as r:
        return json.load(r)


def _base(d):
    return {"latitude": config.CENTRO[0], "longitude": config.CENTRO[1],
            "forecast_days": DIAS + 1, "timezone": config.TZ, **d}


def _serie(daily, var, i):
    """Valores do dia i em todas as colunas daquela variável (modelos ou versões), sem vazios."""
    return [v[i] for k, v in daily.items() if k.startswith(var + "_") and v[i] is not None]


def confianca(n_dia, tmax, chuva):
    nivel = 2 if n_dia <= 3 else 1 if n_dia <= 7 else 0
    discordam = (len(tmax) > 1 and max(tmax) - min(tmax) > DIF_TEMP) or \
                (len(chuva) > 1 and min(chuva) < CHUVA_ALGUMA and max(chuva) >= CHUVA_FORTE)
    return NIVEIS[max(0, nivel - discordam)], discordam


def calcular():
    vars_ = "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_gusts_10m_max"
    m = _get("https://api.open-meteo.com/v1/forecast",
             _base({"daily": vars_, "models": ",".join(MODELOS)}))["daily"]
    try:
        c = _get("https://ensemble-api.open-meteo.com/v1/ensemble",
                 _base({"daily": "precipitation_sum", "models": ",".join(CONJUNTO)}))["daily"]
    except Exception:
        c = None                           # sem conjunto: mostra só os modelos
    hoje = datetime.now().strftime("%Y-%m-%d")
    dias = []
    for i, data in enumerate(m["time"]):
        if data < hoje:
            continue
        tmax, tmin = _serie(m, "temperature_2m_max", i), _serie(m, "temperature_2m_min", i)
        chuva, raj = _serie(m, "precipitation_sum", i), _serie(m, "wind_gusts_10m_max", i)
        if not tmax:
            continue
        n_dia = len(dias) + 1
        conf, discordam = confianca(n_dia, tmax, chuva)
        dia = {"data": data, "tmax": round(statistics.median(tmax)), "tmin": round(statistics.median(tmin)),
               "chuva_mm": round(statistics.median(chuva), 1) if chuva else None,
               "rajada": round(statistics.median(raj)) if raj else None,
               "modelos": len(tmax), "confianca": conf, "discordam": discordam}
        if c and data in c["time"]:
            v = _serie(c, "precipitation_sum", c["time"].index(data))
            if len(v) >= 10:
                dia["chance_chuva"] = round(100 * sum(x >= CHUVA_ALGUMA for x in v) / len(v))
                dia["chance_forte"] = round(100 * sum(x >= CHUVA_FORTE for x in v) / len(v))
                dia["versoes"] = len(v)
        dias.append(dia)
        if len(dias) == DIAS:
            break
    saida = {"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "dias": dias,
             "regras": {"chuva_alguma_mm": CHUVA_ALGUMA, "chuva_forte_mm": CHUVA_FORTE, "dif_temp": DIF_TEMP}}
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    json.dump(saida, open(SAIDA, "w"), ensure_ascii=False)
    return saida


if __name__ == "__main__":
    for d in calcular()["dias"]:
        print(d)
