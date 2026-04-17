"""Bootstrap package for the personal agent evaluation toolkit."""

from personal_agent_eval._version import __version__
from personal_agent_eval.cli import build_parser, main

__all__ = ["__version__", "build_parser", "main"]
