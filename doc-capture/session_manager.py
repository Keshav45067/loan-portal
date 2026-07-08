import copy
import json
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
        
        # Document-level state (manifest)
        self.current_document_config: dict = {}
        self.current_page_index: int = 0
        
        # Coverage Map: {document_id: {part_id: quality_result_dict}}
        self.coverage_map: Dict[str, Dict[str, dict]] = {}
        
        # Part OCR Texts: {document_id: {part_id: ocr_text}}
        self.part_ocr_texts: Dict[str, Dict[str, str]] = {}
        
        self.document_extracted_data: Dict[str, dict] = {}  # {doc_id: flat_extracted_fields}
        
        # Per-document FAQ conversation history
        self.faq_history: Dict[str, List[dict]] = {}  # {doc_id: [{"role": "user", "content": "..."}]}
        
        # Completion tracking
        self.completed_documents: Set[str] = set()
        self.completed_pages: Dict[str, Set[str]] = {}  # {doc_id: {part_id, ...}}
        self.page_uploads: Dict[str, Dict[str, List[str]]] = {}  # {doc_id: {part_id: [filenames/keys]}}

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
        manifest = config_loader.get_manifest(doc_id)
        if not manifest:
            logger.error(f"Manifest not found for document: {doc_id}")
            return False
            
        self.current_document_config = copy.deepcopy(manifest)
        self.current_page_index = 0
        
        if doc_id not in self.completed_pages:
            self.completed_pages[doc_id] = set()
        if doc_id not in self.page_uploads:
            self.page_uploads[doc_id] = {}
        if doc_id not in self.document_extracted_data:
            self.document_extracted_data[doc_id] = {}
        if doc_id not in self.faq_history:
            self.faq_history[doc_id] = []
        if doc_id not in self.coverage_map:
            self.coverage_map[doc_id] = {}
        if doc_id not in self.part_ocr_texts:
            self.part_ocr_texts[doc_id] = {}
            
        return True

    def get_current_document_id(self) -> str:
        if self.current_document_index < len(self.required_documents):
            return self.required_documents[self.current_document_index]
        return ""

    def get_next_uncovered_part(self) -> Optional[dict]:
        """Returns the first part in the current manifest that is not covered."""
        if not self.current_document_config:
            return None
        doc_id = self.get_current_document_id()
        parts = self.current_document_config.get("parts", [])
        
        for part in parts:
            part_id = part.get("id", "")
            if not self.is_part_covered(part_id):
                return part
        return None

    def is_part_covered(self, part_id: str) -> bool:
        doc_id = self.get_current_document_id()
        if not doc_id:
            return False
        return part_id in self.coverage_map.get(doc_id, {})

    def is_coverage_complete(self) -> bool:
        if not self.current_document_config:
            return True
        doc_id = self.get_current_document_id()
        parts = self.current_document_config.get("parts", [])
        return all(part.get("id") in self.coverage_map.get(doc_id, {}) for part in parts)

    def get_current_page(self) -> Optional[dict]:
        """
        Synthesizes a page-like representation of the current uncovering part
        for compatibility with the frontend and voice-engine APIs.
        """
        if not self.current_document_config:
            return None
        manifest = self.current_document_config
        part = self.get_next_uncovered_part()
        if not part:
            return None
            
        part_id = part.get("id", "")
        
        # Build prompt templates
        lang_prompts = manifest.get("prompts", {})
        ask_part_template = lang_prompts.get("ask_part", {})
        
        document_title_en = manifest.get("title", {}).get("English", "Document")
        document_title_hi = manifest.get("title", {}).get("Hindi", document_title_en)
        
        part_title_en = part.get("title", {}).get("English", part_id)
        part_title_hi = part.get("title", {}).get("Hindi", part_title_en)
        
        intro_prompts = {
            "en": ask_part_template.get("en", "Please capture the {part_id} of your {document_title}.").format(
                part_id=part_title_en, part_title=part_title_en, document_title=document_title_en
            ),
            "hi": ask_part_template.get("hi", "कृपया अपने {document_title} का {part_id} कैप्चर करें।").format(
                part_id=part_title_hi, part_title=part_title_hi, document_title=document_title_hi
            )
        }
        
        success_prompts = lang_prompts.get("success", {"en": "Scanned successfully.", "hi": "सफलतापूर्वक स्कैन हो गया।"})
        blur_prompts = lang_prompts.get("error_blur", {"en": "Image is blurry.", "hi": "छवि धुंधली है।"})
        wrong_page_prompts = lang_prompts.get("error_wrong_page", {"en": "Wrong page.", "hi": "गलत पृष्ठ।"})
        
        # Get source configs
        sources = manifest.get("sources", [{}])
        first_source = sources[0] if sources else {}
        
        return {
            "page_id": part_id,
            "page_name": part.get("name", {}).get("English", part_id),
            "allow_multiple": False,
            "ui_camera_overlay": "landscape_id",
            "intro_prompt_json": json.dumps(intro_prompts),
            "success_prompt_json": json.dumps(success_prompts),
            "error_blur_prompt_json": json.dumps(blur_prompts),
            "error_invalid_doc_prompt_json": json.dumps(wrong_page_prompts),
            "acceptable_formats": first_source.get("formats", ["image/jpeg", "image/png"]),
            "max_file_size_mb": first_source.get("max_mb", 10),
            "preprocessing_flags": manifest.get("preprocessing", ["auto_deskew", "remove_glare", "enhance_contrast"])
        }

    def is_all_complete(self) -> bool:
        return self.current_document_index >= len(self.required_documents)
        
    def advance_page(self) -> Tuple[bool, bool]:
        """Advance to next part or document. Returns (page_advanced, document_advanced)."""
        if not self.current_document_config:
            return False, False
            
        doc_id = self.get_current_document_id()
        
        if self.is_coverage_complete():
            if doc_id:
                self.completed_documents.add(doc_id)
            self.current_document_index += 1
            self._load_current_document()
            return True, True
        else:
            # Not fully complete, so we are staying on current document but requesting next part
            return True, False

    def record_part_result(self, part_id: str, quality_res):
        """Record QualityResult and text for a part."""
        doc_id = self.get_current_document_id()
        if not doc_id:
            return
            
        # Store in coverage map
        self.coverage_map[doc_id][part_id] = {
            "part_id": part_id,
            "ocr_confidence": quality_res.ocr_confidence,
            "anchor_hits": quality_res.anchor_hits
        }
        
        # Store OCR text
        self.part_ocr_texts[doc_id][part_id] = quality_res.ocr_text
        
        # Track completed pages/parts for backward compatibility
        self.completed_pages[doc_id].add(part_id)

    def record_extraction(self, page_id: str, fields_dict: dict):
        """Save flat extracted fields for backward compatibility."""
        doc_id = self.get_current_document_id()
        if not doc_id:
            return
            
        # Deep merge extracted values into self.document_extracted_data
        for k, v in fields_dict.items():
            self.document_extracted_data[doc_id][k] = copy.deepcopy(v)

    def mark_page_complete(self, page_id: str):
        # Mapped to record_part_result. Kept for gRPC service compatibility
        pass

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
        for doc_id, fields in self.document_extracted_data.items():
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
