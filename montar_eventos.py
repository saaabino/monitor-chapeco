"""Remonta eventos.json a partir das listas da Wikipédia (SC e RS) + eventos_manuais.json.

Uso: python3 montar_eventos.py
"""
import json
import math
import os
import re
import urllib.parse
import urllib.request

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIO_KM = 150
LISTAS = {
    "SC": "Lista_de_tornados_em_Santa_Catarina",
    "RS": "Lista_de_tornados_no_Rio_Grande_do_Sul",
}
UA = {"User-Agent": "monitor-chapeco/1.0 (uso pessoal)"}


def km(a, b):
    p = math.radians
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin(p(b[0] - a[0]) / 2) ** 2 + math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(p(b[1] - a[1]) / 2) ** 2))


def baixar(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read().decode()


def tornados_wiki():
    saida = []
    for uf, pagina in LISTAS.items():
        texto = baixar(f"https://pt.wikipedia.org/w/index.php?title={pagina}&action=raw")
        mapa = json.loads(re.search(r"<mapframe[^>]*>(.*?)</mapframe>", texto, re.S).group(1))
        pontos = [d for d in mapa if d.get("type") == "FeatureCollection"][0]["features"]
        for f in pontos:
            lon, lat = f["geometry"]["coordinates"]
            dist = km(config.CENTRO, (lat, lon))
            if dist > RAIO_KM:
                continue
            cidade = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", f["properties"]["title"])
            for linha in f["properties"]["description"].split("<br>"):
                m = re.search(r"(registro-\w+-\d+)\|(\d\d)/(\d\d)/(\d{4})\]\](?:\s*·\s*(\S+))?", linha)
                if not m:
                    continue
                saida.append({
                    "data": f"{m.group(4)}-{m.group(3)}-{m.group(2)}", "cidade": cidade, "uf": uf,
                    "lat": round(lat, 3), "lon": round(lon, 3), "dist_km": round(dist),
                    "tipo": "tornado", "intensidade": m.group(5) or "?",
                    "fonte": f"https://pt.wikipedia.org/wiki/{pagina}#{m.group(1)}",
                    "nota": "posição = centro da cidade",
                })
    return saida


def geocodificar(cidade, uf):
    r = json.loads(baixar("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
        {"name": cidade, "count": 10, "language": "pt", "countryCode": "BR"})))
    estado = {"SC": "Santa Catarina", "RS": "Rio Grande do Sul", "PR": "Paraná"}[uf]
    for x in r.get("results", []):
        if x.get("admin1") == estado:
            return round(x["latitude"], 3), round(x["longitude"], 3)
    raise ValueError(f"não achei {cidade}/{uf}")


def main():
    eventos = tornados_wiki()
    for e in json.load(open(os.path.join(AQUI, "eventos_manuais.json"))):
        e = dict(e)
        e["lat"], e["lon"] = geocodificar(e["cidade"], e["uf"])
        e["dist_km"] = round(km(config.CENTRO, (e["lat"], e["lon"])))
        e.setdefault("nota", "posição = centro da cidade")
        tira = e.pop("substitui", None)
        if tira:   # mesma data e cidade, órgão oficial disse outra coisa
            eventos = [x for x in eventos if not (x["data"] == e["data"] and x["cidade"] == e["cidade"] and x["tipo"] == tira)]
        eventos.append(e)
    eventos.sort(key=lambda e: (e["data"], e["cidade"]))
    json.dump(eventos, open(os.path.join(AQUI, "eventos.json"), "w"), ensure_ascii=False, indent=1)
    tipos = {}
    for e in eventos:
        tipos[e["tipo"]] = tipos.get(e["tipo"], 0) + 1
    print(len(eventos), "eventos:", tipos)


if __name__ == "__main__":
    main()
