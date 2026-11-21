"""Painel local. Uso: python3 servidor.py  -> http://localhost:8765

Serve web/ e os arquivos de dados/ (o mesmo que o site online lê do GitHub).
"""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

AQUI = os.path.dirname(os.path.abspath(__file__))
PORTA = int(os.environ.get("PORTA", "8765"))
PUBLICOS = {"estado.json", "raios.json", "status.json", "analise.json", "relatos.json", "conjunto.json", "verificacao.json", "radar.json", "longo.json", "nuvens.json"}


class Painel(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=os.path.join(AQUI, "web"), **kw)

    def translate_path(self, path):
        nome = path.split("?")[0]
        if nome.startswith("/dados/") and nome[7:] in PUBLICOS:
            return os.path.join(AQUI, "dados", nome[7:])
        return super().translate_path(path)


if __name__ == "__main__":
    print(f"Painel em http://localhost:{PORTA}  (rode `python3 ciclo.py` para atualizar os dados)")
    ThreadingHTTPServer(("0.0.0.0", PORTA), Painel).serve_forever()
