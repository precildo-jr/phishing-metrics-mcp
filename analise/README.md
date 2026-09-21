# analise/

Ferramentas de análise e de evidência. Não fazem parte do núcleo da plataforma;
produzem os artefatos apresentados no TCC a partir dos dados de `data/`.

| Arquivo | Papel |
|---|---|
| `make_figures.py` | Gera as figuras de latência, funil e vazão a partir de um CSV de varredura, em escala de cinza. Requer matplotlib. |
| `make_arch_figure.py` | Gera o diagrama arquitetural da plataforma (Figura 1 do TCC). Requer matplotlib. |
| `capture_webhook.py` | Sobe o receptor real e registra cada requisição recebida do Gophish (cabeçalhos, corpo bruto, veredito de assinatura, desfecho), para verificar a integração ponta a ponta. Produz `data/captura-webhook-*.jsonl`. |
| `smtp_sink.py` | Coletor SMTP mínimo que aceita e descarta mensagens, para que o Gophish emita `Email Sent` sem que nenhum e-mail deixe a máquina. |

As figuras são regeneráveis e não são versionadas (ver `.gitignore`).

## Execução (a partir da raiz do repositório)

```
python analise/make_arch_figure.py
python analise/make_figures.py                 # usa o CSV mais recente em data/
python analise/smtp_sink.py                    # coletor, em um terminal
GOPHISH_WEBHOOK_SECRET=<segredo> python analise/capture_webhook.py   # receptor, em outro
```
