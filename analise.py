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


DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]
PERIODOS = [("madrugada", 0, 6), ("manhã", 6, 12), ("tarde", 12, 18), ("noite", 18, 24)]
DICA = {
    "microexplosao": "fique atento a nuvem escura chegando rápido e vento forte de repente; guarde objetos soltos",
    "tornado": "fique atento ao céu e aos avisos; saiba onde se abrigar (cômodo sem janela, no térreo)",
}


def _nome_dia(data, hoje):
    from datetime import date
    d = date.fromisoformat(data)
    delta = (d - hoje).days
    return "hoje" if delta == 0 else "amanhã" if delta == 1 else DIAS_SEMANA[d.weekday()]


def _quando(horas, i0, i1, hoje):
    """'amanhã entre 12h e 17h' ou 'de hoje 22h até amanhã 3h'."""
    a, b = horas[i0], horas[i1]
    fim = int(b[11:13]) + 1
    if a[:10] == b[:10]:
        return f"{_nome_dia(a[:10], hoje)} entre {int(a[11:13])}h e {fim}h"
    return f"de {_nome_dia(a[:10], hoje)} {int(a[11:13])}h até {_nome_dia(b[:10], hoje)} {fim}h"


def janelas(serie, limiar, junta=2):
    """Trechos seguidos com valor >= limiar (junta buracos de até 2 h). Devolve (início, fim, máximo)."""
    saida = []
    for i, v in enumerate(serie):
        if (v or 0) >= limiar:
            if saida and i - saida[-1][1] <= junta + 1:
                saida[-1][1] = i
                saida[-1][2] = max(saida[-1][2], v)
            else:
                saida.append([i, i, v])
    return saida


def frases_previsao(estado, conjunto=None):
    """Frases do tipo 'Amanhã entre 12h e 17h: atenção para microexplosão. Fique atento...'."""
    if not estado:
        return [], "calmo"
    hoje = datetime.now().date()
    H = estado["horas"]
    c = min(estado["celulas"], key=lambda c: c["dist_km"])
    saida, nivel = [], "calmo"
    for f in ("microexplosao", "tornado"):
        js = janelas(c["hora"][f], 0.5)
        if not js:
            continue
        alto = any(mx >= 1 for _, _, mx in js)
        quando = "; ".join(_quando(H, i0, i1, hoje) for i0, i1, _ in js)
        if alto:
            txt = f"Risco ALTO de {NOMES[f]} (todos os modelos concordam): {quando}."
            nivel = "atencao"
        else:
            txt = f"Atenção para {NOMES[f]}: {quando}."
            nivel = "atencao" if nivel == "calmo" else nivel
        saida.append(f"{txt} {DICA[f][0].upper() + DICA[f][1:]}.")
    chuva = c["hora"]["chuva"]
    for i0, i1, mx in janelas(chuva, 1):
        pico = max(range(i0, i1 + 1), key=lambda i: chuva[i] or 0)
        forte = " forte" if mx >= 5 else ""
        quando = _quando(H, i0, i1, hoje)
        saida.append(f"Chuva{forte} {quando}, mais intensa às {int(H[pico][11:13])}h ({chuva[pico]} mm/h).")
    if not janelas(chuva, 1):
        saida.append("Sem chuva relevante prevista nas próximas 48 h.")
    raj = [v or 0 for v in c["hora"]["rajada"]]
    i = max(range(len(raj)), key=lambda i: raj[i])
    if raj[i] >= 60:
        saida.append(f"Vento: rajada de até {round(raj[i])} km/h {_nome_dia(H[i][:10], hoje)} às {int(H[i][11:13])}h.")
    top = sorted(c["janelas"]["0-24h"]["microexplosao"]["top_analogos"] + c["janelas"]["0-24h"]["tornado"]["top_analogos"],
                 key=lambda a: -a["sim"])
    if top and top[0]["sim"] >= 0.7 and nivel != "calmo":
        a = top[0]
        saida.append(f"O tempo previsto lembra {a['data'][8:10]}/{a['data'][5:7]}/{a['data'][:4]} em {a['cidade']} "
                     f"({NOMES[a['tipo']]}, {round(a['sim'] * 100)}% parecido).")
    return saida, nivel


