# Observatório de Turismo da AMITESP: coleta contínua

Código que transforma o Observatório de Turismo da AMITESP, criado em convênio com a Escola de Artes, Ciências e Humanidades da USP (EACH-USP), de um retrato de 2023-2025 em uma série atualizada automaticamente.

Os coletores leem fontes públicas e plataformas, ligam cada registro ao município pelo código IBGE, registram universo e amostra de cada coleta e gravam tudo, com data, no banco que alimenta o painel do Looker Studio.

## Princípios

- **Universo e amostra em toda coleta.** Cada execução grava quantos casos a fonte reporta e quantos foram de fato lidos (`data/cobertura/`).
- **Ausente não é zero.** Resposta em branco, "não informado" e "resposta inválida" ficam fora das médias (`observatorio.qualidade`).
- **Nada é sobrescrito.** Cada carga é uma fotografia datada; a série histórica sai das próprias cargas.
- **Nenhum dado bruto no Git.** Cargas ficam no BigQuery e nos artefatos do Actions; chaves ficam nos segredos do repositório. O ramo `gh-pages` recebe só indicadores agregados por município.

## Coletores

| Fonte | Situação | Frequência | O que entrega |
| --- | --- | --- | --- |
| IBGE | implementado | anual | Cadastro mestre: 645 municípios de SP, população, marcação dos 101 da base AMITESP |
| Cadastur (MTur) | implementado | trimestral | Prestadores formais por categoria, município, leitos e UHs |
| Siconfi (Tesouro) | implementado | anual | Despesa empenhada em turismo (subfunção 695), total e por habitante |
| Novo CAGED (MTE) | implementado | mensal | Admissões, desligamentos e saldo nas atividades características do turismo, 12 meses |
| ANAC | implementado | mensal | Passageiros desembarcados nos aeroportos de SP, por município do aeroporto |
| ANTT | implementado | mensal | Ônibus de fretamento eventual e turístico interestadual chegando e saindo |
| CETESB | implementado | anual | Índice de Qualidade de Aterro (IQR) e toneladas de resíduos por dia |
| Alesp | implementado | mensal | Proposituras e normas sobre turismo que citam cada município |
| Diários oficiais (Querido Diário) | implementado | trimestral | Menções a plano diretor de turismo, COMTUR e inventário turístico |
| Google Notícias e OpenAlex | implementado | mensal | Notícias sobre turismo (30 dias) e trabalhos acadêmicos por município |
| Google Places | implementado, exige chave | trimestral | Hospedagens do Cadastur pareadas no Google, nota e oferta fora do Cadastur |
| TripAdvisor | planejado | trimestral | Inventário de atrativos |

Chaves opcionais, como segredos do repositório: `GOOGLE_PLACES_API_KEY` (sem ela o Google Places fica como "falta credencial") e `OPENALEX_API_KEY` (sem ela a OpenAlex usa o orçamento diário compartilhado).

O catálogo completo está em [`config/fontes.yaml`](config/fontes.yaml). Coletores por raspagem ficam num repositório privado até decisão do convênio.

## Como rodar

```bash
pip install -e ".[dev]"
observatorio fontes
observatorio coletar ibge          # cadastro mestre; os outros coletores dependem dele
observatorio coletar cadastur
observatorio coletar siconfi --anos 2023 2024 2025
python scripts/validar_siconfi.py  # confere contra a base 2023-2025
observatorio rodar-tudo            # todas as fontes; o que falha não interrompe as outras
observatorio site --saida _site    # site e API estática
python -m http.server -d _site     # abre em http://localhost:8000
pytest -q
```

Sem configuração extra, as cargas vão para `data/` em Parquet. Para enviar também ao BigQuery, defina `OBS_BQ_PROJECT` e tenha credenciais do Google Cloud no ambiente.

## No GitHub Actions

O workflow **Coleta** roda sozinho (Cadastur a cada trimestre, Siconfi em maio, IBGE em setembro) e também pela aba Actions, escolhendo a fonte. Cada execução publica o resumo de cobertura e guarda a carga como artefato por 14 dias.

Para gravar no BigQuery, configure no repositório:

| Onde | Nome | Conteúdo |
| --- | --- | --- |
| Variables | `OBS_BQ_PROJECT` | ID do projeto do Google Cloud |
| Secrets | `GCP_SA_KEY` | JSON de uma conta de serviço com permissão de escrita no BigQuery |

As tabelas são criadas nos datasets `obs_bruto`, `obs_tratado` e `obs_cobertura`.

## Site e API

O workflow **Site** roda todo dia 12 (e pela aba Actions): executa `rodar-tudo`, gera o site e publica no ramo `gh-pages`. Para servir pelo GitHub Pages, ative em Settings → Pages → Branch `gh-pages`.

O site tem mapa coroplético dos 645 municípios, página de cada município, tabela comparável e a página **Fontes e cobertura**, que mostra o que rodou, o que falhou (com o erro) e o que ainda não foi implementado ou aguarda decisão do convênio, sempre com universo e amostra.

A API é estática, em `api/v1/`: `meta.json`, `municipios.json`, `municipios/{codigo_ibge}.json`, `indicadores.json`, `status.json`, `cobertura.json` e `malha_sp.geojson`. A organização segue a da [API do UrbVerde](https://github.com/UrbVerde/urbverde-api) (IAU-USP); quando houver dados por setor censitário, o mesmo esquema migra para PostGIS e pg_tileserv.

## Estrutura

```
config/            municípios da base e catálogo de fontes
docs/              arquitetura e fichas metodológicas dos indicadores
scripts/           conferências contra a base 2023-2025
src/observatorio/  pacote: armazenamento, cobertura, qualidade, coletores, execução e site
tests/             testes sem rede
```

## Licença

A definir pelo convênio AMITESP e EACH-USP.
