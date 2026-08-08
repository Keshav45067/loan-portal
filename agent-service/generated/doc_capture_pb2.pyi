from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StartCaptureRequest(_message.Message):
    __slots__ = ("scheme_id", "session_id", "language", "reset")
    SCHEME_ID_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    RESET_FIELD_NUMBER: _ClassVar[int]
    scheme_id: str
    session_id: str
    language: str
    reset: bool
    def __init__(self, scheme_id: _Optional[str] = ..., session_id: _Optional[str] = ..., language: _Optional[str] = ..., reset: _Optional[bool] = ...) -> None: ...

class CaptureSessionResponse(_message.Message):
    __slots__ = ("success", "error", "session_id", "current_document_id", "current_page_id", "current_document_index", "total_documents", "current_page_index", "total_pages", "current_page_info", "all_complete")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    CURRENT_DOCUMENT_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PAGE_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_PAGES_FIELD_NUMBER: _ClassVar[int]
    CURRENT_PAGE_INFO_FIELD_NUMBER: _ClassVar[int]
    ALL_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    session_id: str
    current_document_id: str
    current_page_id: str
    current_document_index: int
    total_documents: int
    current_page_index: int
    total_pages: int
    current_page_info: PageInfo
    all_complete: bool
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., session_id: _Optional[str] = ..., current_document_id: _Optional[str] = ..., current_page_id: _Optional[str] = ..., current_document_index: _Optional[int] = ..., total_documents: _Optional[int] = ..., current_page_index: _Optional[int] = ..., total_pages: _Optional[int] = ..., current_page_info: _Optional[_Union[PageInfo, _Mapping]] = ..., all_complete: _Optional[bool] = ...) -> None: ...

class PageInfoRequest(_message.Message):
    __slots__ = ("session_id", "document_id", "page_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    document_id: str
    page_id: str
    def __init__(self, session_id: _Optional[str] = ..., document_id: _Optional[str] = ..., page_id: _Optional[str] = ...) -> None: ...

class PageInfoResponse(_message.Message):
    __slots__ = ("success", "error", "page_info", "document_id", "document_name", "document_index", "total_documents")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    PAGE_INFO_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_NAME_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_INDEX_FIELD_NUMBER: _ClassVar[int]
    TOTAL_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    page_info: PageInfo
    document_id: str
    document_name: str
    document_index: int
    total_documents: int
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., page_info: _Optional[_Union[PageInfo, _Mapping]] = ..., document_id: _Optional[str] = ..., document_name: _Optional[str] = ..., document_index: _Optional[int] = ..., total_documents: _Optional[int] = ...) -> None: ...

class PageInfo(_message.Message):
    __slots__ = ("page_id", "page_name", "allow_multiple", "ui_camera_overlay", "intro_prompt_json", "success_prompt_json", "error_blur_prompt_json", "error_invalid_doc_prompt_json", "acceptable_formats", "max_file_size_mb", "uploads_count")
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    ALLOW_MULTIPLE_FIELD_NUMBER: _ClassVar[int]
    UI_CAMERA_OVERLAY_FIELD_NUMBER: _ClassVar[int]
    INTRO_PROMPT_JSON_FIELD_NUMBER: _ClassVar[int]
    SUCCESS_PROMPT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_BLUR_PROMPT_JSON_FIELD_NUMBER: _ClassVar[int]
    ERROR_INVALID_DOC_PROMPT_JSON_FIELD_NUMBER: _ClassVar[int]
    ACCEPTABLE_FORMATS_FIELD_NUMBER: _ClassVar[int]
    MAX_FILE_SIZE_MB_FIELD_NUMBER: _ClassVar[int]
    UPLOADS_COUNT_FIELD_NUMBER: _ClassVar[int]
    page_id: str
    page_name: str
    allow_multiple: bool
    ui_camera_overlay: str
    intro_prompt_json: str
    success_prompt_json: str
    error_blur_prompt_json: str
    error_invalid_doc_prompt_json: str
    acceptable_formats: _containers.RepeatedScalarFieldContainer[str]
    max_file_size_mb: int
    uploads_count: int
    def __init__(self, page_id: _Optional[str] = ..., page_name: _Optional[str] = ..., allow_multiple: _Optional[bool] = ..., ui_camera_overlay: _Optional[str] = ..., intro_prompt_json: _Optional[str] = ..., success_prompt_json: _Optional[str] = ..., error_blur_prompt_json: _Optional[str] = ..., error_invalid_doc_prompt_json: _Optional[str] = ..., acceptable_formats: _Optional[_Iterable[str]] = ..., max_file_size_mb: _Optional[int] = ..., uploads_count: _Optional[int] = ...) -> None: ...

