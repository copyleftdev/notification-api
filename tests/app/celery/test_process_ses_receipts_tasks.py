import json
import pytest
from datetime import datetime
from freezegun import freeze_time

from app import statsd_client
from app.celery import process_ses_receipts_tasks
from app.celery.research_mode_tasks import (
    ses_hard_bounce_callback,
    ses_soft_bounce_callback,
    ses_notification_callback
)
from app.celery.service_callback_tasks import create_delivery_status_callback_data
from app.dao.notifications_dao import get_notification_by_id
from app.models import Complaint, Notification, Service, Template
from app.model import User
from app.notifications.notifications_ses_callback import remove_emails_from_complaint, remove_emails_from_bounce

from tests.app.db import (
    create_notification,
    ses_complaint_callback,
    ses_smtp_complaint_callback,
    create_service_callback_api,
    ses_smtp_notification_callback,
    ses_smtp_hard_bounce_callback,
    ses_smtp_soft_bounce_callback
)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_400_with_invalid_header(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )
    assert response.status_code == 400


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_400_with_invalid_message_type(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'foo')]
    )
    assert response.status_code == 400
    assert "SES-SNS callback failed: invalid message type" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_400_with_invalid_json(client):
    data = "FOOO"
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )
    assert response.status_code == 400
    assert "SES-SNS callback failed: invalid JSON given" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_400_with_certificate(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )
    assert response.status_code == 400
    assert "SES-SNS callback failed: validation failed" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_200_autoconfirms_subscription(client, mocker):
    mocker.patch("validatesns.validate")
    requests_mock = mocker.patch("requests.get")
    data = json.dumps({"Type": "SubscriptionConfirmation", "SubscribeURL": "https://foo"})
    response = client.post(
        path='/notifications/email/ses',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'SubscriptionConfirmation')]
    )

    requests_mock.assert_called_once_with("https://foo")
    assert response.status_code == 200


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_200_call_process_task(client, mocker):
    mocker.patch("validatesns.validate")
    process_mock = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_results.apply_async")
    data = {"Type": "Notification", "foo": "bar"}
    json_data = json.dumps(data)
    response = client.post(
        path='/notifications/email/ses',
        data=json_data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )

    process_mock.assert_called_once_with([{'Message': None}], queue='notify-internal-tasks')
    assert response.status_code == 200


def test_process_ses_results(sample_email_template):
    create_notification(sample_email_template, reference='ref1', sent_at=datetime.utcnow(), status='sending')

    assert process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference='ref1'))


def test_process_ses_results_retry_called(sample_email_template, notify_db, mocker):
    create_notification(sample_email_template, reference='ref1', sent_at=datetime.utcnow(), status='sending')

    mocker.patch("app.dao.notifications_dao._update_notification_status", side_effect=Exception("EXPECTED"))
    mocked = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    process_ses_receipts_tasks.process_ses_results(response=ses_notification_callback(reference='ref1'))
    assert mocked.call_count != 0


def test_process_ses_results_call_to_publish_complaint(mocker, notify_api):
    publish_complaint = mocker.patch('app.celery.process_ses_receipts_tasks.publish_complaint')
    provider_message = ses_complaint_callback()

    complaint, notification, email = get_complaint_notification_and_email(mocker)

    mocker.patch(
        'app.celery.process_ses_receipts_tasks.handle_ses_complaint', return_value=(complaint, notification, email)
    )

    process_ses_receipts_tasks.process_ses_results(response=provider_message)

    publish_complaint.assert_called_once_with(
        complaint, notification, email
    )


def test_remove_emails_from_complaint():
    test_json = json.loads(ses_complaint_callback()['Message'])
    remove_emails_from_complaint(test_json)
    assert "recipient1@example.com" not in json.dumps(test_json)


def test_remove_email_from_bounce():
    test_json = json.loads(ses_hard_bounce_callback(reference='ref1')['Message'])
    remove_emails_from_bounce(test_json)
    assert "bounce@simulator.amazonses.com" not in json.dumps(test_json)


def test_ses_callback_should_call_send_delivery_status_to_service(
        client,
        sample_email_template,
        mocker,
        notify_db):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    notification = create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref',
    )

    callback_api = create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")
    callback_id = callback_api.id
    mocked_callback_api = mocker.Mock(
        url=callback_api.url,
        bearer_token=callback_api.bearer_token
    )
    process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref'))

    updated_notification = Notification.query.get(notification.id)

    encrypted_data = create_delivery_status_callback_data(updated_notification, mocked_callback_api)
    send_mock.assert_called_once_with([callback_id, str(notification.id), encrypted_data], queue="service-callbacks")


