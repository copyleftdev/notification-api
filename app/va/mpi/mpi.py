import requests
from time import monotonic
from app.va import IdentifierType
from app.va.mpi import (
    MpiNonRetryableException,
    MpiRetryableException,
    UnsupportedIdentifierException,
    IdentifierNotFound,
    IncorrectNumberOfIdentifiersException,
    MultipleActiveVaProfileIdsException,
    BeneficiaryDeceasedException
)


class MpiClient:
    SYSTEM_IDENTIFIER = "200ENTF"

    FHIR_FORMAT_SUFFIXES = {
        IdentifierType.ICN: "^NI^200M^USVHA",
        IdentifierType.PID: "^PI^200CORP^USVBA",
        IdentifierType.VA_PROFILE_ID: "^PI^200VETS^USDVA",
        IdentifierType.BIRLSID: "^PI^200BRLS^USDVA"
    }

    def init_app(self, logger, url, ssl_cert_path, ssl_key_path, statsd_client):
        self.logger = logger
        self.base_url = url
        self.ssl_cert_path = ssl_cert_path
        self.ssl_key_path = ssl_key_path
        self.statsd_client = statsd_client

    def transform_to_fhir_format(self, recipient_identifier):
        try:
            identifier_type = IdentifierType(recipient_identifier.id_type)
            return f"{recipient_identifier.id_value}{self.FHIR_FORMAT_SUFFIXES[identifier_type]}", \
                   identifier_type, \
                   recipient_identifier.id_value
        except ValueError as e:
            raise UnsupportedIdentifierException(f"No identifier of type: {recipient_identifier.id_type}") from e
        except KeyError as e:
            raise UnsupportedIdentifierException(f"No mapping for identifier: {identifier_type}") from e

    def get_va_profile_id(self, notification):
        recipient_identifiers = notification.recipient_identifiers.values()
        if len(recipient_identifiers) != 1:
            error_message = "Unexpected number of recipient_identifiers in: " \
                            f"{notification.recipient_identifiers.keys()}"
            self.statsd_client.incr("clients.mpi.incorrect_number_of_recipient_identifiers_error")
            raise IncorrectNumberOfIdentifiersException(error_message)

        fhir_identifier, id_type, id_value = self.transform_to_fhir_format(next(iter(recipient_identifiers)))

        self.logger.info(f"Querying MPI with {id_type} {id_value} for notification {notification.id}")
        response_json = self._make_request(fhir_identifier, notification.id)
        mpi_identifiers = response_json['identifier']

        va_profile_id = self._get_active_va_profile_id(mpi_identifiers, fhir_identifier)
        self.statsd_client.incr("clients.mpi.success")
        return va_profile_id

    def _make_request(self, fhir_identifier, notification_id):
        start_time = monotonic()
        try:
            response = requests.get(
                f"{self.base_url}/psim_webservice/fhir/Patient/{fhir_identifier}",
                params={'-sender': self.SYSTEM_IDENTIFIER},
                cert=(self.ssl_cert_path, self.ssl_key_path)
            )
            response.raise_for_status()
        except requests.HTTPError as e:
            self.statsd_client.incr(f"clients.mpi.error.{e.response.status_code}")
            message = f"MPI returned {str(e)} while querying for notification {notification_id}"
            if e.response.status_code in [429, 500, 502, 503, 504]:
                raise MpiRetryableException(message) from e
            else:
                raise MpiNonRetryableException(message) from e
        except requests.RequestException as e:
            self.statsd_client.incr(f"clients.mpi.error.request_exception")
            message = f"MPI returned {str(e)} while querying for notification {notification_id}"
            raise MpiRetryableException(message) from e
        else:
            self._validate_response(response.json(), notification_id, fhir_identifier)
            self._assert_not_deceased(response.json())
            return response.json()
        finally:
            elapsed_time = monotonic() - start_time
            self.statsd_client.timing("clients.mpi.request-time", elapsed_time)

    def _get_active_va_profile_id(self, identifiers, fhir_identifier):
        active_va_profile_suffix = self.FHIR_FORMAT_SUFFIXES[IdentifierType.VA_PROFILE_ID] + '^A'
        va_profile_ids = [identifier['value'].split('^')[0] for identifier in identifiers
                          if identifier['value'].endswith(active_va_profile_suffix)]
        if not va_profile_ids:
            self.statsd_client.incr("clients.mpi.error.no_va_profile_id")
            raise IdentifierNotFound(f"No active VA Profile Identifier found for: {fhir_identifier}")
        if len(va_profile_ids) > 1:
            self.statsd_client.incr("clients.mpi.error.multiple_va_profile_ids")
            raise MultipleActiveVaProfileIdsException(
                f"Multiple active VA Profile Identifiers found for: {fhir_identifier}"
            )
        return va_profile_ids[0]

    def _validate_response(self, response_json, notification_id, fhir_identifier):
        if response_json.get('severity'):
            error_message = \
                f"MPI returned error with severity: {response_json['severity']}, " \
                f"code: {response_json['details']['coding'][0]['code']}, " \
                f"description: {response_json['details']['text']} for notification {notification_id} with" \
                f"fhir {fhir_identifier}"
            self.statsd_client.incr("clients.mpi.error")
            raise MpiNonRetryableException(error_message)

    def _assert_not_deceased(self, response_json):
        if response_json.get('deceasedDateTime'):
            self.statsd_client.incr("clients.mpi.beneficiary_deceased")
            raise BeneficiaryDeceasedException()