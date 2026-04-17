"""Rich-based display helpers for background task lists and results."""

from rich import print as rich_print
from rich.markdown import Markdown
from rich.table import Table

from alara.tasks.models import BackgroundTask, TaskStatus

_STATUS_STYLE: dict[TaskStatus, str] = {
    TaskStatus.PENDING: "yellow",
    TaskStatus.RUNNING: "blue",
    TaskStatus.DONE: "green",
    TaskStatus.FAILED: "red",
    TaskStatus.CANCELLED: "dim",
}


def render_task_list(tasks: list[BackgroundTask]) -> None:
    table = Table(title="Background Tasks")
    table.add_column("ID", style="bold", justify="right")
    table.add_column("Status")
    table.add_column("Description")
    table.add_column("Created")
    table.add_column("Completed")

    for task in tasks:
        style = _STATUS_STYLE.get(task.status, "")
        table.add_row(
            str(task.id),
            f"[{style}]{task.status.value}[/{style}]",
            task.description[:60],
            task.created_at.strftime("%Y-%m-%d %H:%M"),
            task.completed_at.strftime("%Y-%m-%d %H:%M") if task.completed_at else "—",
        )

    rich_print(table)


def render_task_result(task: BackgroundTask) -> None:
    if task.status == TaskStatus.DONE:
        rich_print(f"[bold]Task {task.id} — {task.status.value}[/bold]")
        rich_print(Markdown(task.result or ""))
    elif task.status == TaskStatus.FAILED:
        rich_print(f"[red]Task {task.id} — {task.status.value}:[/red] {task.error}")
    else:
        rich_print(f"Task {task.id} — {task.status.value}")
