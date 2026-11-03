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
├── integrations/      # Catálogo de provedores e conexões de IA
├── multiagent/        # Registro de agentes e contratos de execução futura
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

## Arquitetura multiagente (fundação M1)

O pacote `agente_pessoal.multiagent` adiciona `AgentDefinition`, um catálogo `AgentRegistry` em memória e contratos tipados `AgentExecutionRequest`/`AgentExecutionResult`. O registro permite incluir, consultar, listar e habilitar ou desabilitar definições; IDs repetidos e referências inexistentes geram erros tipados. O `AgentExecutor` define a porta para um executor futuro e permanece separado do `ModelProvider` existente em `agente_pessoal.ai`, que representa provedores de modelos. A composição da aplicação pode manter ambos os contratos disponíveis ao lado de `TaskManager` e `TaskOrchestrator`; nenhum deles foi alterado.

Esta etapa não carrega adaptadores, chama modelos ou executa agentes. Não há armazenamento persistente de definições, interface gráfica, paralelismo ou novas permissões. A execução mediada pelo núcleo, aprovação humana e persistência do registro ficam para etapas futuras; a política de negação padrão e o esquema SQLite existente permanecem intactos.

## Provedores e conexões de IA (M4.1)

O pacote `agente_pessoal.integrations` mantém um catálogo em memória de provedores (`ProviderDefinition`/`ProviderRegistry`), registros de conexão (`ProviderConnection`), verificadores injetados e vínculos lógicos entre uma conexão e um `AgentDefinition`. Os papéis são separados: o provedor descreve o serviço e suas capacidades; a conexão representa o estado de uma conta; o agente continua no `AgentRegistry`; executores e o `MaestroCoordinator` continuam responsáveis pela execução e coordenação. Vincular uma conexão não concede permissões.

Os contratos reconhecem login oficial pelo navegador quando o provedor o declara, autenticação por CLI/SDK oficial, chave de API e modelo local sem autenticação remota. A lista é declarada por provedor; o sistema não presume disponibilidade de OAuth para terceiros. Não há login implementado, entrada de senha, captura de cookies, reutilização de tokens ou adaptadores reais. Os verificadores usados nos testes são simulados.

Cadastrar um provedor não significa que uma conta esteja conectada ou autenticada. Uma conexão registrada inicia como `connection_required` e `unverified`; o status informado e o resultado de verificação são campos distintos. Não existem campos de credencial nos modelos, nem armazenamento em SQLite ou arquivos. Uma referência opcional de conta deve ser opaca e não sensível. Os registros são voláteis e futuros segredos exigirão armazenamento seguro do sistema operacional.

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

## Integração oficial com Codex (M4.2)

O adaptador opcional `agente_pessoal.integrations.adapters.codex` usa o SDK Python oficial `openai-codex` (`>=0.163.0,<0.164.0`) para consultar a sessão Codex existente e iniciar login oficial pelo navegador ou código de dispositivo. O pacote é importado e o runtime criado somente quando uma operação é chamada; importar o módulo ou registrar `openai-codex` como provedor não inicia login, rede ou prompts. As operações requerem uma `AuthorizationContext` com `Permission.WEB_ACCESS`, sem concessões automáticas. O helper `register_codex_provider(ProviderRegistry())` registra a definição de provedor explicitamente; depois, `ConnectionRegistry`, `ConnectionVerifierRegistry` e `ConnectionService` podem verificar a conta usando `CodexConnectionVerifier`. A conexão só recebe status `connected` quando `Codex.account()` retorna uma conta. Falhas públicas não contêm mensagens brutas do SDK.

Para instalar, use o fluxo normal do projeto (`py -m pip install -e .`). Uma verificação manual de login, iniciada somente por decisão explícita do usuário, pode ser feita em uma sessão Python interativa:

```python
from agente_pessoal.integrations.adapters.codex import CodexAuthService, CodexLoginMethod
from agente_pessoal.security import AuthorizationContext, Permission

authorization = AuthorizationContext.from_permissions((Permission.WEB_ACCESS,))
codex = CodexAuthService()
login = codex.start_login(CodexLoginMethod.BROWSER, authorization)
print("Abra manualmente:", login.verification_url)
print("Resultado:", codex.finish_login(login.session_id, authorization).state)
print("Estado da conta:", codex.check_account(authorization).state)
```

Também é possível substituir `BROWSER` por `DEVICE_CODE`; nesse fluxo, exiba `verification_url` e `user_code` ao usuário. O teste manual não é executado automaticamente e está sujeito aos limites e permissões da conta ChatGPT. O adaptador reutiliza a sessão gerenciada pelo Codex e não lê arquivos internos de autenticação, solicita senha, persiste tokens ou copia credenciais ao SQLite.

Execução textual real via `AgentExecutor` fica desativada nesta etapa. Embora o SDK exponha execução em sandbox somente leitura, a API pública de alto nível não aceita um manipulador de aprovação; o cliente subjacente documenta aprovação automática de solicitações de execução de comandos/alteração de arquivos por padrão. Essa combinação não permite garantir o bloqueio de ferramentas e escalonamento exigidos pelo projeto. A autenticação e a verificação de conta podem ser testadas manualmente; o primeiro prompt supervisionado aguarda uma API pública que forneça controles de aprovação adequados. Não há chamadas reais ao Codex nos testes.

