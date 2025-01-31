from app.schema_validation.definitions import uuid

add_service_email_reply_to_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST service email reply to address",
    "type": "object",
    "title": "Add new email reply to address for service",
    "properties": {
        "email_address": {"type": "string", "format": "email_address"},
        "is_default": {"type": "boolean"}
    },
    "required": ["email_address", "is_default"]
}


add_service_letter_contact_block_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST service letter contact block",
    "type": "object",
    "title": "Add new letter contact block for service",
    "properties": {
        "contact_block": {"type": "string"},
        "is_default": {"type": "boolean"}
    },
    "required": ["contact_block", "is_default"]
}


add_service_sms_sender_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST add service SMS sender",
    "type": "object",
    "title": "Add new SMS sender for service",
    "properties": {
        "sms_sender": {"type": "string"},
        "is_default": {"type": "boolean"},
        "inbound_number_id": uuid,
        "rate_limit": {"type": ["integer", "null"], "minimum": 1},
        "rate_limit_interval": {"type": ["integer", "null"], "minimum": 1}
    },
    "required": ["sms_sender", "is_default"]
}


update_service_sms_sender_request = {
    "$schema": "http://json-schema.org/draft-04/schema#",
    "description": "POST update service SMS sender",
    "type": "object",
    "title": "Update SMS sender for service",
    "properties": {
        "sms_sender": {"type": "string"},
        "sms_sender_specifics": {"type": ["object", "null"]},
        "is_default": {"type": "boolean"},
        "rate_limit": {"type": ["integer", "null"], "minimum": 1},
        "rate_limit_interval": {"type": ["integer", "null"], "minimum": 1},
        "inbound_number_id": uuid,
    }
}
