from app.agent.layman_formatter import format_for_layman


VALID_HEX_ID = "a" * 32


def test_formatter_removes_hex_id():
    result = format_for_layman(f"Contact {VALID_HEX_ID} replied")

    assert VALID_HEX_ID not in result
    assert "[contact]" in result


def test_formatter_replaces_with_name():
    contact_map = {VALID_HEX_ID: "Arjun Kumar (arjun@x.com)"}

    result = format_for_layman(f"Contact {VALID_HEX_ID} replied", contact_map)

    assert "Arjun Kumar" in result
    assert VALID_HEX_ID not in result


def test_formatter_iso_timestamp():
    result = format_for_layman("Replied at 2026-05-24T10:30:00Z")

    assert "2026-05-24T10:30:00Z" not in result
    assert "ago" in result or "yesterday" in result or "hours" in result


def test_formatter_status_codes():
    result = format_for_layman("Status: suppressed")

    assert "opted out" in result
    assert "suppressed" not in result


def test_formatter_removes_field_names():
    result = format_for_layman("contact_id: abc123\nThe email was sent.")

    assert "contact_id:" not in result
    assert "The email was sent." in result


def test_formatter_preserves_plain_text():
    plain = "Arjun replied to your email and seems interested."

    assert format_for_layman(plain) == plain


def test_formatter_no_standard_uuid():
    standard_uuid = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"

    result = format_for_layman(f"ID: {standard_uuid}")

    assert standard_uuid in result

