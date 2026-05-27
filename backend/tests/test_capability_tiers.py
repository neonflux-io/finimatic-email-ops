from app.agent.catalog import check_capability_tiered


def test_capability_tiers_ambient():
    for channel in ("awareness", "task", "action"):
        result = check_capability_tiered("campaign_intelligence", channel)

        assert result.allowed is True
        assert result.tier == "AMBIENT"


def test_capability_tiers_action_read():
    result = check_capability_tiered("get_reply_list", "awareness")

    assert result.allowed is True


def test_capability_tiers_action_send():
    result = check_capability_tiered("email_send_draft", "task")

    assert result.allowed is False


def test_capability_tiers_unknown_task():
    result = check_capability_tiered("unknown_capability", "task")

    assert result.allowed is True
    assert result.redirect_to == "campaign_intelligence"


def test_capability_tiers_unknown_awareness():
    result = check_capability_tiered("unknown_capability", "awareness")

    assert result.allowed is True
    assert result.redirect_to == "campaign_intelligence"
