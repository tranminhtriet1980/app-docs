"""Test nhận diện JOB APPLICATION / Application form từ tên file."""

import pytest

from app.services.document_registry import parse_document_filename


class TestApplicationFormFilenameDetection:
    """Xác minh parse_document_filename bắt tất cả biến thể 'application form' / 'job application'."""

    def test_application_form_standard(self):
        """Mẫu chuẩn: 'Application form'."""
        doc_type, is_exc = parse_document_filename("Application form.pdf")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_application_form_standard_docx(self):
        """Mẫu chuẩn Word: 'Application form.docx'."""
        doc_type, is_exc = parse_document_filename("Application form.docx")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_application_form_exception_new(self):
        """Với hậu tố _new: 'Application form_new.pdf'."""
        doc_type, is_exc = parse_document_filename("Application form_new.pdf")
        assert doc_type == "application_form"
        assert is_exc is True

    def test_application_form_exception_new_docx(self):
        """Với hậu tố _new Word: 'Application form_new.docx'."""
        doc_type, is_exc = parse_document_filename("Application form_new.docx")
        assert doc_type == "application_form"
        assert is_exc is True

    def test_job_application_standard(self):
        """'JOB APPLICATION.docx' — không có "form", chỉ có "job application"."""
        doc_type, is_exc = parse_document_filename("JOB APPLICATION.docx")
        assert doc_type == "application_form", f"Expected 'application_form', got {doc_type}"
        assert is_exc is False

    def test_job_application_lowercase(self):
        """'job application.pdf' — phiên bản chữ thường."""
        doc_type, is_exc = parse_document_filename("job application.pdf")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_job_application_with_prefix(self):
        """'NGUYEN VAN A_7 JOB APPLICATION.docx' — tên người + số + JOB APPLICATION."""
        doc_type, is_exc = parse_document_filename("NGUYEN VAN A_7 JOB APPLICATION.docx")
        assert doc_type == "application_form", f"Expected 'application_form', got {doc_type}"
        assert is_exc is False

    def test_job_application_exception(self):
        """'Job_Application_new.doc' — exception variant."""
        doc_type, is_exc = parse_document_filename("Job_Application_new.doc")
        assert doc_type == "application_form"
        assert is_exc is True

    def test_immigrant_application(self):
        """'immigrant application.pdf' — dạng dài."""
        doc_type, is_exc = parse_document_filename("immigrant application.pdf")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_don_xin(self):
        """'don_xin.pdf' — Tiếng Việt 'đơn xin'."""
        doc_type, is_exc = parse_document_filename("don_xin.pdf")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_don_nop(self):
        """'don_nop.pdf' — Tiếng Việt 'đơn nộp'."""
        doc_type, is_exc = parse_document_filename("don_nop.pdf")
        assert doc_type == "application_form"
        assert is_exc is False

    def test_registry_token_application(self):
        """'application' token từ SUPPLEMENTAL registry quét đúng."""
        # Trước fix, token "application" từ application_form registry không bao giờ
        # được dùng vì parse_document_filename chỉ quét DOCUMENT_REGISTRY chuẩn.
        # Sau fix, SUPPLEMENTAL_DOCUMENT_REGISTRY cũng được quét.
        doc_type, is_exc = parse_document_filename("some_application.docx")
        assert doc_type == "application_form", "Token 'application' from SUPPLEMENTAL should match"
        assert is_exc is False

    def test_ds260_not_confused_with_application(self):
        """DS-260 không bị nhầm thành application_form dù có chữ 'form'."""
        doc_type, is_exc = parse_document_filename("DS260.pdf")
        assert doc_type == "ds260_customer_form"
        assert is_exc is False

    def test_employment_letter_not_confused(self):
        """employment_letter không phải application_form — cấu trúc khác."""
        # employment_letter chỉ xác nhận việc làm hiện tại, không có Applicant's Information.
        # Tôi không thêm detection riêng cho nó vào parse_document_filename,
        # nên nó sẽ do AI phân loại từ nội dung — test này chỉ xác minh không có conflict.
        doc_type, is_exc = parse_document_filename("Employment Letter.pdf")
        assert doc_type != "application_form", "Employment letter should not be detected as application_form"
