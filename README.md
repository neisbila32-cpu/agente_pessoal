# Agente Pessoal

Base modular de um agente para Windows, escrita principalmente em Python. A arquitetura recebe solicitações, prepara planos estruturados com um planejador injetável, verifica permissões e registra tarefas em SQLite. Há um contrato para IA e um planejador validado, mas **nenhum fornecedor ou adaptador de modelo concreto foi escolhido ou implementado**.

## Requisitos

- Python 3.11 ou superior.
- Nenhuma dependência de runtime externa; persistência e JSON usam a biblioteca padrão.

## Estrutura

```text
src/agente_pessoal/
├── ai/
│   ├── errors.py      # Erros normalizados de provedor, resposta e plano
│   ├── planner.py     # Interpretação, validação e geração de TaskPlan
│   └── provider.py    # Contrato ModelProvider e modelos de request/response
├── audit/             # Eventos estruturados, sem prompt/argumentos/resultados
├── config/            # Caminhos, modelo, timeouts e limites configuráveis
├── core/
│   ├── agent.py       # Entrada TaskOrchestrator
│   ├── executor.py    # Catálogo e verificação de permissão antes das ferramentas
│   ├── interpretation.py # Objetivo, intenção, dados, limites e ambiguidades
│   ├── planning.py    # Contrato Planner e TaskPlan
│   ├── ports.py       # Contratos de repositório
│   └── task_manager.py # Ciclo de vida, persistência e recuperação de tarefas
├── persistence/       # SQLite para solicitações, tarefas, auditoria e permissões
├── security/          # Concessões persistentes, negação padrão e porta de aprovação
└── tools/             # Contratos Tool e ToolDescription; sem ferramentas reais
tests/                 # Testes locais com provedores e ferramentas controlados
```

## Testes

```powershell
py -m unittest discover -s tests -t . -v
```

Os testes não fazem chamadas a APIs. `pytest` também está configurado no `pyproject.toml`, caso já esteja instalado.

## Integração com um provedor

`ModelProvider` padroniza a chamada usando `ModelRequest` e `ModelResponse`. Um adaptador real deverá ser injetado; não há seleção de SDK, endpoint nem fornecedor nesta versão. O adaptador deverá respeitar `model`, `timeout_seconds` e `max_output_chars`, normalizar falhas para as exceções em `ai/errors.py` e nunca registrar tokens ou o objeto de credencial.

Configuração lida por `Settings.from_environment()`:

| Variável | Uso | Padrão |
|---|---|---|
| `AGENTE_PESSOAL_AI_MODEL` | Identificador do modelo no fornecedor escolhido | Não configurado |
| `AGENTE_PESSOAL_AI_CREDENTIAL_ENV` | **Nome** da variável de ambiente onde o adaptador buscará a credencial | Não configurado |
| `AGENTE_PESSOAL_AI_TIMEOUT_SECONDS` | Timeout repassado ao adaptador (0,1–120 s) | 30 |
| `AGENTE_PESSOAL_AI_MAX_ATTEMPTS` | Tentativas de comunicação (1–3) | 2 |
| `AGENTE_PESSOAL_AI_MAX_REQUEST_CHARS` | Limite de texto enviado | 10.000 |
| `AGENTE_PESSOAL_AI_MAX_RESPONSE_CHARS` | Limite de resposta recebida | 65.536 |

O segredo fica somente na variável indicada no ambiente. `ModelRequest` carrega o nome dessa variável, nunca o valor; um adaptador que necessite dele pode usar `credential_from_environment()`. O núcleo não armazena nem imprime credenciais. Ainda será necessário implementar um adaptador real conforme o fornecedor e validar o tratamento de autenticação, timeout e erros desse SDK.

Quando houver um adaptador real, a conexão segue por injeção de dependências:

