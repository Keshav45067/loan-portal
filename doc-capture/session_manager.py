import copy
import json
from typing import Dict, List, Set, Optional, Tuple
from log_utils.logger import get_logger
from config_loader import config_loader

logger = get_logger("doc-capture")

def parse_page_id(page_id: str) -> Tuple[str, int]:
    # e.g. "cheques_2" -> ("cheques", 2)
    # e.g. "front" -> ("front", 1)
    if "_" in page_id:
        parts = page_id.rsplit("_", 1)
        if parts[1].isdigit():
            return parts[0], int(parts[1])
    return page_id, 1

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
        
        # Part OCR Texts: {document_id: {part_id: {page_index: ocr_text}}}
        self.part_ocr_texts: Dict[str, Dict[str, Dict[int, str]]] = {}
        
        self.document_extracted_data: Dict[str, dict] = {}  # {doc_id: flat_extracted_fields}
        
        # Per-document FAQ conversation history
        self.faq_history: Dict[str, List[dict]] = {}  # {doc_id: [{"role": "user", "content": "..."}]}
        
        # Completion tracking
        self.completed_documents: Set[str] = set()
        self.completed_pages: Dict[str, Set[str]] = {}  # {doc_id: {part_id, ...}}
        self.page_uploads: Dict[str, Dict[str, Dict[int, str]]] = {}  # {doc_id: {part_id: {page_index: filename}}}
        
        # Retake and dynamic multi-page tracking
        self.variable_parts_completed: Dict[str, Set[str]] = {} # {doc_id: {part_id, ...}}
        self.pending_retakes: Dict[str, Dict[str, Set[int]]] = {} # {doc_id: {part_id: {page_index, ...}}}
        self.failed_reasons: Dict[str, Dict[str, Dict[int, List[str]]]] = {} # {doc_id: {part_id: {page_index: [reasons]}}}

    def reset(self):
        """Reset capture session state completely for redo / start over."""
        self.current_document_index = 0
        self.current_page_index = 0
        self.coverage_map.clear()
        self.part_ocr_texts.clear()
        self.part_results.clear()
        self.uploaded_parts.clear()
        self.document_extracted_data.clear()
        self.completed_documents.clear()
        self.completed_pages.clear()
        self.page_uploads.clear()
        self.variable_parts_completed.clear()
        self.pending_retakes.clear()
        self.failed_reasons.clear()
        self.faq_history.clear()
        self._load_current_document()

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
        if doc_id not in self.variable_parts_completed:
            self.variable_parts_completed[doc_id] = set()
        if doc_id not in self.pending_retakes:
            self.pending_retakes[doc_id] = {}
        if doc_id not in self.failed_reasons:
            self.failed_reasons[doc_id] = {}
            
        return True

    def get_current_document_id(self) -> str:
        if self.current_document_index < len(self.required_documents):
            return self.required_documents[self.current_document_index]
        return ""

    def set_active_document(self, doc_id: str, part_id: Optional[str] = None) -> bool:
        """Explicitly switch the session active document and page index."""
        if doc_id in self.required_documents:
            idx = self.required_documents.index(doc_id)
            self.current_document_index = idx
            self._load_current_document()
            
            if part_id and self.current_document_config:
                parts = self.current_document_config.get("parts", [])
                for p_idx, p in enumerate(parts):
                    if p.get("id") == part_id:
                        self.current_page_index = p_idx
                        break
            else:
                self.current_page_index = 0
            return True
        return False

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
            
        # If there are pending retakes for this part, it is NOT covered/complete!
        if self.pending_retakes.get(doc_id, {}).get(part_id):
            return False

        # Find part definition in current manifest
        part_def = None
        for p in self.current_document_config.get("parts", []):
            if p.get("id") == part_id:
                part_def = p
                break
        if not part_def:
            return False
            
        page_count = part_def.get("page_count", 1)
        uploaded_pages = self.part_ocr_texts.get(doc_id, {}).get(part_id, {})
        
        if page_count == 1:
            return len(uploaded_pages) >= 1
        elif page_count > 1:
            return len(uploaded_pages) >= page_count
        elif page_count == 0:
            # Variable page count: complete if user uploaded at least 1 page AND marked as completed
            has_upload = len(uploaded_pages) >= 1
            is_marked = part_id in self.variable_parts_completed.get(doc_id, set())
            return has_upload and is_marked
            
        return False

    def is_coverage_complete(self) -> bool:
        if not self.current_document_config:
            return True
        doc_id = self.get_current_document_id()
        parts = self.current_document_config.get("parts", [])
        return all(self.is_part_covered(part.get("id")) for part in parts)

    def get_current_page(self) -> Optional[dict]:
        """
        Synthesizes a page-like representation of the current uncovering part
        for compatibility with the frontend and voice-engine APIs.
        """
        if not self.current_document_config:
            return None
        manifest = self.current_document_config
        parts = manifest.get("parts", [])

        # Honor current_page_index if valid
        part = None
        if 0 <= self.current_page_index < len(parts):
            part = parts[self.current_page_index]

        if not part:
            part = self.get_next_uncovered_part()

        if not part:
            return None
            
        part_id = part.get("id", "")
        doc_id = self.get_current_document_id()
        page_count = part.get("page_count", 1)
        
        # Determine if there is a pending retake or next sequential page
        retakes = self.pending_retakes.get(doc_id, {}).get(part_id, set())
        
        is_retake = False
        page_index = 1
        
        if retakes:
            is_retake = True
            page_index = sorted(list(retakes))[0]
        else:
            # Multi-page sequential index calculation
            if page_count == 0 or page_count > 1:
                uploaded = self.part_ocr_texts.get(doc_id, {}).get(part_id, {})
                page_index = len(uploaded) + 1
                
        # Build page_id suffix if it's a multi-page part
        if page_count == 0 or page_count > 1:
            page_id = f"{part_id}_{page_index}"
        else:
            page_id = part_id
            
        # Build prompt templates
        lang_prompts = manifest.get("prompts", {})
        ask_part_template = lang_prompts.get("ask_part", {})
        
        document_title_en = manifest.get("title", {}).get("English", "Document")
        document_title_hi = manifest.get("title", {}).get("Hindi", document_title_en)
        
        # Format localized part titles based on page index
        base_title_en = part.get("title", {}).get("English", part_id)
        base_title_hi = part.get("title", {}).get("Hindi", base_title_en)
        
        if page_count == 0 or page_count > 1:
            if is_retake:
                part_title_en = f"{base_title_en} page {page_index} (retake)"
                part_title_hi = f"{base_title_hi} का पृष्ठ {page_index} (पुनः स्कैन करें)"
            else:
                part_title_en = f"{base_title_en} page {page_index}"
                part_title_hi = f"{base_title_hi} का पृष्ठ {page_index}"
        else:
            part_title_en = base_title_en
            part_title_hi = base_title_hi
            
        intro_prompts = {
            "en": ask_part_template.get("en", "Please capture the {part_id} of your {document_title}.").format(
                part_id=part_title_en, part_title=part_title_en, document_title=document_title_en
            ),
            "hi": ask_part_template.get("hi", "कृपया अपने {document_title} का {part_id} कैप्चर करें।").format(
                part_id=part_title_hi, part_title=part_title_hi, document_title=document_title_hi
            ),
            "fr": ask_part_template.get("fr", "Veuillez capturer le {part_id} de votre {document_title}.").format(
                part_id=part_title_en, part_title=part_title_en, document_title=document_title_en
            ),
            "ar": ask_part_template.get("ar", "يرجى التقاط {part_id} الخاص بـ {document_title}.").format(
                part_id=part_title_en, part_title=part_title_en, document_title=document_title_en
            )
        }
        
        # Inject failed reasons and previous image if this is a retake
        if is_retake:
            reasons = self.failed_reasons.get(doc_id, {}).get(part_id, {}).get(page_index, [])
            if reasons:
                reasons_joined = ", ".join(reasons)
                intro_prompts["en"] = f"Verification failed on page {page_index} due to unclear details in: {reasons_joined}. Please capture page {page_index} again."
                intro_prompts["hi"] = f"अस्पष्ट विवरण ({reasons_joined}) के कारण पृष्ठ {page_index} का सत्यापन विफल रहा। कृपया पृष्ठ {page_index} को फिर से कैप्चर करें।"
                intro_prompts["fr"] = f"Échec de la vérification à la page {page_index}. Veuillez recapturer la page {page_index}."
                intro_prompts["ar"] = f"فشلت عملية التحقق في الصفحة {page_index}. يرجى التقاط الصفحة {page_index} مرة أخرى."
            
            # Fetch GCS/URL of the previously uploaded file
            prev_upload = self.page_uploads.get(doc_id, {}).get(part_id, {}).get(page_index, "")
            if prev_upload:
                intro_prompts["previous_image_url"] = prev_upload
                intro_prompts["failed_reasons"] = reasons
                
        success_prompts = lang_prompts.get("success", {
            "en": "Scanned successfully.",
            "hi": "सफलतापूर्वक स्कैन हो गया।",
            "fr": "Scanné avec succès.",
            "ar": "تم المسح بنجاح."
        })
        blur_prompts = lang_prompts.get("error_blur", {
            "en": "Image is blurry.",
            "hi": "छवि धुंधली है।",
            "fr": "L'image est floue. Veuillez reprendre une photo claire.",
            "ar": "الصورة ضبابية. يرجى التقاط صورة واضحة."
        })
        wrong_page_prompts = lang_prompts.get("error_wrong_page", {
            "en": "Wrong page.",
            "hi": "गलत पृष्ठ।",
            "fr": "Page incorrecte détectée.",
            "ar": "تم الكشف عن صفحة خاطئة."
        })
        
        # Get source configs
        sources = manifest.get("sources", [{}])
        first_source = sources[0] if sources else {}
        
        # Format human-friendly page name
        base_name_en = part.get("name", {}).get("English", part_id)
        if page_count == 0 or page_count > 1:
            if is_retake:
                page_name = f"{base_name_en} - Page {page_index} (Retake)"
            else:
                page_name = f"{base_name_en} - Page {page_index}"
        else:
            page_name = base_name_en
        # Get orientation from part, default to landscape
        orientation = part.get("orientation", "landscape")
        ui_camera_overlay = part.get("ui_camera_overlay", manifest.get("ui_camera_overlay", "landscape_id"))

        return {
            "page_id": page_id,
            "page_name": page_name,
            "allow_multiple": (page_count == 0),
            "ui_camera_overlay": ui_camera_overlay,
            "intro_prompt_json": json.dumps(intro_prompts),
            "success_prompt_json": json.dumps(success_prompts),
            "error_blur_prompt_json": json.dumps(blur_prompts),
            "error_invalid_doc_prompt_json": json.dumps(wrong_page_prompts),
            "acceptable_formats": first_source.get("formats", ["image/jpeg", "image/png"]),
            "max_file_size_mb": first_source.get("max_mb", 10),
            "orientation": orientation
        }

    def is_all_complete(self) -> bool:
        """Check if all required documents in the scheme are completed."""
        if not self.required_documents:
            return False
        return len(self.completed_documents) >= len(self.required_documents)
        
    def advance_page(self) -> Tuple[bool, bool]:
        """Advance to next part or document. Returns (page_advanced, document_advanced)."""
        if not self.current_document_config:
            return False, False
            
        doc_id = self.get_current_document_id()
        
        if self.is_coverage_complete():
            if doc_id:
                self.completed_documents.add(doc_id)
            
            if self.is_all_complete():
                self.current_document_index = len(self.required_documents)
                return True, True

            # Advance forward, wrapping around if needed, to find next pending document
            start_idx = self.current_document_index
            total = len(self.required_documents)
            found_next = False

            for step in range(1, total + 1):
                check_idx = (start_idx + step) % total
                candidate_doc_id = self.required_documents[check_idx]
                if candidate_doc_id not in self.completed_documents:
                    self.current_document_index = check_idx
                    self.current_page_index = 0
                    self._load_current_document()
                    found_next = True
                    break

            if not found_next:
                self.current_document_index = len(self.required_documents)

            return True, True
        else:
            # Not fully complete, so we are staying on current document but requesting next part
            self.current_page_index += 1
            return True, False

    def record_part_result(self, page_id: str, quality_res):
        """Record QualityResult and text for a part/page."""
        doc_id = self.get_current_document_id()
        if not doc_id:
            return
            
        part_id, page_index = parse_page_id(page_id)
            
        # Store in coverage map
        self.coverage_map[doc_id][part_id] = {
            "part_id": part_id,
            "ocr_confidence": quality_res.ocr_confidence,
            "anchor_hits": quality_res.anchor_hits
        }
        
        # Store OCR text by page index
        if part_id not in self.part_ocr_texts[doc_id]:
            self.part_ocr_texts[doc_id][part_id] = {}
        self.part_ocr_texts[doc_id][part_id][page_index] = quality_res.ocr_text
        
        # Track completed pages/parts for backward compatibility
        self.completed_pages[doc_id].add(part_id)

    def record_extraction(self, page_id: str, fields_dict: dict, doc_id: Optional[str] = None):
        """Save flat extracted fields for backward compatibility."""
        target_doc_id = doc_id or self.get_current_document_id()
        if not target_doc_id:
            return
        if target_doc_id not in self.document_extracted_data:
            self.document_extracted_data[target_doc_id] = {}
            
        # Deep merge extracted values into self.document_extracted_data
        for k, v in fields_dict.items():
            self.document_extracted_data[target_doc_id][k] = copy.deepcopy(v)

    def mark_page_complete(self, page_id: str):
        # Mapped to record_part_result. Kept for gRPC service compatibility
        pass

    def record_upload(self, page_id: str, filename: str):
        doc_id = self.get_current_document_id()
        if doc_id:
            part_id, page_index = parse_page_id(page_id)
            if doc_id not in self.page_uploads:
                self.page_uploads[doc_id] = {}
            if part_id not in self.page_uploads[doc_id]:
                self.page_uploads[doc_id][part_id] = {}
            # Store filename/path by index
            self.page_uploads[doc_id][part_id][page_index] = filename

    def get_upload_count(self, page_id: str) -> int:
        doc_id = self.get_current_document_id()
        if doc_id:
            part_id, page_index = parse_page_id(page_id)
            uploads = self.page_uploads.get(doc_id, {}).get(part_id, {})
            return len(uploads)
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
