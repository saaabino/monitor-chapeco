"""Alerta no Telegram. Uso: python3 alerta.py  (roda o ciclo em loop a cada 10 min)

Precisa de TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (no arquivo .env ou no ambiente).
  python3 alerta.py chat   -> mostra o ID dos chats que falaram com o bot
  python3 alerta.py teste  -> manda uma mensagem de teste
Sem eles, só mostra no terminal o que mandaria.

Regra (em código, ajustável):
  manda alerta quando, em algum ponto a até RAIO_ALERTA_KM de Chapecó,
  nas próximas 24h, TODOS os modelos marcam nível alto para microexplosão ou tornado.
  Não repete o mesmo fenômeno no mesmo dia.
"""
import json
import os
import time
import urllib.parse
import urllib.request

import config
import motor

def _carregar_env():
    f = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(f):
        for linha in open(f):
            if "=" in linha and not linha.startswith("#"):
                k, v = linha.strip().split("=", 1)
                os.environ.setdefault(k, v)


_carregar_env()
ENVIADOS = os.path.join(motor.DADOS, "alertas_enviados.json")
NOMES = {"microexplosao": "MICROEXPLOSÃO", "tornado": "TORNADO", "vento": "VENTO FORTE"}


def decidir(estado):
    """Devolve lista de (fenômeno, célula) que pedem alerta."""
    saida = []
    perto = [c for c in estado["celulas"] if c["dist_km"] <= config.RAIO_ALERTA_KM]
    for f in ("microexplosao", "tornado"):
        quentes = [c for c in perto if c["janelas"]["0-24h"][f]["modelos"] == 1.0]
        if quentes:
            saida.append((f, max(quentes, key=lambda c: c["janelas"]["0-24h"][f]["combinado"])))
    return saida


def texto(f, c):
    j = c["janelas"]["0-24h"][f]
    i = j["indices"]
    linhas = [
        f"⚠️ Ambiente favorável a {NOMES[f]} perto de Chapecó (próximas 24h)",
        f"Os {len(j['por_modelo'])} modelos disponíveis concordam ({', '.join(config.MODELOS[m] for m in j['por_modelo'])}).",
        f"CAPE {i['cape']:.0f} J/kg · Δθe {i['te']:.0f} K · cisalhamento 0-6 km {i['shear06']:.0f} m/s"
        if None not in (i["cape"], i["te"], i["shear06"]) else "",
    ]
    if j["top_analogos"]:
        a = j["top_analogos"][0]
        linhas.append(f"Mais parecido com: {a['data']} em {a['cidade']} ({a['sim']:.0%})")
    linhas.append("Não é previsão oficial. Siga a Defesa Civil (SMS 40199).")
    return "\n".join(x for x in linhas if x)


def enviar(msg):
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print("[sem Telegram configurado] mandaria:\n" + msg)
        return
    dados = urllib.parse.urlencode({"chat_id": chat, "text": msg}).encode()
    urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", dados, timeout=30)


# ---------- tempestade ao vivo (raios) ----------
# Quanto mais perto, mais avisos: um aviso a cada vez que a tempestade cruza um degrau.
DEGRAUS_MIN = [90, 60, 30, 15, 0]   # minutos até chegar (0 = em cima de Chapecó)
TAXA_MIN = 2                        # célula precisa de pelo menos 2 raios/min
SALTO_PERTO_KM = 60                 # salto de raios a até 60 km também avisa
SALTO_INTERVALO_MIN = 30            # no máximo um aviso de salto a cada 30 min
ESQUECE_MIN = 60                    # sem tempestade vindo por 60 min, recomeça os degraus
BOLETIM_HORAS = (7, 19)             # resumo do dia às 7h e às 19h


def degrau(chega_min):
    """Menor degrau que a tempestade já alcançou (ex.: chega em 25 min -> degrau 30)."""
    return min(d for d in DEGRAUS_MIN if chega_min <= d) if chega_min <= DEGRAUS_MIN[0] else None