class AdvancePageRequest(_message.Message):
    __slots__ = ("session_id",)
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    def __init__(self, session_id: _Optional[str] = ...) -> None: ...

class SwitchPageRequest(_message.Message):
    __slots__ = ("session_id", "document_id", "page_id")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    document_id: str
    page_id: str
    def __init__(self, session_id: _Optional[str] = ..., document_id: _Optional[str] = ..., page_id: _Optional[str] = ...) -> None: ...

class ProcessDocRequest(_message.Message):
    __slots__ = ("session_id", "document_id", "page_id", "image_data", "content_type", "filename")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DATA_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    document_id: str
    page_id: str
    image_data: bytes
    content_type: str
    filename: str
    def __init__(self, session_id: _Optional[str] = ..., document_id: _Optional[str] = ..., page_id: _Optional[str] = ..., image_data: _Optional[bytes] = ..., content_type: _Optional[str] = ..., filename: _Optional[str] = ...) -> None: ...

class ProcessDocResponse(_message.Message):
    __slots__ = ("success", "error", "extracted_fields_json", "validation_error_key", "validation_error_text", "validation_field_id", "page_complete", "document_complete", "all_complete", "next_page_id", "next_document_id", "confirm_fields", "part_id", "next_part_id", "processed_document_id")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    EXTRACTED_FIELDS_JSON_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_KEY_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_ERROR_TEXT_FIELD_NUMBER: _ClassVar[int]
    VALIDATION_FIELD_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    ALL_COMPLETE_FIELD_NUMBER: _ClassVar[int]
    NEXT_PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    NEXT_DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    CONFIRM_FIELDS_FIELD_NUMBER: _ClassVar[int]
    PART_ID_FIELD_NUMBER: _ClassVar[int]
    NEXT_PART_ID_FIELD_NUMBER: _ClassVar[int]
    PROCESSED_DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    extracted_fields_json: str
    validation_error_key: str
    validation_error_text: str
    validation_field_id: str
    page_complete: bool
    document_complete: bool
    all_complete: bool
    next_page_id: str
    next_document_id: str
    confirm_fields: _containers.RepeatedScalarFieldContainer[str]
    part_id: str
    next_part_id: str
    processed_document_id: str
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., extracted_fields_json: _Optional[str] = ..., validation_error_key: _Optional[str] = ..., validation_error_text: _Optional[str] = ..., validation_field_id: _Optional[str] = ..., page_complete: _Optional[bool] = ..., document_complete: _Optional[bool] = ..., all_complete: _Optional[bool] = ..., next_page_id: _Optional[str] = ..., next_document_id: _Optional[str] = ..., confirm_fields: _Optional[_Iterable[str]] = ..., part_id: _Optional[str] = ..., next_part_id: _Optional[str] = ..., processed_document_id: _Optional[str] = ...) -> None: ...

class SchemeConfigRequest(_message.Message):
    __slots__ = ("scheme_id",)
    SCHEME_ID_FIELD_NUMBER: _ClassVar[int]
    scheme_id: str
    def __init__(self, scheme_id: _Optional[str] = ...) -> None: ...

class SchemeConfigResponse(_message.Message):
    __slots__ = ("success", "error", "scheme_id", "scheme_name", "description", "required_documents")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SCHEME_ID_FIELD_NUMBER: _ClassVar[int]
    SCHEME_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    REQUIRED_DOCUMENTS_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    scheme_id: str
    scheme_name: str
    description: str
    required_documents: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., scheme_id: _Optional[str] = ..., scheme_name: _Optional[str] = ..., description: _Optional[str] = ..., required_documents: _Optional[_Iterable[str]] = ...) -> None: ...

class DocConfigRequest(_message.Message):
    __slots__ = ("document_id",)
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    def __init__(self, document_id: _Optional[str] = ...) -> None: ...

