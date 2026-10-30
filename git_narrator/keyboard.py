"""Lightweight keyboard interaction utility for terminal navigation."""

import sys
import click


def get_single_key(prompt: str = "") -> str:
    """Reads a single keypress from standard input without requiring Enter.
    
    Returns standard ASCII key character, or special names for control keys.
    """
    if prompt:
        click.echo(prompt, nl=False)

    try:
        char = click.getchar(echo=False)
    except (KeyboardInterrupt, EOFError):
        return "q"

    # Handle Ctrl+C or Escape
    if char in ("\x03", "\x1b"):
        return "q"

    # Handle Enter
    if char in ("\r", "\n"):
        return "enter"

    return char.lower()
