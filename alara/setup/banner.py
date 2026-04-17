"""ASCII banner for Alara."""

from rich.console import Console

BANNER = r"""
      .o.       oooo
     .888.      `888
    .8"888.      888   .oooo.   oooo d8b  .oooo.
   .8' `888.     888  `P  )88b  `888""8P `P  )88b
  .88ooo8888.    888   .oP"888   888      .oP"888
 .8'     `888.   888  d8(  888   888     d8(  888
o88o     o8888o o888o `Y888""8o d888b    `Y888""8o
"""


def display_banner() -> None:
    """Print the Alara ASCII banner centered in bright cyan, followed by a blank line."""
    console = Console()
    lines = BANNER.splitlines()
    max_width = max((len(line) for line in lines if line), default=0)
    left_pad = " " * max(0, (console.width - max_width) // 2)
    padded = "\n".join(left_pad + line for line in lines)
    console.print(padded, style="bold bright_cyan")
    console.print()
