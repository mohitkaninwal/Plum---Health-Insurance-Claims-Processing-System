import json
from pathlib import Path

import pytest

from app.services.policy_loader import PolicyLoadError, read_policy_terms


def test_read_policy_terms_rejects_coerced_scalar_types(tmp_path: Path) -> None:
    policy_path = Path(__file__).resolve().parents[2] / "policy_terms.json"
    raw = json.loads(policy_path.read_text(encoding="utf-8"))
    raw["policy_holder"]["employee_count"] = "500"
    temp_policy_path = tmp_path / "policy_terms.json"
    temp_policy_path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(PolicyLoadError):
        read_policy_terms(temp_policy_path)
