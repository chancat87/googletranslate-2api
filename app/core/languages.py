"""Google Translate 支持的语言码。

来源: https://cloud.google.com/translate/docs/languages
全部为 BCP-47 / ISO-639-1 风格码, 直接透传给上游。
未列入的代码不会在客户端报错 —— 交给上游校验, 上游不接受时返回 400。
"""

# 常用语言子集, 用于自动检测的快速路径与文档示例。
# 全量代码表见 ALL_LANGUAGES, 与 Google 官方同步。
ALL_LANGUAGES = frozenset({
    "auto", "af", "sq", "am", "ar", "hy", "az", "eu", "be", "bn", "bs", "bg",
    "ca", "ceb", "ny", "zh-CN", "zh-TW", "co", "hr", "cs", "da", "nl", "en",
    "eo", "et", "fi", "fr", "fy", "gl", "ka", "de", "el", "gu", "ht", "ha",
    "haw", "he", "hi", "hmn", "hu", "is", "ig", "id", "ga", "it", "ja", "jw",
    "kn", "kk", "km", "rw", "ko", "ku", "ky", "lo", "la", "lv", "lt", "lb",
    "mk", "mg", "ms", "ml", "mt", "mi", "mr", "mn", "my", "ne", "no", "or",
    "ps", "fa", "pl", "pt", "pa", "ro", "ru", "sm", "gd", "sr", "st", "sn",
    "sd", "si", "sk", "sl", "so", "es", "su", "sw", "sv", "tl", "tg", "ta",
    "tt", "te", "th", "tr", "tk", "uk", "ur", "ug", "uz", "vi", "cy", "xh",
    "yi", "yo", "zu",
})

# 自动检测目标语言时的提示文本片段 -> 目标语言码。
# 仅当用户未显式指定 target_lang 时使用。
AUTO_TARGET_HINTS = (
    (lambda c: "一" <= c <= "鿿", "en"),   # 含中文 -> 译为英文
    (lambda c: "぀" <= c <= "ヿ", "en"),   # 含日文假名 -> 英文
    (lambda c: "가" <= c <= "힯", "en"),   # 含韩文 -> 英文
    (lambda c: "؀" <= c <= "ۿ", "en"),   # 含阿拉伯文 -> 英文
    (lambda c: "Ѐ" <= c <= "ӿ", "en"),   # 含西里尔文 -> 英文
)


def is_supported(code: str) -> bool:
    """客户端是否识别该语言码。未列入会透传给上游。"""
    return code in ALL_LANGUAGES


def auto_detect_target(text: str) -> str:
    """根据文本字符自动判断目标语言 (默认 zh-CN)。"""
    if not text:
        return "zh-CN"
    for predicate, target in AUTO_TARGET_HINTS:
        if any(predicate(c) for c in text):
            return target
    return "zh-CN"