def test_ses_callback_should_send_statsd_statistics(
        client,
        notify_db_session,
        sample_email_template,
        mocker):
    with freeze_time('2001-01-01T12:00:00'):
        mocker.patch('app.statsd_client.incr')
        mocker.patch('app.statsd_client.timing_with_dates')

        notification = create_notification(
            template=sample_email_template,
            status='sending',
            reference='ref',
        )

        process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref'))

        statsd_client.timing_with_dates.assert_any_call(
            "callback.ses.elapsed-time", datetime.utcnow(), notification.sent_at
        )
        statsd_client.incr.assert_any_call("callback.ses.delivered")


def test_ses_callback_should_not_update_notification_status_if_already_delivered(sample_email_template, mocker):
    mock_dup = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao.duplicate_update_warning')
    mock_upd = mocker.patch('app.celery.process_ses_receipts_tasks.notifications_dao._update_notification_status')
    notification = create_notification(template=sample_email_template, reference='ref', status='delivered')

    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref')) is None
    assert get_notification_by_id(notification.id).status == 'delivered'

    mock_dup.assert_called_once_with(notification, 'delivered')
    assert mock_upd.call_count == 0


def test_ses_callback_should_retry_if_notification_is_new(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-17T12:14:03.646Z'):
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref')) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 1


def test_ses_callback_should_log_if_notification_is_missing(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.warning')

    with freeze_time('2017-11-17T12:34:03.646Z'):
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref')) is None
        assert mock_retry.call_count == 0
        mock_logger.assert_called_once_with('notification not found for reference: ref (update to delivered)')


def test_ses_callback_should_not_retry_if_notification_is_old(client, notify_db, mocker):
    mock_retry = mocker.patch('app.celery.process_ses_receipts_tasks.process_ses_results.retry')
    mock_logger = mocker.patch('app.celery.process_ses_receipts_tasks.current_app.logger.error')

    with freeze_time('2017-11-21T12:14:03.646Z'):
        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref')) is None
        assert mock_logger.call_count == 0
        assert mock_retry.call_count == 0


def test_ses_callback_does_not_call_send_delivery_status_if_no_db_entry(
        client,
        notify_db_session,
        sample_email_template,
        mocker):
    with freeze_time('2001-01-01T12:00:00'):

        send_mock = mocker.patch(
            'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
        )
        notification = create_notification(
            template=sample_email_template,
            status='sending',
            reference='ref',
        )

        assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref'))
        assert get_notification_by_id(notification.id).status == 'delivered'

        send_mock.assert_not_called()


def test_ses_callback_should_update_multiple_notification_status_sent(
        client,
        notify_db_session,
        sample_email_template,
        mocker):

    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref1',
    )
    create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref2',
    )
    create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref3',
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref1'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref2'))
    assert process_ses_receipts_tasks.process_ses_results(ses_notification_callback(reference='ref3'))
    assert send_mock.called


def test_ses_callback_should_set_status_to_temporary_failure(client,
                                                             notify_db_session,
                                                             sample_email_template,
                                                             mocker):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    notification = create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref',
    )
    create_service_callback_api(service=notification.service, url="https://original_url.com")
    assert get_notification_by_id(notification.id).status == 'sending'
    assert process_ses_receipts_tasks.process_ses_results(ses_soft_bounce_callback(reference='ref'))
    assert get_notification_by_id(notification.id).status == 'temporary-failure'
    assert send_mock.called


def test_ses_callback_should_set_status_to_permanent_failure(client,
                                                             notify_db_session,
                                                             sample_email_template,
                                                             mocker):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    notification = create_notification(
        template=sample_email_template,
        status='sending',
        reference='ref',
    )
    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    assert get_notification_by_id(notification.id).status == 'sending'
    assert process_ses_receipts_tasks.process_ses_results(ses_hard_bounce_callback(reference='ref'))
    assert get_notification_by_id(notification.id).status == 'permanent-failure'
    assert send_mock.called


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_400_with_invalid_header(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json')]
    )
    assert response.status_code == 400


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_400_with_invalid_message_type(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'foo')]
    )
    assert response.status_code == 400
    assert "SES-SNS SMTP callback failed: invalid message type" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_400_with_invalid_json(client):
    data = "FOOO"
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )
    assert response.status_code == 400
    assert "SES-SNS SMTP callback failed: invalid JSON given" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_400_with_certificate(client):
    data = json.dumps({"foo": "bar"})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )
    assert response.status_code == 400
    assert "SES-SNS SMTP callback failed: validation failed" in response.get_data(as_text=True)


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_200_autoconfirms_subscription(client, mocker):
    mocker.patch("validatesns.validate")
    requests_mock = mocker.patch("requests.get")
    data = json.dumps({"Type": "SubscriptionConfirmation", "SubscribeURL": "https://foo"})
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'SubscriptionConfirmation')]
    )

    requests_mock.assert_called_once_with("https://foo")
    assert response.status_code == 200


