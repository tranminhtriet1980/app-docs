"""Test xung đột địa chỉ giữa Application form và DS-260 worksheet."""

import json
import pytest

from app.models.entities import ApplicantDocRecord
from app.services.ds260_conflicts import build_worksheet_conflict_rows


class TestApplicationFormAddressConflict:
    """Xác minh conflict giữa application_form (Applicant's Information)
    và ds260_customer_form (worksheet khách khai) được phát hiện."""

    def test_address_conflict_application_vs_worksheet(self):
        """Application form cũng địa chỉ, worksheet khác → conflict."""
        app_form_data = {
            "current_address": "123 Main Street",
            "address_city": "Ho Chi Minh City",
            "address_state": "HCM",
            "postal_code": "70000",
            "address_country": "VIETNAM",
        }
        ds260_data = {
            "current_address": "456 Nguyen Hue Blvd",  # Khác
            "address_city": "Hanoi",  # Khác
            "address_state": "Ha Noi",
            "postal_code": "100000",  # Khác
            "address_country": "VIETNAM",
        }

        # Tạo 2 records: application_form (Luồng 1) + ds260_customer_form (worksheet)
        app_rec = ApplicantDocRecord(
            doc_type="application_form",
            variant="standard",
            form_data=json.dumps(app_form_data, ensure_ascii=False),
            raw_data="{}",
        )
        ds260_rec = ApplicantDocRecord(
            doc_type="ds260_customer_form",
            variant="exception",
            form_data=json.dumps(ds260_data, ensure_ascii=False),
            raw_data="{}",
        )

        records = [app_rec, ds260_rec]
        conflicts = build_worksheet_conflict_rows(records, {})

        # Kiểm tra conflict được tạo cho các field địa chỉ
        conflict_keys = {c["field_key"] for c in conflicts}
        assert "ds260.document_vs_worksheet.current_address" in conflict_keys, \
            f"Missing address conflict, got {conflict_keys}"
        assert "ds260.document_vs_worksheet.current_city" in conflict_keys
        assert "ds260.document_vs_worksheet.postal_code" in conflict_keys

    def test_address_match_no_conflict(self):
        """Application form và worksheet cùng địa chỉ → không conflict."""
        same_address = {
            "current_address": "123 Main Street",
            "address_city": "Ho Chi Minh City",
            "address_state": "HCM",
            "postal_code": "70000",
            "address_country": "VIETNAM",
        }

        app_rec = ApplicantDocRecord(
            doc_type="application_form",
            variant="standard",
            form_data=json.dumps(same_address, ensure_ascii=False),
            raw_data="{}",
        )
        ds260_rec = ApplicantDocRecord(
            doc_type="ds260_customer_form",
            variant="exception",
            form_data=json.dumps(same_address, ensure_ascii=False),
            raw_data="{}",
        )

        records = [app_rec, ds260_rec]
        conflicts = build_worksheet_conflict_rows(records, {})

        # Không nên có conflict khi giá trị giống nhau
        conflict_keys = {c["field_key"] for c in conflicts}
        assert len(conflicts) == 0, f"No conflicts should be created, but got {conflict_keys}"

    def test_worksheet_missing_application_form(self):
        """DS-260 worksheet thiếu application_form → không conflict (thiếu source)."""
        ds260_data = {
            "current_address": "456 Nguyen Hue Blvd",
            "address_city": "Hanoi",
        }

        # Chỉ có ds260_customer_form, không có application_form
        ds260_rec = ApplicantDocRecord(
            doc_type="ds260_customer_form",
            variant="exception",
            form_data=json.dumps(ds260_data, ensure_ascii=False),
            raw_data="{}",
        )

        records = [ds260_rec]
        conflicts = build_worksheet_conflict_rows(records, {})

        # Không tạo conflict vì thiếu nguồn chính thức (application_form)
        # — đây là tình huống trước fix, giờ không phát hiện ra thiếu
        assert len(conflicts) == 0, \
            "When application_form is missing, no worksheet conflict is created (expected)"

    def test_whitespace_normalization(self):
        """Whitespace khác nhau nhưng giá trị cốt lõi giống → không conflict."""
        app_data = {
            "current_address": "123  Main   Street",  # Multiple spaces
            "address_city": "  Ho Chi Minh City  ",  # Leading/trailing
        }
        ds260_data = {
            "current_address": "123 Main Street",  # Normalized
            "address_city": "HO CHI MINH CITY",  # Uppercase
        }

        app_rec = ApplicantDocRecord(
            doc_type="application_form",
            variant="standard",
            form_data=json.dumps(app_data, ensure_ascii=False),
            raw_data="{}",
        )
        ds260_rec = ApplicantDocRecord(
            doc_type="ds260_customer_form",
            variant="exception",
            form_data=json.dumps(ds260_data, ensure_ascii=False),
            raw_data="{}",
        )

        records = [app_rec, ds260_rec]
        conflicts = build_worksheet_conflict_rows(records, {})

        # Normalization (uppercase + trim whitespace) giúp bắt match chính xác
        assert len(conflicts) == 0, "Whitespace differences should be normalized"

    def test_resolved_conflict_not_recreated(self):
        """Conflict đã resolve không được tạo lại trong lần sync tiếp theo."""
        app_data = {
            "current_address": "123 Main Street",
            "address_city": "Ho Chi Minh City",
        }
        ds260_data = {
            "current_address": "456 Nguyen Hue Blvd",
            "address_city": "Hanoi",
        }

        app_rec = ApplicantDocRecord(
            doc_type="application_form",
            variant="standard",
            form_data=json.dumps(app_data, ensure_ascii=False),
            raw_data="{}",
        )
        ds260_rec = ApplicantDocRecord(
            doc_type="ds260_customer_form",
            variant="exception",
            form_data=json.dumps(ds260_data, ensure_ascii=False),
            raw_data="{}",
        )

        records = [app_rec, ds260_rec]
        # Giả sử user đã resolve: chọn giá trị từ application_form
        resolutions = {
            "ds260.document_vs_worksheet.current_address": "123 Main Street",
            "ds260.document_vs_worksheet.current_city": "Ho Chi Minh City",
        }

        conflicts = build_worksheet_conflict_rows(records, resolutions)

        # Conflict đã resolve không được tạo lại
        for c in conflicts:
            assert c["field_key"] not in resolutions, \
                f"Resolved conflict {c['field_key']} should not be recreated"