## Integração com Gemini CLI (M4.3)

`agente_pessoal.integrations.adapters.gemini_cli` registra explicitamente o provedor `google-gemini-cli`, detecta a presença do executável `gemini` no `PATH` sem executá-lo e oferece instruções para autenticação por meio da CLI oficial. Os métodos publicados pelo provedor refletem as opções documentadas: login Google gerenciado pela CLI, Gemini API key e Vertex AI/credenciais gerenciadas. Esta subetapa apenas orienta o login Google; não coleta chaves, configura Vertex AI ou gerencia qualquer credencial. Para instalação, consulte o [guia oficial de instalação](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/installation.mdx); o método global via npm é `npm install -g @google/gemini-cli` (requer Node.js 20 ou superior). Consulte também o [guia oficial de autenticação](https://github.com/google-gemini/gemini-cli/blob/main/docs/get-started/authentication.mdx). Depois, inicie `gemini` no terminal e escolha “Sign in with Google” no fluxo interativo. A conta Google precisa ser elegível segundo as políticas e licenças atuais do Gemini CLI; a página oficial do projeto informa que modalidades de acesso podem mudar. O Agente Pessoal não solicita sua senha.

O registro e a detecção local do executável não autenticam uma conta. A documentação do CLI descreve o login interativo e execução headless, mas não oferece um contrato confiável para consultar a sessão Google sem acessar credenciais locais ou iniciar uma chamada de modelo. Por isso, `GeminiConnectionVerifier` informa a disponibilidade da CLI separadamente e mantém a conexão como `connection_required`/`unverified`, mesmo quando o executável existe. A extensão opcional de `ConnectionVerificationResult.verification_status` permite declarar esse estado desconhecido sem alterar o comportamento dos verificadores anteriores.

Esta etapa não inicia subprocessos, não lê dados internos da Gemini CLI, não chama serviços externos e não executa prompts. Em particular, o modo headless aceita prompts e o CLI possui ferramentas que podem operar no ambiente local; integração de execução fica planejada até existir composição com caminho de executável confiável, argumentos fixos e validados, autorização explícita e aprovação que não permita alterações ou comandos automáticos. Não habilite modos de aprovação automática. O vínculo entre agente e conexão permanece apenas lógico e não concede permissões. As conexões Codex e Gemini usam identificadores de provedor distintos e não compartilham estado.

## Diagnóstico operacional (M4.4)

No Windows, com o projeto instalado no ambiente Python ativo, execute o relatório local no PowerShell:

```powershell
py -m agente_pessoal.integrations.diagnostics_cli
```

O relatório lista registro de provedores, versão/instalação do SDK Codex e seu runtime, presença da Gemini CLI no `PATH`, métodos de autenticação, autorização necessária, estado verificável e recursos ainda indisponíveis. `installed` significa apenas dependência encontrada; `authenticated` só é mostrado após consulta Codex autorizada; Gemini permanece `not_verified` porque a CLI não documenta uma consulta independente de sessão que possamos usar sem ler credenciais ou iniciar uma chamada de modelo. `operational` permanece `not_implemented` para ambos, pois esta etapa não integra executores de tarefas. Para automação de leitura do relatório, acrescente `--json`.

Por padrão o comando não consulta contas, inicia login, chama modelos, executa subprocessos nem grava configurações ou SQLite. A consulta de conta Codex é opcional e requer dois argumentos explícitos: `py -m agente_pessoal.integrations.diagnostics_cli --verify-codex-account --allow-web-access`. O segundo argumento autoriza `web.access` apenas durante aquela execução; a autorização não é persistida. Sem os dois argumentos, a conta não é consultada. O SDK pode reutilizar a sessão oficial Codex configurada pelo usuário; o diagnóstico não lê seus arquivos internos nem apresenta identidade ou credenciais. Para Gemini, faça login manualmente na CLI oficial; a mera instalação continua sem comprovar autenticação.

### Limites para futura execução de tarefas

O SDK Codex documenta sandbox `read_only`, mas sua API pública de alto nível não fornece um manipulador de aprovação; o cliente de baixo nível aceita aprovações automaticamente em certos caminhos por padrão. Por isso, não há execução por Codex nesta etapa. [Documentação do SDK Codex](https://github.com/openai/codex/tree/main/sdk/python) · [Referência da API](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md)

A Gemini CLI oferece prompts headless, ferramentas, modos de aprovação e sandbox. O modo `plan` é descrito como somente leitura, mas a documentação atual diz que esse modo ainda está em desenvolvimento; os modos `auto_edit` e `yolo` aprovam ações automaticamente. O Agente Pessoal não inicia esses modos nem os usa como integração de execução. Uma etapa futura precisa limitar ferramentas e caminhos, validar argumentos, manter aprovação explícita e usar isolamento confiável antes de encaminhar tarefas. [Opções oficiais da CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/cli/cli-reference.md) · [Configuração e aprovação](https://github.com/google-gemini/gemini-cli/blob/main/docs/reference/configuration.md)
