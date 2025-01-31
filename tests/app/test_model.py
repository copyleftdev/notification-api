import pytest

from freezegun import freeze_time
from sqlalchemy.exc import IntegrityError

from app import encryption
from app.models import (
    ServiceWhitelist,
    Notification,
    SMS_TYPE,
    MOBILE_TYPE,
    EMAIL_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_SENDING,
    NOTIFICATION_PENDING,
    NOTIFICATION_FAILED,
    NOTIFICATION_STATUS_LETTER_ACCEPTED,
    NOTIFICATION_STATUS_LETTER_RECEIVED,
    NOTIFICATION_STATUS_TYPES_FAILED,
    NOTIFICATION_TECHNICAL_FAILURE,
    PRECOMPILED_TEMPLATE_NAME,
    ServiceCallback,
    COMPLAINT_CALLBACK_TYPE,
    QUEUE_CHANNEL_TYPE,
    WEBHOOK_CHANNEL_TYPE
)
from app.va.identifier import IdentifierType

from tests.app.db import (
    create_notification,
    create_service,
    create_inbound_number,
    create_reply_to_email,
    create_letter_contact,
    create_template,
    create_template_folder
)


@pytest.mark.parametrize('mobile_number', [
    '650 253 2222',
    '+1 650 253 2222'
])
def test_should_build_service_whitelist_from_mobile_number(mobile_number):
    service_whitelist = ServiceWhitelist.from_string('service_id', MOBILE_TYPE, mobile_number)

    assert service_whitelist.recipient == mobile_number


@pytest.mark.parametrize('email_address', [
    'test@example.com'
])
def test_should_build_service_whitelist_from_email_address(email_address):
    service_whitelist = ServiceWhitelist.from_string('service_id', EMAIL_TYPE, email_address)

    assert service_whitelist.recipient == email_address


@pytest.mark.parametrize('contact, recipient_type', [
    ('', None),
    ('07700dsadsad', MOBILE_TYPE),
    ('gmail.com', EMAIL_TYPE)
])
def test_should_not_build_service_whitelist_from_invalid_contact(recipient_type, contact):
    with pytest.raises(ValueError):
        ServiceWhitelist.from_string('service_id', recipient_type, contact)


@pytest.mark.parametrize('initial_statuses, expected_statuses', [
    # passing in single statuses as strings
    (NOTIFICATION_FAILED, NOTIFICATION_STATUS_TYPES_FAILED),
    (NOTIFICATION_STATUS_LETTER_ACCEPTED, [NOTIFICATION_SENDING, NOTIFICATION_CREATED]),
    (NOTIFICATION_CREATED, [NOTIFICATION_CREATED]),
    (NOTIFICATION_TECHNICAL_FAILURE, [NOTIFICATION_TECHNICAL_FAILURE]),
    # passing in lists containing single statuses
    ([NOTIFICATION_FAILED], NOTIFICATION_STATUS_TYPES_FAILED),
    ([NOTIFICATION_CREATED], [NOTIFICATION_CREATED]),
    ([NOTIFICATION_TECHNICAL_FAILURE], [NOTIFICATION_TECHNICAL_FAILURE]),
    (NOTIFICATION_STATUS_LETTER_RECEIVED, NOTIFICATION_DELIVERED),
    # passing in lists containing multiple statuses
    ([NOTIFICATION_FAILED, NOTIFICATION_CREATED], NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_CREATED]),
    ([NOTIFICATION_CREATED, NOTIFICATION_PENDING], [NOTIFICATION_CREATED, NOTIFICATION_PENDING]),
    ([NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE], [NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE]),
    (
        [NOTIFICATION_FAILED, NOTIFICATION_STATUS_LETTER_ACCEPTED],
        NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_SENDING, NOTIFICATION_CREATED]
    ),
    # checking we don't end up with duplicates
    (
        [NOTIFICATION_FAILED, NOTIFICATION_CREATED, NOTIFICATION_TECHNICAL_FAILURE],
        NOTIFICATION_STATUS_TYPES_FAILED + [NOTIFICATION_CREATED]
    ),
])
def test_status_conversion(initial_statuses, expected_statuses):
    converted_statuses = Notification.substitute_status(initial_statuses)
    assert len(converted_statuses) == len(expected_statuses)
    assert set(converted_statuses) == set(expected_statuses)


@freeze_time("2016-01-01 11:09:00.000000")
@pytest.mark.parametrize('template_type, recipient', [
    ('sms', '+16502532222'),
    ('email', 'foo@bar.com'),
])
def test_notification_for_csv_returns_correct_type(sample_service, template_type, recipient):
    template = create_template(sample_service, template_type=template_type)
    notification = create_notification(template, to_field=recipient)

    serialized = notification.serialize_for_csv()
    assert serialized['template_type'] == template_type


@freeze_time("2016-01-01 11:09:00.000000")
def test_notification_for_csv_returns_correct_job_row_number(sample_job):
    notification = create_notification(sample_job.template, sample_job, job_row_number=0)

    serialized = notification.serialize_for_csv()
    assert serialized['row_number'] == 1


