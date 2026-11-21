"""Busca os modelos, aplica as regras e monta o estado do mapa.

Uso: python3 motor.py  -> grava dados/estado.json
"""
import json
import math
import os
import statistics
import time
import urllib.parse
import urllib.request

import config
import regras

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "dados")
os.makedirs(DADOS, exist_ok=True)

VARS = [
    "cape", "temperature_2m", "dew_point_2m", "surface_pressure",
    "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m", "precipitation",
    "temperature_850hPa", "dew_point_850hPa", "wind_speed_850hPa", "wind_direction_850hPa",
    "temperature_700hPa", "dew_point_700hPa",
    "temperature_500hPa", "dew_point_500hPa", "wind_speed_500hPa", "wind_direction_500hPa",
]
# Índices usados para comparar com eventos antigos, e a escala de cada um.
ESCALA = {"cape": 1000, "te": 10, "shear06": 10, "shear01": 5, "rajada": 30}


def _get(url, params):
    q = urllib.parse.urlencode(params, safe=",")
    with urllib.request.urlopen(f"{url}?{q}", timeout=180) as r:
        return json.load(r)


def grade():
    lat0, lon0 = config.CENTRO
    n, p = config.MEIA_GRADE, config.PASSO_GRADE
    return [(round(lat0 + i * p, 3), round(lon0 + j * p, 3))
            for i in range(-n, n + 1) for j in range(-n, n + 1)]


def km(a, b):
    p = math.radians
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin(p(b[0] - a[0]) / 2) ** 2 +
        math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(p(b[1] - a[1]) / 2) ** 2))


def _horas(bloco):
    """Converte a resposta da Open-Meteo em lista de dicts por hora."""
    h = bloco["hourly"]
    return [{k: h[k][t] for k in h} for t in range(len(h["time"]))]


def previsao(modelo, pontos):
    r = _get("https://api.open-meteo.com/v1/forecast", {
        "latitude": ",".join(str(p[0]) for p in pontos),
        "longitude": ",".join(str(p[1]) for p in pontos),
        "hourly": ",".join(VARS), "models": modelo, "wind_speed_unit": "ms",
        "forecast_hours": config.HORAS, "timezone": config.TZ,
    })
    return [_horas(b) for b in (r if isinstance(r, list) else [r])]


# ---------- eventos antigos ----------
def ambiente_eventos(eventos):
    """Para cada evento, o ambiente no pior momento do dia (cache em disco)."""
    cache_f = os.path.join(DADOS, "ambiente_eventos.json")
    cache = json.load(open(cache_f)) if os.path.exists(cache_f) else {}
    for e in eventos:
        chave = f"{e['data']}|{e['lat']}|{e['lon']}"
        if chave in cache:
            e["ambiente"] = cache[chave]
            continue
        if e["data"] < "2021-06-01":      # arquivo de modelos da Open-Meteo não chega antes disso
            e["ambiente"] = None
            continue
        try:
            r = _get("https://historical-forecast-api.open-meteo.com/v1/forecast", {
                "latitude": e["lat"], "longitude": e["lon"], "start_date": e["data"],
                "end_date": e["data"], "hourly": ",".join(VARS),
                "wind_speed_unit": "ms", "timezone": config.TZ})
            melhor = None
            for h in _horas(r):
                i = regras.indices(h)
                if i["cape"] is None or i["shear06"] is None:
                    continue
                peso = i["cape"] * i["shear06"] + (i["wmsi"] or 0) * 100
                if melhor is None or peso > melhor[0]:
                    melhor = (peso, h["time"], i)
            cache[chave] = {"hora": melhor[1], **melhor[2]} if melhor else None
        except Exception as erro:          # sem dado histórico nessa data: fica de fora
            print("sem ambiente para", chave, erro)
            continue
        e["ambiente"] = cache[chave]
        time.sleep(0.3)
    json.dump(cache, open(cache_f, "w"), indent=1)
    return eventos


def _vetor(i):
    return [i[k] / s if i.get(k) is not None else None for k, s in ESCALA.items()]


def semelhanca(a, b):
    """1 = ambiente igual, perto de 0 = nada a ver. Ignora índices faltando."""
    pares = [(x, y) for x, y in zip(_vetor(a), _vetor(b)) if x is not None and y is not None]
    if len(pares) < 3:
        return None
    d2 = sum((x - y) ** 2 for x, y in pares) / len(pares)
    return math.exp(-d2)


TIPOS_POR_FENOMENO = {"microexplosao": {"microexplosao"}, "tornado": {"tornado"},
                      "vento": {"microexplosao", "tornado"}}


