import uuid

from app.models.entities import Applicant, User, UserRole
from app.services.permissions import (
    can_access_applicant,
    can_delete_applicant,
    can_edit_applicant_profile,
    can_view_all_applicants,
)


def _user(role: UserRole) -> User:
    return User(id=uuid.uuid4(), email=f"{role.value}@test.local", role=role, is_active=True)


def _applicant(owner_id: uuid.UUID) -> Applicant:
    return Applicant(id=uuid.uuid4(), user_id=owner_id, display_name="Test")


def test_admin_can_view_all_and_access_any():
    admin = _user(UserRole.admin)
    owner = _user(UserRole.user)
    applicant = _applicant(owner.id)

    assert can_view_all_applicants(admin) is True
    assert can_access_applicant(admin, applicant) is True
    assert can_edit_applicant_profile(admin, applicant) is True


def test_user_only_accesses_own_applicant():
    owner = _user(UserRole.user)
    other = _user(UserRole.user)
    applicant = _applicant(owner.id)

    assert can_view_all_applicants(owner) is False
    assert can_access_applicant(owner, applicant) is True
    assert can_access_applicant(other, applicant) is False
    assert can_edit_applicant_profile(owner, applicant) is True
    assert can_edit_applicant_profile(other, applicant) is False


def test_staff_same_scope_as_user_not_admin():
    staff = _user(UserRole.staff)
    owner = _user(UserRole.user)
    applicant = _applicant(owner.id)

    assert can_view_all_applicants(staff) is False
    assert can_access_applicant(staff, applicant) is False


def test_delete_permissions():
    admin = _user(UserRole.admin)
    staff = _user(UserRole.staff)
    owner = _user(UserRole.user)
    other = _user(UserRole.user)
    own = _applicant(owner.id)
    foreign = _applicant(other.id)

    assert can_delete_applicant(admin, foreign) is True
    assert can_delete_applicant(staff, foreign) is False
    assert can_delete_applicant(owner, own) is True
    assert can_delete_applicant(owner, foreign) is False

    assert can_delete_applicant(admin, foreign, permanent=True) is True
    assert can_delete_applicant(owner, own, permanent=True) is True
    assert can_delete_applicant(owner, foreign, permanent=True) is False
    assert can_delete_applicant(staff, own, permanent=True) is False
