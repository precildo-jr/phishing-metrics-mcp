# experiments/

Arnês de experimento do TCC.

Requisito metodológico atendido em todos os módulos: a geração dos eventos é
probabilística e reprodutível — a mesma semente produz exatamente o mesmo
conjunto de eventos. Os parâmetros das distribuições (probabilidades
condicionais do funil, taxa do processo de Poisson, parâmetros da log-normal do
atraso) são declarados em `generator.py` e descritos na seção Material e
Métodos do TCC.

## Módulos

| Arquivo | Papel |
|---|---|
| `generator.py` | Gerador probabilístico de eventos de campanha. Cadeia de ensaios de Bernoulli condicionais sobre uma linha do tempo de Poisson. Define os perfis `baixo`, `base` e `alto`. |
| `run_experiment.py` | Varredura de carga × funil × repetições, submetendo os eventos pelo receptor de webhook por HTTP. Produz `data/experimento-*.csv`. |
| `robustness.py` | Bateria de verificação de robustez: sete casos adversos contra o receptor de webhook em operação real, sobre HTTP. Produz `data/robustez-*.csv`. |
| `concurrency.py` | Varredura de concorrência: N escritores simultâneos contra o receptor real, comparando requisições aceitas com registros persistidos. Produz `data/concorrencia-*.csv`. |
| `llm_agent_questions.py` | As mesmas dez perguntas, agora entregues em linguagem natural a um modelo, que descobre as ferramentas e decide sozinho quais invocar. Produz `data/agente-llm-*.csv`. Requer `DEEPSEEK_API`. |
| `webhook.py` | Utilitários comuns aos arneses que falam com o receptor: segredo, assinatura HMAC e subida do servidor em porta efêmera. |
| `analytical_questions.py` | Verificação da decisão arquitetural: dez perguntas analíticas submetidas ao servidor MCP por conexão real de protocolo. Produz `data/perguntas-analiticas-*.csv`. |
| `make_figures.py` | Figuras do TCC em escala de cinza, a partir de um CSV de varredura. Requer matplotlib (`requirements-figs.txt`). |

## Execução completa

```
python experiments/run_experiment.py --loads 100,1000,10000 --reps 30 --seed 20260910
python experiments/robustness.py
python experiments/analytical_questions.py
python experiments/make_figures.py
```

A varredura completa leva cerca de duas horas. Para verificação rápida:

```
python experiments/run_experiment.py --loads 100,500 --reps 3
```

## Sobre os vereditos

Em `robustness.py` e `analytical_questions.py`, o veredito de cada caso é
**derivado** do que o componente devolveu — código HTTP, estado da base,
conteúdo da resposta da ferramenta —, e não declarado de antemão no código. Um
caso só é dado por conforme quando a comparação entre o esperado e o observado
o sustenta; `robustness.py` encerra com código de saída diferente de zero se
qualquer caso divergir.
