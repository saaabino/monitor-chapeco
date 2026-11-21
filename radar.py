"""Radar meteorológico de Chapecó (Defesa Civil SC / Epagri-Ciram), imagens públicas.

Fonte: o mesmo serviço da página https://ciram.epagri.sc.gov.br/radar/ (produto CAPPI 2 km).
A cada rodada:
  - lista as últimas imagens e guarda os nomes (o painel mostra a animação direto do servidor deles);
  - lê a imagem mais nova e acha o eco forte mais perto de Chapecó.

"Eco forte" = pixels amarelo, laranja, vermelho ou branco da imagem (chuva muito forte, granizo).
A legenda oficial não bate exatamente com as cores da imagem, então é aproximado.
Saída: dados/radar.json
"""
import json
import math
import os
import struct
import urllib.request
import zlib
from datetime import datetime, timedelta, timezone

import config

AQUI = os.path.dirname(os.path.abspath(__file__))
BASE = "https://sifap.defesacivil.sc.gov.br/radarsc/rest/radar"
PRODUTO = 0                     # CAPPI 2 km
# canto oeste, sul, leste, norte da imagem do radar de Chapecó (da página oficial)
EXTENSAO = (-55.0710069, -29.2106056, -50.1335368, -24.8625699)
UA = {"User-Agent": "Mozilla/5.0 (monitor-chapeco)"}


def _get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
        return r.read()


def _hora_arquivo(nome):
    """'2026112023540400dBZ...' -> datetime UTC 2026-11-20 23:54."""
    return datetime.strptime(nome[:12], "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def ler_png(dados):
    """PNG com paleta (1, 2, 4 ou 8 bits). Devolve largura, altura, paleta, linhas de índices."""
    i, idat, pal = 8, b"", None
    while i < len(dados):
        n, = struct.unpack(">I", dados[i:i + 4])
        tipo, corpo = dados[i + 4:i + 8], dados[i + 8:i + 8 + n]
        i += 12 + n
        if tipo == b"IHDR":
            w, h, bits, cor = struct.unpack(">IIBB", corpo[:10])
        elif tipo == b"PLTE":
            pal = [tuple(corpo[j:j + 3]) for j in range(0, len(corpo), 3)]
        elif tipo == b"IDAT":
            idat += corpo
    if cor != 3:
        raise ValueError("imagem do radar mudou de formato (sem paleta)")
    raw = zlib.decompress(idat)
    stride = (w * bits + 7) // 8
    linhas, ant, p = [], bytearray(stride), 0
    for _ in range(h):
        filtro, lin = raw[p], bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        for x in range(stride):
            a = lin[x - 1] if x >= 1 else 0
            b, c = ant[x], (ant[x - 1] if x >= 1 else 0)
            if filtro == 1:
                lin[x] = (lin[x] + a) & 255
            elif filtro == 2:
                lin[x] = (lin[x] + b) & 255
            elif filtro == 3:
                lin[x] = (lin[x] + (a + b) // 2) & 255
            elif filtro == 4:
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                lin[x] = (lin[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        ant = lin
        por_byte = 8 // bits
        idx = []
        for x in range(w):
            byte = lin[x // por_byte]
            desloc = 8 - bits * (x % por_byte + 1)
            idx.append((byte >> desloc) & ((1 << bits) - 1))
        linhas.append(idx)
    return w, h, pal, linhas


def _forte(rgb):
    r, g, b = rgb
    return (r >= 200 and b <= 100) or rgb == (255, 255, 255)      # amarelo/laranja/vermelho/branco


def _fraco(rgb):
    return rgb not in ((0, 0, 0), (200, 200, 200))                 # tudo menos fundo e ruído cinza


def analisar(png):
    w, h, pal, linhas = ler_png(png)
    oeste, sul, leste, norte = EXTENSAO
    lat0, lon0 = config.CENTRO
    fx = 111.32 * math.cos(math.radians(lat0))
    perto, chove_aqui, fortes_50 = None, False, 0
    for y, lin in enumerate(linhas):
        lat = norte - (y + 0.5) / h * (norte - sul)
        dy = (lat - lat0) * 110.57
        for x, k in enumerate(lin):
            if k == 0:
                continue
            rgb = pal[k]
            lon = oeste + (x + 0.5) / w * (leste - oeste)
            dist = math.hypot((lon - lon0) * fx, dy)
            if dist <= 5 and _fraco(rgb):
                chove_aqui = True
            if _forte(rgb):
                if dist <= 50:
                    fortes_50 += 1
                if perto is None or dist < perto[0]:
                    perto = (dist, lat, lon)
    return {"chove_em_chapeco": chove_aqui, "eco_forte_pixels_50km": fortes_50,
            "eco_forte_mais_perto": None if perto is None else
            {"dist_km": round(perto[0]), "lat": round(perto[1], 3), "lon": round(perto[2], 3)}}


def calcular():
    lista = json.loads(_get(f"{BASE}/getUltimasImagens?prod={PRODUTO}&radar=CHP&data="))
    if not lista:
        raise RuntimeError("radar sem imagens")
    ultimo = lista[-1]
    hora = _hora_arquivo(ultimo)
    idade = (datetime.now(timezone.utc) - hora).total_seconds() / 60
    saida = {
        "gerado_em": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "imagens": [{"url": f"{BASE}/getImagem?prod={PRODUTO}&radar=CHP&file={n}",
                     "hora": (_hora_arquivo(n) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M")} for n in lista],
        "extensao": EXTENSAO, "idade_min": round(idade),
        "fonte": "Defesa Civil SC / Epagri-Ciram (radar de Chapecó, CAPPI 2 km)",
    }
    saida.update(analisar(_get(saida["imagens"][-1]["url"])))
    json.dump(saida, open(os.path.join(AQUI, "dados", "radar.json"), "w"), ensure_ascii=False)
    return saida


if __name__ == "__main__":
    r = calcular()
    print({k: v for k, v in r.items() if k != "imagens"}, len(r["imagens"]), "imagens")
