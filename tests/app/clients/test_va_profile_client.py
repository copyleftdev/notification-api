import pytest
from requests import HTTPError
from requests_mock import ANY

from app.clients.va_profile.va_profile_client import VAProfileClient, VAProfileException

MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov/'


@pytest.fixture(scope='function')
def test_va_profile_client(mocker):
    mock_logger = mocker.Mock()
    mock_ssl_key_path = 'some_key.pem'
    mock_ssl_cert_path = 'some_cert.pem'

    test_va_profile_client = VAProfileClient()
    test_va_profile_client.init_app(
        mock_logger,
        MOCK_VA_PROFILE_URL,
        mock_ssl_cert_path,
        mock_ssl_key_path
    )

    return test_va_profile_client


def test_get_email_gets_from_correct_url(notify_api, rmock, test_va_profile_client):
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": "some@email.com"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    va_profile_id = '12'
    test_va_profile_client.get_email(va_profile_id)

    assert rmock.called

    expected_url = f"{MOCK_VA_PROFILE_URL}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails"
    assert rmock.request_history[0].url == expected_url


def test_get_email_gets_single_email(notify_api, rmock, test_va_profile_client):
    expected_email = 'hello@moto.com'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": expected_email
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_email = test_va_profile_client.get_email('1')
    assert actual_email == expected_email


def test_get_email_gets_most_recently_created_email(notify_api, rmock, test_va_profile_client):
    older_email = 'older@moto.com'
    newer_email = 'newer@moto.com'

    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": older_email
            },
            {
                "createDate": "2020-04-17T16:01:13Z",
                "updateDate": "2020-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2020-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2020-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": newer_email
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_email = test_va_profile_client.get_email('1')
    assert actual_email == newer_email


def test_get_email_raises_exception_when_no_email_bio(notify_api, rmock, test_va_profile_client):
    response = {
        "messages": [
            {
                "code": "CORE103",
                "key": "_CUF_NOT_FOUND",
                "text": "The EmailBio for id/criteria mdm.cuf.",
                "severity": "INFO"
            }
        ],
        "txAuditId": "dca32cae-b410-46c5-b61b-9a382567843f",
        "status": "COMPLETED_SUCCESS"
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(VAProfileException):
        test_va_profile_client.get_email('1')


def test_get_email_raises_exception_when_no_contact_info(notify_api, rmock, test_va_profile_client):
    response = {
        "messages": [
            {
                "code": "CORE103",
                "key": "_CUF_NOT_FOUND",
                "text": "The ContactInformationBio for id/criteria 103 could not be found. Please correct your requ...",
                "severity": "INFO"
            }
        ],
        "txAuditId": "dca32cae-b410-46c5-b61b-9a382567843f",
        "status": "COMPLETED_FAILURE"
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(VAProfileException):
        test_va_profile_client.get_email('1')


@pytest.mark.parametrize(
    "status",
    [400, 403, 404, 429, 500]
)
def test_get_email_raises_exception_when_status_not_200(notify_api, rmock, test_va_profile_client, status):
    rmock.get(ANY, status_code=status)

    with pytest.raises(HTTPError):
        test_va_profile_client.get_email('1')