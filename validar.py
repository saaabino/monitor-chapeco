"""Testa as regras contra o passado.

1. Acerto: nos dias com evento registrado, a regra marcou risco?
2. Alarme falso: em todos os dias de 2022-2025 em Chapecó, quantos ficam marcados?
"""
import collections
import json
import os

import motor
import regras

AQUI = os.path.dirname(os.path.abspath(__file__))
FEN = {"tornado": "tornado", "microexplosao": "microexplosao"}

NOME = ["baixo", "atenção", "alto"]


def historico(lat, lon, ini, fim):
    return motor._horas(motor._get("https://historical-forecast-api.open-meteo.com/v1/forecast", {
        "latitude": lat, "longitude": lon, "start_date": ini, "end_date": fim,
        "hourly": ",".join(motor.VARS), "wind_speed_unit": "ms", "timezone": "America/Sao_Paulo"}))


# --- 1. dias com evento ---
print("ACERTO (maior nível em qualquer hora do dia do evento, no local)")
placar = collections.defaultdict(collections.Counter)
for e in json.load(open(os.path.join(AQUI, "eventos.json"))):
    if e["data"] < "2021-06-01":
        continue
    hs = historico(e["lat"], e["lon"], e["data"], e["data"])
    n = max(regras.NIVEIS[FEN[e["tipo"]]](regras.indices(h)) for h in hs)
    placar[e["tipo"]][NOME[int(n * 2)]] += 1
    print(f"  {e['data']} {e['cidade'][:22]:22} {e['tipo']:13} -> {NOME[int(n * 2)]}")
for tipo, c in placar.items():
    print(f"  RESUMO {tipo}: {sum(c.values())} eventos -> alto {c['alto']}, atenção {c['atenção']}, baixo {c['baixo']}")

# --- 2. todos os dias em Chapecó ---
dia = collections.defaultdict(lambda: collections.defaultdict(float))
todas = []
for ano in range(2022, 2026):
    todas += historico(-27.10, -52.62, f"{ano}-01-01", f"{ano}-12-31")
for h in todas:
    i = regras.indices(h)
    for f, fn in regras.NIVEIS.items():
        dia[h["time"][:10]][f] = max(dia[h["time"][:10]][f], fn(i))
print(f"\nALARME: dos {len(dia)} dias de 2022-2025 em Chapecó, quantos a regra marca")
for f in regras.NIVEIS:
    alto = sum(d[f] == 1 for d in dia.values())
    at = sum(d[f] == 0.5 for d in dia.values())
    print(f"  {f:13} alto {alto:4} dias ({alto / len(dia):.0%})   atenção {at:4} dias ({at / len(dia):.0%})")
