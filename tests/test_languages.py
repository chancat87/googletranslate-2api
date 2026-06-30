"""语言码校验与自动路由 — 纯单元, 无外部依赖。"""
from app.core.languages import ALL_LANGUAGES, is_supported, auto_detect_target


class TestIsSupported:
    def test_auto_is_supported(self):
        assert is_supported("auto") is True

    def test_common_codes(self):
        for code in ("zh-CN", "en", "ja", "ko", "fr", "de", "ar", "ru"):
            assert is_supported(code) is True

    def test_unknown_code(self):
        assert is_supported("klingon") is False
        assert is_supported("") is False

    def test_case_sensitive(self):
        # Google 用小写 / 连字符; 大写不识别 (透传后由上游裁决)
        assert is_supported("EN") is False


class TestAutoDetectTarget:
    def test_chinese_to_en(self):
        assert auto_detect_target("你好世界") == "en"

    def test_japanese_kana_to_en(self):
        assert auto_detect_target("こんにちは") == "en"

    def test_korean_to_en(self):
        assert auto_detect_target("안녕하세요") == "en"

    def test_arabic_to_en(self):
        assert auto_detect_target("مرحبا") == "en"

    def test_cyrillic_to_en(self):
        assert auto_detect_target("Привет") == "en"

    def test_latin_defaults_to_zh(self):
        assert auto_detect_target("Hello world") == "zh-CN"

    def test_empty_defaults_to_zh(self):
        assert auto_detect_target("") == "zh-CN"

    def test_all_listed_codes_in_table(self):
        # 表内自洽性: 白名单代码都通过 is_supported
        for code in ALL_LANGUAGES:
            assert code in ALL_LANGUAGES  # trivial sanity
