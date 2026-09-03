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
│ GoPhish         │   HTTP / webhook   │ recepção e      │
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

## Estado da implementação

| Componente | Arquivo | Estado |
|---|---|---|
| Camada de persistência | `database.py` | implementado |
| Camada de orquestração (3 ferramentas MCP) | `server_mcp.py` | implementado |
| Camada de ingestão (recepção de eventos do GoPhish) | — | em desenvolvimento |
| Esquema de dados de funil (alvo, mensagem, idempotência) | — | em desenvolvimento |
| Módulo analítico (taxas de funil, latências) | — | em desenvolvimento |
| Arnês de experimento | `experiments/` | em desenvolvimento |
| Geração de figuras | — | em desenvolvimento |

---

## Requisitos

- Python 3.14 ou superior (verificado em 3.14.4)
- SQLite — incluído na biblioteca padrão do Python (verificado em 3.50.4)
- GoPhish — distribuição oficial, apenas para os experimentos de ingestão

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
python database.py
```

Cria o arquivo `events.db` caso não exista, registra um evento de verificação e
imprime os registros armazenados.

**Iniciar o servidor MCP:**

```bash
python server_mcp.py
```

O servidor comunica-se por entrada e saída padrão (stdio) e é consumido por um
cliente MCP, não diretamente pelo terminal. Para registrá-lo em um cliente,
acrescente à configuração de servidores MCP:

```json
{
  "mcpServers": {
    "gophish-tcc-server": {
      "command": "python",
      "args": ["CAMINHO/ABSOLUTO/PARA/server_mcp.py"]
    }
  }
}
```

---

## Ferramentas MCP expostas

| Ferramenta | Parâmetros | Retorno |
|---|---|---|
| `register_simulated_event` | `campaign_name: str`, `event_type: str`, `source: str = "mcp_server"` | `status`, `event_id`, `campaign_name`, `event_type`, `source` |
| `get_registered_events` | — | `total`, `events[]` com `id`, `campaign_name`, `event_type`, `source`, `created_at` |
| `generate_basic_metrics` | — | `total_events`, `events_by_type` (contagem por tipo) |

## Modelo de dados

Esquema atual da tabela `events`:

| Campo | Tipo | Descrição |
|---|---|---|
| `id` | INTEGER PK AUTOINCREMENT | identificador do registro |
| `campaign_name` | TEXT NOT NULL | campanha associada |
| `event_type` | TEXT NOT NULL | tipo do evento |
| `source` | TEXT NOT NULL | origem do registro |
| `created_at` | TEXT NOT NULL | instante de gravação (`YYYY-MM-DD HH:MM:SS`) |

As instruções SQL utilizam parâmetros vinculados. O esquema será estendido para
suportar a apuração de funil — identificador de alvo pseudonimizado,
identificador da mensagem, identificador externo do evento (idempotência) e
separação entre o instante de origem e o instante de ingestão, cuja diferença
constitui a latência de propagação medida no trabalho.

---

## Reprodutibilidade

- Versões das dependências fixadas em `requirements.txt`.
- Geração de eventos probabilística e determinística por semente: a mesma
  semente reproduz o mesmo conjunto de eventos.
- Sementes, parâmetros de cada cenário e conjuntos de dados resultantes
  depositados em `data/`.
- A versão citada no TCC é identificada por etiqueta (tag) do repositório.

## Estrutura

```
MCP_TCC/
├── database.py        camada de persistência
├── server_mcp.py      camada de orquestração (servidor MCP)
├── experiments/       arnês de experimento e cenários
├── data/              conjuntos de dados brutos das execuções (CSV)
├── requirements.txt
├── LICENSE
└── README.md
```

## Licença

MIT — ver [LICENSE](LICENSE).

## Autoria

Precildo Azevedo Junior — MBA em Engenharia de Software, MBA USP/Esalq.
Orientação: Prof. Dr. Vinicius Santos Andrade.
