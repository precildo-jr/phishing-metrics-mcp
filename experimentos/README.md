# experimentos/

Reprodução dos resultados citados no TCC. Cada arnês exercita a plataforma real
(camadas de `plataforma/`) e grava seus dados em `data/`. Requisito
metodológico: a geração dos eventos é probabilística e reprodutível — a mesma
semente produz exatamente o mesmo conjunto de eventos.

| Arquivo | Papel |
|---|---|
| `generator.py` | Gerador probabilístico de eventos de campanha (perfis `baixo`, `base`, `alto`). |
| `run_experiment.py` | Varredura de carga × funil × repetições, submetendo os eventos ao receptor por HTTP. Produz `data/experimento-*.csv`. |
| `concurrency.py` | Varredura de concorrência: N escritores simultâneos contra o receptor real. Produz `data/concorrencia-*.csv`. |
| `robustness.py` | Bateria de sete casos adversos contra o receptor em operação. Produz `data/robustez-*.csv`. |
| `analytical_questions.py` | Dez perguntas analíticas resolvidas por composição programática das ferramentas MCP. Produz `data/perguntas-analiticas-*.csv`. |
| `llm_agent_questions.py` | As mesmas perguntas entregues a um agente de modelo de linguagem, que decide quais ferramentas invocar. Produz `data/agente-llm-*.csv`. Requer `DEEPSEEK_API`. |
| `webhook.py` | Utilitários comuns aos arneses: segredo, assinatura HMAC e subida do receptor em porta efêmera. |

## Execução (a partir da raiz do repositório)

```
python experimentos/run_experiment.py --loads 100,1000,10000 --reps 30 --seed 20260910
python experimentos/run_experiment.py --transport direct        # percurso de contraste
python experimentos/concurrency.py
python experimentos/robustness.py
python experimentos/analytical_questions.py
python experimentos/llm_agent_questions.py --load 50            # requer DEEPSEEK_API
```

A varredura de carga pelo webhook leva cerca de 4,5 h; use `--start-rep` para
retomá-la se for interrompida.

## Sobre os vereditos

Em `robustness.py`, `concurrency.py` e `llm_agent_questions.py`, o veredito de
cada caso é derivado do que o componente devolveu — código HTTP, estado da base,
resposta da ferramenta —, e não declarado de antemão no código.
