import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.guards.dosage import DosageKB  # noqa: E402
from app.guards.extraction import DrugLexicon  # noqa: E402
from app.guards.interactions import InteractionTable  # noqa: E402


@pytest.fixture(scope="session")
def lexicon() -> DrugLexicon:
    return DrugLexicon(settings.lexicon_path)


@pytest.fixture(scope="session")
def kb() -> DosageKB:
    return DosageKB(settings.dosage_kb_path)


@pytest.fixture(scope="session")
def interactions() -> InteractionTable:
    return InteractionTable(settings.ddinter_path)
