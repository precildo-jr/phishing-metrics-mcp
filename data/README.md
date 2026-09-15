# data/

Conjuntos de dados brutos das execuções experimentais, em formato CSV.

Todo número apresentado no TCC deve ser rastreável até uma linha de arquivo
depositado aqui. Os arquivos são versionados junto com o código, de modo que a
etiqueta (tag) citada no trabalho identifique simultaneamente o código que
produziu os dados e os dados produzidos.

## Execuções depositadas

| Arquivo | Produzido por | Conteúdo |
|---|---|---|
| `experimento-20260914-122004.csv` | `experiments/run_experiment.py` | Execução parcial de verificação, interrompida. Não sustenta resultado do TCC. |
| `experimento-20260914-143857.csv` | `experiments/run_experiment.py` | **Varredura definitiva**: 3 perfis de funil × 3 faixas de carga × 30 repetições = 270 execuções, 999.000 eventos. |
| `robustez-20260915-085919.csv` | `experiments/robustness.py` | Bateria de verificação de robustez: 7 casos adversos contra o receptor em operação real. |
| `perguntas-analiticas-20260915-090334.csv` | `experiments/analytical_questions.py` | 10 perguntas analíticas submetidas ao servidor MCP por conexão real de protocolo. |

## Dicionário de dados

### `experimento-*.csv` — varredura de carga

| Campo | Tipo | Significado |
|---|---|---|
| `scenario` | texto | Perfil de funil: `baixo`, `base` ou `alto` (ver `experiments/generator.py`). |
| `load` | inteiro | Eventos gerados na execução: 100, 1.000 ou 10.000. |
| `rep` | inteiro | Número da repetição, de 1 a 30. |
| `seed` | inteiro | Semente pseudoaleatória da execução. A mesma semente reproduz exatamente o mesmo conjunto de eventos. |
| `emitted` | inteiro | Eventos efetivamente submetidos à camada de persistência. |
| `persisted` | inteiro | Eventos apurados na base após a execução, por contagem em SQL. |
| `loss_rate` | decimal | `(emitted − persisted) / emitted`. Zero em todas as 270 execuções. |
| `lat_p50_ms` | decimal | Percentil 50 da latência de propagação (ingestão − origem), em milissegundos. |
| `lat_p95_ms` | decimal | Percentil 95 da mesma latência. |
| `lat_max_ms` | decimal | Máximo observado da mesma latência. |
| `click_of_sent` | decimal | Cliques sobre enviados, apurado da base. Compare-se ao nominal do perfil. |
| `submit_of_click` | decimal | Submissões sobre cliques, apurado da base. |
| `elapsed_s` | decimal | Duração da fase de persistência da execução, em segundos. Vazão = `emitted / elapsed_s`. |

Uma linha por execução; 270 linhas mais o cabeçalho.

### `robustez-*.csv` — bateria de verificação de robustez

| Campo | Significado |
|---|---|
| `caso` | Identificador do caso, de `R1` a `R7`. |
| `descricao` | Caso adverso submetido, conforme o protocolo experimental do TCC. |
| `esperado` | Comportamento esperado, declarado antes da execução. |
| `observado` | Comportamento observado, composto a partir dos códigos HTTP e do estado da base. |
| `veredito` | `Conforme` ou `Não conforme`, derivado da comparação — não declarado de antemão. |

### `perguntas-analiticas-*.csv` — composição sobre a camada de orquestração

| Campo | Significado |
|---|---|
| `id` | Identificador da pergunta, de `Q01` a `Q10`. |
| `pergunta` | Pergunta analítica formulada sobre as campanhas simuladas. |
| `ferramentas_compostas` | Ferramentas MCP que o agente invocou para respondê-la. |
| `desfecho` | `Resolvida por composição` ou `Exigiria novo ponto de acesso`. |
| `resposta` | Resposta obtida, ou a indicação de que as ferramentas expostas não bastam. |

## Reprodução

```
python experiments/run_experiment.py --loads 100,1000,10000 --reps 30 --seed 20260910
python experiments/robustness.py
python experiments/analytical_questions.py
python experiments/make_figures.py          # usa o CSV mais recente
```

As figuras derivadas não são versionadas: `experiments/make_figures.py` as
regenera a partir do CSV a qualquer momento.