def periodos(estado, conjunto):
    """Grade dia x período (madrugada, manhã, tarde, noite) para o painel."""
    if not estado:
        return []
    hoje = datetime.now().date()
    H = estado["horas"]
    c = min(estado["celulas"], key=lambda c: c["dist_km"])
    chance = {}
    if conjunto:
        for i, h in enumerate(conjunto["horas"]):
            chance[h] = conjunto["chance"]["chuva_5"][i]
    dias = []
    for data in sorted({h[:10] for h in H})[:3]:
        linha = {"dia": _nome_dia(data, hoje), "data": data, "celulas": []}
        for nome, a, b in PERIODOS:
            idx = [i for i, h in enumerate(H) if h[:10] == data and a <= int(h[11:13]) < b]
            if not idx:
                linha["celulas"].append(None)          # período que já passou ou fora das 48 h
                continue
            linha["celulas"].append({
                "periodo": nome, "horas": f"{a}–{b}h",
                "micro": max(c["hora"]["microexplosao"][i] for i in idx),
                "tornado": max(c["hora"]["tornado"][i] for i in idx),
                "vento": max(c["hora"]["vento"][i] for i in idx),
                "chuva_mm": round(sum(c["hora"]["chuva"][i] or 0 for i in idx), 1),
                "chuva_max": max((c["hora"]["chuva"][i] or 0) for i in idx),
                "rajada": round(max((c["hora"]["rajada"][i] or 0) for i in idx)),
                "chance_chuva_forte": max((chance.get(H[i]) or 0) for i in idx),
            })
        dias.append(linha)
    return dias


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


def frases_nuvens(nuvens, raios, ate_km=100):
    """Nuvem crescendo rápido perto, ainda sem raios. Só informa: não muda o nível até o placar mostrar acerto."""
    if not nuvens:
        return []
    celulas = (raios or {}).get("celulas", [])
    novas = [g for g in nuvens.get("grupos", []) if g["dist_km"] <= ate_km and
             not any(_km(g["lat"], g["lon"], c["lat"], c["lon"]) <= 30 for c in celulas)]
    if not novas:
        return []
    g = novas[0]
    f = (f"Satélite: nuvem crescendo rápido a {g['dist_km']} km ({_rumo(_azimute(g['lat'], g['lon']))}), "
         f"topo a {g['topo_c']} °C e esfriando {g['esfriou_k']:.0f} °C em 10 min, ainda sem raios. "
         f"Pode virar tempestade nos próximos 15 a 45 min.")
    if len(novas) > 1:
        f += f" Mais {len(novas) - 1} assim a até {ate_km} km."
    return [f]


def _km(la1, lo1, la2, lo2):
    p = math.radians
    return 2 * 6371 * math.asin(math.sqrt(math.sin(p(la2 - la1) / 2) ** 2 +
                                          math.cos(p(la1)) * math.cos(p(la2)) * math.sin(p(lo2 - lo1) / 2) ** 2))


def montar(estado, raios, relatos, conjunto=None, radar=None, nuvens=None):
    vivo, n1 = frases_ao_vivo(raios)
    vivo = vivo + frases_nuvens(nuvens, raios) + frases_radar(radar)
    prev, n2 = frases_previsao(estado, conjunto)
    prev += frases_conjunto(conjunto, estado)
    ordem = ["calmo", "atencao", "critico"]
    nivel = max(n1, n2, key=ordem.index)
    a = {"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"), "nivel": nivel,
         "ao_vivo": vivo, "previsao": prev, "relatos": frases_relatos(relatos),
         "periodos": periodos(estado, conjunto)}
    json.dump(a, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "dados", "analise.json"), "w"),
              ensure_ascii=False)
    return a


def texto(a):
    return "\n".join(a["ao_vivo"] + a["previsao"] + a["relatos"])