@freeze_time("2016-01-30 12:39:58.321312")
@pytest.mark.parametrize('template_type, status, expected_status', [
    ('email', 'failed', 'Failed'),
    ('email', 'technical-failure', 'Technical failure'),
    ('email', 'temporary-failure', 'Inbox not accepting messages right now'),
    ('email', 'permanent-failure', 'Email address doesn’t exist'),
    ('sms', 'temporary-failure', 'Phone not accepting messages right now'),
    ('sms', 'permanent-failure', 'Phone number doesn’t exist'),
    ('sms', 'sent', 'Sent internationally'),
    ('letter', 'created', 'Accepted'),
    ('letter', 'sending', 'Accepted'),
    ('letter', 'technical-failure', 'Technical failure'),
    ('letter', 'delivered', 'Received')
])
def test_notification_for_csv_returns_formatted_status(
        sample_service,
        template_type,
        status,
        expected_status
):
    template = create_template(sample_service, template_type=template_type)
    notification = create_notification(template, status=status)

    serialized = notification.serialize_for_csv()
    assert serialized['status'] == expected_status


@freeze_time("2017-03-26 23:01:53.321312")
def test_notification_for_csv_returns_est_correctly(sample_template):
    notification = create_notification(sample_template)

    serialized = notification.serialize_for_csv()
    assert serialized['created_at'] == '2017-03-26 19:01:53'


def test_notification_personalisation_getter_returns_empty_dict_from_None():
    noti = Notification()
    noti._personalisation = None
    assert noti.personalisation == {}


def test_notification_personalisation_getter_always_returns_empty_dict():
    noti = Notification()
    noti._personalisation = encryption.encrypt({})
    assert noti.personalisation == {}


@pytest.mark.parametrize('input_value', [
    None,
    {}
])
def test_notification_personalisation_setter_always_sets_empty_dict(input_value):
    noti = Notification()
    noti.personalisation = input_value

    assert noti._personalisation == encryption.encrypt({})


def test_notification_subject_is_none_for_sms():
    assert Notification(notification_type=SMS_TYPE).subject is None


@pytest.mark.parametrize('template_type', ['email', 'letter'])
def test_notification_subject_fills_in_placeholders(sample_service, template_type):
    template = create_template(service=sample_service, template_type=template_type, subject='((name))')
    notification = create_notification(template=template, personalisation={'name': 'hello'})
    assert notification.subject == 'hello'


def test_letter_notification_serializes_with_address(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        'address_line_1': 'foo',
        'address_line_3': 'bar',
        'address_line_5': None,
        'postcode': 'SW1 1AA'
    }
    res = sample_letter_notification.serialize()
    assert res['line_1'] == 'foo'
    assert res['line_2'] is None
    assert res['line_3'] == 'bar'
    assert res['line_4'] is None
    assert res['line_5'] is None
    assert res['line_6'] is None
    assert res['postcode'] == 'SW1 1AA'


def test_notification_serializes_created_by_name_with_no_created_by_id(client, sample_notification):
    res = sample_notification.serialize()
    assert res['created_by_name'] is None


def test_notification_serializes_created_by_name_with_created_by_id(client, sample_notification, sample_user):
    sample_notification.created_by_id = sample_user.id
    res = sample_notification.serialize()
    assert res['created_by_name'] == sample_user.name


def test_sms_notification_serializes_without_subject(client, sample_template):
    res = sample_template.serialize()
    assert res['subject'] is None


def test_email_notification_serializes_with_subject(client, sample_email_template):
    res = sample_email_template.serialize()
    assert res['subject'] == 'Email Subject'


def test_letter_notification_serializes_with_subject(client, sample_letter_template):
    res = sample_letter_template.serialize()
    assert res['subject'] == 'Template subject'


def test_user_service_role_serializes_without_updated(client, sample_user_service_role, sample_user, sample_service):
    res = sample_user_service_role.serialize()
    assert res['id'] is not None
    assert res['role'] == "admin"
    assert res['user_id'] == str(sample_user.id)
    assert res['service_id'] == str(sample_service.id)
    assert res['updated_at'] is None


def test_user_service_role_serializes_with_updated(client, sample_service_role_udpated, sample_user, sample_service):
    res = sample_service_role_udpated.serialize()
    assert res['id'] is not None
    assert res['role'] == "admin"
    assert res['user_id'] == str(sample_user.id)
    assert res['service_id'] == str(sample_service.id)
    assert res['updated_at'] == sample_service_role_udpated.updated_at.isoformat() + 'Z'


def test_notification_references_template_history(client, sample_template):
    noti = create_notification(sample_template)
    sample_template.version = 3
    sample_template.content = 'New template content'

    res = noti.serialize()
    assert res['template']['version'] == 1

    assert res['body'] == noti.template.content
    assert noti.template.content != sample_template.content


def test_email_notification_serializes_with_recipient_identifiers(client, sample_email_template):
    recipient_identifiers = [
        {
            "id_type": IdentifierType.VA_PROFILE_ID.value,
            "id_value": "some vaprofileid"
        },
        {
            "id_type": IdentifierType.ICN.value,
            "id_value": "some icn"
        }
    ]

    noti = create_notification(sample_email_template, recipient_identifiers=recipient_identifiers)
    response = noti.serialize()
    assert response['recipient_identifiers'] == recipient_identifiers


