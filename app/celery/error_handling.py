from celery.exceptions import MaxRetriesExceededError

from app.config import QueueNames
from app.dao.notifications_dao import update_notification_status_by_id
from app.exceptions import NotificationTechnicalFailureException
from app.models import NOTIFICATION_TECHNICAL_FAILURE


def handle_exceptions(retry_on, fail_on):
    def decorator(task_fn):
        def wrapper(task_self, notification_id):
            retry_on_exceptions = tuple(retry_on)
            fail_on_exceptions = tuple(fail_on) + (MaxRetriesExceededError,)

            try:
                try:
                    task_fn(task_self, notification_id)
                except retry_on_exceptions:
                    task_self.retry(queue=QueueNames.RETRY)

            except fail_on_exceptions as e:
                message = f"The task {task_self.name} failed for notification {notification_id}. " \
                          "Notification has been updated to technical-failure"
                update_notification_status_by_id(notification_id, NOTIFICATION_TECHNICAL_FAILURE)
                raise NotificationTechnicalFailureException(message) from e

        return wrapper

    return decorator
