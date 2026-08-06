"""Gộp N lần OCR độc lập (OCR_CONSENSUS_RUNS) theo đa số phiếu mỗi field.

Báo lỗi thực tế 2026-08-06: model đôi khi trả list/dict cho "value" của một field thay vì
string phẳng như prompt yêu cầu (vd. prior_jobs_history/other_occupation_detail của DS-260
worksheet có nhiều công việc cũ) — Counter(values) trong _merge_consensus_runs cần giá trị
hashable, list làm nó crash "unhashable type: 'list'", khiến cả document rơi vào trạng thái
lỗi (xem 01_6 DS260 - HO CONG BAO LONG.pdf).
"""

from app.services.ocr_pipeline import _merge_consensus_runs


def _meta(value, confidence=0.9, source_page=1):
    return {"value": value, "confidence": confidence, "source_page": source_page}


def test_majority_vote_agrees():
    results = [
        {"fields": {"primary_occupation": _meta("Manager")}},
        {"fields": {"primary_occupation": _meta("Manager")}},
        {"fields": {"primary_occupation": _meta("Manager")}},
    ]
    merged = _merge_consensus_runs(results)
    assert merged["fields"]["primary_occupation"]["value"] == "Manager"
    assert "warnings" not in merged or not merged["warnings"]


def test_majority_vote_with_disagreement_lowers_confidence_and_warns():
    results = [
        {"fields": {"employer_city": _meta("Ho Chi Minh")}},
        {"fields": {"employer_city": _meta("Ho Chi Minh")}},
        {"fields": {"employer_city": _meta("HCM")}},
    ]
    merged = _merge_consensus_runs(results)
    assert merged["fields"]["employer_city"]["value"] == "Ho Chi Minh"
    assert merged["fields"]["employer_city"]["confidence"] <= 0.4
    assert any("employer_city" in w for w in merged["warnings"])


def test_list_value_from_one_run_does_not_crash():
    """Run giữa trả list thay vì string cho 1 field — không được crash, phải coi list là 1
    giá trị khác biệt (không đồng thuận), không phải lỗi hệ thống."""
    results = [
        {
            "fields": {
                "other_occupation_detail": _meta(
                    "Ten cong ty: Xuan Vu garment. Tu 2009-2018"
                )
            }
        },
        {
            "fields": {
                "other_occupation_detail": _meta(
                    ["Ten cong ty: Xuan Vu garment", "Tu 2009-2018"]
                )
            }
        },
        {
            "fields": {
                "other_occupation_detail": _meta(
                    "Ten cong ty: Xuan Vu garment. Tu 2009-2018"
                )
            }
        },
    ]
    merged = _merge_consensus_runs(results)
    value = merged["fields"]["other_occupation_detail"]["value"]
    assert isinstance(value, str)
    assert value == "Ten cong ty: Xuan Vu garment. Tu 2009-2018"


def test_dict_value_from_one_run_does_not_crash():
    results = [
        {"fields": {"weird_field": _meta("A")}},
        {"fields": {"weird_field": _meta({"a": 1})}},
        {"fields": {"weird_field": _meta("A")}},
    ]
    merged = _merge_consensus_runs(results)
    value = merged["fields"]["weird_field"]["value"]
    assert isinstance(value, str)
    assert value == "A"


def test_all_three_runs_return_lists_still_produces_string_value():
    results = [
        {"fields": {"prior_jobs_history": _meta(["Job A", "Job B"])}},
        {"fields": {"prior_jobs_history": _meta(["Job A", "Job B"])}},
        {"fields": {"prior_jobs_history": _meta(["Job A", "Job C"])}},
    ]
    merged = _merge_consensus_runs(results)
    value = merged["fields"]["prior_jobs_history"]["value"]
    assert isinstance(value, str)
    assert value == "Job A; Job B"
