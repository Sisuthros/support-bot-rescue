import copy, json
from pathlib import Path
import pytest
from compiler.dsl import PRIMITIVES, SpecError, json_schema, validate_spec

FIXTURE = Path(__file__).parent / "fixtures" / "maple.spec.json"
POLICY = Path(__file__).resolve().parent.parent / "maple" / "policy.md"

def good():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))

def test_accepts_known_good_spec_and_quotes_are_verbatim():
    spec = validate_spec(good(), policy_text=POLICY.read_text(encoding="utf-8"))
    assert [r.id for r in spec.rules] == ["C1", "C2", "C3", "C4", "C5", "C6"]
    assert {r.primitive for r in spec.rules} == set(PRIMITIVES)

def test_rejects_unknown_primitive():
    data = good(); data["rules"][0]["primitive"] = "free_form_llm_judgement"
    with pytest.raises(SpecError, match="unknown primitive"):
        validate_spec(data)

def test_rejects_missing_quote():
    data = good(); del data["rules"][1]["quote"]
    with pytest.raises(SpecError, match="quote"):
        validate_spec(data)

def test_rejects_quote_not_in_policy():
    data = good(); data["rules"][0]["quote"] = "Refunds are always allowed."
    with pytest.raises(SpecError, match="verbatim"):
        validate_spec(data, policy_text=POLICY.read_text(encoding="utf-8"))

def test_rejects_unknown_param_and_bad_type():
    data = good(); data["rules"][2]["params"]["surprise"] = 1
    with pytest.raises(SpecError):
        validate_spec(data)
    data = good(); data["rules"][2]["params"]["cap"] = "two hundred"
    with pytest.raises(SpecError):
        validate_spec(data)

def test_schema_is_closed_and_names_every_primitive():
    schema = json_schema()
    assert schema["additionalProperties"] is False
    text = json.dumps(schema)
    for name in PRIMITIVES:
        assert name in text
