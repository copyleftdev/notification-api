import json
import uuid
from datetime import datetime

import pytest
import requests_mock
from flask import current_app
from freezegun import freeze_time
from sqlalchemy.exc import SQLAlchemyError

from app import (DATETIME_FORMAT, encryption)
from app.celery.exceptions import NonRetryableException
from app.celery.service_callback_tasks import (
    send_complaint_to_service,
    send_complaint_to_vanotify,
    check_and_queue_callback_task,
    publish_complaint,
    send_inbound_sms_to_service
)

from app.config import QueueNames
from app.exceptions import NotificationTechnicalFailureException
from app.models import Notification, ServiceCallback, Complaint, Service, Template, INBOUND_SMS_CALLBACK_TYPE
from app.model import User
from tests.app.db import (
    create_complaint,
    create_notification,
    create_service,
    create_template,
    create_inbound_sms,
    create_service_callback_api,
    create_service_sms_sender
)


@pytest.fixture
def complaint_and_template_name_to_vanotify():
    service = create_service(service_name="Sample VANotify service", restricted=True)
    template = create_template(
        service=service,
        template_name="Sample VANotify service",
        template_type="email",
        subject='Hello'
    )
    notification = create_notification(template=template)
    complaint = create_complaint(service=template.service, notification=notification)
    return complaint, template.name


@pytest.mark.parametrize("notification_type",
                         ["email", "letter", "sms"])
def test_send_delivery_status_to_service_post_https_request_to_service_with_encrypted_data(
        notify_db_session, notification_type):
    from app.celery.service_callback_tasks import send_delivery_status_to_service
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)

    notification = create_notification(template=template,
                                       created_at=datestr,
                                       updated_at=datestr,
                                       sent_at=datestr,
                                       status='sent'
                                       )
    encrypted_status_update = _set_up_data_for_status_update(callback_api, notification)
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url,
                          json={},
                          status_code=200)
        send_delivery_status_to_service(
            callback_api.id, notification.id, encrypted_status_update=encrypted_status_update
        )

    mock_data = {
        "id": str(notification.id),
        "reference": notification.client_reference,
        "to": notification.to,
        "status": notification.status,
        "created_at": datestr.strftime(DATETIME_FORMAT),
        "completed_at": datestr.strftime(DATETIME_FORMAT),
        "sent_at": datestr.strftime(DATETIME_FORMAT),
        "notification_type": notification_type
    }

    assert request_mock.call_count == 1
    assert request_mock.request_history[0].url == callback_api.url
    assert request_mock.request_history[0].method == 'POST'
    assert request_mock.request_history[0].text == json.dumps(mock_data)
    assert request_mock.request_history[0].headers["Content-type"] == "application/json"
    assert request_mock.request_history[0].headers["Authorization"] == "Bearer {}".format(callback_api.bearer_token)


def test_send_complaint_to_service_posts_https_request_to_service_with_encrypted_data(notify_db_session):
    with freeze_time('2001-01-01T12:00:00'):
        callback_api, template = _set_up_test_data('email', "complaint")

        notification = create_notification(template=template)
        complaint = create_complaint(service=template.service, notification=notification)
        complaint_data = _set_up_data_for_complaint(callback_api, complaint, notification)
        with requests_mock.Mocker() as request_mock:
            request_mock.post(callback_api.url,
                              json={},
                              status_code=200)
            send_complaint_to_service(callback_api.id, complaint_data)

        mock_data = {
            "notification_id": str(notification.id),
            "complaint_id": str(complaint.id),
            "reference": notification.client_reference,
            "to": notification.to,
            "complaint_date": datetime.utcnow().strftime(
                DATETIME_FORMAT),
        }

        assert request_mock.call_count == 1
        assert request_mock.request_history[0].url == callback_api.url
        assert request_mock.request_history[0].method == 'POST'
        assert request_mock.request_history[0].text == json.dumps(mock_data)
        assert request_mock.request_history[0].headers["Content-type"] == "application/json"
        assert request_mock.request_history[0].headers["Authorization"] == "Bearer {}".format(callback_api.bearer_token)


