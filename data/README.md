# data/

Conjuntos de dados brutos das execuções experimentais, em formato CSV.

Todo número apresentado no TCC deve ser rastreável até uma linha de arquivo
depositado aqui. Os arquivos são versionados junto com o código, de modo que a
etiqueta (tag) citada no trabalho identifique simultaneamente o código que
produziu os dados e os dados produzidos.

## Execuções depositadas

| Arquivo | Produzido por | Conteúdo |
|---|---|---|
| `experimento-20260914-143857.csv` | `run_experiment.py --transport direct` | Varredura de carga gravando direto na persistência, sem passar pela camada de ingestão. 270 execuções, 999.000 eventos. Serve de contraste para medir o custo da coleta. |
| `experimento-20260918-172713.csv` | `run_experiment.py` (webhook) | **Varredura definitiva**: mesmos 3 perfis × 3 cargas × 30 repetições, mas com cada evento entregue ao receptor por requisição assinada. 999.000 eventos, perda nula. |
| `concorrencia-v1.0.0-20260917.csv` | `concurrency.py` | Perda sob escrita concorrente antes da correção: 0,98% em 1.740 eventos. |
| `concorrencia-v1.1.0-20260917.csv` | `concurrency.py` | Mesma varredura após a correção: perda nula. |
| `robustez-20260915-085919.csv` | `robustness.py` | Bateria de robustez na versão 1.0.0. |
| `robustez-20260917-083948.csv` | `robustness.py` | Bateria de robustez na versão 1.1.0. 7/7 conformes em ambas. |
| `perguntas-analiticas-*.csv` | `analytical_questions.py` | Composição programática das ferramentas MCP: 8/10. |
| `agente-llm-carga50-20260917.csv` | `llm_agent_questions.py --load 50` | Agente real sobre base de 125 eventos: 8/10, sem truncamento. |
| `agente-llm-carga200-20260917.csv` | `llm_agent_questions.py --load 200` | Agente real sobre base de 500 eventos: 3/10, com 8 retornos truncados. |

## Dicionário de dados

### `experimento-*.csv` — varredura de carga

| Campo | Tipo | Significado |
|---|---|---|
| `scenario` | texto | Perfil de funil: `baixo`, `base` ou `alto` (ver `experiments/generator.py`). |
| `transport` | texto | `webhook` quando o evento percorreu a camada de ingestão por HTTP; `direct` quando foi gravado direto na persistência. |
| `accepted` | inteiro | Requisições que o receptor aceitou (HTTP 200). Difere de `emitted` apenas se alguma for recusada. |
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

### `concorrencia-*.csv` — varredura de concorrência

| Campo | Significado |
|---|---|
| `escritores` | Número de ingestores submetendo eventos simultaneamente. |
| `eventos_por_escritor` | Eventos submetidos por cada escritor. |
| `emitidos` | Total de requisições enviadas (`escritores` × `eventos_por_escritor`). |
| `persistidos` | Registros apurados na base ao final. |
| `perdidos` | `emitidos − persistidos`. |
| `loss_rate` | Taxa de perda sob aquele grau de concorrência. |
| `desfechos` | Contagem por código HTTP e desfecho, como devolvidos pelo receptor. |
| `elapsed_s` | Duração da rodada, em segundos. |
| `vazao_eventos_s` | `emitidos / elapsed_s`. |

Os arquivos trazem o sufixo da versão da plataforma: `concorrencia-v1.0.0-*.csv`
documenta a perda observada antes da correção e `concorrencia-v1.1.0-*.csv`, o
resultado depois dela. Ambos foram produzidos pelo mesmo arnês.

### `agente-llm-*.csv` — perguntas submetidas a um agente real

| Campo | Significado |
|---|---|
| `id` | Identificador da pergunta, de `Q01` a `Q10`. |
| `pergunta` | Pergunta entregue ao modelo em linguagem natural. |
| `ferramentas_invocadas` | Ferramentas que o modelo decidiu chamar, na ordem em que as chamou. |
| `rodadas` | Idas e vindas de conversa até o modelo concluir. |
| `truncou` | `sim` quando algum retorno de ferramenta excedeu o teto e foi cortado. |
| `respondida` | Veredito do próprio modelo sobre ter conseguido responder. |
| `resposta` | Resposta produzida, quando houve. |
| `justificativa` | Explicação do modelo, sobretudo quando não respondeu. |
| `tokens` | Tokens consumidos na pergunta. |

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
python experiments/run_experiment.py --transport direct          # percurso de contraste
python experiments/concurrency.py
python experiments/robustness.py
python experiments/analytical_questions.py
python experiments/llm_agent_questions.py --load 50              # requer DEEPSEEK_API
python experiments/llm_agent_questions.py --load 200
python experiments/make_figures.py                               # usa o CSV mais recente
```

A varredura de carga pelo webhook leva cerca de 4,5 h; use `--start-rep` para
retomá-la se for interrompida.

As figuras derivadas não são versionadas: `experiments/make_figures.py` as
regenera a partir do CSV a qualquer momento.
