from app.core.lang import DEFAULT_LANG, MESSAGES, SUPPORTED, t


def test_english_only():
    assert SUPPORTED == ("en",) and DEFAULT_LANG == "en"
    assert t("stage.searching").startswith("Searching")


def test_every_message_has_all_languages():
    for key, by_lang in MESSAGES.items():
        assert set(by_lang) == set(SUPPORTED), key
