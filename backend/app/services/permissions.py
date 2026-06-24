from app.models.entities import Applicant, User, UserRole


def is_admin(user: User) -> bool:
    return user.role == UserRole.admin


def is_staff_or_admin(user: User) -> bool:
    return user.role in {UserRole.admin, UserRole.staff}


def can_create_applicant(user: User) -> bool:
    return user.is_active and user.can_create_applicants


def can_view_all_applicants(user: User) -> bool:
    return is_admin(user)


def can_manage_users(user: User) -> bool:
    return is_admin(user)


def can_access_applicant(user: User, applicant: Applicant) -> bool:
    if is_admin(user):
        return True
    return applicant.user_id == user.id


def can_edit_applicant_profile(user: User, applicant: Applicant) -> bool:
    """Manual profile / DS-260 overrides / conflict resolution."""
    if applicant.user_id == user.id:
        return True
    if is_admin(user):
        return True
    if is_staff_or_admin(user) and applicant.assigned_staff_id == user.id:
        return True
    return False


def can_delete_applicant(
    user: User, applicant: Applicant, *, force: bool = False, permanent: bool = False
) -> bool:
    if not can_access_applicant(user, applicant):
        return False
    if permanent:
        return is_admin(user) or applicant.user_id == user.id
    if is_admin(user):
        return True
    return applicant.user_id == user.id
