"""Tempestades ao vivo pelos raios do satélite GOES-19 (sensor GLM).

A cada rodada:
  1. baixa os arquivos de raios dos últimos JANELA_MIN minutos (um arquivo a cada 20 s, AWS grátis);
  2. junta raios próximos em células de tempestade;
  3. compara a posição de cada célula entre a primeira e a segunda metade da janela,
     calcula velocidade, direção e quando passa perto de Chapecó;
  4. marca "salto de raios" (taxa dobrou), sinal comum antes de vento forte e granizo.

Tudo aqui é conta. Nenhuma IA.
Uso: python3 raios.py  -> grava dados/raios.json
Precisa de: pip install h5py numpy
"""
import io
import json
import math
import os
import re
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import h5py
import numpy as np

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
DADOS = os.path.join(AQUI, "dados")
BUCKET = "https://noaa-goes19.s3.amazonaws.com"

# ---------- regras (ajustáveis) ----------
JANELA_MIN = 20          # minutos de raios olhados
RAIO_BUSCA_KM = 300      # só raios até aqui de Chapecó
LIGA_KM = 15             # raios a menos disso entram na mesma célula
MIN_RAIOS = 8            # célula precisa de pelo menos isso na janela
CASAMENTO_KM = 40        # deslocamento máximo aceito entre as duas metades (10 min)
VEL_MAX_KMH = 120        # acima disso é erro de casamento, descarta
PERTO_KM = 20            # "vai passar em Chapecó" se a trajetória chega a isso
HORIZONTE_MIN = 120      # só projeta até 2 h
SALTO_FATOR = 2.0        # taxa da 2ª metade / 1ª metade
SALTO_MIN_POR_MIN = 3    # e pelo menos 3 raios/min na 2ª metade


def km(a, b):
    p = math.radians
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin(p(b[0] - a[0]) / 2) ** 2 + math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(p(b[1] - a[1]) / 2) ** 2))


def _xy(lat, lon):
    """km a leste e ao norte de Chapecó (plano local; serve até ~300 km)."""
    lat0, lon0 = config.CENTRO
    return ((lon - lon0) * 111.32 * math.cos(math.radians(lat0)), (lat - lat0) * 110.57)


def _latlon(x, y):
    lat0, lon0 = config.CENTRO
    return (lat0 + y / 110.57, lon0 + x / (111.32 * math.cos(math.radians(lat0))))


def listar_arquivos(agora):
    chaves = []
    for h in {agora - timedelta(minutes=JANELA_MIN), agora}:
        pref = f"GLM-L2-LCFA/{h:%Y}/{h.timetuple().tm_yday:03d}/{h:%H}/"
        with urllib.request.urlopen(f"{BUCKET}/?list-type=2&prefix={pref}", timeout=30) as r:
            chaves += re.findall(r"<Key>([^<]+)</Key>", r.read().decode())
    saida = []
    for k in set(chaves):
        m = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})(\d{2})", k)
        t = datetime(int(m.group(1)), 1, 1, tzinfo=timezone.utc) + timedelta(
            days=int(m.group(2)) - 1, hours=int(m.group(3)), minutes=int(m.group(4)), seconds=int(m.group(5)))
        if agora - t <= timedelta(minutes=JANELA_MIN):
            saida.append((t, k))
    return sorted(saida)


def ler_arquivo(item):
    t, chave = item
    with urllib.request.urlopen(f"{BUCKET}/{chave}", timeout=60) as r:
        dados = r.read()
    with h5py.File(io.BytesIO(dados), "r") as f:
        lat = f["flash_lat"][:]
        lon = f["flash_lon"][:]
        if "scale_factor" in f["flash_lat"].attrs:   # valores podem vir compactados
            lat = lat * f["flash_lat"].attrs["scale_factor"] + f["flash_lat"].attrs["add_offset"]
            lon = lon * f["flash_lon"].attrs["scale_factor"] + f["flash_lon"].attrs["add_offset"]
    return t, np.asarray(lat, float).ravel(), np.asarray(lon, float).ravel()


