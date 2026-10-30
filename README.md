# Agente Pessoal

Base de um agente para Windows, escrito principalmente em Python. O núcleo recebe solicitações, obtém um plano estruturado de um `Planner` injetado, verifica permissões e executa cada etapa somente por ferramentas registradas. Não há provedor de IA, integração com aplicativos, automação do Windows ou ferramenta real nesta etapa.

## Requisitos

- Python 3.11 ou superior.
- Nenhuma dependência de runtime externa.

## Estrutura

```text
src/agente_pessoal/
├── ai/                 # Contrato neutro de provedor de modelo
├── config/             # Configurações do aplicativo
├── core/
│   ├── agent.py        # Entrada Agent e TaskOrchestrator
│   ├── executor.py     # Resolução, autorização e chamada de ferramentas
│   ├── planning.py     # Plano, etapas planejadas e interface Planner
│   ├── request.py      # Solicitação recebida e validada
│   ├── task.py         # Tarefa, etapas, estados e resultados
│   └── task_manager.py # Ciclo de vida e histórico em memória
├── integrations/       # Espaço para integrações futuras reais
├── security/           # Contexto e política deny by default
└── tools/              # Contrato de ferramentas executáveis
tests/                  # Testes do núcleo, permissões e configurações
```

## Executar testes

```powershell
py -m unittest discover -s tests -t . -v
```

O `pyproject.toml` também configura a descoberta pelo `pytest`, caso ele já esteja instalado. Nenhuma dependência de teste foi adicionada.

## Fluxo de orquestração

1. `TaskOrchestrator.handle()` valida a solicitação e cria um `UserRequest`.
2. `TaskManager` registra a tarefa e pede ao `Planner` um `TaskPlan` com uma ou mais etapas explícitas.
3. Para cada etapa, `ToolExecutor` localiza a ferramenta e exige a permissão declarada por ela antes de chamar `execute()`.
4. O gerenciador registra status, horários, resultados ou erro. Após uma falha, interrompe o fluxo e marca as etapas seguintes como ignoradas.

O núcleo não interpreta linguagem natural. A implementação concreta de `Planner` deve ser fornecida pelo aplicativo chamador; os testes usam somente planejadores e ferramentas controlados. Autorizações são passadas por `AuthorizationContext` em memória. A política verifica a concessão recebida, mas ainda não implementa uma interface de consentimento ou gestão persistente de permissões.

## Limitações e evolução

- Tarefas e resultados ficam apenas em memória e são perdidos ao encerrar o processo.
- A execução é síncrona e sequencial; cancelamento, retomada, concorrência e timeout ainda não estão implementados.
- O contrato não oferece isolamento de processo para ferramentas. Ferramentas futuras precisarão de escopo mínimo, validação de argumentos e controles adicionais.
- Não há compreensão de linguagem natural, conectores de IA, navegação, manipulação de arquivos ou execução de comandos.

Próxima etapa recomendada: definir a persistência e a trilha de auditoria, além de um fluxo explícito de concessão/revogação de permissões, antes de adicionar ferramentas com efeitos reais.
