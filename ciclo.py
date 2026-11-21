"""Uma rodada completa: raios ao vivo, previsão (se velha), avisos.

Roda no GitHub Actions a cada 10 min, ou local com `python3 ciclo.py`.
"""
import json
import os
import time
from datetime import datetime

import alerta
import config
import motor

PREVISAO_MAX_MIN = 120    # refaz a previsão a cada 2 h (limite grátis Open-Meteo: 10 mil chamadas/dia; cada rodada gasta ~486)


def _idade_min(arquivo):
    try:
        g = json.load(open(arquivo))["gerado_em"]
        return (datetime.now() - datetime.fromisoformat(g)).total_seconds() / 60
    except Exception:
        return 1e9


def rodar():
    erros = []
    estado = raios = None
    f_estado = os.path.join(motor.DADOS, "estado.json")
    t0 = time.time()
    try:                                   # raios primeiro: é o dado mais urgente
        import raios as r
        raios = r.calcular()
        print(f"raios ok ({time.time() - t0:.0f}s)", flush=True)
    except Exception as e:
        erros.append(f"raios: {e}")
    try:
        if _idade_min(f_estado) > PREVISAO_MAX_MIN:
            estado = motor.calcular()
            print(f"previsão refeita ({time.time() - t0:.0f}s)", flush=True)
        else:
            estado = json.load(open(f_estado))
    except Exception as e:
        erros.append(f"previsão: {e}")
        if os.path.exists(f_estado):        # mantém a última previsão boa no painel
            estado = json.load(open(f_estado))
    alerta.processar(estado, raios)
    json.dump({"rodou_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "erros": erros},
              open(os.path.join(motor.DADOS, "status.json"), "w"), ensure_ascii=False)
    print("ok" if not erros else erros)
    if erros and not (estado or raios):
        raise SystemExit(1)


if __name__ == "__main__":
    rodar()
