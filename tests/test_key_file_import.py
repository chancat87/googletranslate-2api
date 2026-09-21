"""v2.8.0: 从本地文件批量加载上游 Key (每行一个, # 注释, 自动去重)。"""

from app.core import config as cfg
from app.providers.googletranslate_provider import GoogleTranslateProvider


def test_effective_keys_merges_env_and_file(monkeypatch, tmp_path):
    key_file = tmp_path / "keys.txt"
    key_file.write_text("k-file-1\n# comment\n  k-file-2  \n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", "k-env-1,k-file-1")
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS_FILE", str(key_file))
    provider = GoogleTranslateProvider()
    assert provider._effective_keys() == ["k-env-1", "k-file-1", "k-file-2"]


def test_effective_keys_file_only(monkeypatch, tmp_path):
    key_file = tmp_path / "keys.txt"
    key_file.write_text("k-only-1\nk-only-2\n", encoding="utf-8")
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS_FILE", str(key_file))
    provider = GoogleTranslateProvider()
    assert provider._effective_keys() == ["k-only-1", "k-only-2"]


def test_effective_keys_missing_file_falls_back_to_single_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", "legacy-key")
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS_FILE", str(tmp_path / "missing.txt"))
    provider = GoogleTranslateProvider()
    assert provider._effective_keys() == ["legacy-key"]


def test_effective_keys_unreadable_file_warns_and_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS", None)
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEY", "legacy-key")
    monkeypatch.setattr(cfg.settings, "GOOGLE_API_KEYS_FILE", str(tmp_path))
    provider = GoogleTranslateProvider()
    assert provider._effective_keys() == ["legacy-key"]
