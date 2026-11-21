"""Mede o acerto: compara o que foi previsto com o que aconteceu em Chapecó.

O que guarda (dados/, carregado de rodada em rodada):
  previsoes.json  - resumo por dia de cada previsão feita (risco, chance de chuva/rajada)
  observado.json  - por hora: raios a até 15 km (satélite), rajada e tempo do aeroporto (METAR SBCH)
  avisos_log.json - cada aviso de "tempestade chega em X min"

Como julga (regras simples, em código):
  tempestade aconteceu  = 5 ou mais raios a até 15 km de Chapecó no dia
  tempestade prevista   = risco de microexplosão ou tornado em "atenção" ou mais, no dia,
                          na previsão feita no dia anterior
  vento forte aconteceu = rajada >= 60 km/h no aeroporto ou relato de vento
  vento forte previsto  = chance >= 20% de rajada >= 60 km/h (conjunto)
  aviso confirmado      = raio a até 15 km entre o aviso e 30 min depois da hora prevista

Saída pública: dados/verificacao.json
"""
import json
import math
import os
import urllib.request
from datetime import datetime, timedelta

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(AQUI, "dados")
F_PREV, F_OBS, F_AVISOS, F_SAIDA = (os.path.join(D, n) for n in
                                    ("previsoes.json", "observado.json", "avisos_log.json", "verificacao.json"))

RAIO_KM = 15
RAIOS_TEMPESTADE = 5
RAJADA_FORTE = 60
CHANCE_VENTO = 20
GUARDA_DIAS = 45


def _ler(f, padrao):
    return json.load(open(f)) if os.path.exists(f) else padrao


def _km(lat, lon):
    lat0, lon0 = config.CENTRO
    return 111.2 * math.hypot(lat - lat0, (lon - lon0) * math.cos(math.radians(lat0)))


def registrar_previsao(estado, conjunto):
    """Guarda o resumo diário da previsão, uma vez por previsão nova."""
    prev = _ler(F_PREV, [])
    if not estado or (prev and prev[-1]["feito"] == estado["gerado_em"]):
        return
    c = min(estado["celulas"], key=lambda c: c["dist_km"])
    dias = {}
    for i, h in enumerate(estado["horas"]):
        d = dias.setdefault(h[:10], {"micro": 0, "tornado": 0, "vento": 0, "chuva_mm": 0})
        d["micro"] = max(d["micro"], c["hora"]["microexplosao"][i])
        d["tornado"] = max(d["tornado"], c["hora"]["tornado"][i])
        d["vento"] = max(d["vento"], c["hora"]["vento"][i])
        d["chuva_mm"] = round(d["chuva_mm"] + (c["hora"]["chuva"][i] or 0), 1)
    if conjunto:
        for i, h in enumerate(conjunto["horas"]):
            if h[:10] in dias:
                d = dias[h[:10]]
                for k in ("chuva_5", "rajada_60"):
                    d[k] = max(d.get(k, 0), conjunto["chance"][k][i] or 0)
    prev.append({"feito": estado["gerado_em"], "dias": dias})
    limite = (datetime.now() - timedelta(days=GUARDA_DIAS)).isoformat()
    json.dump([p for p in prev if p["feito"] >= limite], open(F_PREV, "w"))


