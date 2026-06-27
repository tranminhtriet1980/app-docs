"""Family bundle — pick passport by person name."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import pick_luong1_pair_for_person


def _rec(raw: dict, doc_type: str, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id="1",
    )


def test_norm_member_name_collapses_spaces():
    from app.services.family_case import _norm_member_name

    assert _norm_member_name("  dang   mai  phuong  thao ") == "DANG MAI PHUONG THAO"


def test_clear_child_adult_only_ds260_sections():
    from app.services.ds260_mapping import clear_child_adult_only_ds260_sections

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "current_marital_status", "value": "Divorced", "source": {"derived": "x"}},
                {"key": "applicant_name", "value": "DANG MAI PHUONG THAO", "source": {}},
            ],
        },
        {
            "id": "section_spouse",
            "fields": [
                {"key": "spouse_full_name", "value": "MAI THI HUONG", "source": {"derived": "x"}},
            ],
        },
        {
            "id": "section_previous_spouse",
            "fields": [
                {"key": "previous_spouse_full_name", "value": "EX SPOUSE", "source": {"derived": "x"}},
            ],
        },
        {
            "id": "section_divorce",
            "fields": [
                {"key": "divorce_date", "value": "2020-01-01", "source": {"derived": "x"}},
            ],
        },
        {
            "id": "section_children",
            "fields": [
                {"key": "child_1_full_name", "value": "SIBLING NAME", "source": {"derived": "x"}},
            ],
        },
    ]
    clear_child_adult_only_ds260_sections(sections)
    personal = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert personal["current_marital_status"] == ""
    assert personal["applicant_name"] == "DANG MAI PHUONG THAO"
    assert sections[1]["fields"][0]["value"] == ""
    assert sections[2]["fields"][0]["value"] == ""
    assert sections[3]["fields"][0]["value"] == ""
    assert sections[4]["fields"][0]["value"] == ""


def test_apply_child_sections_from_birth_cert_parents():
    import json
    from types import SimpleNamespace

    from app.services.family_case import apply_child_sections_from_birth_cert

    child_bc = SimpleNamespace(
        doc_type="birth_certificate_child",
        variant="standard",
        form_data=json.dumps(
            {
                "child_full_name": "DANG MAI PHUONG THAO",
                "father_name": "DANG VAN HUNG",
                "mother_name": "MAI NGOC HOA",
                "child_date_of_birth": "2010-05-01",
            }
        ),
        raw_data="{}",
        updated_at=None,
        id="child-bc-1",
    )
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_full_name", "value": "DANG THI TIEM", "source": {"document_type": "birth_certificate"}},
                {"key": "father_surname", "value": "DANG", "source": {}},
                {"key": "father_given_names", "value": "THI TIEM", "source": {}},
                {"key": "father_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_full_name", "value": "WRONG MOTHER", "source": {}},
                {"key": "mother_surname", "value": "", "source": {}},
                {"key": "mother_given_names", "value": "", "source": {}},
                {"key": "mother_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_birth_certificate",
            "fields": [
                {"key": "birth_cert_full_name", "value": "", "source": {}},
                {"key": "birth_cert_father_name", "value": "", "source": {}},
                {"key": "birth_cert_mother_name", "value": "", "source": {}},
            ],
        },
    ]
    apply_child_sections_from_birth_cert(sections, child_bc)
    father = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert father["father_full_name"] == "DANG VAN HUNG"
    assert father["father_surname"] == "DANG"
    assert father["father_given_names"] == "VAN HUNG"
    assert father["father_is_living"] == "Yes"
    mother = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert mother["mother_full_name"] == "MAI NGOC HOA"
    assert mother["mother_is_living"] == "Yes"
    bc = {f["key"]: f["value"] for f in sections[2]["fields"]}
    assert bc["birth_cert_full_name"] == "DANG MAI PHUONG THAO"
    assert bc["birth_cert_father_name"] == "DANG VAN HUNG"
    assert bc["birth_cert_mother_name"] == "MAI NGOC HOA"


def test_child_parents_fallback_from_case_members():
    """GKS con thiếu father_name/mother_name → lấy chủ hồ sơ + phối ngẫu."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import apply_child_sections_from_birth_cert

    child_bc = _rec(
        {
            "child_full_name": "HO BAO CHAU",
            "child_date_of_birth": "2015-03-10",
        },
        "birth_certificate_child",
    )
    child_bc.id = "child-bc"
    passport_father = _rec(
        {
            "full_name": "HO CONG BAO LONG",
            "date_of_birth": "1980-01-15",
            "place_of_birth": "HO CHI MINH",
        },
        "passport",
    )
    passport_father.id = "pp-father"
    passport_mother = _rec(
        {
            "full_name": "VAN THI HUONG",
            "date_of_birth": "1982-06-20",
            "place_of_birth": "HA NOI",
        },
        "passport",
    )
    passport_mother.id = "pp-mother"
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="HO CONG BAO LONG",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.spouse.value,
            display_name="VAN THI HUONG",
            sort_order=1,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="HO BAO CHAU",
            sort_order=2,
        ),
    ]
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_full_name", "value": "", "source": {}},
                {"key": "father_date_of_birth", "value": "", "source": {}},
                {"key": "father_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_full_name", "value": "", "source": {}},
                {"key": "mother_date_of_birth", "value": "", "source": {}},
                {"key": "mother_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_birth_certificate",
            "fields": [
                {"key": "birth_cert_father_name", "value": "", "source": {}},
                {"key": "birth_cert_mother_name", "value": "", "source": {}},
            ],
        },
    ]
    records = [child_bc, passport_father, passport_mother]
    apply_child_sections_from_birth_cert(
        sections, child_bc, records=records, members=members
    )
    father = {f["key"]: f["value"] for f in sections[0]["fields"]}
    mother = {f["key"]: f["value"] for f in sections[1]["fields"]}
    bc = {f["key"]: f["value"] for f in sections[2]["fields"]}

    assert father["father_full_name"] == "HO CONG BAO LONG"
    assert father["father_date_of_birth"] == "1980-01-15"
    assert father["father_is_living"] == "Yes"
    assert mother["mother_full_name"] == "VAN THI HUONG"
    assert mother["mother_date_of_birth"] == "1982-06-20"
    assert bc["birth_cert_father_name"] == "HO CONG BAO LONG"
    assert bc["birth_cert_mother_name"] == "VAN THI HUONG"


