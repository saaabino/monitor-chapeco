"""Índices de tempestade e regras de risco. Tudo visível e testável.

Nível: 0 = baixo, 0.5 = atenção, 1 = alto.
Os limites vêm da literatura de previsão de tempo severo (WMSI de Pryor &
Ellrod; cisalhamento 0-6 km e 0-1,5 km usados por SPC/ESSL), arredondados.
São pontos de partida: ajustar com os eventos da região.
"""
import math

# ---------- limites ----------
MICRO = {
    "wmsi_alto": 80, "wmsi_atencao": 50,      # índice de microexplosão úmida
    "cape_alto": 1000, "te_alto": 25,          # CAPE J/kg, diferença θe em K
    "cape_atencao": 500, "te_atencao": 20,
}
TORNADO = {
    "cape_alto": 500, "shear06_alto": 20, "shear01_alto": 10,          # m/s
    "cape_atencao": 250, "shear06_atencao": 15,
    # "pouca energia, muito vento em altura" (comum no Sul do Brasil no inverno)
    "hslc_cape": 100, "hslc_shear06": 25, "hslc_shear01": 12,
}
VENTO = {"rajada_alta": 80, "rajada_atencao": 60}   # km/h, rajada do modelo


# ---------- física ----------
def theta_e(t_c, td_c, p_hpa):
    """Temperatura potencial equivalente (Bolton 1980), em K."""
    if None in (t_c, td_c, p_hpa):
        return None
    t = t_c + 273.15
    td = td_c + 273.15
    e = 6.112 * math.exp(17.67 * td_c / (td_c + 243.5))
    r = 0.622 * e / (p_hpa - e)
    tl = 1 / (1 / (td - 56) + math.log(t / td) / 800) + 56
    return t * (1000 / p_hpa) ** (0.2854 * (1 - 0.28 * r)) * math.exp(
        (3.376 / tl - 0.00254) * r * 1000 * (1 + 0.81 * r))


def _vetor(vel, dir_graus):
    a = math.radians(dir_graus)
    return (-vel * math.sin(a), -vel * math.cos(a))


def cisalhamento(v1, d1, v2, d2):
    """Diferença vetorial do vento entre dois níveis (mesma unidade de v)."""
    if None in (v1, d1, v2, d2):
        return None
    a, b = _vetor(v1, d1), _vetor(v2, d2)
    return math.hypot(a[0] - b[0], a[1] - b[1])


def indices(h):
    """h = dict com as variáveis de UMA hora de UM ponto (vento em m/s)."""
    te_sfc = theta_e(h.get("temperature_2m"), h.get("dew_point_2m"), h.get("surface_pressure"))
    te_meio = [x for x in (
        theta_e(h.get("temperature_700hPa"), h.get("dew_point_700hPa"), 700),
        theta_e(h.get("temperature_500hPa"), h.get("dew_point_500hPa"), 500)) if x is not None]
    te = (te_sfc - min(te_meio)) if (te_sfc is not None and te_meio) else None
    cape = h.get("cape")
    return {
        "cape": cape,
        "te": te,
        "wmsi": (cape * te / 1000) if (cape is not None and te is not None and te > 0) else None,
        "shear06": cisalhamento(h.get("wind_speed_10m"), h.get("wind_direction_10m"),
                                h.get("wind_speed_500hPa"), h.get("wind_direction_500hPa")),
        "shear01": cisalhamento(h.get("wind_speed_10m"), h.get("wind_direction_10m"),
                                h.get("wind_speed_850hPa"), h.get("wind_direction_850hPa")),
        # rajada vem em m/s (pedimos wind_speed_unit=ms) -> km/h
        "rajada": h["wind_gusts_10m"] * 3.6 if h.get("wind_gusts_10m") is not None else None,
    }


def _ok(x, lim):
    return x is not None and x >= lim


# ---------- regras ----------
def nivel_microexplosao(i):
    c = MICRO
    if _ok(i["wmsi"], c["wmsi_alto"]) or (_ok(i["cape"], c["cape_alto"]) and _ok(i["te"], c["te_alto"])):
        return 1.0
    if _ok(i["wmsi"], c["wmsi_atencao"]) or (_ok(i["cape"], c["cape_atencao"]) and _ok(i["te"], c["te_atencao"])):
        return 0.5
    return 0.0


def nivel_tornado(i):
    c = TORNADO
    if _ok(i["cape"], c["cape_alto"]) and _ok(i["shear06"], c["shear06_alto"]) and _ok(i["shear01"], c["shear01_alto"]):
        return 1.0
    if (_ok(i["cape"], c["cape_atencao"]) and _ok(i["shear06"], c["shear06_atencao"])) or (
            _ok(i["cape"], c["hslc_cape"]) and _ok(i["shear06"], c["hslc_shear06"]) and _ok(i["shear01"], c["hslc_shear01"])):
        return 0.5
    return 0.0


def nivel_vento(i):
    if _ok(i["rajada"], VENTO["rajada_alta"]):
        return 1.0
    if _ok(i["rajada"], VENTO["rajada_atencao"]):
        return 0.5
    return 0.0


NIVEIS = {"microexplosao": nivel_microexplosao, "tornado": nivel_tornado, "vento": nivel_vento}


def motivos(i):
    """Frases curtas explicando os números (para o painel e o alerta)."""
    m = []
    if i["cape"] is not None:
        m.append(f"energia (CAPE) {i['cape']:.0f} J/kg")
    if i["te"] is not None:
        m.append(f"ar seco em altura (Δθe) {i['te']:.0f} K")
    if i["wmsi"] is not None:
        m.append(f"índice microexplosão (WMSI) {i['wmsi']:.0f}")
    if i["shear06"] is not None:
        m.append(f"cisalhamento 0-6 km {i['shear06']:.0f} m/s")
    if i["shear01"] is not None:
        m.append(f"cisalhamento 0-1,5 km {i['shear01']:.0f} m/s")
    if i["rajada"] is not None:
        m.append(f"rajada do modelo {i['rajada']:.0f} km/h")
    return m
