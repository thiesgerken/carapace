"""Example commands: one that talks to an API with a credential, one that stays local."""

import os
import sys

import httpx
from docopt import docopt

USAGE = """Usage:
  demo-usage <name>
  demo-usage --version
"""


def status() -> None:
    """Report whether the example API answers, authenticated with the declared credential."""
    response = httpx.get(
        "https://api.example.com/status",
        headers={"Authorization": f"Bearer {os.environ['DEMO_API_TOKEN']}"},
        timeout=10,
    )
    print(f"api.example.com answered {response.status_code}")


def usage() -> None:
    """Parse arguments locally; needs nothing from outside the sandbox."""
    args = docopt(USAGE, argv=sys.argv[1:], version="demo-usage 0.1.0")
    print(f"hello, {args['<name>']}")
