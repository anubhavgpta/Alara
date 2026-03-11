"""ALARA setup flow - Rich-based first-time configuration."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.columns import Columns
from rich import box
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from alara.utils.paths import (
    get_config_path,
    get_profile_path,
    get_alara_dir
)

# Color palette
ALARA_PURPLE = "#9B59FF"
SUCCESS_GREEN = "#2ECC71"
ERROR_RED = "#E74C3C"
ACCENT_BLUE = "#3B9EFF"
DIM_WHITE = "dim white"

console = Console()


class AlaraSetup:
    """Main setup class for ALARA configuration."""
    
    def __init__(self) -> None:
        self.config = {}
        self.profile = {}
        
    def run(self) -> None:
        """Run the complete setup flow."""
        self._show_banner()
        time.sleep(1)
        
        console.print("Let's get you set up. This will take about 2 minutes.\n")
        
        self._section_about_you()
        self._section_use_cases()
        self._section_ai_model()
        self._section_integrations()
        self._section_permissions()
        self._section_environment()
        self._section_preferences()
        
        self._save_configuration()
        self._show_summary()
        
    def _show_banner(self) -> None:
        """Display the opening ALARA banner."""
        console.clear()
        banner = Panel(
            Text.from_markup(
                """\
    ░█████╗░██╗░░░░░░█████╗░██████╗░░█████╗░
    ██╔══██╗██║░░░░░██╔══██╗██╔══██╗██╔══██╗
    ███████║██║░░░░░███████║██████╔╝███████║
    ██╔══██║██║░░░░░██╔══██║██╔══██╗██╔══██║
    ██║░░██║███████╗██║░░██║██║░░██║██║░░██║
    ╚═╝░░╚═╝╚══════╝╚═╝░░╚═╝╚═╝░░╚═╝╚═╝░░╚═╝

       Ambient Language & Reasoning Assistant
       First-time setup""",
                style=f"bold {ALARA_PURPLE}"
            ),
            border_style=ALARA_PURPLE,
            padding=(1, 3)
        )
        console.print(banner)
        
    def _section_about_you(self) -> None:
        """Section 1: Collect user information."""
        console.rule(f"[bold {ALARA_PURPLE}]ABOUT YOU[/bold {ALARA_PURPLE}]")
        
        self.profile["name"] = Prompt.ask("Your name", console=console)
        
        preferred_name = Prompt.ask(
            "Preferred name",
            default=self.profile["name"],
            console=console
        )
        self.profile["preferred_name"] = preferred_name or self.profile["name"]
        
        # Auto-detect timezone
        import datetime as dt
        timezone_name = dt.datetime.now().astimezone().tzname()
        self.profile["timezone"] = Prompt.ask(
            "Timezone",
            default=timezone_name or "UTC",
            console=console
        )
        
        console.print()
        
    def _section_use_cases(self) -> None:
        """Section 2: Determine use cases."""
        console.rule(f"[bold {ALARA_PURPLE}]WHAT WILL YOU USE ALARA FOR?[/bold {ALARA_PURPLE}]")
        
        use_cases = [
            "Coding & development",
            "Research & writing", 
            "Creative writing",
            "Personal productivity",
            "Email & communications"
        ]
        
        console.print("Select use cases (e.g., 1,3,5 or 'all'):")
        for i, use_case in enumerate(use_cases, 1):
            console.print(f"  {i}. {use_case}")
        
        selection = Prompt.ask("Your selection", console=console)
        
        if selection.lower() == "all":
            selected_indices = list(range(len(use_cases)))
        else:
            try:
                selected_indices = [int(x.strip()) - 1 for x in selection.split(",")]
            except ValueError:
                selected_indices = [0]  # Default to first option
        
        self.profile["use_cases"] = [
            use_cases[i].lower().replace(" & ", "_").replace(" ", "_")
            for i in selected_indices if 0 <= i < len(use_cases)
        ]
        
        console.print()
        
    def _section_ai_model(self) -> None:
        """Section 3: AI model configuration."""
        console.rule(f"[bold {ALARA_PURPLE}]AI MODEL[/bold {ALARA_PURPLE}]")
        
        providers = [
            "Google Gemini (recommended)",
            "OpenAI",
            "Anthropic Claude"
        ]
        
        console.print("Which model provider?")
        for i, provider in enumerate(providers, 1):
            console.print(f"  {i}. {provider}")
        
        provider_choice = Prompt.ask(
            "Provider",
            choices=["1", "2", "3"],
            default="1",
            console=console
        )
        
        if provider_choice == "1":
            self.config["provider"] = "gemini"
            self._setup_gemini()
        elif provider_choice == "2":
            self.config["provider"] = "openai"
            self._setup_openai()
        else:
            self.config["provider"] = "anthropic"
            self._setup_anthropic()
            
        console.print()
        
    def _setup_gemini(self) -> None:
        """Setup Google Gemini model."""
        console.print("Enter your Google Gemini API key (input will be hidden):")
        api_key = Prompt.ask(
            "API key",
            console=console
        )
        
        models = ["gemini-2.5-flash", "gemini-2.5-pro"]
        console.print("Which Gemini model?")
        console.print("  1. gemini-2.5-flash (fast, recommended)")
        console.print("  2. gemini-2.5-pro (powerful, slower)")
        
        model_choice = Prompt.ask(
            "Model",
            choices=["1", "2"],
            default="1",
            console=console
        )
        
        model = models[int(model_choice) - 1]
        
        # Verify API key
        with console.status("[bold green]Verifying API key..."):
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                client.models.generate_content(
                    model=model,
                    contents="hi",
                    config=genai.types.GenerateContentConfig(
                        max_output_tokens=5
                    )
                )
                console.print(f"[{SUCCESS_GREEN}]✓ API key verified[/{SUCCESS_GREEN}]")
                self.config["api_key"] = api_key
                self.config["model"] = model
            except Exception as e:
                console.print(f"[{ERROR_RED}]✗ Invalid key: {e}[/{ERROR_RED}]")
                self._setup_gemini()  # Retry
                
    def _setup_openai(self) -> None:
        """Setup OpenAI model."""
        console.print("Enter your OpenAI API key (input will be hidden):")
        api_key = Prompt.ask(
            "API key",
            console=console
        )
        
        models = ["gpt-4o", "gpt-4o-mini"]
        console.print("Which OpenAI model?")
        console.print("  1. gpt-4o (recommended)")
        console.print("  2. gpt-4o-mini (faster, cheaper)")
        
        model_choice = Prompt.ask(
            "Model",
            choices=["1", "2"],
            default="1",
            console=console
        )
        
        model = models[int(model_choice) - 1]
        
        console.print("[dim]Note: API key verification skipped for OpenAI[/dim]")
        self.config["api_key"] = api_key
        self.config["model"] = model
        
    def _setup_anthropic(self) -> None:
        """Setup Anthropic Claude model."""
        console.print("Enter your Anthropic API key (input will be hidden):")
        api_key = Prompt.ask(
            "API key",
            console=console
        )
        
        models = ["claude-sonnet-4-5", "claude-opus-4-5"]
        console.print("Which Claude model?")
        console.print("  1. claude-sonnet-4-5 (recommended)")
        console.print("  2. claude-opus-4-5 (most powerful)")
        
        model_choice = Prompt.ask(
            "Model",
            choices=["1", "2"],
            default="1",
            console=console
        )
        
        model = models[int(model_choice) - 1]
        
        console.print("[dim]Note: API key verification skipped for Anthropic[/dim]")
        self.config["api_key"] = api_key
        self.config["model"] = model
        
    def _section_integrations(self) -> None:
        """Section 4: Third-party integrations."""
        console.rule(
            "[bold #9B59FF]INTEGRATIONS[/bold #9B59FF]"
        )
        console.print(
            "Composio connects Alara to Gmail, Slack, "
            "Calendar, Notion, and 250+ other apps.\n",
            style="dim white"
        )

        use_composio = Confirm.ask(
            "Connect Composio?"
        )

        if use_composio:

            ### STEP 1 — API Key
            console.print(
                "\n  Get your free API key at "
                "[bold]composio.dev[/bold]\n",
                style="dim"
            )
            composio_key = Prompt.ask(
                "  Composio API key"
            )

            ### STEP 2 — User ID
            console.print(
                "\n  Your Composio user ID is the email "
                "you use to identify yourself in Composio.\n"
                "  This is used to scope your connected "
                "accounts (e.g. anubhav@gmail.com)\n",
                style="dim"
            )
            composio_user_id = Prompt.ask(
                "  Your Composio user ID (email)"
            )

            ### STEP 3 — Validate API key
            with console.status(
                "[bold #9B59FF]Verifying Composio "
                "API key...[/bold #9B59FF]"
            ):
                try:
                    from composio import Composio
                    composio_client = Composio(
                        api_key=composio_key
                    )
                    # Verify by listing auth configs
                    composio_client.auth_configs.list()
                    console.print(
                        "  [bold #2ECC71]✓ Composio API "
                        "key verified.[/bold #2ECC71]"
                    )
                    valid_composio = True
                except Exception as e:
                    if composio_key and \
                       len(composio_key) > 15:
                        console.print(
                            "  [bold #2ECC71]✓ Composio "
                            "key saved.[/bold #2ECC71]"
                        )
                        valid_composio = True
                        composio_client = None
                    else:
                        console.print(
                            "  [bold #E74C3C]✗ Invalid "
                            f"key.[/bold #E74C3C]"
                        )
                        composio_key = None
                        composio_user_id = None
                        valid_composio = False

            ### STEP 4 — Check Gmail connection
            if valid_composio and composio_client:

                gmail_connected = False

                with console.status(
                    "[bold #9B59FF]Checking Gmail "
                    "connection...[/bold #9B59FF]"
                ):
                    try:
                        accounts = \
                            composio_client\
                            .connected_accounts.list()
                        items = getattr(
                            accounts, 'items', []
                        )
                        for account in items:
                            toolkit = getattr(
                                account, 'toolkit', None
                            )
                            slug = getattr(
                                toolkit, 'slug', ''
                            ) if toolkit else ''
                            status = getattr(
                                account, 'status', ''
                            )
                            uid = getattr(
                                account, 'user_id',
                                getattr(
                                    account,
                                    'client_unique_user_id',
                                    ''
                                )
                            )
                            if slug == 'gmail' and \
                               status == 'ACTIVE' and \
                               uid == composio_user_id:
                                gmail_connected = True
                                break
                    except Exception:
                        gmail_connected = False

                if gmail_connected:
                    console.print(
                        "  [bold #2ECC71]✓ Gmail already "
                        "connected.[/bold #2ECC71]"
                    )

                else:
                    console.print(
                        "\n  [yellow]Gmail is not "
                        "connected for your user ID."
                        "[/yellow]"
                    )
                    console.print(
                        "  Alara will generate an "
                        "authorization URL for you.\n",
                        style="dim"
                    )

                    # Find Gmail auth config
                    auth_config_id = None
                    with console.status(
                        "[bold #9B59FF]Finding Gmail "
                        "auth config...[/bold #9B59FF]"
                    ):
                        try:
                            auth_configs = \
                                composio_client\
                                .auth_configs.list()
                            ac_items = getattr(
                                auth_configs, 'items', []
                            )
                            for ac in ac_items:
                                toolkit = getattr(
                                    ac, 'toolkit', None
                                )
                                slug = getattr(
                                    toolkit, 'slug', ''
                                ) if toolkit else ''
                                if slug == 'gmail':
                                    auth_config_id = \
                                        getattr(
                                            ac, 'id',
                                            None
                                        )
                                    break
                        except Exception as e:
                            console.print(
                                f"  [dim]Could not find "
                                f"auth config: {e}[/dim]"
                            )

                    if auth_config_id:
                        # Generate OAuth URL
                        with console.status(
                            "[bold #9B59FF]Generating "
                            "authorization URL..."
                            "[/bold #9B59FF]"
                        ):
                            try:
                                connection = \
                                    composio_client\
                                    .connected_accounts\
                                    .initiate(
                                        user_id=\
                                            composio_user_id,
                                        auth_config_id=\
                                            auth_config_id
                                    )
                                redirect_url = \
                                    connection.redirect_url
                            except Exception as e:
                                redirect_url = None
                                console.print(
                                    f"  [red]Could not "
                                    f"generate URL: "
                                    f"{e}[/red]"
                                )

                        if redirect_url:
                            console.print(
                                "\n  [bold]Open this URL "
                                "in your browser to "
                                "authorize Gmail:[/bold]"
                            )
                            console.print(
                                f"\n  [bold #3B9EFF]"
                                f"{redirect_url}"
                                f"[/bold #3B9EFF]\n"
                            )
                            Prompt.ask(
                                "  Press Enter after "
                                "you have authorized "
                                "Gmail in your browser"
                            )

                            # Verify connection
                            with console.status(
                                "[bold #9B59FF]Verifying "
                                "Gmail connection..."
                                "[/bold #9B59FF]"
                            ):
                                try:
                                    accounts = \
                                        composio_client\
                                        .connected_accounts\
                                        .list()
                                    items = getattr(
                                        accounts,
                                        'items', []
                                    )
                                    for account in items:
                                        toolkit = getattr(
                                            account,
                                            'toolkit', None
                                        )
                                        slug = getattr(
                                            toolkit,
                                            'slug', ''
                                        ) if toolkit \
                                            else ''
                                        status = getattr(
                                            account,
                                            'status', ''
                                        )
                                        if slug == \
                                             'gmail' and \
                                             status == \
                                             'ACTIVE':
                                            gmail_connected\
                                                = True
                                            break
                                except Exception:
                                    pass

                            if gmail_connected:
                                console.print(
                                    "  [bold #2ECC71]"
                                    "✓ Gmail connected "
                                    "successfully."
                                    "[/bold #2ECC71]"
                                )
                            else:
                                console.print(
                                    "  [yellow]Could not "
                                    "verify Gmail "
                                    "connection. You can "
                                    "retry later by "
                                    "running alara-setup."
                                    "[/yellow]"
                                )
                    else:
                        console.print(
                            "  [yellow]No Gmail auth "
                            "config found. Visit "
                            "composio.dev to set up "
                            "Gmail first.[/yellow]"
                        )

            ### STEP 5 — Service selection
            if valid_composio:
                console.print(
                    "\n  Which services are you using?",
                    style="bold white"
                )
                console.print(
                    "  Type numbers separated by "
                    "commas or 'all'\n",
                    style="dim"
                )
                services_list = [
                    "Gmail", "Slack",
                    "Microsoft Outlook",
                    "Google Calendar", "Notion",
                    "Trello", "Linear",
                    "WhatsApp", "Discord"
                ]
                for i, s in enumerate(
                    services_list, 1
                ):
                    console.print(f"  {i}. {s}")

                selection = Prompt.ask(
                    "\n  Services", default="1"
                )
                if selection.lower() == "all":
                    selected_services = [
                        s.lower().replace(" ", "_")
                        for s in services_list
                    ]
                else:
                    indices = [
                        int(x.strip()) - 1
                        for x in selection.split(",")
                        if x.strip().isdigit()
                    ]
                    selected_services = [
                        services_list[i]
                        .lower()
                        .replace(" ", "_")
                        for i in indices
                        if 0 <= i < len(services_list)
                    ]
            else:
                composio_key = None
                composio_user_id = None
                selected_services = []

        else:
            composio_key = None
            composio_user_id = None
            selected_services = []

        # Write to config
        self.config["composio_api_key"] = composio_key
        self.config["composio_user_id"] = composio_user_id
        self.config["composio_services"] = selected_services
        
    def _section_permissions(self) -> None:
        """Section 5: System permissions."""
        console.rule(f"[bold {ALARA_PURPLE}]SYSTEM PERMISSIONS[/bold {ALARA_PURPLE}]")
        
        console.print("Alara will request the following permissions.")
        console.print("Deselect anything you're not comfortable with.\n")
        
        permissions = {
            "filesystem": "File system access - Read and write files and folders",
            "terminal": "Terminal commands - Run shell commands and scripts", 
            "browser": "Browser automation - Control Chrome/Edge via Playwright",
            "system": "System automation - Access environment variables and processes"
        }
        
        console.print("Type numbers to deselect, or Enter to accept all:")
        for i, (key, desc) in enumerate(permissions.items(), 1):
            console.print(f"  [{i}] {desc}")
        
        selection = Prompt.ask("Deselect permissions", default="", console=console)
        
        # Start with all enabled
        self.config["permissions"] = {k: True for k in permissions.keys()}
        
        if selection:
            try:
                deselect_indices = [int(x.strip()) - 1 for x in selection.split(",")]
                keys = list(permissions.keys())
                for i in deselect_indices:
                    if 0 <= i < len(keys):
                        self.config["permissions"][keys[i]] = False
            except ValueError:
                pass  # Keep all enabled
                
        console.print()
        
    def _section_environment(self) -> None:
        """Section 6: Working environment."""
        console.rule(f"[bold {ALARA_PURPLE}]WORKING ENVIRONMENT[/bold {ALARA_PURPLE}]")
        
        # Auto-detect directories
        desktop = Path.home() / "Desktop"
        projects_default = str(desktop / "Projects") if desktop.exists() else str(Path.home())
        
        projects_dir = Prompt.ask(
            "Projects directory",
            default=projects_default,
            console=console
        )
        self.profile["projects_dir"] = projects_dir
        
        documents_default = str(Path.home() / "Documents")
        documents_dir = Prompt.ask(
            "Documents directory", 
            default=documents_default,
            console=console
        )
        self.profile["documents_dir"] = documents_dir
        
        editors = ["VS Code", "Cursor", "Other"]
        console.print("Preferred code editor?")
        for i, editor in enumerate(editors, 1):
            console.print(f"  {i}. {editor}")
        
        editor_choice = Prompt.ask(
            "Editor",
            choices=["1", "2", "3"],
            default="1",
            console=console
        )
        
        if editor_choice == "3":
            custom_editor = Prompt.ask("Editor name", console=console)
            self.profile["editor"] = custom_editor.lower()
        else:
            self.profile["editor"] = editors[int(editor_choice) - 1].lower().replace(" ", "")
            
        console.print()
        
    def _section_preferences(self) -> None:
        """Section 7: User preferences."""
        console.rule(f"[bold {ALARA_PURPLE}]PREFERENCES[/bold {ALARA_PURPLE}]")
        
        console.print("Output style:")
        console.print("  1. Concise — just the essentials")
        console.print("  2. Detailed — show steps and reasoning")
        
        style_choice = Prompt.ask(
            "Output style",
            choices=["1", "2"],
            default="2",
            console=console
        )
        
        self.config["output_style"] = "concise" if style_choice == "1" else "detailed"
        
        show_logs = Confirm.ask(
            "Show execution logs by default?",
            default=True,
            console=console
        )
        self.config["show_logs"] = show_logs
        
        console.print()
        
    def _save_configuration(self) -> None:
        """Save configuration and profile files."""
        # Add version and timestamps
        self.config["version"] = "0.3.0"
        self.config["browser_headless"] = True
        self.profile["created_at"] = datetime.now().isoformat()
        
        # Remove any zapier references if they exist
        self.config.pop("zapier_api_key", None)
        self.config.pop("zapier_services", None)
        
        # Ensure .alara directory exists
        get_alara_dir()
        
        # Save config
        with open(get_config_path(), "w") as f:
            json.dump(self.config, f, indent=2)
            
        # Save profile
        with open(get_profile_path(), "w") as f:
            json.dump(self.profile, f, indent=2)
            
    def _show_summary(self) -> None:
        """Display setup completion summary."""
        # Create summary table
        table = Table(
            title=f"[bold {ALARA_PURPLE}]ALARA IS READY[/bold {ALARA_PURPLE}]",
            box=box.ROUNDED,
            show_header=False,
            border_style=ALARA_PURPLE
        )
        
        table.add_column("Key", style=f"bold {ALARA_PURPLE}")
        table.add_column("Value")
        
        # Add user info
        table.add_row("Name", self.profile["name"])
        table.add_row("Model", f"{self.config['model']}")
        table.add_row("Provider", self.config["provider"].title())
        
        # Add use cases
        if self.profile.get("use_cases"):
            use_cases_text = ", ".join(uc.replace("_", " ").title() for uc in self.profile["use_cases"])
            table.add_row("Use cases", use_cases_text)
            
        # Add permissions
        enabled_perms = [k for k, v in self.config.get("permissions", {}).items() if v]
        perms_text = ", ".join(p.title() for p in enabled_perms)
        table.add_row("Permissions", perms_text)
        
        # Add Composio info
        if self.config.get("composio_api_key"):
            services = self.config.get("composio_services", [])
            services_text = ", ".join(s.replace("_", " ").title() for s in services) if services else "None selected"
            table.add_row("Composio", services_text)
            if self.config.get("composio_user_id"):
                table.add_row("User ID", self.config["composio_user_id"])
        else:
            table.add_row("Composio", "Not connected")
        
        table.add_row("", "")  # Spacer
        table.add_row("Data stored at", "~/.alara/")
        
        console.print(table)
        console.print(f"\nAll set, {self.profile['preferred_name']}. Run `[bold green]alara[/bold green]` to start.")


def run_setup() -> None:
    """Entry point for `alara-setup` CLI command."""
    try:
        setup = AlaraSetup()
        setup.run()
    except KeyboardInterrupt:
        console.print("\n[dim]Setup cancelled.[/dim]")
        sys.exit(0)


if __name__ == "__main__":
    run_setup()
