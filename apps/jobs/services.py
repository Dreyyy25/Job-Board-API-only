"""Service layer for the jobs app.

Business logic for applications. Views translate domain exceptions into
HTTP responses via the exception-to-HTTP map pinned in the Tier 2 spec.
"""
from .models import JobPost, JobPostActivity


class AlreadyAppliedError(Exception):
    """Raised when a user applies to a job they've already applied to."""


class InvalidApplicantError(Exception):
    """Raised when a non-seeker tries to apply, or user_account mismatches."""


class JobNotAvailableError(Exception):
    """Raised when the job is missing, unpublished, or inactive."""


class JobNotFoundError(Exception):
    """Raised by applications_for_job when the job id is unknown."""


class DashboardPermissionError(Exception):
    """Raised by applications_for_user when the requester isn't allowed."""


def apply_for_job(user, job_post_id, cover_letter='', user_account_id=None):
    """Create a JobPostActivity. Preserves the existing API contract strictly.

    user_account_id must be present in the request body AND match the
    authenticated user — matches the pre-Tier-2 view behaviour where
    omitting the field 403'd because str(None) != str(user.id).
    """
    if user.user_type != 'job_seeker':
        raise InvalidApplicantError('Only job seekers can apply for jobs')

    if user_account_id is None or str(user_account_id) != str(user.id):
        raise InvalidApplicantError(
            'You can only apply for jobs for yourself'
        )

    try:
        job = JobPost.objects.get(
            id=job_post_id, is_published=True, is_active=True,
        )
    except (JobPost.DoesNotExist, ValueError):
        # ValueError covers malformed UUIDs
        raise JobNotAvailableError()

    if JobPostActivity.objects.filter(
        user_account=user, job_post=job,
    ).exists():
        raise AlreadyAppliedError()

    return JobPostActivity.objects.create(
        user_account=user, job_post=job, cover_letter=cover_letter,
    )


def applications_for_job(requester, job_id):
    """Return applications for a job if the requester is admin or job's company owner."""
    try:
        job = JobPost.objects.select_related('company', 'company__user_account').get(id=job_id)
    except (JobPost.DoesNotExist, ValueError):
        raise JobNotFoundError()

    is_admin = requester.is_staff or requester.is_superuser
    is_owner = job.company.user_account_id == requester.id
    if not (is_admin or is_owner):
        raise DashboardPermissionError(
            'You do not have permission to view these applications'
        )

    return JobPostActivity.objects.with_related().filter(job_post_id=job_id)


def applications_for_user(requester, target_user_id):
    """Return applications by a user if the requester is admin or the user themselves."""
    is_admin = requester.is_staff or requester.is_superuser
    is_self = str(requester.id) == str(target_user_id)
    if not (is_admin or is_self):
        raise DashboardPermissionError(
            'You do not have permission to view these applications'
        )

    return JobPostActivity.objects.with_related().filter(user_account_id=target_user_id)
