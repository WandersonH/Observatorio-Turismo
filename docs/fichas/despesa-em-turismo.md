# Ficha do indicador: despesa empenhada em turismo

| Campo | Conteúdo |
| --- | --- |
| Eixo do observatório | Despesas públicas |
| Dimensão do ranqueamento (Decreto 70.596/2026) | Ação normativo-institucional |
| Eixo da RITS-SP | nenhum |
| Fonte | Siconfi, Tesouro Nacional: Declaração de Contas Anuais, Anexo I-E (despesas por função e subfunção) |
| Tabela de origem | `tratado/siconfi/despesas_turismo` |
| Fórmula | soma da coluna "Despesas Empenhadas" nas contas da subfunção 23.695 (Turismo); participação = turismo ÷ despesa total empenhada; per capita = turismo ÷ população IBGE |
| Unidade | R$ correntes; % do total; R$ por habitante |
| Frequência | anual; a DCA tem prazo legal até 30 de abril do ano seguinte |
| Universo | pares município-ano esperados (101 municípios × anos coletados) |
| Amostra | pares com DCA entregue; registrado em `cobertura/siconfi` |
| Tratamento de ausentes | município sem linha na subfunção 23.695 fica vazio (não declarado), não zero |
| O que mede | o quanto o município classificou como turismo na sua contabilidade |
| O que não mede | gasto com turismo lançado em outras subfunções (cultura, eventos, infraestrutura); recursos estaduais executados diretamente pelo Estado; efeito do gasto |
| Responsável | a definir |
| Última revisão | novembro de 2026 |

A base de 2023-2025 tinha 34 municípios com zero em 2023 e 36 em 2024. A primeira coleta automática deve dizer quantos desses são falta de declaração.
