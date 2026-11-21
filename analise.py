"""Resumo em frases do momento: ao vivo + previsão + passado + relatos.

Tudo montado por código a partir dos números já calculados. Não inventa nada.
Saída: dados/analise.json (o painel mostra no topo; o boletim do Telegram usa o mesmo texto).
"""
import json
import math
import os
from datetime import datetime

import config

NOMES = {"microexplosao": "microexplosão", "tornado": "tornado", "vento": "vento forte"}
ROSA = ["norte", "nordeste", "leste", "sudeste", "sul", "sudoeste", "oeste", "noroeste"]


def _rumo(g):
    return ROSA[int(((g + 22.5) % 360) // 45)]


def _azimute(lat, lon):
    lat0, lon0 = config.CENTRO
    r = math.radians
    y = math.sin(r(lon - lon0)) * math.cos(r(lat))
    x = math.cos(r(lat0)) * math.sin(r(lat)) - math.sin(r(lat0)) * math.cos(r(lat)) * math.cos(r(lon - lon0))
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _hora(estado, i):
    h = estado["horas"][i]
    hoje = estado["horas"][0][:10]
    dia = "" if h[:10] == hoje else f" de {h[8:10]}/{h[5:7]}"
    return f"{h[11:13]}h{dia}"


def frases_ao_vivo(raios):
    if not raios:
        return ["Sem dados de raios nesta rodada."], "calmo"
    vem = sorted([c for c in raios["celulas"] if c["chega_min"] is not None], key=lambda c: c["chega_min"])
    if vem:
        c = vem[0]
        if c["chega_min"] == 0:
            f = f"Tempestade com raios sobre Chapecó agora ({c['raios_por_min']} raios/min)."
        else:
            f = (f"Tempestade a {c['dist_km']} km a {_rumo(_azimute(c['lat'], c['lon']))}, "
                 f"vindo a {c['vel_kmh']} km/h, chega em ~{c['chega_min']} min.")
        if c["salto"]:
            f += " Salto de raios: sinal de vento forte e granizo."
        return [f], "critico"
    if raios["celulas"]:
        c = raios["celulas"][0]
        f = f"Nenhuma tempestade vindo. Mais perto: {c['dist_km']} km a {_rumo(_azimute(c['lat'], c['lon']))}"
        if c["vel_kmh"]:
            f += f", indo para {_rumo(c['rumo'])}"
            if c["passa_a_km"] is not None:
                f += f" (passa a ~{c['passa_a_km']} km)"
        return [f + "."], "calmo"
    return [f"Nenhuma tempestade com raios a até 300 km nos últimos {raios['janela_min']} min."], "calmo"


def frases_previsao(estado):
    if not estado:
        return [], "calmo"
    c = min(estado["celulas"], key=lambda c: c["dist_km"])
    saida, nivel = [], "calmo"
    for f in ("microexplosao", "tornado"):
        serie = c["hora"][f]
        alto = next((i for i, v in enumerate(serie) if v >= 1), None)
        aten = next((i for i, v in enumerate(serie) if v >= 0.5), None)
        if alto is not None:
            saida.append(f"Ambiente favorável a {NOMES[f]} a partir das {_hora(estado, alto)} (todos os modelos concordam).")
            nivel = "atencao"
        elif aten is not None:
            saida.append(f"Atenção para {NOMES[f]} a partir das {_hora(estado, aten)}.")
            nivel = "atencao" if nivel == "calmo" else nivel
    chuva = c["hora"]["chuva"]
    forte = next((i for i, v in enumerate(chuva) if (v or 0) >= 5), None)
    pico = max(range(len(chuva)), key=lambda i: chuva[i] or 0)
    if forte is not None:
        saida.append(f"Chuva forte (≥5 mm/h) prevista às {_hora(estado, forte)}; pico {chuva[pico]} mm/h às {_hora(estado, pico)}.")
    elif (chuva[pico] or 0) >= 1:
        saida.append(f"Chuva moderada: pico {chuva[pico]} mm/h às {_hora(estado, pico)}.")
    else:
        saida.append("Sem chuva relevante prevista nas próximas 48 h.")
    raj = [v or 0 for v in c["hora"]["rajada"]]
    i = max(range(len(raj)), key=lambda i: raj[i])
    if raj[i] >= 60:
        saida.append(f"Rajada de até {round(raj[i])} km/h prevista às {_hora(estado, i)}.")
    top = sorted(c["janelas"]["0-24h"]["microexplosao"]["top_analogos"] + c["janelas"]["0-24h"]["tornado"]["top_analogos"],
                 key=lambda a: -a["sim"])
    if top and top[0]["sim"] >= 0.7 and nivel != "calmo":
        a = top[0]
        saida.append(f"O tempo previsto lembra {a['data'][8:10]}/{a['data'][5:7]}/{a['data'][:4]} em {a['cidade']} "
                     f"({NOMES[a['tipo']]}, {round(a['sim'] * 100)}% parecido).")
    return saida, nivel


def frases_relatos(relatos):
    agora = datetime.now()
    rec = [r for r in relatos if (agora - datetime.fromisoformat(r["hora"])).total_seconds() < 6 * 3600]
    if not rec:
        return []
    tipos = {}
    for r in rec:
        tipos[r["tipo"]] = tipos.get(r["tipo"], 0) + 1
    partes = [f"{n} de {t.replace('_', ' ')}" for t, n in sorted(tipos.items(), key=lambda x: -x[1])]
    return [f"Relatos nas últimas 6 h: " + ", ".join(partes) + "."]


def frases_conjunto(conj, estado):
    if not conj:
        return []
    saida = []
    H = conj["horas"]
    def quando(i):
        h = H[i]
        return f"{h[11:13]}h" + ("" if h[:10] == H[0][:10] else f" de {h[8:10]}/{h[5:7]}")
    for chave, rotulo, minimo in (("chuva_5", "chuva forte (≥5 mm/h)", 10), ("rajada_60", "rajada ≥60 km/h", 10)):
        s = [x or 0 for x in conj["chance"][chave]]
        i = max(range(len(s)), key=lambda i: s[i])
        if s[i] >= minimo:
            saida.append(f"Chance de {rotulo}: até {s[i]}% às {quando(i)}.")
    return saida


def frases_radar(radar):
    if not radar:
        return []
    if radar["idade_min"] > 30:
        return [f"Radar de Chapecó: última imagem de {radar['idade_min'] // 60}h{radar['idade_min'] % 60:02d} atrás (atrasado)."]
    p = radar["eco_forte_mais_perto"]
    f = "Radar: chovendo em Chapecó agora. " if radar["chove_em_chapeco"] else ""
    if p and p["dist_km"] <= 150:
        f += f"Chuva muito forte mais perto a {p['dist_km']} km ({_rumo(_azimute(p['lat'], p['lon']))})."
    elif not f:
        f = "Radar: sem chuva muito forte a até 150 km."
    return [f.strip()]


def montar(estado, raios, relatos, conjunto=None, radar=None):
    vivo, n1 = frases_ao_vivo(raios)
    vivo = vivo + frases_radar(radar)
    prev, n2 = frases_previsao(estado)
    prev += frases_conjunto(conjunto, estado)
    ordem = ["calmo", "atencao", "critico"]
    nivel = max(n1, n2, key=ordem.index)
    a = {"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "nivel": nivel,
         "ao_vivo": vivo, "previsao": prev, "relatos": frases_relatos(relatos)}
    json.dump(a, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "analise.json"), "w"),
              ensure_ascii=False)
    return a


def texto(a):
    return "\n".join(a["ao_vivo"] + a["previsao"] + a["relatos"])
