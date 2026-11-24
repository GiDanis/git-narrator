"""Lightweight keyboard interaction utility for terminal navigation."""

import click

_SPECIAL_KEYS = {
    "\x03": "q",
    "\x1b": "q",
    "\r": "enter",
    "\n": "enter",
    "\t": "tab",
    "\x1b[D": "left",
    "\x1bOD": "left",
    "\x1b[C": "right",
    "\x1bOC": "right",
    "\x1b[A": "up",
    "\x1bOA": "up",
    "\x1b[B": "down",
    "\x1bOB": "down",
}


def get_single_key(prompt: str = "") -> str:
    """Read a single keypress from stdin without requiring Enter."""
    if prompt:
        click.echo(prompt, nl=False)

    try:
        char = click.getchar(echo=False)
    except (KeyboardInterrupt, EOFError, OSError):
        return "q"

    if char in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[char]

    return char.lower()
