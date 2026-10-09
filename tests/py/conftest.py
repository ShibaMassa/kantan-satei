import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT))


@pytest.fixture
def raw_files():
    return json.loads((FIXTURES / "fixture_raw.json").read_text(encoding="utf-8"))


@pytest.fixture
def shared_cases():
    return json.loads((FIXTURES / "fixture_shared_cases.json").read_text(encoding="utf-8"))

