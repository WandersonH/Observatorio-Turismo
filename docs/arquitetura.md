# Arquitetura

Três origens de dados, um único banco e três camadas. Só o que passa nos testes de qualidade chega ao painel.

| Origem | Exemplos | Onde o código mora |
| --- | --- | --- |
| Fontes públicas | IBGE, Cadastur, Siconfi, CAGED, ANAC, ANTT, CETESB, Alesp | este repositório |
| Plataformas | Google Places, TripAdvisor, Airbnb, Booking, redes sociais | este repositório (APIs oficiais) e o privado (raspagem) |
| Equipe de campo | formulário anual, pesquisa com hotéis, pesquisa de demanda | instrumentos digitais, fora do Git |

## Camadas

1. **bruto**: o que a fonte entregou, com `data_coleta`. Nada é sobrescrito.
2. **tratado**: padronizado por município (código IBGE) e período.
3. **indicadores**: o que o Looker Studio lê, cada indicador com sua ficha em `docs/fichas/`.

Uma quarta tabela, **cobertura**, registra em cada coleta o universo que a fonte reporta e a amostra efetivamente lida.

## Princípios

- **Universo e amostra sempre.** Nenhum indicador é publicado sem dizer quantos casos a fonte tinha e quantos foram lidos.
- **Ausente não é zero.** Resposta em branco, "não informado" e "resposta inválida" ficam fora das médias.
- **Append-only.** Cada carga é uma fotografia datada; a série histórica sai das próprias cargas.
- **Sem dados sensíveis no Git.** Dados ficam no BigQuery; chaves ficam nos segredos do GitHub Actions. Dados de hotéis sob termo de sigilo vão para área restrita, e o painel suprime municípios com poucos estabelecimentos.
- **Falha visível.** Um coletor que quebra encerra com erro e o Actions avisa.

## Ligação entre fontes

O cadastro mestre (`observatorio coletar ibge`) liga cada município ao código IBGE de 7 dígitos e marca os 101 da base AMITESP. Estabelecimentos se ligam pelo CNPJ (Cadastur) e pelo `place_id` (Google).
