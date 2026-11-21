"""Topo de nuvem esfriando rápido (GOES-19 ABI, canal 13, infravermelho 10,3 µm).

Nuvem de tempestade crescendo sobe e o topo esfria. Isso costuma aparecer 15-30 min antes
dos primeiros raios. A cada rodada:
  1. lê as duas imagens mais recentes do disco inteiro (uma a cada 10 min), só o pedaço até
     RAIO_KM de Chapecó (leitura por partes do arquivo na AWS, sem baixar os 24 MB);
  2. divide em caixas de CAIXA_GRAUS e pega a temperatura mais fria de cada caixa;
  3. esfriamento = mais fria agora - mais fria da imagem anterior nas caixas vizinhas (3x3).
     Olhar as vizinhas evita confundir nuvem que só andou com nuvem que cresceu;
  4. marca a caixa se esfriou >= ESFRIOU_K e o topo já está abaixo de TOPO_MAX_K (-15 °C,
     onde começa a formar gelo, fase em que vêm os raios). Caixas marcadas vizinhas viram um grupo.

Tudo aqui é conta. Nenhuma IA.
Uso: python3 abi.py  -> grava dados/nuvens.json
"""
import json
import math
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import h5py
import numpy as np

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
SAIDA = os.path.join(AQUI, "dados", "nuvens.json")
BUCKET = "https://noaa-goes19.s3.amazonaws.com"
PRODUTO = "ABI-L2-CMIPF"

# ---------- regras (ajustáveis) ----------
RAIO_KM = 300
CAIXA_GRAUS = 0.1        # ~11 km
TOPO_MAX_K = 258         # -15 °C
ESFRIOU_K = 4            # moderado: >= 4 K em 10 min
FORTE_K = 8              # forte:    >= 8 K em 10 min
MIN_CAIXAS = 2           # grupo precisa de pelo menos 2 caixas (corta ruído de 1 pixel)
# placar: grupo a até PLACAR_RAIO_KM de Chapecó "virou tempestade" se aparece célula de raios
# a até CONFIRMA_KM dele em até CONFIRMA_MIN minutos
PLACAR_RAIO_KM = 150
CONFIRMA_KM = 30
CONFIRMA_MIN = 45
LOG = os.path.join(AQUI, "dados", "nuvens_log.json")


