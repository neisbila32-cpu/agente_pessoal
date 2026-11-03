"""Janela Tkinter para navegação, contas, agentes e demonstração simulada."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Callable

from agente_pessoal.desktop.controller import DesktopController, DesktopPage
from agente_pessoal.desktop.services import (
    DesktopApplicationServices,
)
from agente_pessoal.integrations.adapters.codex import CodexAccountState, CodexLoginMethod


_PAGE_TITLES = {
    DesktopPage.HOME: "Painel inicial",
    DesktopPage.INTEGRATIONS: "Contas e integrações",
    DesktopPage.AGENTS: "Meus agentes",
    DesktopPage.MAESTRO: "Maestro e fluxos",
    DesktopPage.DIAGNOSTICS: "Diagnóstico e permissões",
}


class DesktopWindow(tk.Tk):
    """Apresentação Tk; operações potencialmente lentas são executadas em workers."""

    def __init__(self, controller: DesktopController | None = None) -> None:
        super().__init__()
        self.controller = controller or DesktopController(DesktopApplicationServices())
        self.title("Agente Pessoal")
        self.geometry("1120x740")
        self.minsize(900, 620)
        self.configure(bg="#f3f5f8")
        self._results: queue.Queue[tuple[Callable, bool, object]] = queue.Queue()
        self._polling = False
        self._active_workers = 0
        self._login_url: str | None = None
        self._login_code: str | None = None
        self._provider_rows = {}
        self._login_starting = False
        self._login_finishing = False
        self._demo_running = False
        self._login_method = tk.StringVar(value="Navegador")
        self._agent_provider = tk.StringVar(value="Sem vínculo")
        self._agent_id = tk.StringVar()
        self._agent_name = tk.StringVar()
        self._agent_description = tk.StringVar()
        self._agent_capabilities = tk.StringVar(value="texto")
        self._bind_provider = tk.StringVar(value="OpenAI Codex")
        self._demo_prompt = tk.StringVar(value="Planejar uma rotina de estudos semanal")
        self._setup_style()
        self._build_shell()
        self._show_page(DesktopPage.HOME)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("App.TFrame", background="#f3f5f8")
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Sidebar.TFrame", background="#17243a")
        style.configure("Sidebar.TLabel", background="#17243a", foreground="#e8eef8")
        style.configure("Title.TLabel", background="#f3f5f8", foreground="#16243a", font=("Segoe UI", 20, "bold"))
        style.configure("Subtitle.TLabel", background="#f3f5f8", foreground="#58677d", font=("Segoe UI", 10))
        style.configure("CardTitle.TLabel", background="#ffffff", foreground="#17243a", font=("Segoe UI", 12, "bold"))
        style.configure("CardText.TLabel", background="#ffffff", foreground="#536176", font=("Segoe UI", 10))
        style.configure("Nav.TButton", background="#17243a", foreground="#e8eef8", anchor="w", padding=(12, 10), borderwidth=0)
        style.map("Nav.TButton", background=[("active", "#263955"), ("pressed", "#263955")])
        style.configure("Treeview", rowheight=30, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(10, 7), font=("Segoe UI", 9))
        style.configure("Primary.TButton", background="#315fbd", foreground="#ffffff", padding=(12, 8))
        style.map("Primary.TButton", background=[("active", "#274f9f")])

    def _build_shell(self) -> None:
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        sidebar = ttk.Frame(self, style="Sidebar.TFrame", padding=(14, 20))
        sidebar.grid(row=0, column=0, sticky="ns")
        sidebar.configure(width=225)
        sidebar.grid_propagate(False)
        ttk.Label(sidebar, text="AGENTE PESSOAL", style="Sidebar.TLabel", font=("Segoe UI", 13, "bold")).pack(anchor="w", padx=8, pady=(4, 3))
        ttk.Label(sidebar, text="Ambiente local", style="Sidebar.TLabel", font=("Segoe UI", 9)).pack(anchor="w", padx=8, pady=(0, 22))
        for page in self.controller.PAGES:
            ttk.Button(
                sidebar,
                text=_PAGE_TITLES[page],
                style="Nav.TButton",
                command=lambda target=page: self._show_page(target),
            ).pack(fill="x", pady=2)
        ttk.Label(
            sidebar,
            text="EXECUÇÃO REAL DESATIVADA",
            style="Sidebar.TLabel",
            font=("Segoe UI", 8, "bold"),
        ).pack(side="bottom", anchor="w", padx=8, pady=8)

        main = ttk.Frame(self, style="App.TFrame", padding=(28, 22))
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)
        self._heading = ttk.Frame(main, style="App.TFrame")
        self._heading.grid(row=0, column=0, sticky="ew", pady=(0, 20))
        self._heading.columnconfigure(0, weight=1)
        self._title = ttk.Label(self._heading, text="", style="Title.TLabel")
        self._title.grid(row=0, column=0, sticky="w")
        self._subtitle = ttk.Label(self._heading, text="", style="Subtitle.TLabel")
        self._subtitle.grid(row=1, column=0, sticky="w", pady=(4, 0))
        self._content = ttk.Frame(main, style="App.TFrame")
        self._content.grid(row=1, column=0, sticky="nsew")
        self._content.columnconfigure(0, weight=1)
        self._content.rowconfigure(0, weight=1)

    def _show_page(self, page: DesktopPage) -> None:
        self.controller.navigate(page)
        self._title.configure(text=_PAGE_TITLES[page])
        self._subtitle.configure(text="Controles explícitos, estado local e permissões temporárias.")
        for child in self._content.winfo_children():
            child.destroy()
        renderer = {
            DesktopPage.HOME: self._render_home,
            DesktopPage.INTEGRATIONS: self._render_integrations,
            DesktopPage.AGENTS: self._render_agents,
            DesktopPage.MAESTRO: self._render_maestro,
            DesktopPage.DIAGNOSTICS: self._render_diagnostics,
        }[page]
        renderer()

    def _card(self, parent, title: str, text: str, *, row: int, column: int, columnspan: int = 1):
        card = ttk.Frame(parent, style="Card.TFrame", padding=18)
        card.grid(row=row, column=column, columnspan=columnspan, sticky="nsew", padx=7, pady=7)
        ttk.Label(card, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(card, text=text, style="CardText.TLabel", wraplength=290, justify="left").pack(anchor="w", pady=(8, 0))
        return card

    def _render_home(self) -> None:
        pane = ttk.Frame(self._content, style="App.TFrame")
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.columnconfigure(1, weight=1)
        pane.rowconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)
        self._card(pane, "Contas", "Codex e Gemini CLI aparecem como provedores separados. O estado só é atualizado quando você solicita o diagnóstico.", row=0, column=0)
        self._card(pane, "Agentes", "Cadastre definições em memória, altere seu estado e associe logicamente uma conexão. Vínculo não concede permissões.", row=0, column=1)
        self._card(pane, "Maestro", "A demonstração usa três executores simulados, sem contas, chamadas de rede, comandos ou arquivos.", row=1, column=0)
        self._card(pane, "Permissões", "Login Codex requer web.access confirmado por operação. Nenhuma autorização é gravada permanentemente pela interface.", row=1, column=1)

    def _render_integrations(self) -> None:
        pane = ttk.Frame(self._content, style="App.TFrame")
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        self._provider_tree = ttk.Treeview(
            pane,
            columns=("name", "install", "auth", "operation"),
            show="headings",
            height=4,
        )
        for column, title, width in (
            ("name", "Provedor", 180),
            ("install", "Instalação", 130),
            ("auth", "Autenticação", 190),
            ("operation", "Operação", 270),
        ):
            self._provider_tree.heading(column, text=title)
            self._provider_tree.column(column, width=width, anchor="w")
        self._provider_tree.grid(row=0, column=0, sticky="ew")
        self._provider_tree.bind("<<TreeviewSelect>>", self._provider_selected)
        self._provider_detail = tk.StringVar(value="O diagnóstico é local e só ocorre quando você seleciona Atualizar diagnóstico.")
        ttk.Label(pane, textvariable=self._provider_detail, style="CardText.TLabel", wraplength=760, justify="left").grid(row=1, column=0, sticky="ew", pady=(10, 14))
        controls = ttk.LabelFrame(pane, text="Login oficial Codex", padding=12)
        controls.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(2, weight=1)
        ttk.Label(controls, text="Método").grid(row=0, column=0, sticky="w")
        ttk.Combobox(controls, textvariable=self._login_method, values=("Navegador", "Código de dispositivo"), state="readonly", width=24).grid(row=0, column=1, padx=8, sticky="w")
        ttk.Button(controls, text="Iniciar login…", style="Primary.TButton", command=self._start_login).grid(row=0, column=2, sticky="w")
        self._login_label = tk.StringVar(value="Nenhum login em andamento.")
        ttk.Label(controls, textvariable=self._login_label, wraplength=720, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(12, 5))
        self._login_actions = ttk.Frame(controls)
        self._login_actions.grid(row=2, column=0, columnspan=3, sticky="w")
        ttk.Button(self._login_actions, text="Abrir URL oficial", command=self._open_login_url).pack(side="left", padx=(0, 6))
        ttk.Button(self._login_actions, text="Concluí o login", command=self._finish_login).pack(side="left", padx=6)
        ttk.Button(self._login_actions, text="Cancelar", command=self._cancel_login).pack(side="left", padx=6)
        diagnostics_actions = ttk.Frame(pane, style="App.TFrame")
        diagnostics_actions.grid(row=3, column=0, sticky="ew")
        ttk.Button(diagnostics_actions, text="Verificar conta Codex…", command=self._verify_codex).pack(side="left")
        ttk.Button(diagnostics_actions, text="Atualizar diagnóstico local", command=self._refresh_integrations).pack(side="right")
        ttk.Label(pane, text="Gemini: no terminal, inicie `gemini` e conclua “Sign in with Google” na CLI oficial. A sessão fica não verificada aqui; nenhum prompt é enviado.", style="CardText.TLabel", wraplength=760).grid(row=4, column=0, sticky="w", pady=(12, 0))
        self._fill_provider_tree()

    def _fill_provider_tree(self, rows=None) -> None:
        if not hasattr(self, "_provider_tree") or not self._provider_tree.winfo_exists():
            return
        self._provider_tree.delete(*self._provider_tree.get_children())
        if rows is None:
            providers = self.controller.services.providers.list_providers()
            self._provider_rows = {
                provider.id: (
                    provider.name,
                    "Não verificada",
                    self.controller.codex_authentication if provider.id == "openai-codex" else "Não verificada",
                    "Não disponível — execução real desativada",
                    "Atualize o diagnóstico local para detectar dependências.",
                )
                for provider in providers
            }
        else:
            self._provider_rows = {
                row.provider_id: (row.name, row.installation, row.authentication, row.operation, row.guidance)
                for row in rows
            }
        for provider_id, row in self._provider_rows.items():
            self._provider_tree.insert(
                "",
                "end",
                iid=provider_id,
                values=row[:4],
            )

    def _provider_selected(self, _event=None) -> None:
        selection = self._provider_tree.selection()
        if not selection:
            return
        provider_id = selection[0]
        row = self._provider_rows.get(provider_id)
        if row is not None:
            self._provider_detail.set(row[4] or "Nenhuma ação recomendada.")

    def _refresh_integrations(self) -> None:
        self._run_async(
            self.controller.integration_statuses,
            self._fill_provider_tree,
            "Não foi possível atualizar o diagnóstico local.",
        )

    def _start_login(self) -> None:
        if self._login_starting or self.controller.codex_login_active:
            messagebox.showinfo("Login Codex", "Já existe um login Codex em andamento.", parent=self)
            return
        method = CodexLoginMethod.BROWSER if self._login_method.get() == "Navegador" else CodexLoginMethod.DEVICE_CODE
        confirmed = messagebox.askyesno(
            "Autorizar login Codex",
            "A interface iniciará o login oficial Codex e, quando você confirmar a conclusão, verificará a conta. "
            "Isso usa web.access somente durante este fluxo; nenhuma permissão será salva. Continuar?",
            parent=self,
        )
        if not confirmed:
            return
        self._login_starting = True
        self._login_label.set("Iniciando o fluxo oficial…")
        self._run_async(lambda: self.controller.start_codex_login(method, confirmed=True), self._login_started, "Não foi possível iniciar o login Codex. Verifique se as dependências estão disponíveis.", on_error=lambda: setattr(self, "_login_starting", False))

    def _login_started(self, result) -> None:
        self._login_starting = False
        self._login_url = result.verification_url
        self._login_code = result.user_code
        details = ["Login Codex aguardando confirmação do usuário."]
        if result.verification_url:
            details.append(f"URL: {result.verification_url}")
        if result.user_code:
            details.append(f"Código: {result.user_code}")
        self._login_label.set("\n".join(details))

    def _open_login_url(self) -> None:
        if not self._login_url:
            messagebox.showinfo("Login Codex", "Inicie o login para receber uma URL oficial.", parent=self)
            return
        url = self._login_url
        self._run_async(
            lambda: webbrowser.open(url, new=2, autoraise=True),
            lambda opened: None if opened else messagebox.showinfo("Login Codex", "Copie a URL exibida e abra-a no navegador.", parent=self),
            "Não foi possível abrir o navegador padrão. Copie a URL exibida.",
        )

    def _finish_login(self) -> None:
        if self._login_finishing:
            return
        if not self.controller.codex_login_active:
            messagebox.showinfo("Login Codex", "Não há login em andamento.", parent=self)
            return
        self._login_finishing = True
        self._login_label.set("Aguardando retorno do login e verificando a conta…")
        self._run_async(self.controller.finish_codex_login, self._login_finished, "Não foi possível concluir a verificação Codex.", on_error=lambda: setattr(self, "_login_finishing", False))

    def _login_finished(self, result) -> None:
        self._login_finishing = False
        if result.account_state is CodexAccountState.AUTHENTICATED:
            text = "Conta Codex autenticada e verificada."
        elif result.account_state is CodexAccountState.NOT_AUTHENTICATED:
            text = "Login concluído, mas a conta não foi confirmada."
        elif result.login.state.value == "cancelled":
            text = "Login cancelado."
        else:
            text = "Login encerrado; a conta não foi verificada."
        self._login_label.set(text)
        self._login_url = None
        self._login_code = None
        self._refresh_integrations()

    def _cancel_login(self) -> None:
        self._run_async(self.controller.cancel_codex_login, self._login_cancelled, "Não foi possível cancelar o login.")

    def _login_cancelled(self, _result) -> None:
        self._login_finishing = False
        self._login_starting = False
        self._login_url = None
        self._login_code = None
        self._login_label.set("Login cancelado.")
        self._refresh_integrations()

    def _verify_codex(self) -> None:
        confirmed = messagebox.askyesno(
            "Consultar conta Codex",
            "A consulta usará o SDK oficial para verificar a sessão Codex atual via web.access. "
            "A autorização vale apenas para esta consulta. Continuar?",
            parent=self,
        )
        if not confirmed:
            return
        self._run_async(
            lambda: self.controller.verify_codex_account(confirmed=True),
            lambda _state: self._refresh_integrations(),
            "Não foi possível consultar o estado da conta Codex.",
        )

    def _render_agents(self) -> None:
        pane = ttk.Frame(self._content, style="App.TFrame")
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(0, weight=1)
        tree = ttk.Treeview(pane, columns=("name", "description", "capabilities", "state", "binding"), show="headings", height=9)
        for column, title, width in (("name", "Agente", 170), ("description", "Função", 240), ("capabilities", "Capacidades", 170), ("state", "Estado", 110), ("binding", "Vínculo", 175)):
            tree.heading(column, text=title)
            tree.column(column, width=width, anchor="w")
        tree.grid(row=0, column=0, sticky="nsew")
        self._agent_tree = tree
        self._fill_agents_tree()
        actions = ttk.Frame(pane, style="App.TFrame")
        actions.grid(row=1, column=0, sticky="ew", pady=9)
        ttk.Button(actions, text="Habilitar selecionado", command=lambda: self._toggle_agent(True)).pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Desabilitar selecionado", command=lambda: self._toggle_agent(False)).pack(side="left")
        form = ttk.LabelFrame(pane, text="Cadastrar agente em memória", padding=12)
        form.grid(row=2, column=0, sticky="ew", pady=(5, 0))
        for col in range(4):
            form.columnconfigure(col, weight=1)
        fields = (("ID", self._agent_id), ("Nome", self._agent_name), ("Função/descrição", self._agent_description), ("Capacidades (separadas por vírgula)", self._agent_capabilities))
        for index, (label, variable) in enumerate(fields):
            ttk.Label(form, text=label).grid(row=0, column=index, sticky="w", padx=4)
            ttk.Entry(form, textvariable=variable).grid(row=1, column=index, sticky="ew", padx=4, pady=(3, 8))
        ttk.Label(form, text="Vincular provedor (opcional)").grid(row=2, column=0, sticky="w", padx=4)
        ttk.Combobox(form, textvariable=self._agent_provider, values=("Sem vínculo", "OpenAI Codex", "Google Gemini CLI"), state="readonly").grid(row=3, column=0, sticky="ew", padx=4, pady=(3, 8))
        ttk.Button(form, text="Cadastrar", style="Primary.TButton", command=self._add_agent).grid(row=3, column=1, sticky="w", padx=4)
        ttk.Label(form, text="Vínculo é apenas lógico; não adiciona executor nem permissão.", style="CardText.TLabel").grid(row=3, column=2, columnspan=2, sticky="w", padx=4)
        binding = ttk.Frame(pane, style="App.TFrame")
        binding.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(binding, text="Vincular agente selecionado a:").pack(side="left")
        ttk.Combobox(binding, textvariable=self._bind_provider, values=("OpenAI Codex", "Google Gemini CLI"), state="readonly", width=22).pack(side="left", padx=8)
        ttk.Button(binding, text="Criar vínculo", command=self._bind_selected).pack(side="left")

    def _fill_agents_tree(self) -> None:
        if not hasattr(self, "_agent_tree") or not self._agent_tree.winfo_exists():
            return
        self._agent_tree.delete(*self._agent_tree.get_children())
        connections = {item.id: item.provider_id for item in self.controller.services.list_connections()}
        for agent in self.controller.services.list_agents():
            links = self.controller.services.bindings_for(agent.id)
            provider_id = connections.get(links[-1].connection_id) if links else None
            binding = {"openai-codex": "Codex", "google-gemini-cli": "Gemini CLI"}.get(provider_id, "Sem vínculo")
            self._agent_tree.insert("", "end", iid=agent.id, values=(agent.name, agent.description, ", ".join(agent.capabilities), "Habilitado" if agent.enabled else "Desabilitado", binding))

    def _selected_agent_id(self) -> str | None:
        if not hasattr(self, "_agent_tree"):
            return None
        selected = self._agent_tree.selection()
        return selected[0] if selected else None

    def _toggle_agent(self, enabled: bool) -> None:
        agent_id = self._selected_agent_id()
        if not agent_id:
            messagebox.showinfo("Meus agentes", "Selecione um agente.", parent=self)
            return
        try:
            self.controller.set_agent_enabled(agent_id, enabled)
        except Exception:
            messagebox.showerror("Meus agentes", "Não foi possível alterar o estado do agente.", parent=self)
            return
        self._fill_agents_tree()

    def _add_agent(self) -> None:
        provider_id = {"OpenAI Codex": "openai-codex", "Google Gemini CLI": "google-gemini-cli"}.get(self._agent_provider.get())
        try:
            self.controller.add_agent(
                agent_id=self._agent_id.get(),
                name=self._agent_name.get(),
                description=self._agent_description.get(),
                capabilities_text=self._agent_capabilities.get(),
                provider_id=provider_id,
            )
        except (ValueError, TypeError) as exc:
            messagebox.showerror("Cadastro de agente", str(exc), parent=self)
            return
        except Exception:
            messagebox.showerror("Cadastro de agente", "Não foi possível cadastrar o agente.", parent=self)
            return
        self._agent_id.set("")
        self._agent_name.set("")
        self._agent_description.set("")
        self._fill_agents_tree()

    def _bind_selected(self) -> None:
        agent_id = self._selected_agent_id()
        provider_id = {"OpenAI Codex": "openai-codex", "Google Gemini CLI": "google-gemini-cli"}.get(self._bind_provider.get())
        if not agent_id or not provider_id:
            messagebox.showinfo("Vínculo", "Selecione um agente e um provedor.", parent=self)
            return
        try:
            self.controller.bind_agent(agent_id, provider_id)
        except Exception:
            messagebox.showerror("Vínculo", "Não foi possível criar o vínculo. Verifique se já existe.", parent=self)
            return
        self._fill_agents_tree()

    def _render_maestro(self) -> None:
        pane = ttk.Frame(self._content, style="App.TFrame")
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(2, weight=1)
        ttk.Label(pane, text="SIMULAÇÃO — executores locais determinísticos; nenhuma conta real é usada.", font=("Segoe UI", 11, "bold"), foreground="#8b4b00", background="#f3f5f8").grid(row=0, column=0, sticky="w", pady=(0, 12))
        bar = ttk.Frame(pane, style="App.TFrame")
        bar.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        bar.columnconfigure(0, weight=1)
        ttk.Entry(bar, textvariable=self._demo_prompt).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(bar, text="Iniciar demonstração…", style="Primary.TButton", command=self._run_demo).grid(row=0, column=1)
        self._demo_tree = ttk.Treeview(pane, columns=("agent", "dependencies", "state", "output"), show="headings", height=8)
        for column, title, width in (("agent", "Agente", 170), ("dependencies", "Dependências", 160), ("state", "Estado", 110), ("output", "Resultado simulado", 420)):
            self._demo_tree.heading(column, text=title)
            self._demo_tree.column(column, width=width, anchor="w")
        self._demo_tree.grid(row=2, column=0, sticky="nsew")
        self._demo_state = tk.StringVar(value="Aguardando ação explícita.")
        ttk.Label(pane, textvariable=self._demo_state, style="Subtitle.TLabel").grid(row=3, column=0, sticky="w", pady=(9, 0))

    def _run_demo(self) -> None:
        if self._demo_running:
            return
        confirmed = messagebox.askyesno(
            "Iniciar simulação",
            "Executar três etapas com respostas explicitamente simuladas? A autorização agent.execute será temporária e usada somente nesta demonstração.",
            parent=self,
        )
        if not confirmed:
            return
        self._demo_running = True
        self._demo_state.set("Demonstração em andamento…")
        prompt = self._demo_prompt.get()
        self._run_async(lambda: self.controller.run_demo(prompt, confirmed=True), self._demo_completed, "A demonstração não pôde ser concluída.", on_error=self._demo_failed)

    def _demo_completed(self, result) -> None:
        self._demo_running = False
        self._show_demo_result(result)

    def _demo_failed(self) -> None:
        self._demo_running = False
        self._demo_state.set("SIMULAÇÃO falhou; nenhuma execução real foi iniciada.")
        messagebox.showerror("Agente Pessoal", "A demonstração não pôde ser concluída.", parent=self)

    def _show_demo_result(self, result) -> None:
        if not hasattr(self, "_demo_tree") or not self._demo_tree.winfo_exists():
            self._demo_running = False
            return
        self._demo_tree.delete(*self._demo_tree.get_children())
        agents = {agent.id: agent.name for agent in self.controller.services.list_agents()}
        dependencies = {"demo-plan": "—", "demo-review": "demo-plan", "demo-synthesis": "demo-review"}
        for item in result.task_results:
            dependency = dependencies.get(item.task_id, "—")
            self._demo_tree.insert("", "end", values=(agents.get(item.agent_id, item.agent_id), dependency, item.status.value.upper(), item.output or item.error or ""))
        self._demo_state.set(f"SIMULAÇÃO encerrada: {result.status.value.upper()} — sem provedor real.")

    def _render_diagnostics(self) -> None:
        pane = ttk.Frame(self._content, style="App.TFrame")
        pane.grid(row=0, column=0, sticky="nsew")
        pane.columnconfigure(0, weight=1)
        pane.rowconfigure(1, weight=1)
        ttk.Label(pane, text="Permissões nesta interface", style="CardTitle.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        text = tk.Text(pane, wrap="word", height=12, relief="flat", padx=14, pady=12, font=("Segoe UI", 10), bg="#ffffff", fg="#29384d")
        text.grid(row=1, column=0, sticky="nsew")
        text.insert("1.0", "agent.execute: não concedida permanentemente; solicitada apenas para executar a demonstração local quando iniciada.\n\nweb.access: não concedida permanentemente; solicitada para iniciar login ou verificar conta Codex.\n\nCodex: verificação de conta usa o SDK oficial somente após confirmação explícita.\n\nGemini CLI: login deve ser feito manualmente na ferramenta oficial; autenticação permanece não verificada.\n\nExecutores de provedores: desativados. A associação de agente a provedor não concede permissões.\n\nDiagnóstico local: detecta instalação e disponibilidade sem chamadas de rede; execute manualmente em Contas e integrações.")
        text.configure(state="disabled")
        ttk.Button(pane, text="Abrir contas e integrações", command=lambda: self._show_page(DesktopPage.INTEGRATIONS)).grid(row=2, column=0, sticky="w", pady=(12, 0))

    def _run_async(self, operation: Callable, on_success: Callable, safe_error: str, *, on_error: Callable | None = None) -> None:
        def worker() -> None:
            try:
                value = operation()
            except (ValueError, PermissionError) as exc:
                message = str(exc)
                self._results.put((lambda _result, message=message: (messagebox.showerror("Agente Pessoal", message, parent=self), on_error() if on_error else None), False, None))
            except Exception:
                self._results.put((lambda _result: (messagebox.showerror("Agente Pessoal", safe_error, parent=self), on_error() if on_error else None), False, None))
            else:
                self._results.put((on_success, True, value))

        self._active_workers += 1
        threading.Thread(target=worker, name="desktop-operation", daemon=True).start()
        if not self._polling:
            self._polling = True
            self.after(60, self._poll_results)

    def _poll_results(self) -> None:
        while True:
            try:
                callback, succeeded, value = self._results.get_nowait()
            except queue.Empty:
                break
            self._active_workers -= 1
            if succeeded:
                callback(value)
            else:
                callback(value)
        if self._active_workers > 0 or not self._results.empty():
            self.after(60, self._poll_results)
        else:
            self._polling = False


def main() -> int:
    window = DesktopWindow()
    window.mainloop()
    return 0
