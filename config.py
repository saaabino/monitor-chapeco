"""Tudo que dá pra ajustar fica aqui: área, modelos, pesos do mapa."""

CENTRO = (-27.10, -52.62)          # Chapecó
PASSO_GRADE = 0.1                   # graus (~11 km)
MEIA_GRADE = 4                      # 9x9 pontos -> ~±45 km em volta de Chapecó
TZ = "America/Sao_Paulo"
HORAS = 48

# Modelos independentes. "Chance" no mapa = quantos deles marcam risco.
MODELOS = {
    "ecmwf_ifs025": "ECMWF",
    "gfs_seamless": "GFS",
    "icon_seamless": "ICON",
}

# Peso de cada camada no mapa "combinado" (soma 1).
PESOS = {"modelos": 0.60, "analogos": 0.25, "historico": 0.15}

RAIO_HISTORICO_KM = 15             # quanto um evento antigo "espalha" no mapa
RAIO_ALERTA_KM = 15                # alerta Telegram olha pontos até aqui de Chapecó
CACHE_MIN = 30                     # recalcula a cada 30 min

JANELAS = {"0-24h": (0, 24), "24-48h": (24, 48)}
FENOMENOS = ["microexplosao", "tornado", "vento"]