@pytest.mark.skip(reason="Endpoint disabled and slated for removal")
def test_notifications_ses_smtp_200_call_process_task(client, mocker):
    mocker.patch("validatesns.validate")
    process_mock = mocker.patch("app.celery.process_ses_receipts_tasks.process_ses_smtp_results.apply_async")
    data = {"Type": "Notification", "foo": "bar"}
    json_data = json.dumps(data)
    response = client.post(
        path='/notifications/email/ses-smtp',
        data=json_data,
        headers=[('Content-Type', 'application/json'), ('x-amz-sns-message-type', 'Notification')]
    )

    process_mock.assert_called_once_with([{'Message': None}], queue='notify-internal-tasks')
    assert response.status_code == 200


def test_process_ses_smtp_results(sample_email_template, smtp_template):
    create_notification(template=sample_email_template)
    assert process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_notification_callback())


def test_process_ses_smtp_results_in_complaint(sample_email_template, mocker, smtp_template):
    create_notification(template=sample_email_template, reference='ref1')
    mocked = mocker.patch("app.dao.notifications_dao.update_notification_status_by_reference")
    process_ses_receipts_tasks.process_ses_smtp_results(response=ses_smtp_complaint_callback())
    assert mocked.call_count == 0
    complaints = Complaint.query.all()
    assert len(complaints) == 1


def test_ses_smtp_callback_should_set_status_to_temporary_failure(client,
                                                                  notify_db,
                                                                  notify_db_session,
                                                                  sample_email_template,
                                                                  smtp_template,
                                                                  mocker):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    notification = create_notification(template=sample_email_template, reference='ref1')

    create_service_callback_api(service=notification.service, url="https://original_url.com")

    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_soft_bounce_callback(reference='ref'))
    assert send_mock.called


def test_ses_smtp_callback_should_set_status_to_permanent_failure(client,
                                                                  notify_db,
                                                                  notify_db_session,
                                                                  sample_email_template,
                                                                  smtp_template,
                                                                  mocker):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )
    create_notification(template=sample_email_template, reference='ref1')

    create_service_callback_api(service=sample_email_template.service, url="https://original_url.com")

    assert process_ses_receipts_tasks.process_ses_smtp_results(ses_smtp_hard_bounce_callback(reference='ref'))
    assert send_mock.called


def test_ses_smtp_callback_should_send_on_complaint_to_user_callback_api(smtp_template, sample_email_template, mocker):
    send_mock = mocker.patch(
        'app.celery.service_callback_tasks.send_complaint_to_service.apply_async'
    )
    create_service_callback_api(
        service=sample_email_template.service, url="https://original_url.com", callback_type="complaint"
    )

    create_notification(template=sample_email_template, reference='ref1')

    response = ses_smtp_complaint_callback()
    assert process_ses_receipts_tasks.process_ses_smtp_results(response)

    assert send_mock.call_count == 1


def get_complaint_notification_and_email(mocker):
    service = mocker.Mock(Service, id='service_id', name='Service Name', users=[mocker.Mock(User, id="user_id")])
    template = mocker.Mock(Template,
                           id='template_id',
                           name='Email Template Name',
                           service=service,
                           template_type='email')
    notification = mocker.Mock(Notification,
                               service_id=template.service.id,
                               service=template.service,
                               template_id=template.id,
                               template=template,
                               status='sending',
                               reference='ref1')
    complaint = mocker.Mock(Complaint,
                            service_id=notification.service_id,
                            notification_id=notification.id,
                            feedback_id='feedback_id',
                            complaint_type='complaint',
                            complaint_date=datetime.utcnow(),
                            created_at=datetime.now())
    recipient_email = 'recipient1@example.com'
    return complaint, notification, recipient_email
