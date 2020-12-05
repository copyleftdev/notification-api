from flask import current_app
from notifications_utils.statsd_decorators import statsd

from app import notify_celery, va_profile_client
from app.celery.error_handling import handle_exceptions
from app.dao.notifications_dao import get_notification_by_id, dao_update_notification
from app.models import VA_PROFILE_ID
from app.va.va_profile import VAProfileRetryableException, VAProfileNonRetryableException


@notify_celery.task(bind=True, name="lookup-contact-info-tasks", max_retries=3, default_retry_delay=10)
@handle_exceptions(
    retry_on=[VAProfileRetryableException],
    fail_on=[VAProfileNonRetryableException]
)
@statsd(namespace="tasks")
def lookup_contact_info(self, notification_id):
    current_app.logger.info(f"Looking up contact information for notification_id:{notification_id}.")

    notification = get_notification_by_id(notification_id)

    va_profile_id = notification.recipient_identifiers[VA_PROFILE_ID].id_value

    email = va_profile_client.get_email(va_profile_id)

    notification.to = email
    dao_update_notification(notification)