@pytest.mark.parametrize("notification_type",
                         ["email", "letter", "sms"])
def test__send_data_to_service_callback_api_retries_if_request_returns_500_with_encrypted_data(
        notify_db_session, mocker, notification_type
):
    from app.celery.service_callback_tasks import send_delivery_status_to_service
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = create_notification(template=template,
                                       created_at=datestr,
                                       updated_at=datestr,
                                       sent_at=datestr,
                                       status='sent'
                                       )
    encrypted_data = _set_up_data_for_status_update(callback_api, notification)
    mocked = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.retry')
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url,
                          json={},
                          status_code=501)
        send_delivery_status_to_service(callback_api.id, notification.id, encrypted_status_update=encrypted_data)

    assert mocked.call_count == 1


@pytest.mark.parametrize("notification_type",
                         ["email", "letter", "sms"])
def test_send_data_to_service_callback_api_does_not_retry_if_request_returns_404_with_encrypted_data(
        notify_db_session,
        mocker,
        notification_type
):
    from app.celery.service_callback_tasks import send_delivery_status_to_service
    callback_api, template = _set_up_test_data(notification_type, "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = create_notification(template=template,
                                       created_at=datestr,
                                       updated_at=datestr,
                                       sent_at=datestr,
                                       status='sent'
                                       )
    encrypted_data = _set_up_data_for_status_update(callback_api, notification)
    mocked = mocker.patch('app.celery.service_callback_tasks.send_delivery_status_to_service.retry')
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url,
                          json={},
                          status_code=404)
        with pytest.raises(NonRetryableException):
            send_delivery_status_to_service(callback_api.id, notification.id, encrypted_status_update=encrypted_data)

    assert mocked.call_count == 0


def test_send_delivery_status_to_service_succeeds_if_sent_at_is_none(
        notify_db_session
):
    from app.celery.service_callback_tasks import send_delivery_status_to_service
    callback_api, template = _set_up_test_data('email', "delivery_status")
    datestr = datetime(2017, 6, 20)
    notification = create_notification(template=template,
                                       created_at=datestr,
                                       updated_at=datestr,
                                       sent_at=None,
                                       status='technical-failure'
                                       )
    encrypted_data = _set_up_data_for_status_update(callback_api, notification)
    with requests_mock.Mocker() as request_mock:
        request_mock.post(callback_api.url,
                          json={},
                          status_code=200)
        send_delivery_status_to_service(callback_api.id, notification.id, encrypted_status_update=encrypted_data)

    assert request_mock.call_count == 1
    assert request_mock.request_history[0].url == callback_api.url
    assert request_mock.request_history[0].method == 'POST'
    assert request_mock.request_history[0].headers["Content-type"] == "application/json"
    assert request_mock.request_history[0].headers["Authorization"] == "Bearer {}".format(callback_api.bearer_token)


def test_send_complaint_to_vanotify_invokes_send_notification_to_service_users(
        notify_db_session, mocker, complaint_and_template_name_to_vanotify
):
    mocked = mocker.patch('app.service.sender.send_notification_to_service_users')
    complaint, template_name = complaint_and_template_name_to_vanotify
    send_complaint_to_vanotify(complaint.id, template_name)

    mocked.assert_called_once_with(
        service_id=current_app.config['NOTIFY_SERVICE_ID'],
        template_id=current_app.config['EMAIL_COMPLAINT_TEMPLATE_ID'],
        personalisation={
            'notification_id': str(complaint.notification_id),
            'service_name': complaint.service.name,
            'template_name': template_name,
            'complaint_id': str(complaint.id),
            'complaint_type': complaint.complaint_type,
            'complaint_date': complaint.complaint_date.strftime(DATETIME_FORMAT)
        }
    )