# ---------- estado completo ----------
def calcular():
    pontos = grade()
    eventos = ambiente_eventos(json.load(open(os.path.join(AQUI, "eventos.json"))))

    por_modelo = {}
    for m in config.MODELOS:
        try:
            por_modelo[m] = previsao(m, pontos)
        except Exception as erro:
            print("modelo falhou:", m, erro)   # mostra no painel, não vira "sem risco"
    if not por_modelo:
        raise RuntimeError("nenhum modelo respondeu")

    horas = [h["time"] for h in next(iter(por_modelo.values()))[0]]
    celulas = []
    for idx, p in enumerate(pontos):
        cel = {"lat": p[0], "lon": p[1], "dist_km": round(km(config.CENTRO, p), 1), "janelas": {}}
        # níveis por modelo, por hora
        niveis = {m: [] for m in por_modelo}
        ind = {m: [] for m in por_modelo}
        for m, dados in por_modelo.items():
            for h in dados[idx]:
                i = regras.indices(h)
                ind[m].append(i)
                niveis[m].append({f: fn(i) for f, fn in regras.NIVEIS.items()})

        for nome, (a, b) in config.JANELAS.items():
            jan = {}
            for f in config.FENOMENOS:
                picos = {m: max(n[f] for n in niveis[m][a:b]) for m in niveis}
                modelos = sum(picos.values()) / len(picos)
                # índices do pior momento de cada modelo -> mediana -> compara com histórico
                piores = []
                for m in niveis:
                    t = max(range(a, b), key=lambda t: (niveis[m][t][f], ind[m][t]["cape"] or 0))
                    piores.append(ind[m][t])
                atual = {k: statistics.median([x[k] for x in piores if x[k] is not None])
                         if any(x[k] is not None for x in piores) else None for k in ESCALA}
                analogos = []
                for e in eventos:
                    if e["tipo"] in TIPOS_POR_FENOMENO[f] and e.get("ambiente"):
                        s = semelhanca(atual, e["ambiente"])
                        if s is not None:
                            analogos.append((s, e))
                analogos.sort(key=lambda x: -x[0])
                jan[f] = {
                    "modelos": round(modelos, 3),
                    "por_modelo": picos,
                    "analogos": round(analogos[0][0], 3) if analogos else 0,
                    "top_analogos": [{"sim": round(s, 2), "data": e["data"], "cidade": e["cidade"],
                                      "tipo": e["tipo"]} for s, e in analogos[:3]],
                    "indices": {k: (round(v, 1) if v is not None else None) for k, v in atual.items()},
                }
            cel["janelas"][nome] = jan
        cel["serie"] = {m: [{f: n[f] for f in config.FENOMENOS} for n in niveis[m]] for m in niveis}
        # projeção hora a hora: mediana dos modelos (chuva mm/h, rajada km/h) e risco médio
        def _med(vals):
            v = [x for x in vals if x is not None]
            return round(statistics.median(v), 1) if v else None
        n_h = len(horas)
        cel["hora"] = {
            "chuva": [_med([por_modelo[m][idx][t].get("precipitation") for m in por_modelo]) for t in range(n_h)],
            "chuva_max": [max([por_modelo[m][idx][t].get("precipitation") or 0 for m in por_modelo]) for t in range(n_h)],
            "rajada": [_med([ind[m][t]["rajada"] for m in ind]) for t in range(n_h)],
            **{f: [round(sum(niveis[m][t][f] for m in niveis) / len(niveis), 2) for t in range(n_h)]
               for f in config.FENOMENOS},
        }
        cel["motivos_agora"] = {m: regras.motivos(ind[m][0]) for m in ind}
        celulas.append(cel)

    # série por modelo só no ponto de Chapecó (deixa o arquivo leve)
    perto = min(celulas, key=lambda c: c["dist_km"])
    for c in celulas:
        if c is not perto:
            c.pop("serie", None)
            c.pop("motivos_agora", None)

    # densidade histórica (quanto já aconteceu perto de cada ponto), 0-1
    for f in config.FENOMENOS:
        dens = [sum(math.exp(-(km((c["lat"], c["lon"]), (e["lat"], e["lon"])) / config.RAIO_HISTORICO_KM) ** 2)
                    for e in eventos if e["tipo"] in TIPOS_POR_FENOMENO[f]) for c in celulas]
        top = max(dens) or 1
        for c, d in zip(celulas, dens):
            for jan in c["janelas"].values():
                j = jan[f]
                j["historico"] = round(d / top, 3)
                w = config.PESOS
                j["combinado"] = round(w["modelos"] * j["modelos"] + w["analogos"] * j["analogos"] * j["modelos"] ** 0.5
                                       + w["historico"] * j["historico"] * j["modelos"] ** 0.5, 3)

    estado = {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "centro": config.CENTRO, "passo": config.PASSO_GRADE, "horas": horas,
        "modelos": {m: config.MODELOS[m] for m in por_modelo},
        "modelos_falharam": [config.MODELOS[m] for m in config.MODELOS if m not in por_modelo],
        "pesos": config.PESOS, "celulas": celulas,
        "eventos": [{k: e[k] for k in ("data", "cidade", "lat", "lon", "tipo", "intensidade", "fonte")} for e in eventos],
    }
    json.dump(estado, open(os.path.join(DADOS, "estado.json"), "w"), ensure_ascii=False)
    return estado


def estado_cacheado():
    f = os.path.join(DADOS, "estado.json")
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < config.CACHE_MIN * 60:
        return json.load(open(f))
    return calcular()


if __name__ == "__main__":
    e = calcular()
    c = min(e["celulas"], key=lambda c: c["dist_km"])
    print("Chapecó, próximas 24h:", json.dumps(c["janelas"]["0-24h"], ensure_ascii=False, indent=1))
