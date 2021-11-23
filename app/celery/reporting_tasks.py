from datetime import datetime, timedelta
import io
import boto3
import csv

from flask import current_app
from celery import chain
from notifications_utils.statsd_decorators import statsd
from notifications_utils.timezones import convert_utc_to_local_timezone

from app import notify_celery
from app.config import QueueNames
from app.cronitor import cronitor
from app.dao.services_dao import (
    dao_fetch_service_by_id
)
from app.dao.fact_billing_dao import (
    fetch_billing_data_for_day,
    update_fact_billing
)
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_for_day,
    update_fact_notification_status,
    fetch_monthly_notification_statuses_per_service)
from app.dao.templates_dao import dao_get_template_by_id
from app.feature_flags import is_feature_enabled, FeatureFlag


@notify_celery.task(name="create-nightly-billing")
@cronitor("create-nightly-billing")
@statsd(namespace="tasks")
def create_nightly_billing(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # up to 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, "%Y-%m-%d").date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        create_nightly_billing_for_day.apply_async(
            kwargs={'process_day': process_day.isoformat()},
            queue=QueueNames.REPORTING
        )


@notify_celery.task(name="create-nightly-billing-for-day")
@statsd(namespace="tasks")
def create_nightly_billing_for_day(process_day):
    process_day = datetime.strptime(process_day, "%Y-%m-%d").date()

    start = datetime.utcnow()
    transit_data = fetch_billing_data_for_day(process_day=process_day)
    end = datetime.utcnow()

    current_app.logger.info('create-nightly-billing-for-day {} fetched in {} seconds'.format(
        process_day,
        (end - start).seconds)
    )

    for data in transit_data:
        update_fact_billing(data, process_day)

    current_app.logger.info(
        "create-nightly-billing-for-day task complete. {} rows updated for day: {}".format(
            len(transit_data),
            process_day
        )
    )


@notify_celery.task(name="create-nightly-notification-status")
@cronitor("create-nightly-notification-status")
@statsd(namespace="tasks")
def create_nightly_notification_status(day_start=None):
    # day_start is a datetime.date() object. e.g.
    # 4 days of data counting back from day_start is consolidated
    if day_start is None:
        day_start = convert_utc_to_local_timezone(datetime.utcnow()).date() - timedelta(days=1)
    else:
        # When calling the task its a string in the format of "YYYY-MM-DD"
        day_start = datetime.strptime(day_start, "%Y-%m-%d").date()
    for i in range(0, 4):
        process_day = day_start - timedelta(days=i)

        tasks = [create_nightly_notification_status_for_day.si(process_day.isoformat()).set(queue=QueueNames.REPORTING)]

        if is_feature_enabled(FeatureFlag.NIGHTLY_NOTIF_CSV_ENABLED):
            tasks.insert(
                1,
                generate_daily_notification_status_csv_report
                .si(process_day.isoformat())
                .set(queue=QueueNames.REPORTING)
            )
        chain(*tasks).apply_async()


@notify_celery.task(name="create-nightly-notification-status-for-day")
@statsd(namespace="tasks")
def create_nightly_notification_status_for_day(process_day):
    process_day = datetime.strptime(process_day, "%Y-%m-%d").date()

    start = datetime.utcnow()
    transit_data = fetch_notification_status_for_day(process_day=process_day)
    end = datetime.utcnow()
    current_app.logger.info('create-nightly-notification-status-for-day {} fetched in {} seconds'.format(
        process_day,
        (end - start).seconds)
    )

    update_fact_notification_status(transit_data, process_day)

    current_app.logger.info(
        "create-nightly-notification-status-for-day task complete: {} rows updated for day: {}".format(
            len(transit_data), process_day
        )
    )


@notify_celery.task(name="generate-daily-notification-status-csv-report")
@statsd(namespace="tasks")
def generate_daily_notification_status_csv_report(process_day):
    process_day = datetime.strptime(process_day, "%Y-%m-%d").date()
    transit_data = fetch_monthly_notification_statuses_per_service(process_day, process_day)
    buff = io.StringIO()

    writer = csv.writer(buff, dialect='excel', delimiter=',')
    writer.writerow(["date", "service name", "service id", "template name", "template id", "status", "count"])
    for row in transit_data:
        formatted_row = [process_day,
                         dao_fetch_service_by_id(row.service_id).name, row.service_id,
                         dao_get_template_by_id(row.template_id).name, row.template_id, row.status,
                         row.notification_count]
        writer.writerow(formatted_row)

    encoded_csv = io.BytesIO(buff.getvalue().encode())

    bucket = 'notifications-va-gov-daily-stats'
    csv_key = str(process_day).join(' .csv')

    client = boto3.client('s3')
    client.upload_fileobj(encoded_csv, bucket, csv_key)