def test_pick_child_birth_cert_misclassified_adult_bc():
    from app.services.family_case import pick_child_birth_cert_for_person

    child_bc = _rec(
        {"full_name": "HO BAO CHAU", "child_full_name": "HO BAO CHAU"},
        "birth_certificate",
    )
    picked = pick_child_birth_cert_for_person([child_bc], "HO BAO CHAU")
    assert picked is child_bc


def test_enrich_child_parent_details_from_case_passport_and_divorce():
    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import (
        apply_child_sections_from_birth_cert,
        enrich_child_parent_details_from_case,
    )

    child_bc = _rec(
        {
            "child_full_name": "DANG MAI PHUONG THAO",
            "father_name": "DANG VAN HUNG",
            "mother_name": "MAI NGOC HOA",
        },
        "birth_certificate_child",
    )
    child_bc.id = "child-bc"
    passport = _rec(
        {
            "full_name": "DANG VAN HUNG",
            "date_of_birth": "1975-05-05",
            "place_of_birth": "DA NANG",
            "nationality": "VIETNAMESE",
        },
        "passport",
    )
    passport.id = "pp-hung"
    divorce = _rec(
        {
            "husband_full_name": "DANG VAN HUNG",
            "wife_full_name": "MAI NGOC HOA",
            "wife_date_of_birth": "1979-01-01",
        },
        "divorce",
    )
    divorce.id = "div-1"
    records = [child_bc, passport, divorce]
    members = [
        CaseMember(
            applicant_id="a",
            role=PersonRole.principal.value,
            display_name="DANG VAN HUNG",
            sort_order=0,
        ),
        CaseMember(
            applicant_id="a",
            role=PersonRole.child.value,
            display_name="DANG MAI PHUONG THAO",
            sort_order=1,
        ),
    ]

    father_fields = [
        {"key": "father_full_name", "value": "DANG VAN HUNG", "source": {}},
        {"key": "father_date_of_birth", "value": "", "source": {}},
        {"key": "father_birth_city", "value": "", "source": {}},
        {"key": "father_birth_state", "value": "", "source": {}},
        {"key": "father_birth_country", "value": "", "source": {}},
    ]
    enrich_child_parent_details_from_case(
        father_fields, "father", "DANG VAN HUNG", records, members
    )
    father = {f["key"]: f["value"] for f in father_fields}
    assert father["father_date_of_birth"] == "1975-05-05"
    assert father["father_birth_city"] == "DA NANG"
    assert father["father_birth_country"] == "Vietnam"

    mother_fields = [
        {"key": "mother_full_name", "value": "MAI NGOC HOA", "source": {}},
        {"key": "mother_date_of_birth", "value": "", "source": {}},
    ]
    enrich_child_parent_details_from_case(
        mother_fields, "mother", "MAI NGOC HOA", records, members
    )
    mother = {f["key"]: f["value"] for f in mother_fields}
    assert mother["mother_date_of_birth"] == "1979-01-01"

    sections = [
        {"id": "section_father", "fields": [{"key": "father_full_name", "value": "", "source": {}}]},
        {"id": "section_mother", "fields": [{"key": "mother_full_name", "value": "", "source": {}}]},
    ]
    apply_child_sections_from_birth_cert(
        sections, child_bc, records=records, members=members
    )
    father_sec = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert father_sec["father_full_name"] == "DANG VAN HUNG"


