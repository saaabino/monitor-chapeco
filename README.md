# Monitor Chapecó

Painel e alerta de ambiente favorável a microexplosão, tornado e vento forte na região de Chapecó (SC).
Uso pessoal. **Não substitui a Defesa Civil** (alerta SMS: CEP para 40199).

## Online
- GitHub Actions roda `ciclo.py` a cada 10 min (`.github/workflows/ciclo.yml`):
  raios ao vivo sempre, previsão a cada 2 h, avisos no Telegram.
- Os dados saem na branch `dados` (um commit só, sobrescrito) e o painel lê de lá.
- Vercel serve só a pasta `web/` (site estático).
- Segredos no GitHub: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Variável: `SITE_URL`.

## Rodar local
```
python3 ciclo.py           # uma rodada: raios + previsão + avisos
python3 servidor.py        # painel em http://localhost:8765
python3 alerta.py          # ciclo em loop a cada 10 min
python3 raios.py           # só os raios (pip install h5py numpy)
python3 validar.py         # testa as regras contra o passado
python3 jev.py "relato"    # classifica um relato com o Jev (precisa TYPESAFE_API_KEY)
```
Python 3.9+. Só `raios.py` precisa instalar algo: `pip install -r requirements.txt`.

Telegram: crie um bot com o @BotFather e exporte `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

## Como funciona
- `motor.py` puxa ECMWF, GFS e ICON (Open-Meteo) numa grade 9x9 (~±45 km) em volta de Chapecó.
- `regras.py` calcula os índices (CAPE, Δθe, WMSI, cisalhamento 0-6 e 0-1,5 km, rajada) e aplica as regras de nível.
- O mapa "combinado" junta: quantos modelos marcam risco + quanto o dia lembra eventos antigos + onde já aconteceu (pesos em `config.py`).
- `eventos.json`: gerado por `montar_eventos.py` = tornados a até 150 km (listas da Wikipédia SC e RS) + `eventos_manuais.json` (microexplosões com fonte). Posição = centro da cidade.
- `jev.py`: perguntas simples sobre um relato; a decisão (tornado/microexplosão/vendaval) é a tabela em `decidir()`.

## Teste com o passado (rodado em 20/11/2026, 112 eventos)
- Tornados desde 2021 (32): alto 25, atenção 5, baixo 2.
- Microexplosões desde 2021 (10): alto 2, atenção 4, baixo 4. Das 4 perdidas, 3 são de maio a julho
  (pouca energia, muito vento em altura: Herval d'Oeste 2023, São Miguel do Oeste 2025, Descanso 2025) e 1 de verão (Abelardo Luz, jan/2023).
  A regra atual só pega o tipo de verão (muita energia + ar seco em altura). Falta uma regra para o tipo de inverno.
- Dias comuns 2022-2025 em Chapecó: microexplosão alto 10% dos dias, tornado alto 4%.
  Ou seja: o painel diz "ambiente favorável", não "vai acontecer".

## Jev (testado 20/11/2026, jev-1.14.0)
9 de 9 certos: 6 notícias reais (microexplosão Chapecó 2025, Descanso 2025, tornado 04/11/2026,
vendavais de 08/11 e 20/11/2026) e 3 relatos inventados (funil, só chuva, árvores caídas para fora).

## Limites
- Modelos têm 10-25 km de resolução; microexplosão tem 1-4 km.
- Ao vivo usa raios do GOES-19 (sensor GLM) e satélite infravermelho; não usa radar
  (RainViewer não cobre Chapecó; acesso ao radar da Defesa Civil SC ainda não verificado).
- Velocidade da tempestade = deslocamento do grupo de raios em 10 min; erra quando a célula muda de forma.
- Regra de microexplosão de inverno testada e descartada: acertava 1 de 10 casos.
- Open-Meteo grátis: 10 mil chamadas/dia. Previsão a cada 2 h gasta ~5,8 mil.
- Histórico de ambiente só existe a partir de 2021.
- Cidade maior tem mais registro, o que puxa a camada "já aconteceu" para ela.
