import pytest
from collections import namedtuple
import uuid

from app.celery.lookup_recipient_communication_permissions_task import (
    lookup_recipient_communication_permissions,
    recipient_has_given_permission
)
from app.models import NOTIFICATION_PREFERENCES_DECLINED, SMS_TYPE, RecipientIdentifier, Notification
from app.va.va_profile.va_profile_client import VAProfileClient
from app.va.identifier import IdentifierType


@pytest.fixture
def mock_communication_item(mocker):
    mock_communication_item = mocker.Mock()
    mock_communication_item.va_profile_item_id = 'some-va-profile-item-id'
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.get_communication_item',
                 return_value=mock_communication_item)


@pytest.fixture
def mock_notification_with_vaprofile_id(mocker) -> Notification:
    id = uuid.uuid4()
    Notification = namedtuple('Notification', ['id', 'notification_type', 'recipient_identifiers'])
    return Notification(
        id=id,
        notification_type=SMS_TYPE,
        recipient_identifiers={
            f"{IdentifierType.VA_PROFILE_ID.value}": RecipientIdentifier(
                notification_id=id,
                id_type=IdentifierType.VA_PROFILE_ID.value,
                id_value='va-profile-id'),
        })


def test_lookup_recipient_communication_permissions_should_not_update_notification_status_if_recipient_has_permissions(
        client, mocker, mock_notification_with_vaprofile_id
):
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
                 return_value=True)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id',
        return_value=mock_notification_with_vaprofile_id
    )

    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    lookup_recipient_communication_permissions(
        'VAPROFILEID', '1', str(mock_notification_with_vaprofile_id.id), SMS_TYPE, 'some-communication-item-id'
    )
    update_notification.assert_not_called()


def test_lookup_recipient_communication_permissions_should_not_send_if_recipient_has_not_given_permission(
        client, mocker, mock_notification_with_vaprofile_id
):
    mocker.patch('app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
                 return_value=False)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id',
        return_value=mock_notification_with_vaprofile_id
    )
    update_notification = mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    lookup_recipient_communication_permissions(
        'VAPROFILEID', '1', str(mock_notification_with_vaprofile_id.id), SMS_TYPE, 'some-communication-item-id'
    )

    update_notification.assert_called_once_with(
        str(mock_notification_with_vaprofile_id.id),
        NOTIFICATION_PREFERENCES_DECLINED)


def test_recipient_has_given_permission_should_return_false_if_user_denies_permissions(
        client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=False)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client',
        new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    assert not recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )


def test_recipient_has_given_permission_should_return_true_if_user_grants_permissions(
        client, mocker, mock_communication_item
):
    mocked_va_profile_client = mocker.Mock(VAProfileClient)
    mocked_va_profile_client.get_is_communication_allowed = mocker.Mock(return_value=True)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.va_profile_client',
        new=mocked_va_profile_client
    )

    mock_task = mocker.Mock()
    assert recipient_has_given_permission(
        mock_task, 'VAPROFILEID', '1', 'some-notification-id', SMS_TYPE, 'some-communication-id'
    )


@pytest.mark.parametrize(('notification_type'), ['sms', 'email'])
def test_recipient_has_given_permission_is_called_with_va_profile_id(
    client, mocker, notification_type, mock_notification_with_vaprofile_id
):
    mock = mocker.patch('app.celery.lookup_recipient_communication_permissions_task.recipient_has_given_permission',
                        return_value=False)
    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.update_notification_status_by_id'
    )

    communication_item_id = 'some-communication-item-id'
    non_va_profile_id_type = IdentifierType.PID.value
    non_va_profile_id_value = 'pid-id'

    mock_notification_with_vaprofile_id.recipient_identifiers[f"{non_va_profile_id_type}"] = RecipientIdentifier(
        notification_id=mock_notification_with_vaprofile_id.id,
        id_type=non_va_profile_id_type,
        id_value=non_va_profile_id_value
    )

    mocker.patch(
        'app.celery.lookup_recipient_communication_permissions_task.get_notification_by_id',
        return_value=mock_notification_with_vaprofile_id
    )

    lookup_recipient_communication_permissions(
        non_va_profile_id_type,
        non_va_profile_id_value,
        str(mock_notification_with_vaprofile_id.id),
        notification_type,
        communication_item_id
    )

    id_value = mock_notification_with_vaprofile_id.recipient_identifiers[IdentifierType.VA_PROFILE_ID.value].id_value

    mock.assert_called_once_with(
        lookup_recipient_communication_permissions,
        IdentifierType.VA_PROFILE_ID.value,
        id_value,
        str(mock_notification_with_vaprofile_id.id),
        notification_type,
        communication_item_id)