def test_grandchild_parents_from_child_branch_family_tree():
    """Cháu nội: cha là thành viên 'con', lấy DOB/nơi sinh từ hộ chiếu của con đó."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import apply_child_sections_from_birth_cert

    grandchild_bc = _rec(
        {
            "child_full_name": "DANG GIA BAO",
            "father_name": "DANG VAN HUNG",
            "mother_name": "TRAN THI LAN",
            "child_date_of_birth": "2018-09-09",
        },
        "birth_certificate_child",
    )
    grandchild_bc.id = "gc-bc"
    # Hộ chiếu của con (cha của cháu) — nhánh con trong cây gia phả.
    father_passport = _rec(
        {
            "full_name": "DANG VAN HUNG",
            "date_of_birth": "1990-02-02",
            "place_of_birth": "HO CHI MINH",
            "nationality": "VIETNAMESE",
        },
        "passport",
    )
    father_passport.id = "pp-hung"
    records = [grandchild_bc, father_passport]
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN TIEN",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG VAN HUNG",
            sort_order=1,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.grandchild.value,
            display_name="DANG GIA BAO",
            sort_order=2,
        ),
    ]
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_full_name", "value": "", "source": {}},
                {"key": "father_date_of_birth", "value": "", "source": {}},
                {"key": "father_birth_city", "value": "", "source": {}},
                {"key": "father_birth_country", "value": "", "source": {}},
                {"key": "father_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_full_name", "value": "", "source": {}},
                {"key": "mother_is_living", "value": "", "source": {}},
            ],
        },
    ]
    apply_child_sections_from_birth_cert(
        sections, grandchild_bc, records=records, members=members, role="grandchild"
    )
    father = {f["key"]: f["value"] for f in sections[0]["fields"]}
    mother = {f["key"]: f["value"] for f in sections[1]["fields"]}
    # Cha lấy từ GKS cháu, chi tiết bổ sung từ hộ chiếu của con (cây gia phả).
    assert father["father_full_name"] == "DANG VAN HUNG"
    assert father["father_date_of_birth"] == "1990-02-02"
    assert father["father_birth_city"] == "HO CHI MINH"
    assert father["father_birth_country"] == "Vietnam"
    assert father["father_is_living"] == "Yes"
    # Mẹ lấy từ GKS cháu (không thuộc hồ sơ, không khớp ai → chỉ có tên).
    assert mother["mother_full_name"] == "TRAN THI LAN"


def test_grandchild_no_principal_fallback_when_birth_cert_missing_parent():
    """Cháu không có tên cha trên GKS → KHÔNG fallback chủ hồ sơ (ông), để trống."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import _resolve_child_parent_name_for_fill

    grandchild_bc = _rec({"child_full_name": "DANG GIA BAO"}, "birth_certificate_child")
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN TIEN",
            sort_order=0,
        ),
    ]
    # Con: fallback chủ hồ sơ.
    assert (
        _resolve_child_parent_name_for_fill(grandchild_bc, "father", members, "child")
        == "DANG VAN TIEN"
    )
    # Cháu: không fallback.
    assert (
        _resolve_child_parent_name_for_fill(grandchild_bc, "father", members, "grandchild")
        == ""
    )


