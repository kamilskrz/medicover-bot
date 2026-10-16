import sys
from pathlib import Path

import pytest

# Moduły aplikacji leżą w katalogu głównym repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def last_search_path(tmp_path, monkeypatch):
    """Testy nigdy nie piszą do prawdziwego last_search.json w katalogu projektu."""
    import last_search

    path = tmp_path / "last_search.json"
    monkeypatch.setattr(last_search, "PATH", path)
    return path
