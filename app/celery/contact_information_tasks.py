from flask import current_app

from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.dao import notifications_dao


@notify_celery.task(name="lookup-contact-info-tasks")
@statsd(namespace="tasks")
def lookup_contact_info(notification_id):
    current_app.logger.info("This task will look up contact information.")

    # get notification using id
    notification = notifications_dao.get_notification_by_id(notification_id)

    # read the identifier value aka va profile id
    # user va profile client to send the request to get the VAProfile
    # get the email form VAProfile
    # update (db) notification with the email address
    # place it on the email queue


@notify_celery.task(name="lookup-va-profile-id-tasks")
@statsd(namespace="tasks")
def lookup_va_profile_id(notification_id):
    current_app.logger.info("This task will look up VA Profile ID.")