def test_member_number_map_grandchildren_after_children():
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import member_number_map

    def _m(role: str, order: int) -> CaseMember:
        return CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=role,
            display_name=f"{role}-{order}",
            sort_order=order,
        )

    principal = _m(PersonRole.principal.value, 0)
    spouse = _m(PersonRole.spouse.value, 1)
    child1 = _m(PersonRole.child.value, 2)
    child2 = _m(PersonRole.child.value, 3)
    gc1 = _m(PersonRole.grandchild.value, 4)
    gc2 = _m(PersonRole.grandchild.value, 5)
    numbers = member_number_map([principal, spouse, child1, child2, gc1, gc2])
    assert numbers[principal.id] == "01"
    assert numbers[spouse.id] == "02"
    assert numbers[child1.id] == "03"
    assert numbers[child2.id] == "04"
    assert numbers[gc1.id] == "05"
    assert numbers[gc2.id] == "06"


def test_grandchild_birth_cert_excluded_from_principal_children_section():
    """GKS của cháu không được liệt kê vào mục 'con' của chủ hồ sơ."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.ds260_mapping import enrich_children_section_from_birth_certs

    child_bc = _rec(
        {"child_full_name": "DANG VAN HUNG", "child_date_of_birth": "1990-02-02"},
        "birth_certificate_child",
    )
    child_bc.id = "child-bc"
    child_bc.source_document_id = None
    grandchild_bc = _rec(
        {"child_full_name": "DANG GIA BAO", "child_date_of_birth": "2018-09-09"},
        "birth_certificate_child",
    )
    grandchild_bc.id = "gc-bc"
    grandchild_bc.source_document_id = None
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG VAN HUNG",
            sort_order=1,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.grandchild.value,
            display_name="DANG GIA BAO",
            sort_order=2,
        ),
    ]
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(
        fields,
        [child_bc, grandchild_bc],
        all_records=[child_bc, grandchild_bc],
        case_members=members,
        applicant_name="DANG VAN TIEN",
    )
    out = {f["key"]: f["value"] for f in fields}
    names = {out.get("child_1_full_name"), out.get("child_2_full_name")}
    assert "DANG VAN HUNG" in names
    assert "DANG GIA BAO" not in names
    assert out["children_count"] == "1"


def test_sibling_parent_fallback_from_principal_birth_cert():
    """Anh/chị/em thiếu cha/mẹ trên GKS riêng → kế thừa cha/mẹ của đương đơn chính."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import apply_sibling_parent_fallback

    # GKS của đương đơn chính — ghi cha/mẹ (ông bà chung của hai anh em).
    principal_bc = _rec(
        {
            "full_name": "DANG VAN MINH",
            "father_name": "DANG VAN TIEN",
            "mother_name": "LE THI HOA",
            "father_date_of_birth": "1950-01-01",
        },
        "birth_certificate",
    )
    principal_bc.id = "principal-bc"
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN MINH",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.sibling.value,
            display_name="DANG VAN HUNG",
            sort_order=1,
        ),
    ]
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_full_name", "value": "", "source": {}},
                {"key": "father_surname", "value": "", "source": {}},
                {"key": "father_given_names", "value": "", "source": {}},
                {"key": "father_date_of_birth", "value": "", "source": {}},
                {"key": "father_is_living", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_full_name", "value": "", "source": {}},
                {"key": "mother_is_living", "value": "", "source": {}},
            ],
        },
    ]
    apply_sibling_parent_fallback(sections, [principal_bc], members, "DANG VAN HUNG")
    father = {f["key"]: f["value"] for f in sections[0]["fields"]}
    mother = {f["key"]: f["value"] for f in sections[1]["fields"]}
    assert father["father_full_name"] == "DANG VAN TIEN"
    assert father["father_surname"] == "DANG"
    assert father["father_is_living"] == "Yes"
    assert mother["mother_full_name"] == "LE THI HOA"