class DocConfigResponse(_message.Message):
    __slots__ = ("success", "error", "document_id", "document_name", "description", "allowed_languages", "acceptable_formats", "max_file_size_mb", "pages")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    DOCUMENT_NAME_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    ALLOWED_LANGUAGES_FIELD_NUMBER: _ClassVar[int]
    ACCEPTABLE_FORMATS_FIELD_NUMBER: _ClassVar[int]
    MAX_FILE_SIZE_MB_FIELD_NUMBER: _ClassVar[int]
    PAGES_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    document_id: str
    document_name: str
    description: str
    allowed_languages: _containers.RepeatedScalarFieldContainer[str]
    acceptable_formats: _containers.RepeatedScalarFieldContainer[str]
    max_file_size_mb: int
    pages: _containers.RepeatedCompositeFieldContainer[PageSummary]
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., document_id: _Optional[str] = ..., document_name: _Optional[str] = ..., description: _Optional[str] = ..., allowed_languages: _Optional[_Iterable[str]] = ..., acceptable_formats: _Optional[_Iterable[str]] = ..., max_file_size_mb: _Optional[int] = ..., pages: _Optional[_Iterable[_Union[PageSummary, _Mapping]]] = ...) -> None: ...

class PageSummary(_message.Message):
    __slots__ = ("page_id", "page_name", "allow_multiple", "ui_camera_overlay", "prompts_json")
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_NAME_FIELD_NUMBER: _ClassVar[int]
    ALLOW_MULTIPLE_FIELD_NUMBER: _ClassVar[int]
    UI_CAMERA_OVERLAY_FIELD_NUMBER: _ClassVar[int]
    PROMPTS_JSON_FIELD_NUMBER: _ClassVar[int]
    page_id: str
    page_name: str
    allow_multiple: bool
    ui_camera_overlay: str
    prompts_json: str
    def __init__(self, page_id: _Optional[str] = ..., page_name: _Optional[str] = ..., allow_multiple: _Optional[bool] = ..., ui_camera_overlay: _Optional[str] = ..., prompts_json: _Optional[str] = ...) -> None: ...

class FAQPromptRequest(_message.Message):
    __slots__ = ("session_id", "language")
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    session_id: str
    language: str
    def __init__(self, session_id: _Optional[str] = ..., language: _Optional[str] = ...) -> None: ...

class FAQPromptResponse(_message.Message):
    __slots__ = ("success", "error", "system_prompt", "context_prompt")
    SUCCESS_FIELD_NUMBER: _ClassVar[int]
    ERROR_FIELD_NUMBER: _ClassVar[int]
    SYSTEM_PROMPT_FIELD_NUMBER: _ClassVar[int]
    CONTEXT_PROMPT_FIELD_NUMBER: _ClassVar[int]
    success: bool
    error: str
    system_prompt: str
    context_prompt: str
    def __init__(self, success: _Optional[bool] = ..., error: _Optional[str] = ..., system_prompt: _Optional[str] = ..., context_prompt: _Optional[str] = ...) -> None: ...

class ProcessDocDirectRequest(_message.Message):
    __slots__ = ("document_id", "page_id", "image_data", "content_type", "filename", "language", "session_id")
    DOCUMENT_ID_FIELD_NUMBER: _ClassVar[int]
    PAGE_ID_FIELD_NUMBER: _ClassVar[int]
    IMAGE_DATA_FIELD_NUMBER: _ClassVar[int]
    CONTENT_TYPE_FIELD_NUMBER: _ClassVar[int]
    FILENAME_FIELD_NUMBER: _ClassVar[int]
    LANGUAGE_FIELD_NUMBER: _ClassVar[int]
    SESSION_ID_FIELD_NUMBER: _ClassVar[int]
    document_id: str
    page_id: str
    image_data: bytes
    content_type: str
    filename: str
    language: str
    session_id: str
    def __init__(self, document_id: _Optional[str] = ..., page_id: _Optional[str] = ..., image_data: _Optional[bytes] = ..., content_type: _Optional[str] = ..., filename: _Optional[str] = ..., language: _Optional[str] = ..., session_id: _Optional[str] = ...) -> None: ...
