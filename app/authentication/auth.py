from flask import request, _request_ctx_stack, current_app, g
from flask import jsonify
from sqlalchemy.exc import DataError
from sqlalchemy.orm.exc import NoResultFound

from notifications_python_client.authentication import decode_jwt_token, get_token_issuer
from notifications_python_client.errors import TokenDecodeError, TokenExpiredError, TokenIssuerError

from app.dao.services_dao import dao_fetch_service_by_id_with_api_keys


class AuthError(Exception):
    def __init__(self, message, code):
        self.message = {"token": [message]}
        self.short_message = message
        self.code = code

    def to_dict_v2(self):
        return {
            'status_code': self.code,
            "errors": [
                {
                    "error": "AuthError",
                    "message": self.short_message
                }
            ]
        }


def get_auth_token(req):
    auth_header = req.headers.get('Authorization', None)
    if not auth_header:
        raise AuthError('Unauthorized, authentication token must be provided', 401)

    auth_scheme = auth_header[:7].title()

    if auth_scheme != 'Bearer ':
        raise AuthError('Unauthorized, authentication bearer scheme must be used', 401)

    return auth_header[7:]


def requires_no_auth():
    pass


def restrict_ip_sms():
    '''
    ip_addr = jsonify({'remote_addr': request.remote_addr,
                       'X-Forwarded_FOR': request.headers.getlist('X-Forwarded-For'),
                       'X_Real-Ip': request.headers.getlist('X-Real-Ip')})
    '''
    current_app.logger.info("Inbound sms ip addresses remote_addr = {}, "
                            "X-Forwarded_FOR = {}".format(request.remote_addr,
                                                          request.headers.getlist('X-Forwarded-For')))

    return


def requires_admin_auth():
    auth_token = get_auth_token(request)
    client = __get_token_issuer(auth_token)

    if client == current_app.config.get('ADMIN_CLIENT_USER_NAME'):
        g.service_id = current_app.config.get('ADMIN_CLIENT_USER_NAME')
        return handle_admin_key(auth_token, current_app.config.get('ADMIN_CLIENT_SECRET'))
    else:
        raise AuthError('Unauthorized, admin authentication token required', 401)


def requires_auth():
    auth_token = get_auth_token(request)
    client = __get_token_issuer(auth_token)

    try:
        service = dao_fetch_service_by_id_with_api_keys(client)
    except DataError:
        raise AuthError("Invalid token: service id is not the right data type", 403)
    except NoResultFound:
        raise AuthError("Invalid token: service not found", 403)

    if not service.api_keys:
        raise AuthError("Invalid token: service has no API keys", 403)

    if not service.active:
        raise AuthError("Invalid token: service is archived", 403)

    for api_key in service.api_keys:
        try:
            get_decode_errors(auth_token, api_key.secret)
        except TokenDecodeError:
            continue

        if api_key.expiry_date:
            raise AuthError("Invalid token: API key revoked", 403)

        g.service_id = api_key.service_id
        _request_ctx_stack.top.authenticated_service = service
        _request_ctx_stack.top.api_user = api_key

        return
    else:
        # service has API keys, but none matching the one the user provided
        raise AuthError("Invalid token: signature, api token is not valid", 403)


def __get_token_issuer(auth_token):
    try:
        client = get_token_issuer(auth_token)
    except TokenIssuerError:
        raise AuthError("Invalid token: iss field not provided", 403)
    except TokenDecodeError as e:
        raise AuthError("Invalid token: signature, api token is not valid", 403)
    return client


def handle_admin_key(auth_token, secret):
    try:
        get_decode_errors(auth_token, secret)
        return
    except TokenDecodeError as e:
        raise AuthError("Invalid token: signature, api token is not valid", 403)


def get_decode_errors(auth_token, unsigned_secret):
    try:
        decode_jwt_token(auth_token, unsigned_secret)
    except TokenExpiredError:
        raise AuthError("Invalid token: expired, check that your system clock is accurate", 403)