def agrupar(pts):
    """pts = lista de (x, y, minutos_atras). Junta pontos a menos de LIGA_KM (grade + união)."""
    pai = list(range(len(pts)))

    def raiz(i):
        while pai[i] != i:
            pai[i] = pai[pai[i]]
            i = pai[i]
        return i

    caixas = {}
    for i, (x, y, _) in enumerate(pts):
        caixas.setdefault((int(x // LIGA_KM), int(y // LIGA_KM)), []).append(i)
    for (cx, cy), membros in caixas.items():
        viz = [j for dx in (-1, 0, 1) for dy in (-1, 0, 1) for j in caixas.get((cx + dx, cy + dy), [])]
        for i in membros:
            for j in viz:
                if j > i and (pts[i][0] - pts[j][0]) ** 2 + (pts[i][1] - pts[j][1]) ** 2 <= LIGA_KM ** 2:
                    pai[raiz(i)] = raiz(j)
    grupos = {}
    for i in range(len(pts)):
        grupos.setdefault(raiz(i), []).append(pts[i])
    return [g for g in grupos.values() if len(g) >= MIN_RAIOS]


def _centro(g):
    return (sum(p[0] for p in g) / len(g), sum(p[1] for p in g) / len(g))


def analisar_celula(g):
    meio = JANELA_MIN / 2
    velho = [p for p in g if p[2] >= meio]      # 10-20 min atrás
    novo = [p for p in g if p[2] < meio]        # últimos 10 min
    cx, cy = _centro(novo or g)
    lat, lon = _latlon(cx, cy)
    cel = {
        "lat": round(lat, 3), "lon": round(lon, 3), "raios": len(g),
        "raios_por_min": round(len(novo) / meio, 1),
        "raios_por_min_antes": round(len(velho) / meio, 1),
        "dist_km": round(math.hypot(cx, cy)), "vel_kmh": None, "rumo": None,
        "chega_min": None, "passa_a_km": None,
    }
    cel["salto"] = (cel["raios_por_min"] >= SALTO_MIN_POR_MIN and
                    cel["raios_por_min"] >= SALTO_FATOR * max(cel["raios_por_min_antes"], 0.5))
    if len(velho) >= MIN_RAIOS // 2 and len(novo) >= MIN_RAIOS // 2:
        vx0, vy0 = _centro(velho)
        dx, dy = cx - vx0, cy - vy0
        desloc = math.hypot(dx, dy)
        vel = desloc / meio * 60          # km/h
        if desloc <= CASAMENTO_KM and vel <= VEL_MAX_KMH:
            cel["vel_kmh"] = round(vel)
            cel["rumo"] = round((math.degrees(math.atan2(dx, dy)) + 360) % 360)   # para onde vai
            if vel > 5:
                ux, uy = dx / desloc, dy / desloc
                ao_longo = -(cx * ux + cy * uy)          # km até o ponto mais perto de Chapecó
                lateral = abs(cx * uy - cy * ux)
                cel["passa_a_km"] = round(lateral)
                if ao_longo > 0 and lateral <= PERTO_KM:
                    minutos = ao_longo / vel * 60
                    if minutos <= HORIZONTE_MIN:
                        cel["chega_min"] = round(minutos)
    if cel["dist_km"] <= PERTO_KM:
        cel["chega_min"] = 0                           # já está em cima
    return cel


ROSA = ["norte", "nordeste", "leste", "sudeste", "sul", "sudoeste", "oeste", "noroeste"]


def direcao(graus):
    return ROSA[int((graus + 22.5) // 45) % 8]


def calcular(agora=None):
    agora = agora or datetime.now(timezone.utc)
    arquivos = listar_arquivos(agora)
    if not arquivos:
        raise RuntimeError("nenhum arquivo de raios do GOES-19 na janela")
    with ThreadPoolExecutor(8) as ex:
        lidos = list(ex.map(ler_arquivo, arquivos))
    pts = []
    for t, lat, lon in lidos:
        atras = (agora - t).total_seconds() / 60
        for la, lo in zip(lat, lon):
            x, y = _xy(la, lo)
            if math.hypot(x, y) <= RAIO_BUSCA_KM:
                pts.append((x, y, atras))
    celulas = sorted((analisar_celula(g) for g in agrupar(pts)), key=lambda c: c["dist_km"])
    estado = {
        "gerado_em": agora.astimezone(timezone(timedelta(hours=-3))).strftime("%Y-%m-%dT%H:%M:%S"),
        "janela_min": JANELA_MIN, "arquivos": len(arquivos),
        "ultimo_dado": arquivos[-1][0].astimezone(timezone(timedelta(hours=-3))).strftime("%H:%M"),
        "raios": [[round(_latlon(x, y)[0], 3), round(_latlon(x, y)[1], 3), round(a, 1)] for x, y, a in pts],
        "celulas": celulas,
    }
    os.makedirs(DADOS, exist_ok=True)
    json.dump(estado, open(os.path.join(DADOS, "raios.json"), "w"), ensure_ascii=False)
    return estado


if __name__ == "__main__":
    t0 = time.time()
    e = calcular()
    print(f"{e['arquivos']} arquivos, {len(e['raios'])} raios a até {RAIO_BUSCA_KM} km, "
          f"{len(e['celulas'])} células, {time.time() - t0:.0f}s, último dado {e['ultimo_dado']}")
    for c in e["celulas"][:8]:
        print(" ", c)
