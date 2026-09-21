# Instrumentação de campanhas simuladas de engenharia social via MCP

Plataforma modular para coleta, persistência e consolidação de eventos de
campanhas simuladas de phishing, com camada de orquestração implementada
segundo o **Model Context Protocol (MCP)**.

Código-fonte de referência do Trabalho de Conclusão de Curso *Confiabilidade da
coleta de eventos em simulações de phishing orquestradas por Model Context
Protocol*, do MBA em Engenharia de Software da USP/Esalq.

---

## Aviso de uso

Este repositório é material acadêmico. A plataforma foi construída para operar
em **ambiente isolado e controlado**, com eventos gerados sinteticamente:

- o módulo de envio por SMTP permanece **desabilitado** em todas as execuções;
- nenhuma mensagem é transmitida a destinatários reais;
- nenhum dado pessoal é coletado ou processado;
- não há interação com usuários ou sistemas organizacionais reais.

A condução de campanhas simuladas em ambiente organizacional exige autorização
formal prévia da organização. Este código não deve ser utilizado fora dessas
condições.

---

## Arquitetura

Quatro camadas com responsabilidades distintas:

```
┌─────────────────┐   eventos de       ┌─────────────────┐
│   SIMULAÇÃO     │   campanha         │    INGESTÃO     │
│                 │ ─────────────────► │                 │
│ Gophish         │   HTTP / webhook   │ recepção e      │
│ (admin + phish  │                    │ normalização    │
│  server)        │                    │                 │
└─────────────────┘                    └────────┬────────┘
                                                │
                                                ▼
┌─────────────────┐                    ┌─────────────────┐
│  PERSISTÊNCIA   │ ◄───────────────── │  ORQUESTRAÇÃO   │
│                 │                    │                 │
│ SQLite          │   registrar        │ servidor MCP    │
│ (events.db)     │   consultar        │ (FastMCP)       │
│                 │   consolidar       │ 3 ferramentas   │
└─────────────────┘                    └─────────────────┘
                                                ▲
                                                │ linguagem natural
                                       ┌────────┴────────┐
                                       │ agente de LLM   │
                                       │ (cliente MCP)   │
                                       └─────────────────┘
```

A camada de orquestração expõe os dados como **ferramentas descritas e
invocáveis por agentes**, e não como pontos de acesso REST fixos. É essa
diferença que o TCC submete a verificação experimental: consultas analíticas
podem ser formuladas em linguagem natural e compostas a partir das ferramentas
existentes, sem implementação prévia de um endpoint por pergunta.

---

## Estrutura do repositório

```
plataforma/     núcleo da solução — a contribuição do trabalho
  persistencia.py   camada de persistência (SQLite, idempotência, latência)
  ingestao.py       camada de ingestão (webhook, validação HMAC, normalização)
  orquestracao.py   camada de orquestração (servidor MCP, três ferramentas)
experimentos/   reprodução dos resultados citados no TCC
  generator.py, run_experiment.py, concurrency.py, robustness.py,
  analytical_questions.py, llm_agent_questions.py, webhook.py
analise/        ferramentas de análise e evidência
  make_figures.py, make_arch_figure.py, capture_webhook.py, smtp_sink.py
data/           conjuntos de dados brutos das execuções (rastreabilidade)
```

Os scripts são executados a partir da raiz do repositório; cada um insere a
raiz em `sys.path` para importar o pacote `plataforma`.

## Componentes

| Componente | Arquivo |
|---|---|
| Camada de persistência (esquema de funil, idempotência, latência) | `plataforma/persistencia.py` |
| Camada de ingestão (webhook do Gophish, validação HMAC) | `plataforma/ingestao.py` |
| Camada de orquestração (três ferramentas MCP) | `plataforma/orquestracao.py` |
| Módulo analítico (taxas de funil, latências) | `plataforma/persistencia.py` |
| Arnês de experimento (carga, concorrência, robustez, composição) | `experimentos/` |
| Geração de figuras e captura de evidência | `analise/` |

---

## Requisitos

- Python 3.14 ou superior (verificado em 3.14.4)
- SQLite — incluído na biblioteca padrão do Python (verificado em 3.50.4)
- Gophish — distribuição oficial, apenas para os experimentos de ingestão

## Instalação

```bash
git clone <URL-DO-REPOSITORIO>
cd MCP_TCC
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux / macOS
source .venv/bin/activate
pip install -r requirements.txt
```

## Execução

**Criar a base e executar a verificação da camada de persistência:**

```bash
python plataforma/persistencia.py
```

Cria o arquivo `events.db` caso não exista, registra um evento de verificação e
imprime os registros armazenados.

