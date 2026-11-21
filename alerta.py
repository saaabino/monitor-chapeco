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
        f"Os {len(j['por_modelo'])} modelos concordam (ECMWF, GFS, ICON).",
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
CHEGA_MAX_MIN = 90        # avisa se a célula chega a Chapecó em até 90 min
TAXA_MIN = 2              # e tem pelo menos 2 raios/min
SALTO_PERTO_KM = 60       # salto de raios a até 60 km também avisa
INTERVALO_TEMPESTADE_MIN = 60   # no máximo um aviso de tempestade por hora


def decidir_tempestade(raios):
    vem = [c for c in raios["celulas"] if c["chega_min"] is not None
           and c["chega_min"] <= CHEGA_MAX_MIN and c["raios_por_min"] >= TAXA_MIN]
    salto = [c for c in raios["celulas"] if c["salto"] and c["dist_km"] <= SALTO_PERTO_KM]
    return sorted({id(c): c for c in vem + salto}.values(), key=lambda c: c["chega_min"] if c["chega_min"] is not None else 999)


def risco_hoje(estado):
    """Fenômenos com nível alto em todos os modelos perto de Chapecó (contexto para o aviso)."""
    return [NOMES[f].lower() for f, _ in decidir(estado)] if estado else []


def texto_tempestade(c, estado):
    import raios as r
    linhas = []
    if c["chega_min"] == 0:
        linhas.append("⛈️ Tempestade com raios EM CHAPECÓ agora")
    elif c["chega_min"] is not None:
        linhas.append(f"⛈️ Tempestade a {c['dist_km']} km, chega em Chapecó em ~{c['chega_min']} min")
    else:
        linhas.append(f"⛈️ Tempestade a {c['dist_km']} km de Chapecó")
    if c["vel_kmh"]:
        linhas.append(f"Andando a {c['vel_kmh']} km/h para {r.direcao(c['rumo'])}.")
    linhas.append(f"Raios: {c['raios_por_min']}/min (antes {c['raios_por_min_antes']}/min)"
                  + (" · SALTO DE RAIOS, sinal de vento forte/granizo" if c["salto"] else ""))
    risco = risco_hoje(estado)
    if risco:
        linhas.append("Ambiente de hoje favorável a: " + ", ".join(risco) + ".")
    linhas.append("Estimativa por raios de satélite, pode errar. Siga a Defesa Civil (SMS 40199).")
    return "\n".join(linhas)


def processar(estado, raios):
    """Decide e manda os avisos. Guarda o que já foi enviado em dados/alertas_enviados.json."""
    enviados = json.load(open(ENVIADOS)) if os.path.exists(ENVIADOS) else {}
    hoje = time.strftime("%Y-%m-%d")
    site = os.environ.get("SITE_URL", "")
    if estado:
        for f, c in decidir(estado):
            if enviados.get(f) != hoje:
                enviar(texto(f, c) + (f"\n{site}" if site else ""))
                enviados[f] = hoje
    if raios:
        cand = decidir_tempestade(raios)
        ultimo = enviados.get("tempestade_ts", 0)
        if cand and time.time() - ultimo >= INTERVALO_TEMPESTADE_MIN * 60:
            enviar(texto_tempestade(cand[0], estado) + (f"\n{site}" if site else ""))
            enviados["tempestade_ts"] = time.time()
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
