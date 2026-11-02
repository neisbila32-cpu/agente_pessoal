# Agente Pessoal

Base modular de um agente para Windows, escrita principalmente em Python. O projeto recebe solicitações, prepara planos estruturados, verifica permissões e registra tarefas em SQLite. A chamada a modelos usa um contrato agnóstico de fornecedor com adaptador NVIDIA NIM opcional; não há ferramentas de produção nem automação do computador.

## Requisitos

- Python 3.11 ou superior.
- SDK oficial OpenAI Python (`openai`, instalado pelas dependências do projeto) para o adaptador compatível com NVIDIA NIM.
- SQLite e JSON usam a biblioteca padrão.

## Estrutura

```text
src/agente_pessoal/
├── ai/
│   ├── errors.py      # Erros normalizados de provedor, resposta e plano
│   ├── planner.py     # Interpretação, validação e geração de TaskPlan
│   ├── provider.py    # Contrato ModelProvider e request/response
│   └── nvidia.py      # Adaptador NVIDIA NIM via SDK OpenAI compatível
├── audit/             # Eventos estruturados, sem prompt/argumentos/resultados
├── config/            # Modelo, timeout e limites configuráveis
├── core/              # Orquestração, execução, planejamento e ciclo de vida
├── persistence/       # SQLite para tarefas, auditoria e permissões
├── security/          # Concessões persistentes, negação padrão e aprovação
└── tools/             # Contratos de ferramentas; sem ferramentas reais
tests/                 # Testes offline com clientes e ferramentas controlados
```

## Configuração da NVIDIA NIM

O `NvidiaNimProvider` implementa `ModelProvider` com o endpoint OpenAI compatível da NVIDIA. A chave é lida exclusivamente de `NVIDIA_API_KEY` no momento da chamada, enviada diretamente ao cliente SDK e nunca armazenada na configuração ou no banco. `OPENAI_API_KEY` não é usada como fallback. Não registre a chave, cabeçalhos HTTP ou objetos de erro do SDK.

| Variável | Uso | Padrão |
|---|---|---|
| `NVIDIA_API_KEY` | Credencial da NVIDIA NIM (obrigatória para chamadas reais) | Sem padrão |
| `AGENTE_PESSOAL_AI_MODEL` | Identificador de modelo | `nvidia/nemotron-3.5-super-vl-120b-a12b` |
| `AGENTE_PESSOAL_AI_TIMEOUT_SECONDS` | Timeout por chamada (0,1–120 s) | 30 |
| `AGENTE_PESSOAL_AI_MAX_ATTEMPTS` | Tentativas limitadas pelo `AIPlanner` (1–3) | 2 |
| `AGENTE_PESSOAL_AI_MAX_REQUEST_CHARS` | Limite da solicitação enviada | 10.000 |
| `AGENTE_PESSOAL_AI_MAX_RESPONSE_CHARS` | Limite da resposta recebida | 65.536 |

`Settings.from_environment()` não aceita configurar outro nome de variável de credencial. Para configurar a chave no Windows, use as configurações de variáveis de ambiente da conta ou da sessão de terminal; não a escreva no código, README, histórico do shell ou arquivos versionados. A aplicação não imprime a credencial.

### Teste manual de conexão

Os testes automatizados usam cliente simulado e nunca chamam a NVIDIA. Para um teste real, configure `NVIDIA_API_KEY` no ambiente e execute este trecho no ambiente Python do projeto:

```python
from agente_pessoal.ai import ModelRequest
from agente_pessoal.ai.nvidia import NvidiaNimProvider
from agente_pessoal.config import Settings

settings = Settings.from_environment()
provider = NvidiaNimProvider()
response = provider.generate(
    ModelRequest(
        prompt='Responda somente: NVIDIA NIM OK',
        model=settings.ai_model,
        credential_env_var=settings.ai_credential_env_var,
        timeout_seconds=settings.ai_timeout_seconds,
        max_output_chars=settings.ai_max_response_chars,
    )
)
print(response.content)
```

Esse teste envia um prompt à API e pode consumir cota. Não é executado pela suíte automatizada. O adaptador usa Chat Completions; a interface atual de `ModelRequest` transporta prompt textual, então suporte a imagem do modelo ainda não está exposto no contrato.

## Planejamento e segurança

`AIPlanner` envia a solicitação e o catálogo de ferramentas registradas ao provedor, valida uma resposta JSON estrita e só aceita etapas que referenciem ferramentas conhecidas. Respostas incompletas, campos extras, ferramentas não registradas e formatos inválidos são rejeitados. O modelo nunca determina nem concede permissões. O `ToolExecutor` consulta a política existente imediatamente antes de qualquer ferramenta; a política padrão nega operações sem autorização.

O adaptador configura o endpoint `https://integrate.api.nvidia.com/v1`, encaminha o modelo e o timeout configurados, valida o conteúdo e limita o tamanho da resposta. Timeout, indisponibilidade e rejeições HTTP são convertidos em erros tipados sem repassar mensagens potencialmente sensíveis. O `AIPlanner` é o único responsável por tentativas; o SDK é configurado com `max_retries=0` para evitar repetição duplicada.

O núcleo continua desacoplado: recebe qualquer implementação de `ModelProvider`, sem importar o cliente NVIDIA. Para conectar a NVIDIA ao planejador, injete `NvidiaNimProvider()` na construção de `AIPlanner`, mantendo o `ToolExecutor` e suas verificações de autorização.

## Persistência e auditoria

`SQLiteStore` mantém solicitações, tarefas, interpretação, etapas, resultados JSON, erros, transições de status, eventos de auditoria e permissões. O caminho padrão é `~/.agente_pessoal/agente_pessoal.sqlite3`, alterável por `AGENTE_PESSOAL_DB_PATH`. Eventos não incluem prompt, texto da solicitação, argumentos, resultados, mensagens de exceção ou credenciais. Os dados operacionais no SQLite não são criptografados e devem ser protegidos pelas permissões da conta do sistema operacional.

## Testes

```powershell
py -m unittest discover -s tests -t . -v
```

Os testes do adaptador usam um cliente controlado e não dependem de rede ou credenciais. `pytest` também está configurado no `pyproject.toml`, caso esteja instalado.

## Limitações e próxima etapa

- O planejador envia texto; a entrada de imagens/capturas de tela e as capacidades multimodais ainda não foram adicionadas ao contrato.
- Não existem ferramentas reais, execução de automação, navegação ou manipulação de arquivos.
- O adaptador normaliza falhas de conexão, timeout e status HTTP, mas a suíte não verifica credenciais ou disponibilidade real da conta NIM.
- A aprovação do usuário tem um contrato, sem interface gráfica ou ciclo de retomada de tarefas.
- O banco não tem criptografia, expurgo/retention ou migrações versionadas.

Próxima etapa recomendada: revisar o contrato de entrada multimodal e o desenho de aprovação humana antes de registrar ferramentas com efeitos reais. Depois, começar por uma ferramenta de baixo risco, com argumentos estritos, autorização explícita e testes de segurança.