**Iniciar o receptor de webhook do Gophish (camada de ingestão):**

```bash
# o segredo deve ser o mesmo configurado no webhook do Gophish
GOPHISH_WEBHOOK_SECRET=<segredo> python plataforma/ingestao.py --host 127.0.0.1 --port 9099
```

O receptor valida a assinatura HMAC-SHA256 do corpo de cada requisição
(cabeçalho `X-Gophish-Signature`), normaliza o evento e o persiste de forma
idempotente. Requisições sem assinatura válida recebem `401`.

**Iniciar o servidor MCP:**

```bash
python plataforma/orquestracao.py
```

O servidor comunica-se por entrada e saída padrão (stdio) e é consumido por um
cliente MCP, não diretamente pelo terminal. Para registrá-lo em um cliente,
acrescente à configuração de servidores MCP:

```json
{
  "mcpServers": {
    "gophish-tcc-server": {
      "command": "python",
      "args": ["CAMINHO/ABSOLUTO/PARA/plataforma/orquestracao.py"]
    }
  }
}
```

---

## Ferramentas MCP expostas

| Ferramenta | Parâmetros | Retorno |
|---|---|---|
| `register_simulated_event` | `campaign_name: str`, `event_type: str`, `source: str = "mcp_server"` | `status`, `event_id`, `campaign_name`, `event_type`, `source` |
| `get_registered_events` | — | `total`, `events[]` com `id`, `campaign_name`, `event_type`, `source`, `origin_ts`, `ingest_ts`, `target_id` |
| `generate_basic_metrics` | — | `total_events`, `events_by_type`, `funnel_rates` (taxas de conversão), `propagation_latency_ms` (percentis 50 e 95 e máximo) |

## Modelo de dados

Duas tabelas. `campaigns` normaliza a campanha, antes tratada como texto livre:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | identificador interno |
| `external_id` | INTEGER UNIQUE | `campaign_id` do Gophish, quando houver |
| `name` | TEXT NOT NULL | nome da campanha |
| `created_at` | TEXT NOT NULL | instante de criação do registro |

`events` guarda os campos necessários à apuração de funil, à idempotência e à
medição de latência:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK | identificador do registro |
| `campaign_id` | INTEGER FK → campaigns | campanha associada |
| `target_id` | TEXT | identificador do alvo **pseudonimizado** por HMAC-SHA256 com chave; sem a chave não se associa de volta ao endereço |
| `message_id` | TEXT | identificador da mensagem, quando disponível |
| `external_event_id` | TEXT UNIQUE | chave de **idempotência**: reentrega não duplica |
| `event_type` | TEXT NOT NULL | tipo normalizado (ver abaixo) |
| `source` | TEXT NOT NULL | origem do registro (`gophish_webhook`, `mcp_server`) |
| `origin_ts` | TEXT NOT NULL | instante em que o evento ocorreu |
| `ingest_ts` | TEXT NOT NULL | instante em que foi persistido |
| `raw_payload` | TEXT | notificação original, para auditoria, com o endereço do destinatário **suprimido** antes da gravação |

A latência de propagação de cada evento é `ingest_ts − origin_ts`. As
instruções SQL utilizam parâmetros vinculados, e há índice em
`(campaign_id, event_type)`.

**Tipos de evento normalizados** (degraus do funil): `EMAIL_SENT`,
`EMAIL_OPENED`, `LINK_CLICKED`, `DATA_SUBMITTED`, `EMAIL_REPORTED`. A camada de
ingestão converte as mensagens do Gophish (`Email Sent`, `Email Opened`,
`Clicked Link`, `Submitted Data`, `Email Reported`) para esse vocabulário;
mensagens fora do funil, como `Campaign Created`, são descartadas.

> **Mudança de esquema:** a versão anterior tinha uma única tabela `events`
> com `campaign_name`/`created_at`. O `events.db` é recriado por
> `create_database()` a cada execução e não é versionado, de modo que a
> migração se resume ao esquema aqui descrito; não há dado de produção a migrar.

---

## Reprodutibilidade

- Versões das dependências fixadas em `requirements.txt`.
- Geração de eventos probabilística e determinística por semente: a mesma
  semente reproduz o mesmo conjunto de eventos.
- Sementes, parâmetros de cada cenário e conjuntos de dados resultantes
  depositados em `data/`.
- A versão citada no TCC é identificada por etiqueta (tag) do repositório.

## Licença

MIT — ver [LICENSE](LICENSE).

## Autoria

Precildo Azevedo Junior — MBA em Engenharia de Software, MBA USP/Esalq.
Orientação: Prof. Dr. Vinicius Santos Andrade.
