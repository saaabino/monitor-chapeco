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
    try:
        if _idade_min(f_estado) > PREVISAO_MAX_MIN:
            estado = motor.calcular()
        else:
            estado = json.load(open(f_estado))
    except Exception as e:
        erros.append(f"previsão: {e}")
    try:
        import raios as r
        raios = r.calcular()
    except Exception as e:
        erros.append(f"raios: {e}")
    alerta.processar(estado, raios)
    json.dump({"rodou_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "erros": erros},
              open(os.path.join(motor.DADOS, "status.json"), "w"), ensure_ascii=False)
    print("ok" if not erros else erros)
    if erros and not (estado or raios):
        raise SystemExit(1)


if __name__ == "__main__":
    rodar()
