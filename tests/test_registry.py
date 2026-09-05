"""Tests for the `nobs workshops` listing.

Importing `nobs` registers every workshop plugin as an import side-effect,
so this is the check that a plugin is still wired into the CLI at all.
"""

from __future__ import annotations

import pytest
from nobs.lifecycle.commands import list_workshops

EXPECTED_SLUGS = ["autocon5", "packt"]


@pytest.mark.parametrize("slug", EXPECTED_SLUGS)
def test_workshops_lists_registered_plugin(slug: str, capsys: pytest.CaptureFixture[str]) -> None:
    list_workshops()
    out = " ".join(capsys.readouterr().out.split())
    # `<slug> -` is the tree's name node; a bare slug would also match the dir path line.
    assert f"{slug} -" in out
