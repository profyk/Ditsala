"""
Data classification registry — docs/DITSALA_MASTER_SPEC.md §5.

This is the single source of truth for which class a field belongs to. It
drives: (1) the DB role grants applied in the classification migration,
(2) the structured-logging allowlist (core/logging.py must never emit a P0
field, and P1/P2 only via their designated redaction), (3) review — any new
column should be classified here before it ships.

This module is intentionally framework-agnostic (no SQLAlchemy import) so it
can be imported from anywhere, including tooling that isn't DB-connected.
"""

from enum import StrEnum


class DataClass(StrEnum):
    P0_CRYPTOGRAPHIC_SECRET = "P0"  # never logged, never admin-readable, hashed/encrypted at rest
    P1_BIOMETRIC_KYC = "P1"  # zero raw-imagery retention; result_summary only; logged admin access
    P2_MESSAGE_CONTENT_LOCATION = "P2"  # ciphertext/location; no admin path may ever decrypt
    P3_OPERATIONAL_METADATA = "P3"  # admin-visible per RBAC scope, still access-logged


# table -> {column: class}. Only sensitive/non-obvious columns are listed —
# id/created_at/updated_at and plain foreign keys are implicitly P3 unless
# stated otherwise.
REGISTRY: dict[str, dict[str, DataClass]] = {
    "users": {
        "ditsala_code_hash": DataClass.P0_CRYPTOGRAPHIC_SECRET,
        "national_id_hash": DataClass.P1_BIOMETRIC_KYC,
    },
    "kyc_documents": {
        "smile_id_job_id": DataClass.P1_BIOMETRIC_KYC,
        "result_summary": DataClass.P1_BIOMETRIC_KYC,
    },
    "kyc_face_verifications": {
        "smile_id_job_id": DataClass.P1_BIOMETRIC_KYC,
        "selfie_liveness_score": DataClass.P1_BIOMETRIC_KYC,
        "face_match_score": DataClass.P1_BIOMETRIC_KYC,
    },
    "sessions": {
        "refresh_token_hash": DataClass.P0_CRYPTOGRAPHIC_SECRET,
    },
    "identity_keys": {
        "public_identity_key": DataClass.P0_CRYPTOGRAPHIC_SECRET,
    },
    "signed_prekeys": {
        "public_key": DataClass.P0_CRYPTOGRAPHIC_SECRET,
        "signature": DataClass.P0_CRYPTOGRAPHIC_SECRET,
    },
    "one_time_prekeys": {
        "public_key": DataClass.P0_CRYPTOGRAPHIC_SECRET,
    },
    "sender_keys": {
        "distribution_message_ref": DataClass.P0_CRYPTOGRAPHIC_SECRET,
    },
    "messages": {
        "ciphertext": DataClass.P2_MESSAGE_CONTENT_LOCATION,
    },
    "media_objects": {
        "s3_key": DataClass.P2_MESSAGE_CONTENT_LOCATION,
        "content_hash": DataClass.P2_MESSAGE_CONTENT_LOCATION,
    },
    "location_pings": {
        "lat": DataClass.P2_MESSAGE_CONTENT_LOCATION,
        "lng": DataClass.P2_MESSAGE_CONTENT_LOCATION,
        "accuracy_m": DataClass.P2_MESSAGE_CONTENT_LOCATION,
    },
}


def classify(table: str, column: str) -> DataClass:
    """Default to P3 (operational metadata) for anything not explicitly listed."""
    return REGISTRY.get(table, {}).get(column, DataClass.P3_OPERATIONAL_METADATA)