def test_sibling_parent_fallback_keeps_own_birth_cert_parents():
    """Anh/chị/em đã có cha/mẹ trên form (GKS riêng) → không bị đè bởi đương đơn chính."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import apply_sibling_parent_fallback

    principal_bc = _rec(
        {"full_name": "DANG VAN MINH", "father_name": "DANG VAN TIEN"},
        "birth_certificate",
    )
    principal_bc.id = "principal-bc"
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN MINH",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.sibling.value,
            display_name="DANG VAN HUNG",
            sort_order=1,
        ),
    ]
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_full_name", "value": "DANG VAN TIEN ALREADY", "source": {}},
            ],
        },
    ]
    apply_sibling_parent_fallback(sections, [principal_bc], members, "DANG VAN HUNG")
    assert sections[0]["fields"][0]["value"] == "DANG VAN TIEN ALREADY"


def test_member_number_map_siblings_after_grandchildren():
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import member_number_map

    def _m(role: str, order: int) -> CaseMember:
        return CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=role,
            display_name=f"{role}-{order}",
            sort_order=order,
        )

    principal = _m(PersonRole.principal.value, 0)
    child1 = _m(PersonRole.child.value, 1)
    gc1 = _m(PersonRole.grandchild.value, 2)
    sib1 = _m(PersonRole.sibling.value, 3)
    sib2 = _m(PersonRole.sibling.value, 4)
    numbers = member_number_map([principal, child1, gc1, sib1, sib2])
    assert numbers[principal.id] == "01"
    assert numbers[child1.id] == "03"
    assert numbers[gc1.id] == "04"
    assert numbers[sib1.id] == "05"
    assert numbers[sib2.id] == "06"


def test_siblings_children_scoped_by_parent_name():
    """Có nhánh anh/chị/em → con chỉ gán cho người là cha/mẹ trên GKS."""
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.ds260_mapping import enrich_children_section_from_birth_certs

    # Con của đương đơn chính.
    principal_child = _rec(
        {
            "child_full_name": "DANG GIA AN",
            "father_name": "DANG VAN MINH",
            "child_date_of_birth": "2012-01-01",
        },
        "birth_certificate_child",
    )
    principal_child.id = "pc-bc"
    principal_child.source_document_id = None
    # Con của anh/chị/em.
    sibling_child = _rec(
        {
            "child_full_name": "DANG GIA BAO",
            "father_name": "DANG VAN HUNG",
            "child_date_of_birth": "2015-01-01",
        },
        "birth_certificate_child",
    )
    sibling_child.id = "sc-bc"
    sibling_child.source_document_id = None
    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN MINH",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.sibling.value,
            display_name="DANG VAN HUNG",
            sort_order=1,
        ),
    ]
    records = [principal_child, sibling_child]

    def _fields():
        return [
            {"key": "children_used", "value": "", "source": {}},
            {"key": "children_count", "value": "", "source": {}},
            {"key": "child_1_full_name", "value": "", "source": {}},
            {"key": "child_2_full_name", "value": "", "source": {}},
        ]

    # Form đương đơn chính: chỉ thấy con của mình.
    principal_fields = _fields()
    enrich_children_section_from_birth_certs(
        principal_fields,
        records,
        all_records=records,
        case_members=members,
        applicant_name="DANG VAN MINH",
        member_role="principal",
    )
    p_out = {f["key"]: f["value"] for f in principal_fields}
    p_names = {p_out.get("child_1_full_name"), p_out.get("child_2_full_name")}
    assert "DANG GIA AN" in p_names
    assert "DANG GIA BAO" not in p_names

    # Form anh/chị/em: chỉ thấy con của họ.
    sibling_fields = _fields()
    enrich_children_section_from_birth_certs(
        sibling_fields,
        records,
        all_records=records,
        case_members=members,
        applicant_name="DANG VAN HUNG",
        member_role="sibling",
    )
    s_out = {f["key"]: f["value"] for f in sibling_fields}
    s_names = {s_out.get("child_1_full_name"), s_out.get("child_2_full_name")}
    assert "DANG GIA BAO" in s_names
    assert "DANG GIA AN" not in s_names


def test_format_member_number_and_filename_prefix():
    from app.services.family_case import (
        format_member_file_label,
        format_member_number,
        parse_member_file_prefix,
        parse_member_number_from_filename,
    )

    assert format_member_number(1) == "01"
    assert format_member_number(4) == "04"
    assert parse_member_number_from_filename("01 - Passport - DANG VAN HUNG.pdf") == 1
    assert parse_member_number_from_filename("03_Birth certificate child.pdf") == 3
    assert parse_member_number_from_filename("Passport.pdf") is None

    assert parse_member_file_prefix("01_1 BIRTH CERTIFICATE - DANG VAN HUNG.pdf") == (1, 1)
    assert parse_member_file_prefix("01_4 JUDICIAL CERTIFICATE - DANG VAN HUNG.pdf") == (1, 4)
    assert parse_member_file_prefix("05_2 PASSPORT - CHILD.pdf") == (5, 2)
    assert parse_member_file_prefix("01_2 - Birth certificate.pdf") == (1, 2)
    assert parse_member_file_prefix("02_1 - Passport wife.pdf") == (2, 1)
    assert parse_member_file_prefix("04_2_GKS con.pdf") == (4, 2)
    assert parse_member_file_prefix("01_01 - Passport.pdf") == (1, 1)
    assert parse_member_file_prefix("01 - Passport.pdf") == (1, None)
    assert format_member_file_label("01", 2) == "01_2"
    assert format_member_file_label("04", 1) == "04_1"
    assert format_member_file_label("02", None) == "02"


def test_member_number_map_role_based_without_spouse():
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import member_number_map

    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN HUNG",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG MAI PHUONG THAO",
            sort_order=1,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG KHOI NGUYEN",
            sort_order=2,
        ),
    ]
    nums = member_number_map(members)
    assert nums[members[0].id] == "01"
    assert nums[members[1].id] == "03"
    assert nums[members[2].id] == "04"


def test_resolve_document_member_label_infers_file_slot():
    import uuid

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import resolve_document_member_label

    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.principal.value,
            display_name="DANG VAN HUNG",
            sort_order=0,
        ),
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG MAI PHUONG THAO",
            sort_order=1,
        ),
    ]
    rec = _rec({"full_name": "DANG VAN HUNG"}, "passport")
    num, name, label = resolve_document_member_label(
        filename="PASSPORT - DANG VAN HUNG.pdf",
        registry_doc_type="passport",
        doc_record=rec,
        members=members,
    )
    assert num == "01"
    assert name == "DANG VAN HUNG"
    assert label == "01_2"

    child_rec = _rec({"child_full_name": "DANG MAI PHUONG THAO"}, "birth_certificate_child")
    num2, name2, label2 = resolve_document_member_label(
        filename="Birth certificate child - DANG MAI PHUONG THAO.pdf",
        registry_doc_type="birth_certificate_child",
        doc_record=child_rec,
        members=members,
    )
    assert num2 == "03"
    assert name2 == "DANG MAI PHUONG THAO"
    assert label2 == "03_1"


def test_resolve_document_member_labels_batch_extra_slots():
    import uuid
    from datetime import datetime, timedelta

    from app.models.entities import CaseMember, PersonRole
    from app.services.family_case import DocumentLabelInput, resolve_document_member_labels_batch

    members = [
        CaseMember(
            id=uuid.uuid4(),
            applicant_id=uuid.uuid4(),
            role=PersonRole.child.value,
            display_name="DANG MAI PHUONG THAO",
            sort_order=1,
        ),
    ]
    base = datetime(2025, 1, 1)
    docs = [
        DocumentLabelInput(
            document_id=uuid.uuid4(),
            filename="Birth certificate child - DANG MAI PHUONG THAO.pdf",
            registry_doc_type="birth_certificate_child",
            doc_record=_rec({"child_full_name": "DANG MAI PHUONG THAO"}, "birth_certificate_child"),
            uploaded_at=base,
        ),
        DocumentLabelInput(
            document_id=uuid.uuid4(),
            filename="Birth certificate child 2 - DANG MAI PHUONG THAO.pdf",
            registry_doc_type="birth_certificate_child",
            doc_record=_rec({"child_full_name": "DANG MAI PHUONG THAO"}, "birth_certificate_child"),
            uploaded_at=base + timedelta(minutes=1),
        ),
        DocumentLabelInput(
            document_id=uuid.uuid4(),
            filename="DS260 - DANG MAI PHUONG THAO_new.pdf",
            registry_doc_type="ds260_customer_form",
            doc_record=_rec({"full_name": "DANG MAI PHUONG THAO"}, "ds260_customer_form"),
            uploaded_at=base + timedelta(minutes=2),
        ),
    ]
    labels = resolve_document_member_labels_batch(items=docs, members=members)
    assert labels[docs[0].document_id][2] == "03_1"
    assert labels[docs[1].document_id][2] == "03_5"
    assert labels[docs[2].document_id][2] == "03_6"


def test_single_applicant_document_labels_without_case_members():
    import uuid
    from datetime import datetime, timedelta

    from app.models.entities import Applicant, PersonRole
    from app.services.family_case import DocumentLabelInput, members_for_document_labeling, resolve_document_member_labels_batch

    applicant = Applicant(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        display_name="DANG VAN HUNG",
    )
    members = members_for_document_labeling(applicant, [])
    assert len(members) == 1
    assert members[0].display_name == "DANG VAN HUNG"

    base = datetime(2025, 6, 1)
    docs = [
        ("BIRTH CERTIFICATE.pdf", "birth_certificate", 1),
        ("PASSPORT.pdf", "passport", 2),
        ("Divorce Decree.pdf", "divorce", 3),
        ("JUDICIAL CERTIFICATE.pdf", "judicial_certificate", 4),
        ("Marriage Certificate.pdf", "marriage_certificate", 5),
        ("DS-260 (khách khai).pdf", "ds260_customer_form", 6),
    ]
    inputs = [
        DocumentLabelInput(
            document_id=uuid.uuid4(),
            filename=name,
            registry_doc_type=doc_type,
            doc_record=None,
            uploaded_at=base + timedelta(minutes=i),
        )
        for i, (name, doc_type, _slot) in enumerate(docs)
    ]
    labels = resolve_document_member_labels_batch(items=inputs, members=members)
    assert labels[inputs[0].document_id][2] == "01_1"
    assert labels[inputs[1].document_id][2] == "01_2"
    assert labels[inputs[2].document_id][2] == "01_3"
    assert labels[inputs[3].document_id][2] == "01_4"
    assert labels[inputs[4].document_id][2] == "01_5"
    assert labels[inputs[5].document_id][2] == "01_6"


def test_pick_passport_no_fallback_when_name_unmatched():
    records = [
        _rec({"full_name": "DANG MAI PHUONG THAO"}, "passport", "standard"),
        _rec({"full_name": "DANG VAN HUNG"}, "passport", "standard"),
    ]
    std, ref = pick_luong1_pair_for_person(records, "passport", "DANG KHOI NGUYEN")
    assert std is None
    assert ref is None


def test_pick_passport_for_husband_in_family_upload():
    records = [
        _rec({"full_name": "DANG VAN HUNG"}, "passport", "standard"),
        _rec({"full_name": "MAI THI HUONG"}, "passport", "standard"),
    ]
    std, ref = pick_luong1_pair_for_person(records, "passport", "DANG VAN HUNG")
    assert std is records[0]
    std2, _ = pick_luong1_pair_for_person(records, "passport", "MAI THI HUONG")
    assert std2 is records[1]