def decidir_tempestade(raios, enviados, agora):
    """Devolve (célula, motivo) se precisa avisar agora, e atualiza o registro de enviados."""
    vem = sorted([c for c in raios["celulas"] if c["chega_min"] is not None
                  and c["chega_min"] <= DEGRAUS_MIN[0] and c["raios_por_min"] >= TAXA_MIN],
                 key=lambda c: c["chega_min"])
    if vem:
        c = vem[0]
        d = degrau(c["chega_min"])
        ultimo = enviados.get("degrau")
        recente = agora - enviados.get("degrau_ts", 0) < ESQUECE_MIN * 60
        enviados["vem_ts"] = agora
        if ultimo is None or not recente or d < ultimo:
            enviados["degrau"], enviados["degrau_ts"] = d, agora
            return c, "degrau"
        return None
    if agora - enviados.get("vem_ts", 0) >= ESQUECE_MIN * 60:
        enviados.pop("degrau", None)            # passou: a próxima começa do zero
    salto = [c for c in raios["celulas"] if c["salto"] and c["dist_km"] <= SALTO_PERTO_KM]
    if salto and agora - enviados.get("salto_ts", 0) >= SALTO_INTERVALO_MIN * 60:
        enviados["salto_ts"] = agora
        return min(salto, key=lambda c: c["dist_km"]), "salto"
    return None


def risco_hoje(estado):
    """Fenômenos com nível alto em todos os modelos perto de Chapecó (contexto para o aviso)."""
    return [NOMES[f].lower() for f, _ in decidir(estado)] if estado else []


def texto_tempestade(c, estado):
    import raios as r
    linhas = []
    if c["chega_min"] == 0:
        linhas.append("🔴 Tempestade com raios EM CHAPECÓ agora")
    elif c["chega_min"] is not None:
        icone = "🔴" if c["chega_min"] <= 15 else "🟠" if c["chega_min"] <= 30 else "🟡"
        linhas.append(f"{icone} Tempestade a {c['dist_km']} km, chega em Chapecó em ~{c['chega_min']} min")
    else:
        linhas.append(f"⚡ Salto de raios em tempestade a {c['dist_km']} km de Chapecó")
    if c["vel_kmh"]:
        linhas.append(f"Andando a {c['vel_kmh']} km/h para {r.direcao(c['rumo'])}.")
    linhas.append(f"Raios: {c['raios_por_min']}/min (antes {c['raios_por_min_antes']}/min)"
                  + (" · SALTO DE RAIOS, sinal de vento forte/granizo" if c["salto"] else ""))
    risco = risco_hoje(estado)
    if risco:
        linhas.append("Ambiente de hoje favorável a: " + ", ".join(risco) + ".")
    linhas.append("Estimativa por raios de satélite, pode errar. Siga a Defesa Civil (SMS 40199).")
    return "\n".join(linhas)


def processar(estado, raios, analise=None):
    """Decide e manda os avisos. Guarda o que já foi enviado em dados/alertas_enviados.json."""
    enviados = json.load(open(ENVIADOS)) if os.path.exists(ENVIADOS) else {}
    hoje = time.strftime("%Y-%m-%d")
    agora = time.time()
    site = os.environ.get("SITE_URL", "")
    rodape = f"\n{site}" if site else ""
    if estado:
        for f, c in decidir(estado):
            if enviados.get(f) != hoje:
                enviar(texto(f, c) + rodape)
                enviados[f] = hoje
    if raios:
        r = decidir_tempestade(raios, enviados, agora)
        if r:
            enviar(texto_tempestade(r[0], estado) + rodape)
    hora = int(time.strftime("%H"))
    for h in BOLETIM_HORAS:
        chave = f"boletim_{h}"
        if analise and hora >= h and enviados.get(chave) != hoje and hora < h + 2:
            import analise as an
            enviar(f"📋 Boletim {h}h · Monitor Chapecó\n" + an.texto(analise) + rodape)
            enviados[chave] = hoje
    json.dump(enviados, open(ENVIADOS, "w"))


def mostrar_chats():
    """Mostra os chats que mandaram mensagem pro bot (para achar o TELEGRAM_CHAT_ID)."""
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    r = json.load(urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/getUpdates", timeout=30))
    vistos = {}
    for u in r["result"]:
        msg = u.get("message") or u.get("my_chat_member") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            vistos[chat["id"]] = chat.get("title") or chat.get("first_name") or chat.get("type")
    for cid, nome in vistos.items():
        print(cid, nome)
    if not vistos:
        print("Nenhuma mensagem ainda. Mande /start pro bot (ou adicione ele no grupo e mande uma mensagem).")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["chat"]:
        mostrar_chats()
        sys.exit()
    if sys.argv[1:] == ["teste"]:
        enviar("Teste do Monitor Chapecó: bot funcionando.")
        sys.exit()
    import ciclo
    while True:
        try:
            ciclo.rodar()
        except Exception as erro:
            print("falhou, tento de novo no próximo ciclo:", erro)
        time.sleep(10 * 60)
