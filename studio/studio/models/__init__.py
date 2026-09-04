"""Beanie ODM documents for MIVAIS Studio."""
from studio.models.admin_user import AdminUser
from studio.models.api_key import ApiKey
from studio.models.audio_chunk import AudioChunk
from studio.models.audit_log import AuditEntry
from studio.models.biometric_chunk import BiometricChunk
from studio.models.code import Code
from studio.models.event import Event
from studio.models.participant import Participant
from studio.models.saved_view import SavedView
from studio.models.sensor_chunk import SensorChunk
from studio.models.sensor_token import SensorIngestToken
from studio.models.session import Session
from studio.models.study import Study
from studio.models.transcript import Transcript
from studio.models.video_chunk import VideoChunk
from studio.models.webhook import WebhookEndpoint

ALL_DOCUMENTS = [
    AdminUser, Study, Code, Session, Participant, Event,
    AudioChunk, VideoChunk, BiometricChunk, Transcript, AuditEntry, WebhookEndpoint, SavedView,
    ApiKey, SensorChunk, SensorIngestToken,
]

__all__ = [
    "ALL_DOCUMENTS",
    "AdminUser",
    "ApiKey",
    "AudioChunk",
    "AuditEntry",
    "BiometricChunk",
    "Code",
    "Event",
    "Participant",
    "SavedView",
    "SensorChunk",
    "SensorIngestToken",
    "Session",
    "Study",
    "Transcript",
    "VideoChunk",
    "WebhookEndpoint",
]