def test_email_notification_serializes_with_empty_recipient_identifiers(client, sample_email_template):
    notifcation = create_notification(sample_email_template)
    response = notifcation.serialize()
    assert response['recipient_identifiers'] == []


def test_notification_requires_a_valid_template_version(client, sample_template):
    sample_template.version = 2
    with pytest.raises(IntegrityError):
        create_notification(sample_template)


def test_inbound_number_serializes_with_service(client, notify_db_session):
    service = create_service()
    inbound_number = create_inbound_number(number='1', service_id=service.id)
    serialized_inbound_number = inbound_number.serialize()
    assert serialized_inbound_number.get('id') == str(inbound_number.id)
    assert serialized_inbound_number.get('service').get('id') == str(inbound_number.service.id)
    assert serialized_inbound_number.get('service').get('name') == inbound_number.service.name


def test_inbound_number_returns_inbound_number(client, notify_db_session):
    service = create_service()
    inbound_number = create_inbound_number(number='1', service_id=service.id)

    assert inbound_number in service.inbound_numbers


def test_inbound_number_returns_none_when_no_inbound_number(client, notify_db_session):
    service = create_service()

    assert service.inbound_numbers == []


def test_service_get_default_reply_to_email_address(sample_service):
    create_reply_to_email(service=sample_service, email_address="default@email.com")

    assert sample_service.get_default_reply_to_email_address() == 'default@email.com'


def test_service_get_default_contact_letter(sample_service):
    create_letter_contact(service=sample_service, contact_block='London,\nNW1A 1AA')

    assert sample_service.get_default_letter_contact() == 'London,\nNW1A 1AA'


def test_service_get_default_sms_sender(notify_db_session):
    service = create_service()
    assert service.get_default_sms_sender() == 'testing'


def test_letter_notification_serializes_correctly(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        'addressline1': 'test',
        'addressline2': 'London',
        'postcode': 'N1',
    }

    json = sample_letter_notification.serialize()
    assert json['line_1'] == 'test'
    assert json['line_2'] == 'London'
    assert json['postcode'] == 'N1'


def test_letter_notification_postcode_can_be_null_for_precompiled_letters(client, sample_letter_notification):
    sample_letter_notification.personalisation = {
        'address_line_1': 'test',
        'address_line_2': 'London',
    }

    json = sample_letter_notification.serialize()
    assert json['line_1'] == 'test'
    assert json['line_2'] == 'London'
    assert json['postcode'] is None


def test_is_precompiled_letter_false(sample_letter_template):
    assert not sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_true(sample_letter_template):
    sample_letter_template.hidden = True
    sample_letter_template.name = PRECOMPILED_TEMPLATE_NAME
    assert sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_hidden_true_not_name(sample_letter_template):
    sample_letter_template.hidden = True
    assert not sample_letter_template.is_precompiled_letter


def test_is_precompiled_letter_name_correct_not_hidden(sample_letter_template):
    sample_letter_template.name = PRECOMPILED_TEMPLATE_NAME
    assert not sample_letter_template.is_precompiled_letter


def test_template_folder_is_parent(sample_service):
    x = None
    folders = []
    for i in range(5):
        x = create_template_folder(sample_service, name=str(i), parent=x)
        folders.append(x)

    assert folders[0].is_parent_of(folders[1])
    assert folders[0].is_parent_of(folders[2])
    assert folders[0].is_parent_of(folders[4])
    assert folders[1].is_parent_of(folders[2])
    assert not folders[1].is_parent_of(folders[0])


def test_fido2_key_serialization(sample_fido2_key):
    json = sample_fido2_key.serialize()
    assert json['name'] == sample_fido2_key.name
    assert json['created_at']


def test_login_event_serialization(sample_login_event):
    json = sample_login_event.serialize()
    assert json['data'] == sample_login_event.data
    assert json['created_at']


class TestServiceCallback:
    @pytest.mark.parametrize(
        ['callback_channel', 'callback_strategy_path'],
        [
            (QUEUE_CHANNEL_TYPE, 'app.callback.queue_callback_strategy.QueueCallbackStrategy'),
            (WEBHOOK_CHANNEL_TYPE, 'app.callback.webhook_callback_strategy.WebhookCallbackStrategy')
        ]
    )
    def test_service_callback_send_uses_queue_strategy(
            self, mocker, sample_service, callback_channel, callback_strategy_path
    ):
        service_callback = ServiceCallback(  # nosec
            service_id=sample_service.id,
            url="https://something.com",
            bearer_token="some_super_secret",
            updated_by_id=sample_service.users[0].id,
            callback_type=COMPLAINT_CALLBACK_TYPE,
            callback_channel=callback_channel
        )

        mock_callback_strategy = mocker.patch(callback_strategy_path)

        service_callback.send(
            payload={},
            logging_tags={}
        )

        mock_callback_strategy.send_callback.assert_called_with(
            service_callback, {}, {}
        )
