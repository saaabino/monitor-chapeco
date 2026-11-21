"""Relatos dos amigos pelo Telegram, classificados com o Jev.

Como usar no Telegram (conversa com o bot ou grupo com o bot):
  /relato caiu tudo pra fora aqui na Efapi, durou 2 min
  depois, se quiser, mande a localização (clipe > Localização) para pôr no mapa.

O Jev responde perguntas simples sobre o texto (jev.py); quem decide o tipo é jev.decidir().
Se o Jev falhar, o relato NÃO é classificado (nunca vira "não"); o bot pede para mandar de novo.

Privacidade: o texto e o nome NÃO são guardados nem publicados.
Vai para dados/relatos.json (público) só: hora, tipo, motivo, posição arredondada (~1 km).
"""
import hashlib
import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import jev
import motor

ARQ = os.path.join(motor.DADOS, "relatos.json")
OFFSET = os.path.join(motor.DADOS, "telegram_offset.json")
LOCAL_ATE_MIN = 15          # localização enviada até 15 min depois do relato entra nele
GUARDA_DIAS = 30

NOMES = {
    "tornado": "tornado (segundo a Defesa Civil/órgão citado)",
    "microexplosao": "microexplosão (segundo órgão citado)",
    "vendaval": "vendaval",
    "tornado_provavel": "provável tornado",
    "tornado_possivel": "possível tornado",
    "microexplosao_provavel": "provável microexplosão",
    "microexplosao_possivel": "possível microexplosão",
    "nao_e_vento": "sem dano por vento",
    "indefinido": "não deu para dizer",
}


def _tg(metodo, **params):
    tok = os.environ["TELEGRAM_BOT_TOKEN"]
    dados = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/{metodo}", dados, timeout=30) as r:
        return json.load(r)


def responder(chat, msg_id, texto):
    _tg("sendMessage", chat_id=chat, text=texto, reply_to_message_id=msg_id)


def processar():
    """Lê mensagens novas do bot, classifica relatos, guarda. Devolve a lista de relatos."""
    relatos = json.load(open(ARQ)) if os.path.exists(ARQ) else []
    if not os.environ.get("TELEGRAM_BOT_TOKEN"):
        return relatos
    offset = json.load(open(OFFSET)).get("offset", 0) if os.path.exists(OFFSET) else 0
    upd = _tg("getUpdates", offset=offset, timeout=0)["result"]
    for u in upd:
        offset = max(offset, u["update_id"] + 1)
        m = u.get("message")
        if not m:
            continue
        chat, quando = m["chat"]["id"], datetime.fromtimestamp(m["date"])
        # o arquivo é público: guarda só um código do autor, não o id do Telegram
        autor = hashlib.sha256(f"{m.get('from', {}).get('id')}{os.environ['TELEGRAM_BOT_TOKEN']}".encode()).hexdigest()[:12]
        texto = (m.get("text") or "").strip()
        if texto.split(" ")[0].split("@")[0] == "/relato":
            corpo = texto.split(" ", 1)[1].strip() if " " in texto else ""
            if len(corpo) < 10:
                responder(chat, m["message_id"], "Escreva o que viu depois do /relato. Ex.: /relato árvores caíram todas pra um lado, durou 2 min")
                continue
            try:
                resp = jev.perguntar(corpo, mostrar=False)   # log do GitHub é público: não imprime o texto
            except Exception as erro:
                print("Jev falhou:", erro)
                responder(chat, m["message_id"], "Não consegui analisar agora. Mande o relato de novo daqui a pouco.")
                continue
            tipo, motivo = jev.decidir(resp)
            relatos.append({"hora": quando.strftime("%Y-%m-%dT%H:%M:%S"), "tipo": tipo, "motivo": motivo,
                            "lat": None, "lon": None, "_autor": autor})
            responder(chat, m["message_id"],
                      f"Relato recebido: {NOMES.get(tipo, tipo)} ({motivo}).\n"
                      "Se puder, mande agora a localização (clipe > Localização) para entrar no mapa.")
        elif "location" in m:
            pend = [r for r in relatos if r.get("_autor") == autor and r["lat"] is None
                    and quando - datetime.fromisoformat(r["hora"]) <= timedelta(minutes=LOCAL_ATE_MIN)]
            if pend:
                pend[-1]["lat"] = round(m["location"]["latitude"], 2)
                pend[-1]["lon"] = round(m["location"]["longitude"], 2)
                responder(chat, m["message_id"], "Localização adicionada ao relato. Obrigado!")
    limite = datetime.now() - timedelta(days=GUARDA_DIAS)
    relatos = [r for r in relatos if datetime.fromisoformat(r["hora"]) >= limite]
    # o id do autor só serve para casar a localização; some depois de 15 min
    for r in relatos:
        if datetime.now() - datetime.fromisoformat(r["hora"]) > timedelta(minutes=LOCAL_ATE_MIN):
            r.pop("_autor", None)
    json.dump(relatos, open(ARQ, "w"), ensure_ascii=False)
    json.dump({"offset": offset}, open(OFFSET, "w"))
    return relatos
