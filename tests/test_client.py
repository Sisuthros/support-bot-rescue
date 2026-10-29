import pytest

from agent.client import MetaAPIError, MetaClient


@pytest.fixture
def fake_openai(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    return captured


def test_api_key_argument_constructs_without_touching_filesystem(fake_openai, monkeypatch):
    def no_read(*args, **kwargs):
        raise AssertionError("key file must not be read")

    monkeypatch.setattr("pathlib.Path.read_text", no_read)
    monkeypatch.setenv("META_API_KEY_FILE", "does-not-exist.meta-key")
    client = MetaClient(api_key="x")
    assert client is not None
    assert fake_openai["api_key"] == "x"


def test_meta_api_key_env_is_used(fake_openai, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("META_API_KEY_FILE", raising=False)
    monkeypatch.setenv("META_API_KEY", "env-key")
    MetaClient()
    assert fake_openai["api_key"] == "env-key"


def test_meta_api_key_file_is_used(fake_openai, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("META_API_KEY", raising=False)
    key_file = tmp_path / "meta-key.txt"
    key_file.write_text("file-key\n", encoding="utf-8")
    monkeypatch.setenv("META_API_KEY_FILE", str(key_file))
    MetaClient()
    assert fake_openai["api_key"] == "file-key"


def test_missing_key_error_names_meta_api_key(fake_openai, monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.delenv("META_API_KEY_FILE", raising=False)
    with pytest.raises(MetaAPIError) as excinfo:
        MetaClient()
    message = str(excinfo.value)
    assert "META_API_KEY" in message
    assert "META_API_KEY_FILE" in message
    assert "~/.meta-model-api-key" in message

