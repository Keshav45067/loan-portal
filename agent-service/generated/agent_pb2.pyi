from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class InitSessionRequest(_message.Message):
    __slots__ = ("scheme_id", "session_id", "language")
    SCHEME_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    scheme_id: str
    session_id: str
    language: str
    def __init__(self, scheme_id: _Optional[str] = ..., session_id: _Optional[str] = ..., language: _Optional[str] = ...) -> None: ...

class InitSessionResponse(_message.Message):
    __slots__ = ("success", "session_id", "json_session_state", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    JSON_SESSION_STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    session_id: str
    json_session_state: str
    error: str
    def __init__(self, success: _Optional[bool] = ..., session_id: _Optional[str] = ..., json_session_state: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class RunTurnRequest(_message.Message):
    __slots__ = ("session_id", "message", "language")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    message: str
    language: str
    def __init__(self, session_id: _Optional[str] = ..., message: _Optional[str] = ..., language: _Optional[str] = ...) -> None: ...

class ToolCallInfo(_message.Message):
    __slots__ = ("tool_name", "json_arguments", "status", "message", "json_signal")
    TOOL_NAME_FIELD_NUMBER: _ClassVar[int]
    JSON_ARGUMENTS_FIELD_NUMBER: _ClassVar[int]
    STATUS_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    JSON_SIGNAL_FIELD_NUMBER: _ClassVar[int]
    tool_name: str
    json_arguments: str
    status: str
    message: str
    json_signal: str
    def __init__(self, tool_name: _Optional[str] = ..., json_arguments: _Optional[str] = ..., status: _Optional[str] = ..., message: _Optional[str] = ..., json_signal: _Optional[str] = ...) -> None: ...

class RunTurnResponse(_message.Message):
    __slots__ = ("success", "agent_response", "tool_calls", "json_session_state", "json_pending_confirmation", "json_internal_log", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    AGENT_RESPONSE_FIELD_NUMBER: _ClassVar[int]
    TOOL_CALLS_FIELD_NUMBER: _ClassVar[int]
    JSON_SESSION_STATE_FIELD_NUMBER: _ClassVar[int]
    JSON_PENDING_CONFIRMATION_FIELD_NUMBER: _ClassVar[int]
    JSON_INTERNAL_LOG_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    agent_response: str
    tool_calls: _containers.RepeatedCompositeFieldContainer[ToolCallInfo]
    json_session_state: str
    json_pending_confirmation: str
    json_internal_log: str
    error: str
    def __init__(self, success: _Optional[bool] = ..., agent_response: _Optional[str] = ..., tool_calls: _Optional[_Iterable[_Union[ToolCallInfo, _Mapping]]] = ..., json_session_state: _Optional[str] = ..., json_pending_confirmation: _Optional[str] = ..., json_internal_log: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class GetSessionStateRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class GetSessionStateResponse(_message.Message):
    __slots__ = ("success", "json_session_state", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    JSON_SESSION_STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    json_session_state: str
    error: str
    def __init__(self, success: _Optional[bool] = ..., json_session_state: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...

class SyncExtractedDataRequest(_message.Message):
    __slots__ = ("session_id", "doc_id", "part_id", "json_extracted_fields", "page_complete", "all_complete", "reset")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DOC_ID_FIELD_NUMBER: _ClassVar[int]
    PART_ID_FIELD_NUMBER: _ClassVar[int]
    JSON_EXTRACTED_FIELDS_FIELD_NUMBER: _ClassVar[int]
    PAGE_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    ALL_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    RESET_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    doc_id: str
    part_id: str
    json_extracted_fields: str
    page_complete: bool
    all_complete: bool
    reset: bool
    def __init__(self, session_id: _Optional[str] = ..., doc_id: _Optional[str] = ..., part_id: _Optional[str] = ..., json_extracted_fields: _Optional[str] = ..., page_complete: _Optional[bool] = ..., all_complete: _Optional[bool] = ..., reset: _Optional[bool] = ...) -> None: ...

class SyncExtractedDataResponse(_message.Message):
    __slots__ = ("success", "json_session_state", "error")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    JSON_SESSION_STATE_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    success: bool
    json_session_state: str
    error: str
    def __init__(self, success: _Optional[bool] = ..., json_session_state: _Optional[str] = ..., error: _Optional[str] = ...) -> None: ...