class ArquivoRemoto:
    """Arquivo da AWS lido por partes (HTTP Range), em blocos guardados na memória."""
    BLOCO = 1 << 20

    def __init__(self, url):
        self.url, self.pos, self.blocos = url, 0, {}
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            self.tam = int(r.headers["Content-Length"])

    def _bloco(self, n):
        if n not in self.blocos:
            a, b = n * self.BLOCO, min(self.tam, (n + 1) * self.BLOCO) - 1
            req = urllib.request.Request(self.url, headers={"Range": f"bytes={a}-{b}"})
            with urllib.request.urlopen(req, timeout=60) as r:
                self.blocos[n] = r.read()
        return self.blocos[n]

    def read(self, n=-1):
        if n < 0:
            n = self.tam - self.pos
        n = max(0, min(n, self.tam - self.pos))
        out = bytearray()
        while len(out) < n:
            p = self.pos + len(out)
            b = self._bloco(p // self.BLOCO)
            ini = p % self.BLOCO
            out += b[ini:ini + n - len(out)]
        self.pos += n
        return bytes(out)

    def readinto(self, buf):
        d = self.read(len(buf))
        buf[:len(d)] = d
        return len(d)

    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.tam + off
        return self.pos

    def tell(self):
        return self.pos

    def seekable(self):
        return True

    def readable(self):
        return True


def listar(agora, n=2):
    """As n imagens mais recentes do canal 13 (procura na hora atual e na anterior)."""
    chaves = []
    for h in (1, 0):
        t = agora - timedelta(hours=h)
        pre = f"{PRODUTO}/{t:%Y}/{t.timetuple().tm_yday:03d}/{t:%H}/"
        with urllib.request.urlopen(f"{BUCKET}/?list-type=2&prefix={pre}", timeout=30) as r:
            chaves += [k for k in re.findall(r"<Key>([^<]+)</Key>", r.read().decode()) if "M6C13_" in k or "C13_G19" in k]
    return sorted(chaves)[-n:]


def _hora(chave):
    s = re.search(r"_s(\d{4})(\d{3})(\d{2})(\d{2})", chave).groups()
    return datetime(int(s[0]), 1, 1, int(s[2]), int(s[3]), tzinfo=timezone.utc) + timedelta(days=int(s[1]) - 1)


def _para_xy(lat, lon, p):
    """lat/lon -> ângulos de varredura x, y do GOES (fórmulas do manual do produto, GOES-R PUG)."""
    req, rpol = p["semi_major_axis"], p["semi_minor_axis"]
    H = p["perspective_point_height"] + req
    lon0 = math.radians(p["longitude_of_projection_origin"])
    phi, lam = np.radians(lat), np.radians(lon)
    phic = np.arctan((rpol ** 2 / req ** 2) * np.tan(phi))
    e2 = (req ** 2 - rpol ** 2) / req ** 2
    rc = rpol / np.sqrt(1 - e2 * np.cos(phic) ** 2)
    sx = H - rc * np.cos(phic) * np.cos(lam - lon0)
    sy = -rc * np.cos(phic) * np.sin(lam - lon0)
    sz = rc * np.sin(phic)
    return np.arcsin(-sy / np.sqrt(sx ** 2 + sy ** 2 + sz ** 2)), np.arctan(sz / sx)


def _para_latlon(x, y, p):
    """ângulos de varredura -> lat/lon (inverso de _para_xy, mesmo manual)."""
    req, rpol = p["semi_major_axis"], p["semi_minor_axis"]
    H = p["perspective_point_height"] + req
    a = np.sin(x) ** 2 + np.cos(x) ** 2 * (np.cos(y) ** 2 + (req ** 2 / rpol ** 2) * np.sin(y) ** 2)
    b = -2 * H * np.cos(x) * np.cos(y)
    rs = (-b - np.sqrt(b ** 2 - 4 * a * (H ** 2 - req ** 2))) / (2 * a)
    sx, sy, sz = rs * np.cos(x) * np.cos(y), -rs * np.sin(x), rs * np.cos(x) * np.sin(y)
    lat = np.degrees(np.arctan((req ** 2 / rpol ** 2) * sz / np.sqrt((H - sx) ** 2 + sy ** 2)))
    lon = p["longitude_of_projection_origin"] - np.degrees(np.arctan(sy / (H - sx)))
    return lat, lon


def ler_caixas(chave, lats, lons):
    """Temperatura mais fria (K) em cada caixa da grade lats x lons."""
    with h5py.File(ArquivoRemoto(f"{BUCKET}/{chave}"), "r") as f:
        p = {k: float(np.squeeze(v)) for k, v in f["goes_imager_projection"].attrs.items()
             if k in ("semi_major_axis", "semi_minor_axis", "perspective_point_height", "longitude_of_projection_origin")}
        xs, ys = f["x"], f["y"]
        x = xs[:] * xs.attrs["scale_factor"] + xs.attrs["add_offset"]
        y = ys[:] * ys.attrs["scale_factor"] + ys.attrs["add_offset"]
        LA, LO = np.meshgrid(lats, lons, indexing="ij")
        bx, by = _para_xy(LA, LO, p)
        j0, j1 = np.searchsorted(x, [bx.min(), bx.max()])                 # x cresce
        i0, i1 = np.searchsorted(-y, [-by.max(), -by.min()])              # y decresce
        i0, j0, i1, j1 = max(0, i0 - 2), max(0, j0 - 2), i1 + 2, j1 + 2
        v = f["CMI"]
        bruto = v[i0:i1, j0:j1].astype(float)
        cheio = v.attrs.get("_FillValue")
        temp = bruto * v.attrs["scale_factor"] + v.attrs["add_offset"]
        if cheio is not None:
            temp[bruto == np.squeeze(cheio)] = np.nan
        sub_x, sub_y = x[j0:j1], y[i0:i1]
    plat, plon = _para_latlon(*np.meshgrid(sub_x, sub_y), p)
    ci = np.round((lats[0] - plat) / CAIXA_GRAUS).astype(int)       # lats vai de norte para sul
    cj = np.round((plon - lons[0]) / CAIXA_GRAUS).astype(int)
    ok = (ci >= 0) & (ci < len(lats)) & (cj >= 0) & (cj < len(lons)) & ~np.isnan(temp)
    fria = np.full((len(lats), len(lons)), np.nan)
    np.fmin.at(fria, (ci[ok], cj[ok]), temp[ok])
    return fria


def grade():
    lat0, lon0 = config.CENTRO
    dlat = RAIO_KM / 110.57
    dlon = RAIO_KM / (111.32 * math.cos(math.radians(lat0)))
    lats = np.arange(lat0 + dlat, lat0 - dlat - 1e-9, -CAIXA_GRAUS)     # norte -> sul
    lons = np.arange(lon0 - dlon, lon0 + dlon + 1e-9, CAIXA_GRAUS)
    return lats, lons


def km(a, b):
    p = math.radians
    return 2 * 6371 * math.asin(math.sqrt(
        math.sin(p(b[0] - a[0]) / 2) ** 2 + math.cos(p(a[0])) * math.cos(p(b[0])) * math.sin(p(b[1] - a[1]) / 2) ** 2))


def grupos(marca):
    """Caixas marcadas vizinhas (8 direções) viram um grupo."""
    vistos, saida = set(), []
    for ini in zip(*np.nonzero(marca)):
        if ini in vistos:
            continue
        pilha, g = [ini], []
        vistos.add(ini)
        while pilha:
            i, j = pilha.pop()
            g.append((i, j))
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    n = (i + di, j + dj)
                    if 0 <= n[0] < marca.shape[0] and 0 <= n[1] < marca.shape[1] and marca[n] and n not in vistos:
                        vistos.add(n)
                        pilha.append(n)
        saida.append(g)
    return saida


def conferir(grupos_novos, raios, agora):
    """Guarda grupos perto de Chapecó e confere, rodada a rodada, se viraram tempestade com raios."""
    try:
        log = json.load(open(LOG))
    except Exception:
        log = []
    celulas = (raios or {}).get("celulas", [])
    for e in log:
        if e.get("virou") is None:
            if any(km((e["lat"], e["lon"]), (c["lat"], c["lon"])) <= CONFIRMA_KM for c in celulas):
                e["virou"] = True
            elif (agora - datetime.fromisoformat(e["hora"])).total_seconds() / 60 > CONFIRMA_MIN:
                e["virou"] = False
    ja = {(e["imagem"], e["lat"], e["lon"]) for e in log}
    for g in grupos_novos:
        if g["dist_km"] > PLACAR_RAIO_KM or (g["imagem"], g["lat"], g["lon"]) in ja:
            continue
        # já tinha raio perto: não é aviso antecipado, não conta
        ja_tinha = any(km((g["lat"], g["lon"]), (c["lat"], c["lon"])) <= CONFIRMA_KM for c in celulas)
        log.append({"hora": agora.isoformat(timespec="seconds"), "imagem": g["imagem"], "lat": g["lat"], "lon": g["lon"],
                    "dist_km": g["dist_km"], "esfriou_k": g["esfriou_k"], "forte": g["forte"],
                    "virou": None if not ja_tinha else "ja_tinha_raio"})
    log = log[-2000:]
    json.dump(log, open(LOG, "w"), ensure_ascii=False)
    julg = [e for e in log if e["virou"] in (True, False)]
    return {"julgados": len(julg), "viraram": sum(e["virou"] is True for e in julg),
            "fortes_julgados": sum(1 for e in julg if e["forte"]),
            "fortes_viraram": sum(1 for e in julg if e["forte"] and e["virou"] is True)}


def calcular(agora=None, raios=None):
    agora = agora or datetime.now(timezone.utc)
    chaves = listar(agora)
    if len(chaves) < 2:
        raise RuntimeError("menos de 2 imagens do canal 13")
    lats, lons = grade()
    antes, agora_k = (ler_caixas(c, lats, lons) for c in chaves)
    # mais fria da imagem anterior entre as vizinhas 3x3
    pad = np.pad(antes, 1, constant_values=np.nan)
    viz = np.nanmin(np.stack([pad[1 + di:1 + di + antes.shape[0], 1 + dj:1 + dj + antes.shape[1]]
                              for di in (-1, 0, 1) for dj in (-1, 0, 1)]), axis=0)
    esfriou = viz - agora_k                     # positivo = esfriou
    marca = (esfriou >= ESFRIOU_K) & (agora_k <= TOPO_MAX_K)
    lista = []
    for g in grupos(np.nan_to_num(marca, nan=0).astype(bool)):
        if len(g) < MIN_CAIXAS:
            continue
        ii, jj = zip(*g)
        lat, lon = float(np.mean(lats[list(ii)])), float(np.mean(lons[list(jj)]))
        e = float(np.nanmax(esfriou[ii, jj]))
        lista.append({"imagem": _hora(chaves[-1]).strftime("%H:%M"), "lat": round(lat, 3), "lon": round(lon, 3), "dist_km": round(km(config.CENTRO, (lat, lon))),
                      "esfriou_k": round(e, 1), "topo_c": round(float(np.nanmin(agora_k[ii, jj])) - 273.15),
                      "caixas": len(g), "forte": e >= FORTE_K})
    lista = sorted((x for x in lista if x["dist_km"] <= RAIO_KM), key=lambda x: x["dist_km"])
    saida = {"gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
             "imagens": [_hora(c).strftime("%Y-%m-%dT%H:%M:%SZ") for c in chaves],
             "grupos": lista,
             "placar": conferir(lista, raios, agora),
             "regras": {"raio_km": RAIO_KM, "caixa_graus": CAIXA_GRAUS, "topo_max_c": TOPO_MAX_K - 273,
                        "esfriou_k_10min": ESFRIOU_K, "forte_k_10min": FORTE_K,
                        "placar_raio_km": PLACAR_RAIO_KM, "confirma_km": CONFIRMA_KM, "confirma_min": CONFIRMA_MIN}}
    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    json.dump(saida, open(SAIDA, "w"), ensure_ascii=False)
    return saida


if __name__ == "__main__":
    t0 = time.time()
    s = calcular()
    print(f"{len(s['grupos'])} grupos esfriando, imagens {s['imagens']}, {time.time() - t0:.0f}s")
    for g in s["grupos"][:10]:
        print(g)
