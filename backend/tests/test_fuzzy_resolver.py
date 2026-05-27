from app.agent.fuzzy_resolver import fuzzy_resolve_contact
from app.db.models import Contact
from app.db.session import SessionLocal


def _contact(
    db,
    *,
    contact_id: str,
    email: str,
    creator_name: str | None = None,
    business_name: str | None = None,
    notes: str | None = None,
    personalization: str | None = None,
    lead_category: str | None = None,
):
    contact = Contact(
        id=contact_id,
        email=email,
        creator_name=creator_name,
        business_name=business_name,
        notes=notes,
        personalization=personalization,
        lead_category=lead_category,
        source="manual",
        status="imported",
    )
    db.add(contact)
    db.commit()
    return contact


def test_fuzzy_exact_email(client):
    with SessionLocal() as db:
        _contact(db, contact_id="a" * 32, email="exact@test.com", creator_name="Exact Person")

        result = fuzzy_resolve_contact("exact@test.com", db)

    assert result.match
    assert result.match.email == "exact@test.com"
    assert result.confidence == 1.0
    assert result.method == "exact_email"


def test_fuzzy_partial_name(client):
    with SessionLocal() as db:
        _contact(db, contact_id="b" * 32, email="arjun@example.com", creator_name="Arjun Kumar")

        result = fuzzy_resolve_contact("arjun", db)

    assert result.match
    assert result.match.creator_name == "Arjun Kumar"


def test_fuzzy_niche_search(client):
    with SessionLocal() as db:
        _contact(
            db,
            contact_id="c" * 32,
            email="yoga@example.com",
            creator_name="Priya Yoga",
            lead_category="yoga instructor",
        )

        result = fuzzy_resolve_contact("yoga instructor", db)

    assert result.match
    assert result.match.lead_category == "yoga instructor"


def test_fuzzy_multi_match(client):
    with SessionLocal() as db:
        for index, name in enumerate(("Creator One", "Creator Two", "Creator Three"), 1):
            _contact(
                db,
                contact_id=f"{index}" * 32,
                email=f"creator-{index}@example.com",
                creator_name=name,
                notes="creator profile",
            )

        result = fuzzy_resolve_contact("creator", db)

    assert result.needs_clarification is True
    assert len(result.candidates) == 3
    assert "Which one did you mean?" in result.clarification_question


def test_fuzzy_zero_match(client):
    with SessionLocal() as db:
        result = fuzzy_resolve_contact("nobody", db)

    assert result.needs_clarification is True
    assert result.clarification_question


def test_fuzzy_stop_words_only(client):
    with SessionLocal() as db:
        result = fuzzy_resolve_contact("send to the guy", db)

    assert result.needs_clarification is True
    assert result.clarification_question


def test_fuzzy_no_ids_in_clarification(client):
    ids = ["d" * 32, "e" * 32, "f" * 32]
    with SessionLocal() as db:
        for index, contact_id in enumerate(ids, 1):
            _contact(
                db,
                contact_id=contact_id,
                email=f"coach-{index}@example.com",
                creator_name=f"Coach {index}",
                notes="creator",
            )

        result = fuzzy_resolve_contact("creator", db)

    assert result.needs_clarification is True
    for contact_id in ids:
        assert contact_id not in result.clarification_question

