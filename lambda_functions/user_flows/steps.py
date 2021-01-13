import requests
import json
import jwt
import time
import boto3
from requests import Response

client = boto3.client('ssm')


def get_admin_client_secret(environment: str) -> str:
    key = "/{env}/notification-api/admin-client-secret".format(env=environment)
    resp = client.get_parameter(
        Name=key,
        WithDecryption=True
    )
    api_secret = resp["Parameter"]["Value"]

    if not api_secret:
        raise ValueError("Could not retrieve secret environment variable")

    return api_secret


def encode_jwt(issuer: str, secret_key: str) -> bytes:
    header = {'typ': 'JWT', 'alg': 'HS256'}
    combo = {}
    current_timestamp = int(time.time())
    data = {
        'iss': issuer,
        'iat': current_timestamp,
        'exp': current_timestamp + 30,
        'jti': 'jwt_nonce'
    }
    combo.update(data)
    combo.update(header)
    return jwt.encode(combo, secret_key, algorithm='HS256')


def get_admin_jwt(environment: str) -> bytes:
    admin_client_secret = get_admin_client_secret(environment)
    return encode_jwt('notify-admin', admin_client_secret)


def get_service_jwt(service_id: str, api_key_secret: str) -> bytes:
    return encode_jwt(service_id, api_key_secret)


def get_authenticated_request(url: str, jwt_token: bytes) -> Response:
    header = {"Authorization": F"Bearer {jwt_token.decode('utf-8')}"}
    return requests.get(url, headers=header)


def post_authenticated_request(url: str, jwt_token: bytes, payload: str = '{}') -> Response:
    header = {"Authorization": F"Bearer {jwt_token.decode('utf-8')}", 'Content-Type': 'application/json'}
    return requests.post(url, headers=header, data=payload)


def revoke_service_api_keys(environment: str, notification_url: str, service_id: str) -> None:
    jwt_token = get_admin_jwt(environment)
    existing_api_keys_response = get_authenticated_request(
        F"{notification_url}/service/{service_id}/api-keys",
        jwt_token
    )
    existing_api_keys = existing_api_keys_response.json()['apiKeys']
    active_api_keys = [api_key for api_key in existing_api_keys if api_key["expiry_date"] is None]

    for api_key in active_api_keys:
        revoke_url = F"{notification_url}/service/{service_id}/api-key/revoke/{api_key['id']}"
        post_authenticated_request(revoke_url, jwt_token)


def create_service_api_key(environment: str, notification_url: str, service_id: str, user_id: str, key_type: str):
    jwt_token = get_admin_jwt(environment)
    post_api_key_payload = json.dumps({
        "created_by": user_id,
        "key_type": key_type,
        "name": f"userflows-key-{key_type}"
    })
    post_api_key_url = F"{notification_url}/service/{service_id}/api-key"
    new_key_response = post_authenticated_request(post_api_key_url, jwt_token, post_api_key_payload)
    return new_key_response.json()['data']


def send_email(notification_url: str, service_jwt: bytes, payload: str) -> Response:
    return post_authenticated_request(F"{notification_url}/v2/notifications/email", service_jwt, payload)


def send_sms(notification_url: str, service_jwt: bytes, payload: str) -> Response:
    return post_authenticated_request(F"{notification_url}/v2/notifications/sms", service_jwt, payload)


def send_email_with_email_address(notification_url: str, service_jwt: bytes, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "email_address": "test@sink.govdelivery.com",
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "Test Subject"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def send_email_with_va_profile_id(notification_url: str, service_jwt: bytes, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "VAPROFILEID",
            "id_value": "1243"
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "VA Profile ID Email"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def send_email_with_icn(notification_url: str, service_jwt: bytes, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "ICN",
            "id_value": "1008794780V325793"
        },
        "personalisation": {
            "claim_id": "600191990",
            "date_submitted": "October 30, 2020",
            "full_name": "ICN Email"
        }
    })
    return send_email(notification_url, service_jwt, payload)


def get_notification_id(notification_response: Response) -> str:
    return notification_response.json()['id']


def get_notification_status(notification_id: str, notification_url: str, service_jwt: bytes) -> Response:
    return get_authenticated_request(F"{notification_url}/v2/notifications/{notification_id}", service_jwt)


def send_sms_with_phone_number(notification_url: str, service_jwt: bytes, template_id: str, recipient_number: str) -> Response:
    payload = json.dumps({
        "phone_number": recipient_number,
        "template_id": template_id
    })

    return send_sms(notification_url, service_jwt, payload)


def send_sms_with_va_profile_id(notification_url: str, service_jwt: bytes, template_id: str) -> Response:
    payload = json.dumps({
        "template_id": template_id,
        "recipient_identifier": {
            "id_type": "VAPROFILEID",
            "id_value": "203"
        }
    })
    return send_sms(notification_url, service_jwt, payload)
