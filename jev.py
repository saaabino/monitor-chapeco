"""Classifica um relato (notícia, mensagem de amigo) de temporal usando o Jev.

O Jev só responde perguntas simples sobre o texto. Quem decide se foi
tornado, microexplosão ou vendaval é a tabela em `decidir()`.

Uso: python3 jev.py "texto do relato"
Precisa de TYPESAFE_API_KEY. Mostra o pedido exato antes de enviar.
"""
import json
import os
import sys
import urllib.request

MODELO = "jev-latest"
SIM, NAO = 0.7, 0.3          # acima de 0.7 = sim, abaixo de 0.3 = não, entre = incerto

# Todas as perguntas ficam aqui.
PERGUNTAS = {
    "dano_por_vento": {
        "type": "noul",
        "instructions": "Does `relato` describe damage caused by wind?",
        "criteria": {"true": "Roofs, trees, poles or buildings were damaged by wind",
                     "false": "The damage came only from rain, flooding, hail or lightning, or there was no damage"},
    },
    "funil_visto": {
        "type": "noul",
        "instructions": "Does `relato` say someone saw a funnel cloud or a tornado?",
    },
    "giro_relatado": {
        "type": "noul",
        "instructions": "Does `relato` describe wind or debris spinning in a circle?",
    },
    "queda_mesma_direcao": {
        "type": "noul",
        "instructions": "Does `relato` say the fallen trees or debris all point in the same direction?",
    },
    "queda_para_fora": {
        "type": "noul",
        "instructions": "Does `relato` say the fallen trees or debris spread outward in different directions from one spot?",
    },
    "faixa_estreita": {
        "type": "noul",
        "instructions": "Does `relato` say the damage was concentrated in a narrow strip, with little damage beside it?",
    },
    "vento_poucos_minutos": {
        "type": "noul",
        "instructions": "Does `relato` say the strongest wind lasted only a few minutes?",
    },
    "orgao_classificou": {
        "type": "choice",
        "instructions": "How did a weather agency or civil defense classify the event in `relato`?",
        "criteria": {"tornado": "They called it a tornado",
                     "microexplosao": "They called it a microburst (microexplosão) or downburst",
                     "vendaval": "They called it a windstorm (vendaval) without saying tornado or microburst"},
    },
    "orgao_citado": {
        "type": "noul",
        "instructions": "Does `relato` report how a weather agency or civil defense classified the event?",
    },
}


def _f(p):
    """Converte probabilidade em 'sim' / 'nao' / 'incerto'."""
    return "sim" if p > SIM else "nao" if p < NAO else "incerto"


def decidir(resp):
    """Tabela de decisão. Devolve (tipo, porquê)."""
    a = {k: v for k, v in resp["answers"].items()}
    n = {k: _f(v["noul"]) for k, v in a.items() if v["type"] == "noul"}

    if n["orgao_citado"] == "sim":
        return a["orgao_classificou"]["choice"], "classificação de órgão oficial citada no relato"
    if n["dano_por_vento"] == "nao":
        return "nao_e_vento", "relato não descreve dano por vento"
    if n["funil_visto"] == "sim" or n["giro_relatado"] == "sim":
        return "tornado_provavel", "funil ou giro relatado"
    if n["queda_para_fora"] == "sim":
        return "microexplosao_provavel", "queda espalhada para fora a partir de um ponto"
    if n["faixa_estreita"] == "sim" and n["queda_mesma_direcao"] != "sim":
        return "tornado_possivel", "dano em faixa estreita"
    if n["queda_mesma_direcao"] == "sim" and n["vento_poucos_minutos"] == "sim":
        return "microexplosao_possivel", "tudo caído para o mesmo lado em rajada curta"
    if n["dano_por_vento"] == "sim":
        return "vendaval", "dano por vento sem sinal de giro ou explosão"
    return "indefinido", "relato não deixa claro"


def perguntar(relato, mostrar=True):
    chave = os.environ.get("TYPESAFE_API_KEY")
    if not chave:
        raise RuntimeError("falta TYPESAFE_API_KEY")
    pedido = {"model": MODELO, "state": {"relato": relato}, "questions": PERGUNTAS}
    if mostrar:
        print("PEDIDO ENVIADO:\n" + json.dumps(pedido, ensure_ascii=False, indent=1))
    req = urllib.request.Request(
        "https://api.typesafe.ai/v1/systemone", data=json.dumps(pedido).encode(),
        headers={"User-Agent": "monitor-chapeco/1.0", "Authorization": f"Bearer {chave}", "Content-Type": "application/json"})
    # falha de rede ou da API sobe como erro; nunca vira "não"
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


if __name__ == "__main__":
    resp = perguntar(" ".join(sys.argv[1:]))
    print("RESPOSTAS:", json.dumps(resp["answers"], ensure_ascii=False, indent=1))
    print("DECISÃO:", decidir(resp))
