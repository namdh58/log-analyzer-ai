from retrieval.masking import mask_log_entry, mask_text
from retrieval.models import LogEntry


def test_mask_text_synthetic_line():
    line = "user john@example.com paid with 4111111111111111 token=abcd1234efgh5678ijkl9012"
    masked = mask_text(line)
    assert masked == "user <EMAIL_MASKED> paid with <CARD_MASKED> <TOKEN_MASKED>"


def test_mask_log_entry_masks_message_and_raw():
    entry = LogEntry(
        timestamp=1,
        service="payment",
        level="info",
        message="charge for jane@example.com failed",
        raw="charge for jane@example.com failed, card 4242424242424242",
    )
    masked = mask_log_entry(entry)
    assert masked.message == "charge for <EMAIL_MASKED> failed"
    assert masked.raw == "charge for <EMAIL_MASKED> failed, card <CARD_MASKED>"


def test_non_sensitive_words_untouched():
    line = "order placed for product OLJCESPC7Z"
    assert mask_text(line) == line