def test_send_email_complaint_to_vanotify_fails(notify_db_session, mocker, complaint_and_template_name_to_vanotify):
    mocker.patch(
        'app.service.sender.send_notification_to_service_users',
        side_effect=NotificationTechnicalFailureException('error!!!')
    )
    mock_logger = mocker.patch('app.celery.service_callback_tasks.current_app.logger.exception')
    complaint, template_name = complaint_and_template_name_to_vanotify

    send_complaint_to_vanotify(complaint.id, template_name)

    mock_logger.assert_called_once_with(
        f'Problem sending complaint to va-notify for notification {complaint.notification_id}: error!!!'
    )


def test_check_and_queue_callback_task_does_not_queue_task_if_service_callback_api_does_not_exist(mocker):
    mock_notification = create_mock_notification(mocker)

    mocker.patch(
        'app.celery.service_callback_tasks.get_service_delivery_status_callback_api_for_service',
        return_value=None
    )

    mock_send_delivery_status = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )

    check_and_queue_callback_task(mock_notification)

    mock_send_delivery_status.assert_not_called()


def test_check_and_queue_callback_task_queues_task_if_service_callback_api_exists(mocker):
    mock_notification = create_mock_notification(mocker)
    mock_service_callback_api = mocker.Mock(ServiceCallback)
    mock_notification_data = mocker.Mock()

    mocker.patch(
        'app.celery.service_callback_tasks.get_service_delivery_status_callback_api_for_service',
        return_value=mock_service_callback_api
    )

    mock_create_callback_data = mocker.patch(
        'app.celery.service_callback_tasks.create_delivery_status_callback_data',
        return_value=mock_notification_data
    )
    mock_send_delivery_status = mocker.patch(
        'app.celery.service_callback_tasks.send_delivery_status_to_service.apply_async'
    )

    check_and_queue_callback_task(mock_notification)

    mock_create_callback_data.assert_called_once_with(mock_notification, mock_service_callback_api)
    mock_send_delivery_status.assert_called_once_with(
        [mock_service_callback_api.id, str(mock_notification.id), mock_notification_data],
        queue=QueueNames.CALLBACKS
    )


def test_publish_complaint_results_in_invoking_handler(mocker, notify_api):
    notification_db = mocker.patch("app.dao.notifications_dao.update_notification_status_by_reference")

    mocker.patch('app.celery.service_callback_tasks._check_and_queue_complaint_callback_task')
    mocker.patch('app.celery.service_callback_tasks.send_complaint_to_vanotify.apply_async')

    complaint, notification, recipient_email = get_complaint_notification_and_email(mocker)

    assert publish_complaint(complaint, notification, recipient_email)
    assert notification_db.call_count == 0


def test_publish_complaint_notifies_vanotify(mocker, notify_api):
    mocker.patch('app.celery.service_callback_tasks._check_and_queue_complaint_callback_task')
    send_complaint = mocker.patch('app.celery.service_callback_tasks.send_complaint_to_vanotify.apply_async')

    complaint, notification, recipient_email = get_complaint_notification_and_email(mocker)

    publish_complaint(complaint, notification, recipient_email)

    send_complaint.assert_called_once_with(
        [str(complaint.id), notification.template.name], queue='notify-internal-tasks'
    )


def test_ses_callback_should_call_user_complaint_callback_task(mocker, notify_api):
    complaint, notification, recipient_email = get_complaint_notification_and_email(mocker)
    complaint_callback_task = mocker.patch('app.celery.service_callback_tasks._check_and_queue_complaint_callback_task')
    mocker.patch('app.celery.service_callback_tasks.send_complaint_to_vanotify.apply_async')

    publish_complaint(complaint, notification, recipient_email)

    complaint_callback_task.assert_called_once_with(complaint, notification, recipient_email)


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