```python
from agente_pessoal.ai import AIPlanner
from agente_pessoal.audit import AuditLogger
from agente_pessoal.config import Settings
from agente_pessoal.core import TaskManager, TaskOrchestrator
from agente_pessoal.core.executor import ToolExecutor
from agente_pessoal.persistence import SQLiteStore
from agente_pessoal.security import PermissionManager

settings = Settings.from_environment()
store = SQLiteStore(settings.database_path)
audit = AuditLogger(store)
permissions = PermissionManager(store, audit)
executor = ToolExecutor(tools, permission_manager=permissions, audit=audit)
planner = AIPlanner(provider, settings, executor.tool_catalog)
manager = TaskManager(planner, executor, repository=store, audit=audit)
agent = TaskOrchestrator(manager)
```

`provider` será a implementação escolhida pelo projeto consumidor; `tools` deverá conter somente ferramentas concretas já revisadas. Este repositório não fornece nenhum dos dois.

## Interpretação e planejamento

`AIPlanner` implementa o contrato `Planner` existente. Ele envia ao provedor a solicitação e um catálogo de nomes/descrições obtido de `ToolExecutor.tool_catalog`. A resposta deve ser JSON estrito com objetivo, intenção, informações necessárias, limitações, ambiguidades e etapas com nome de ferramenta e argumentos.

Antes de retornar um `TaskPlan`, o planejador valida esquema exato, campos obrigatórios, duplicatas JSON, limites de tamanho/profundidade, tipos serializáveis e se cada ferramenta está no catálogo. Campos adicionais, inclusive qualquer tentativa de definir permissões, são rejeitados. Se faltar informação essencial, o plano precisa conter ambiguidades, não pode conter etapas executáveis e a tarefa fica em `AWAITING_INPUT`.

Fluxo:

```text
TaskOrchestrator.handle
  → TaskManager
  → AIPlanner / Planner
  → ModelProvider injetado
  → validação da resposta e do catálogo
  → TaskPlan
  → ToolExecutor
  → PermissionManager / política existente
  → ferramenta registrada
```

A IA só propõe nomes de ferramentas e argumentos. O `ToolExecutor` continua verificando a permissão declarada pela implementação da ferramenta imediatamente antes da execução; o modelo não recebe nem concede permissões. Sem autorização, a etapa falha e não chama a ferramenta.

## Persistência e auditoria

`SQLiteStore` mantém solicitações, tarefas, interpretação, etapas, resultados JSON, erros, transições de status, eventos de auditoria e estado das permissões. O caminho padrão é `~/.agente_pessoal/agente_pessoal.sqlite3`, alterável por `AGENTE_PESSOAL_DB_PATH` ou `Settings.database_path`. Argumentos e resultados persistidos precisam ser serializáveis em JSON. Tarefas e histórico são recuperáveis com `TaskManager.get()`, `list_tasks()` e `store.get_status_history(task_id)`.

Eventos guardam tipo, horário, IDs, nome da ferramenta, permissão, decisão e classe do erro. Não incluem prompt, texto da solicitação, argumentos, resultados, mensagem de exceção ou credenciais. Os dados operacionais necessários para recuperar tarefas continuam no banco; ele não é criptografado e deve ser protegido pelas permissões da conta do sistema operacional.

## Limitações e próxima etapa

- Sem adaptador real, nenhuma chamada de rede ou interpretação por modelo pode ocorrer ainda. Os testes usam apenas provedores controlados.
- A aprovação do usuário tem somente o contrato `ApprovalProvider`; não há interface nem ciclo para responder/retomar uma tarefa em `AWAITING_INPUT`.
- As tentativas são limitadas, mas backoff e timeout dependem de serem respeitados pelo adaptador.
- Não há ferramentas de produção, isolamento de processo, execução de automação, navegação ou manipulação de arquivos.
- O banco ainda não tem criptografia, expurgo/retention ou migrações versionadas.

Próxima etapa recomendada: escolher um fornecedor e implementar seu adaptador isolado, com testes de contrato sem segredos; em seguida revisar consentimento explícito, proteção do banco e validação específica dos argumentos antes de registrar qualquer ferramenta com efeitos reais.