def metar():
    """Rajada máxima (km/h) e tempo presente por hora, aeroporto de Chapecó (fecha à noite)."""
    url = "https://aviationweather.gov/api/data/metar?ids=SBCH&hours=3&format=json"
    req = urllib.request.Request(url, headers={"User-Agent": "monitor-chapeco/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        corpo = r.read()
    dados = json.loads(corpo) if corpo.strip() else []     # vazio = aeroporto fechado (noite)
    saida = {}
    for m in dados:
        t = datetime.fromisoformat(m["reportTime"].replace("Z", "+00:00")) - timedelta(hours=3)
        v = max(m.get("wspd") or 0, m.get("wgst") or 0) * 1.852
        saida[t.strftime("%Y-%m-%dT%H")] = {"rajada_kmh": round(v), "tempo": m.get("wxString") or ""}
    return saida


def registrar_observacao(raios, relatos, erros):
    obs = _ler(F_OBS, {})
    agora = datetime.now().strftime("%Y-%m-%dT%H")
    o = obs.setdefault(agora, {})
    if raios:
        perto = sum(1 for la, lo, idade in raios["raios"] if _km(la, lo) <= RAIO_KM)
        o["raios_15km"] = max(o.get("raios_15km", 0), perto)   # maior contagem de 20 min vista na hora
    try:
        for hora, m in metar().items():
            x = obs.setdefault(hora, {})
            x["rajada_kmh"] = max(x.get("rajada_kmh", 0), m["rajada_kmh"])
            x["tempo"] = m["tempo"] or x.get("tempo", "")
    except Exception as e:
        erros.append(f"METAR: {e}")
    for r in relatos or []:
        if r["tipo"] not in ("nao_e_vento", "indefinido"):
            obs.setdefault(r["hora"][:13], {})["relato_vento"] = True
    limite = (datetime.now() - timedelta(days=GUARDA_DIAS)).strftime("%Y-%m-%dT%H")
    json.dump({k: v for k, v in obs.items() if k >= limite}, open(F_OBS, "w"))


def registrar_aviso(chega_min):
    av = _ler(F_AVISOS, [])
    av.append({"hora": datetime.now().strftime("%Y-%m-%dT%H:%M"), "chega_min": chega_min})
    json.dump(av[-500:], open(F_AVISOS, "w"))


def _placar():
    return {"acertos": 0, "alarmes_falsos": 0, "perdidas": 0, "calmos_certos": 0}


def _somar(p, previsto, aconteceu):
    k = ("acertos" if aconteceu else "alarmes_falsos") if previsto else ("perdidas" if aconteceu else "calmos_certos")
    p[k] += 1


def avaliar():
    prev, obs, avisos = _ler(F_PREV, []), _ler(F_OBS, {}), _ler(F_AVISOS, [])
    hoje = datetime.now().strftime("%Y-%m-%d")
    dias_obs = sorted({k[:10] for k in obs if k[:10] < hoje})
    placar = {"tempestade": _placar(), "vento": _placar()}
    linhas = []
    for dia in dias_obs[-30:]:
        horas = [v for k, v in obs.items() if k.startswith(dia)]
        if len(horas) < 18:                        # dia sem dados suficientes: não conta
            continue
        # previsão feita no dia anterior (a última antes da meia-noite)
        feitas = [p for p in prev if p["feito"][:10] < dia and dia in p["dias"]]
        if not feitas:
            continue
        p = feitas[-1]["dias"][dia]
        tempestade_obs = sum(h.get("raios_15km", 0) for h in horas) >= RAIOS_TEMPESTADE
        tempestade_prev = max(p["micro"], p["tornado"]) >= 0.5
        vento_obs = any(h.get("rajada_kmh", 0) >= RAJADA_FORTE or h.get("relato_vento") for h in horas)
        vento_prev = p.get("rajada_60", 0) >= CHANCE_VENTO or p["vento"] >= 0.5
        _somar(placar["tempestade"], tempestade_prev, tempestade_obs)
        _somar(placar["vento"], vento_prev, vento_obs)
        linhas.append({"dia": dia, "tempestade": [tempestade_prev, tempestade_obs], "vento": [vento_prev, vento_obs],
                       "chuva_prevista_mm": p["chuva_mm"]})
    # avisos de chegada
    conf = total = 0
    agora = datetime.now()
    for a in avisos:
        t = datetime.fromisoformat(a["hora"])
        fim = t + timedelta(minutes=(a["chega_min"] or 0) + 30)
        if fim > agora:
            continue                               # ainda não dá para julgar
        total += 1
        horas = {(t + timedelta(hours=i)).strftime("%Y-%m-%dT%H") for i in range(int((fim - t).total_seconds() // 3600) + 1)}
        if any(obs.get(h, {}).get("raios_15km", 0) > 0 for h in horas):
            conf += 1
    saida = {"gerado_em": agora.strftime("%Y-%m-%dT%H:%M:%S"), "dias_avaliados": len(linhas),
             "placar": placar, "avisos": {"julgados": total, "confirmados": conf}, "dias": linhas,
             "regras": {"raio_km": RAIO_KM, "raios_tempestade": RAIOS_TEMPESTADE,
                        "rajada_forte_kmh": RAJADA_FORTE, "chance_vento_pct": CHANCE_VENTO}}
    json.dump(saida, open(F_SAIDA, "w"), ensure_ascii=False)
    return saida
