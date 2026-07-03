import copy
from typing import Dict, List, Set, Optional, Tuple
from log_utils.logger import get_logger
from config_loader import config_loader

logger = get_logger("doc-capture")

class CaptureSession:
    def __init__(self, session_id: str, scheme_id: str, language: str):
        self.session_id = session_id
        self.scheme_id = scheme_id
        self.language = language
        
        # Scheme-level state
        self.scheme_config: dict = {}
        self.required_documents: List[str] = []
        self.current_document_index: int = 0
        
        # Document-level state
        self.current_document_config: dict = {}
        self.current_page_index: int = 0
        self.document_extracted_data: Dict[str, Dict[str, Dict[str, dict]]] = {}  # {doc_id: {page_id: {field_id: value_dict}}}
        
        # Per-document FAQ conversation history
        self.faq_history: Dict[str, List[dict]] = {}  # {doc_id: [{"role": "user", "content": "..."}]}
        
        # Completion tracking
        self.completed_documents: Set[str] = set()
        self.completed_pages: Dict[str, Set[str]] = {}  # {doc_id: {page_id, ...}}
        self.page_uploads: Dict[str, Dict[str, List[str]]] = {}  # {doc_id: {page_id: [filenames/keys]}}

    def initialize(self) -> bool:
        """Load scheme and first document config."""
        scheme = config_loader.get_scheme(self.scheme_id)
        if not scheme:
            logger.error(f"Scheme not found: {self.scheme_id}")
            return False
            
        self.scheme_config = copy.deepcopy(scheme)
        self.required_documents = self.scheme_config.get("required_documents", [])
        
        if not self.required_documents:
            logger.error(f"No required documents in scheme {self.scheme_id}")
            return False
            
        # Load first document
        return self._load_current_document()

    def _load_current_document(self) -> bool:
        """Load the document config for current_document_index."""
        if self.current_document_index >= len(self.required_documents):
            self.current_document_config = {}
            return True # All done
            
        doc_id = self.required_documents[self.current_document_index]
        doc_config = config_loader.get_document(doc_id)
        if not doc_config:
            logger.error(f"Document not found: {doc_id}")
            return False
            
        self.current_document_config = copy.deepcopy(doc_config)
        self.current_page_index = 0
        
        if doc_id not in self.completed_pages:
            self.completed_pages[doc_id] = set()
        if doc_id not in self.page_uploads:
            self.page_uploads[doc_id] = {}
        if doc_id not in self.document_extracted_data:
            self.document_extracted_data[doc_id] = {}
        if doc_id not in self.faq_history:
            self.faq_history[doc_id] = []
            
        return True

    def get_current_document_id(self) -> str:
        if self.current_document_index < len(self.required_documents):
            return self.required_documents[self.current_document_index]
        return ""

    def get_current_page(self) -> Optional[dict]:
        if not self.current_document_config:
            return None
        pages = self.current_document_config.get("pages", [])
        if self.current_page_index < len(pages):
            return pages[self.current_page_index]
        return None

    def is_all_complete(self) -> bool:
        return self.current_document_index >= len(self.required_documents)
        
    def advance_page(self) -> Tuple[bool, bool]:
        """Advance to next page or document. Returns (page_advanced, document_advanced)."""
        if not self.current_document_config:
            return False, False
            
        pages = self.current_document_config.get("pages", [])
        if self.current_page_index < len(pages) - 1:
            self.current_page_index += 1
            return True, False
        else:
            # Document complete
            doc_id = self.get_current_document_id()
            if doc_id:
                self.completed_documents.add(doc_id)
            
            self.current_document_index += 1
            self._load_current_document()
            return True, True

    def record_extraction(self, page_id: str, fields_dict: dict):
        """Deep merge extracted fields."""
        doc_id = self.get_current_document_id()
        if not doc_id:
            return
            
        if doc_id not in self.document_extracted_data:
            self.document_extracted_data[doc_id] = {}
            
        if page_id not in self.document_extracted_data[doc_id]:
            self.document_extracted_data[doc_id][page_id] = {}
            
        # Merge
        for k, v in fields_dict.items():
            self.document_extracted_data[doc_id][page_id][k] = copy.deepcopy(v)

    def mark_page_complete(self, page_id: str):
        doc_id = self.get_current_document_id()
        if doc_id:
            if doc_id not in self.completed_pages:
                self.completed_pages[doc_id] = set()
            self.completed_pages[doc_id].add(page_id)

    def record_upload(self, page_id: str, filename: str):
        doc_id = self.get_current_document_id()
        if doc_id:
            if doc_id not in self.page_uploads:
                self.page_uploads[doc_id] = {}
            if page_id not in self.page_uploads[doc_id]:
                self.page_uploads[doc_id][page_id] = []
            self.page_uploads[doc_id][page_id].append(filename)

    def get_upload_count(self, page_id: str) -> int:
        doc_id = self.get_current_document_id()
        if doc_id and doc_id in self.page_uploads and page_id in self.page_uploads[doc_id]:
            return len(self.page_uploads[doc_id][page_id])
        return 0

    def add_faq_message(self, role: str, content: str):
        doc_id = self.get_current_document_id()
        if doc_id:
            if doc_id not in self.faq_history:
                self.faq_history[doc_id] = []
            self.faq_history[doc_id].append({"role": role, "content": content})

    def get_faq_history(self) -> List[dict]:
        doc_id = self.get_current_document_id()
        if doc_id and doc_id in self.faq_history:
            return copy.deepcopy(self.faq_history[doc_id])
        return []

    def get_all_extracted_data(self) -> dict:
        """Flatten extracted data for saving to DB."""
        flat_data = {}
        for doc_id, pages in self.document_extracted_data.items():
            for page_id, fields in pages.items():
                for field_id, field_data in fields.items():
                    if isinstance(field_data, dict) and "value" in field_data:
                        flat_data[field_id] = field_data["value"]
                    else:
                        flat_data[field_id] = field_data
        return flat_data


class SessionManager:
    def __init__(self):
        self._sessions: Dict[str, CaptureSession] = {}
        
    def create_session(self, session_id: str, scheme_id: str, language: str) -> Optional[CaptureSession]:
        session = CaptureSession(session_id, scheme_id, language)
        if session.initialize():
            self._sessions[session_id] = session
            return session
        return None
        
    def get_session(self, session_id: str) -> Optional[CaptureSession]:
        return self._sessions.get(session_id)
        
    def remove_session(self, session_id: str):
        if session_id in self._sessions:
            del self._sessions[session_id]

session_manager = SessionManager()