def create_mock_notification(mocker):
    notification = mocker.Mock(Notification)
    notification.id = uuid.uuid4()
    notification.service_id = uuid.uuid4()
    return notification


def _set_up_test_data(notification_type, callback_type):
    service = create_service(restricted=True)
    template = create_template(service=service, template_type=notification_type, subject='Hello')
    callback_api = create_service_callback_api(service=service, url="https://some.service.gov.uk/",  # nosec
                                               bearer_token="something_unique", callback_type=callback_type)
    return callback_api, template


def _set_up_data_for_status_update(callback_api, notification):
    data = {
        "notification_id": str(notification.id),
        "notification_client_reference": notification.client_reference,
        "notification_to": notification.to,
        "notification_status": notification.status,
        "notification_created_at": notification.created_at.strftime(DATETIME_FORMAT),
        "notification_updated_at": notification.updated_at.strftime(
            DATETIME_FORMAT) if notification.updated_at else None,
        "notification_sent_at": notification.sent_at.strftime(DATETIME_FORMAT) if notification.sent_at else None,
        "notification_type": notification.notification_type,
        "service_callback_api_url": callback_api.url,
        "service_callback_api_bearer_token": callback_api.bearer_token,
    }
    encrypted_status_update = encryption.encrypt(data)
    return encrypted_status_update


def _set_up_data_for_complaint(callback_api, complaint, notification):
    data = {
        "complaint_id": str(complaint.id),
        "notification_id": str(notification.id),
        "reference": notification.client_reference,
        "to": notification.to,
        "complaint_date": complaint.complaint_date.strftime(DATETIME_FORMAT),
        "service_callback_api_url": callback_api.url,
        "service_callback_api_bearer_token": callback_api.bearer_token,
    }
    obscured_status_update = encryption.encrypt(data)
    return obscured_status_update


class TestSendInboundSmsToService:

    def test_post_https_request_to_service(self, notify_api, sample_service, mocker):
        inbound_api = create_service_callback_api(  # nosec
            service=sample_service,
            url="https://some.service.gov.uk/",
            callback_type=INBOUND_SMS_CALLBACK_TYPE,
            bearer_token="something_unique"
        )
        mock_send = mocker.Mock()
        mocker.patch.object(inbound_api, 'send', mock_send)
        mocker.patch(
            'app.celery.service_callback_tasks.get_service_inbound_sms_callback_api_for_service',
            return_value=inbound_api
        )

        inbound_sms = create_inbound_sms(
            service=sample_service,
            notify_number="0751421",
            user_number="447700900111",
            provider_date=datetime(2017, 6, 20),
            content="Here is some content"
        )
        sms_sender = create_service_sms_sender(
            service=sample_service,
            sms_sender="0751421"
        )
        expected_data = {
            "id": str(inbound_sms.id),
            "source_number": inbound_sms.user_number,
            "destination_number": inbound_sms.notify_number,
            "message": inbound_sms.content,
            "date_received": inbound_sms.provider_date.strftime(DATETIME_FORMAT),
            "sms_sender_id": str(sms_sender.id)
        }

        send_inbound_sms_to_service(inbound_sms.id, inbound_sms.service_id)

        call = mock_send.call_args_list[0]
        args, kwargs = call
        assert kwargs['payload'] == expected_data

    def test_does_not_send_request_when_inbound_sms_does_not_exist(self, notify_api, sample_service, mocker):
        inbound_api = create_service_callback_api(service=sample_service, callback_type=INBOUND_SMS_CALLBACK_TYPE)
        mock_send = mocker.Mock()
        mocker.patch.object(inbound_api, 'send', mock_send)
        mocker.patch(
            'app.celery.service_callback_tasks.get_service_inbound_sms_callback_api_for_service',
            return_value=inbound_api
        )

        with pytest.raises(SQLAlchemyError):
            send_inbound_sms_to_service(inbound_sms_id=uuid.uuid4(), service_id=sample_service.id)

        assert mock_send.call_count == 0
