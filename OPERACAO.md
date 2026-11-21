# Operação do Monitor Chapecó

Como o sistema fica no ar e onde está cada coisa. Estado em 21/11/2026.

## Endereços
- Painel / app: https://monitor-chapeco.vercel.app
- Código: https://github.com/saaabino/monitor-chapeco (público)
- Dados ao vivo: branch `dados` do mesmo repositório (sobrescrita a cada rodada)
- Bot do Telegram: @Tempocco_bot

## O que mantém o ciclo rodando (qualquer um basta)
1. **Corrente na nuvem**: o último passo de `.github/workflows/ciclo.yml` espera 200 s e dispara a próxima rodada.
2. **cron-job.org**: trabalho "Monitor Chapecó - disparo do ciclo" (id 8909648), a cada 5 min,
   POST em `https://api.github.com/repos/saaabino/monitor-chapeco/actions/workflows/ciclo.yml/dispatches`
   com o token `GITHUB_TOKEN_CRON` (só Actions read/write neste repositório, vence em 20/11/2027).
   Avisa por e-mail se falhar.
3. **Mac**: `ops/com.monitorchapeco.disparo.plist` (cópia do que está em `~/Library/LaunchAgents/`),
   roda `gh workflow run` a cada 5 min quando o Mac está ligado.
   Ligar: `launchctl load ~/Library/LaunchAgents/com.monitorchapeco.disparo.plist`
   Desligar: `launchctl unload ~/Library/LaunchAgents/com.monitorchapeco.disparo.plist`
4. O `cron` do próprio workflow existe mas o GitHub nunca chegou a disparar.

## Segredos
- No GitHub (Settings > Secrets): `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TYPESAFE_API_KEY`. Variável: `SITE_URL`.
- Neste Mac, em `.env` (fora do git): token do bot, chat, chave da API do cron-job.org, token do GitHub do cron.
- Nunca subir `.env`.

## Publicar mudanças
- Código: `git push` (o próximo ciclo já usa a versão nova).
- Painel: `cd web && npx vercel deploy --prod --yes` (a Vercel não está ligada ao GitHub).
- Regra do CLAUDE.md: mostrar o que vai subir e pedir confirmação antes de push ou deploy.

## Fontes de dados
- Raios: NOAA GOES-19 GLM (AWS, grátis).
- Satélite: NASA GIBS (GOES-East, banda 13).
- Radar de Chapecó: Defesa Civil SC / Epagri-Ciram (`sifap.defesacivil.sc.gov.br`), às vezes com atraso.
  O servidor não manda os certificados intermediários; eles estão em `certs/sifap-cadeia.pem`
  (Let's Encrypt YR2 e Root YR). Se o radar voltar a dar erro de certificado, baixar o intermediário
  novo indicado em "CA Issuers" do certificado do servidor.
- Previsão: Open-Meteo (ECMWF, GFS, ICON) a cada 2 h; conjunto (122 versões) para chances.
  Limite grátis: 10 mil chamadas/dia.
- Aeroporto de Chapecó (METAR SBCH), só de dia.
- INMET (estação A895 Chapecó): precisa de token gratuito, ainda não pedido.

## Telegram: quando manda
- Tempestade vindo: degraus de 90, 60, 30, 15 min e "agora".
- Salto de raios a até 60 km: no máximo a cada 30 min.
- Ambiente favorável (todos os modelos em alto): 1 vez por dia por fenômeno.
- Boletim: 7h e 19h.
- Resposta a `/relato` (Jev classifica; o texto vai para a TypeSafe, o painel não mostra texto nem nome).

## Pendências
- Rastreio melhor das tempestades (4 posições, vento dos modelos, mesma tempestade entre rodadas).
- Aviso antes do primeiro raio (topo de nuvem esfriando no GOES ABI).
- Token do INMET para medir acerto da chuva.
- Regra de microexplosão de inverno: testada e descartada (acertava 1 de 10).
