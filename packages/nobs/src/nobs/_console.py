"""Shared Rich console + small printing helpers.

Every nobs command (and any third-party that wants to feel native) should
import `console` from here so the look stays consistent.
"""
from __future__ import annotations

from rich.console import Console
from rich.theme import Theme

THEME = Theme(
    {
        "info": "cyan",
        "ok": "green",
        "warn": "yellow",
        "fail": "bold red",
        "muted": "dim",
        "label": "bold",
        "kbd": "reverse",
    }
)

console = Console(theme=THEME, highlight=False)


def step(message: str) -> None:
    console.print(f"[label]==>[/] {message}")


def ok(message: str) -> None:
    console.print(f"   [ok]✓[/] {message}")


def warn(message: str) -> None:
    console.print(f"   [warn]![/] {message}")


def fail(message: str) -> None:
    console.print(f"   [fail]✗[/] {message}")


def note(message: str) -> None:
    console.print(f"   [muted]{message}[/]")
