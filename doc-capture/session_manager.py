import copy
import json
from typing import Dict, List, Set, Optional, Tuple, Any
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
        self.language = language or "en"
        
        # Scheme-level state
        self.scheme_config: dict = {}
        self.slots: List[dict] = []  # Normalized slot objects
        self.slot_selections: Dict[str, str] = {}  # {slot_id: selected_doc_id}
        self.current_slot_index: int = 0
        
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

    @property
    def current_document_index(self) -> int:
        return self.current_slot_index

    @current_document_index.setter
    def current_document_index(self, value: int):
        self.current_slot_index = value

    @property
    def required_documents(self) -> List[str]:
        """Dynamically list active doc_ids (or first candidate option) for backward compatibility."""
        docs = []
        for slot in self.slots:
            sel = slot.get("selected_doc_id")
            if sel:
                docs.append(sel)
            elif slot.get("options"):
                docs.append(slot["options"][0].get("doc_id", slot.get("slot_id")))
            else:
                docs.append(slot.get("slot_id", ""))
        return docs

    def reset(self):
        """Reset capture session state completely for redo / start over."""
        self.current_slot_index = 0
        self.current_page_index = 0
        self.coverage_map.clear()
        self.part_ocr_texts.clear()
        self.document_extracted_data.clear()
        self.completed_documents.clear()
        self.completed_pages.clear()
        self.page_uploads.clear()
        self.variable_parts_completed.clear()
        self.pending_retakes.clear()
        self.failed_reasons.clear()
        self.faq_history.clear()
        self.slot_selections.clear()
        # Reset selections on multi-option slots
        for slot in self.slots:
            if len(slot.get("options", [])) > 1:
                slot["selected_doc_id"] = None
            else:
                slot["selected_doc_id"] = slot["options"][0].get("doc_id") if slot.get("options") else None
        self._load_current_document()

    def initialize(self) -> bool:
        """Load scheme and initialize slots."""
        scheme = config_loader.get_scheme(self.scheme_id)
        if not scheme:
            logger.error(f"Scheme not found: {self.scheme_id}")
            return False
            
        self.scheme_config = copy.deepcopy(scheme)
        raw_required = self.scheme_config.get("required_documents", [])
        
        if not raw_required:
            logger.error(f"No required documents in scheme {self.scheme_id}")
            return False
            
        self.slots = []
        for idx, item in enumerate(raw_required):
            if isinstance(item, str):
                manifest = config_loader.get_manifest(item)
                doc_title = manifest.get("title", {}) if manifest else {"English": item}
                self.slots.append({
                    "slot_id": item,
                    "slot_name": doc_title,
                    "description": {},
                    "options": [{"doc_id": item, "name": doc_title}],
                    "selected_doc_id": item,
                    "status": "PENDING"
                })
                self.slot_selections[item] = item
            elif isinstance(item, dict):
                slot_id = item.get("slot_id", f"slot_{idx}")
                slot_name = item.get("slot_name", {"English": slot_id})
                desc = item.get("description", {})
                options = item.get("options", [])
                selected_doc_id = None
                if len(options) == 1:
                    selected_doc_id = options[0].get("doc_id")
                    self.slot_selections[slot_id] = selected_doc_id
                self.slots.append({
                    "slot_id": slot_id,
                    "slot_name": slot_name,
                    "description": desc,
                    "options": options,
                    "selected_doc_id": selected_doc_id,
                    "status": "PENDING"
                })
        
        self.current_slot_index = 0
        return self._load_current_document()

    def get_current_slot(self) -> Optional[dict]:
        if 0 <= self.current_slot_index < len(self.slots):
            return self.slots[self.current_slot_index]
        return None

    def get_slot(self, slot_id: str) -> Optional[dict]:
        for s in self.slots:
            if s.get("slot_id") == slot_id or s.get("slot_id", "").lower() == slot_id.lower():
                return s
        return None

    def get_slot_for_doc(self, doc_id: str) -> Optional[dict]:
        for s in self.slots:
            if s.get("selected_doc_id") == doc_id:
                return s
            for opt in s.get("options", []):
                if opt.get("doc_id") == doc_id or opt.get("doc_id", "").lower() == doc_id.lower():
                    return s
        return None

    def select_slot_option(self, slot_id: str, doc_id: str) -> bool:
        """Select which document option to use for a slot."""
        slot = self.get_slot(slot_id)
        if not slot:
            slot = self.get_slot_for_doc(doc_id)
        if not slot:
            logger.warning(f"select_slot_option: Slot '{slot_id}' or doc '{doc_id}' not found")
            return False

        # Validate doc_id is among allowed options
        matched_doc_id = None
        for opt in slot.get("options", []):
            opt_id = opt.get("doc_id", "")
            opt_en = opt.get("name", {}).get("English", "").lower()
            opt_hi = opt.get("name", {}).get("Hindi", "").lower()
            d_lower = doc_id.lower().strip()
            if opt_id.lower() == d_lower or opt_en == d_lower or opt_hi == d_lower or d_lower in opt_id.lower() or d_lower in opt_en:
                matched_doc_id = opt_id
                break

        if not matched_doc_id:
            logger.warning(f"select_slot_option: Doc '{doc_id}' not allowed for slot '{slot.get('slot_id')}'")
            return False

        slot["selected_doc_id"] = matched_doc_id
        self.slot_selections[slot["slot_id"]] = matched_doc_id
        
        # Set active slot to this slot
        self.current_slot_index = self.slots.index(slot)
        self._load_current_document()
        self.current_page_index = 0
        logger.info(f"select_slot_option: Selected '{matched_doc_id}' for slot '{slot.get('slot_id')}'")
        return True

    def _load_current_document(self) -> bool:
        """Load the document config for current_slot_index."""
        slot = self.get_current_slot()
        if not slot:
            self.current_document_config = {}
            return True
            
        doc_id = slot.get("selected_doc_id")
        if not doc_id:
            # Slot is pending option selection
            self.current_document_config = {}
            self.current_page_index = 0
            return True

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
        slot = self.get_current_slot()
        if slot:
            return slot.get("selected_doc_id") or ""
        return ""

    def set_active_document(self, doc_id_or_slot_id: str, part_id: Optional[str] = None) -> bool:
        """Explicitly switch the session active document / slot and page index."""
        target = (doc_id_or_slot_id or "").lower().strip()
        
        # 1. Check if matches slot_id
        for idx, s in enumerate(self.slots):
            s_id = s.get("slot_id", "").lower()
            s_en = s.get("slot_name", {}).get("English", "").lower()
            s_hi = s.get("slot_name", {}).get("Hindi", "").lower()
            if target == s_id or target == s_en or target == s_hi or target in s_id or target in s_en:
                self.current_slot_index = idx
                self._load_current_document()
                if part_id and self.current_document_config:
                    parts = self.current_document_config.get("parts", [])
                    for p_idx, p in enumerate(parts):
                        if p.get("id") == part_id or p.get("name", {}).get("English", "").lower() == part_id.lower():
                            self.current_page_index = p_idx
                            break
                else:
                    self.current_page_index = 0
                return True

        # 2. Check if matches a doc_id or option in any slot
        for idx, s in enumerate(self.slots):
            for opt in s.get("options", []):
                opt_id = opt.get("doc_id", "").lower()
                opt_en = opt.get("name", {}).get("English", "").lower()
                opt_hi = opt.get("name", {}).get("Hindi", "").lower()
                if target == opt_id or target == opt_en or target == opt_hi or target in opt_id or target in opt_en:
                    # Select this option for the slot and activate
                    s["selected_doc_id"] = opt.get("doc_id")
                    self.slot_selections[s["slot_id"]] = opt.get("doc_id")
                    self.current_slot_index = idx
                    self._load_current_document()
                    if part_id and self.current_document_config:
                        parts = self.current_document_config.get("parts", [])
                        for p_idx, p in enumerate(parts):
                            if p.get("id") == part_id or p.get("name", {}).get("English", "").lower() == part_id.lower():
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
            
        if self.pending_retakes.get(doc_id, {}).get(part_id):
            return False

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
            has_upload = len(uploaded_pages) >= 1
            is_marked = part_id in self.variable_parts_completed.get(doc_id, set())
            return has_upload and is_marked
            
        return False

    def is_coverage_complete(self) -> bool:
        if not self.current_document_config:
            return False
        doc_id = self.get_current_document_id()
        if not doc_id:
            return False
        parts = self.current_document_config.get("parts", [])
        return all(self.is_part_covered(part.get("id")) for part in parts)

    def get_current_page(self) -> Optional[dict]:
        """
        Returns page representation. If current slot has no selected option,
        returns an interactive SLOT_SELECTION page descriptor.
        """
        slot = self.get_current_slot()
        if not slot:
            return None

        lang_key = "Hindi" if self.language == "hi" else ("French" if self.language == "fr" else ("Arabic" if self.language == "ar" else "English"))
        slot_name_loc = slot.get("slot_name", {}).get(lang_key, slot.get("slot_name", {}).get("English", slot.get("slot_id", "")))

        # 1. Slot is pending selection
        if not slot.get("selected_doc_id"):
            options_formatted = []
            for opt in slot.get("options", []):
                opt_doc_id = opt.get("doc_id", "")
                manifest = config_loader.get_manifest(opt_doc_id)
                opt_title = opt.get("name", {})
                if not opt_title and manifest:
                    opt_title = manifest.get("title", {})
                options_formatted.append({
                    "doc_id": opt_doc_id,
                    "name": opt_title.get(lang_key, opt_title.get("English", opt_doc_id)),
                    "name_dict": opt_title,
                    "parts_count": len(manifest.get("parts", [])) if manifest else 1
                })

            options_names_en = ", ".join([o.get("name_dict", {}).get("English", o["doc_id"]) for o in options_formatted])
            options_names_hi = ", ".join([o.get("name_dict", {}).get("Hindi", o.get("name_dict", {}).get("English", o["doc_id"])) for o in options_formatted])

            intro_prompts = {
                "en": f"Please select which document you would like to provide for {slot_name_loc}: {options_names_en}. You can tap an option or just tell me.",
                "hi": f"कृपया {slot_name_loc} के लिए दस्तावेज़ चुनें: {options_names_hi}। आप विकल्प पर टैप कर सकते हैं या मुझे बता सकते हैं।",
                "fr": f"Veuillez sélectionner le document pour {slot_name_loc}.",
                "ar": f"يرجى تحديد الوثيقة لـ {slot_name_loc}."
            }

            return {
                "page_id": f"slot_select_{slot.get('slot_id')}",
                "page_name": f"Select Document ({slot_name_loc})",
                "is_slot_selection": True,
                "slot_id": slot.get("slot_id"),
                "slot_name": slot_name_loc,
                "slot_description": slot.get("description", {}).get(lang_key, slot.get("description", {}).get("English", "")),
                "options": options_formatted,
                "allow_multiple": False,
                "ui_camera_overlay": "slot_selection",
                "intro_prompt_json": json.dumps(intro_prompts),
                "success_prompt_json": json.dumps({"en": "Option selected"}),
                "error_blur_prompt_json": json.dumps({}),
                "error_invalid_doc_prompt_json": json.dumps({}),
                "acceptable_formats": [],
                "max_file_size_mb": 10,
                "orientation": "portrait"
            }

        # 2. Document selected — return active part
        if not self.current_document_config:
            return None
            
        manifest = self.current_document_config
        parts = manifest.get("parts", [])

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
        
        retakes = self.pending_retakes.get(doc_id, {}).get(part_id, set())
        is_retake = False
        page_index = 1
        
        if retakes:
            is_retake = True
            page_index = sorted(list(retakes))[0]
        else:
            if page_count == 0 or page_count > 1:
                uploaded = self.part_ocr_texts.get(doc_id, {}).get(part_id, {})
                page_index = len(uploaded) + 1
                
        if page_count == 0 or page_count > 1:
            page_id = f"{part_id}_{page_index}"
        else:
            page_id = part_id
            
        lang_prompts = manifest.get("prompts", {})
        ask_part_template = lang_prompts.get("ask_part", {})
        
        document_title_en = manifest.get("title", {}).get("English", "Document")
        document_title_hi = manifest.get("title", {}).get("Hindi", document_title_en)
        
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
        
        if is_retake:
            reasons = self.failed_reasons.get(doc_id, {}).get(part_id, {}).get(page_index, [])
            if reasons:
                reasons_joined = ", ".join(reasons)
                intro_prompts["en"] = f"Verification failed on page {page_index} due to unclear details in: {reasons_joined}. Please capture page {page_index} again."
                intro_prompts["hi"] = f"अस्पष्ट विवरण ({reasons_joined}) के कारण पृष्ठ {page_index} का सत्यापन विफल रहा। कृपया पृष्ठ {page_index} को फिर से कैप्चर करें।"
                intro_prompts["fr"] = f"Échec de la vérification à la page {page_index}. Veuillez recapturer la page {page_index}."
                intro_prompts["ar"] = f"فشلت عملية التحقق في الصفحة {page_index}. يرجى التقاط الصفحة {page_index} مرة أخرى."
            
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
        
        sources = manifest.get("sources", [{}])
        first_source = sources[0] if sources else {}
        
        base_name_en = part.get("name", {}).get("English", part_id)
        if page_count == 0 or page_count > 1:
            if is_retake:
                page_name = f"{base_name_en} - Page {page_index} (Retake)"
            else:
                page_name = f"{base_name_en} - Page {page_index}"
        else:
            page_name = base_name_en
            
        orientation = part.get("orientation", "landscape")
        ui_camera_overlay = part.get("ui_camera_overlay", manifest.get("ui_camera_overlay", "landscape_id"))

        return {
            "page_id": page_id,
            "page_name": page_name,
            "is_slot_selection": False,
            "slot_id": slot.get("slot_id"),
            "slot_name": slot_name_loc,
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
        """Check if all slots in the scheme have completed documents."""
        if not self.slots:
            return False
        for slot in self.slots:
            sel_doc = slot.get("selected_doc_id")
            if not sel_doc or sel_doc not in self.completed_documents:
                return False
        return True
        
    def advance_page(self) -> Tuple[bool, bool]:
        """Advance to next part or slot. Returns (page_advanced, document_advanced)."""
        slot = self.get_current_slot()
        if not slot:
            return False, False
            
        doc_id = self.get_current_document_id()
        
        if self.is_coverage_complete():
            if doc_id:
                self.completed_documents.add(doc_id)
            
            if self.is_all_complete():
                self.current_slot_index = len(self.slots)
                return True, True

            # Advance forward to next pending slot
            start_idx = self.current_slot_index
            total = len(self.slots)
            found_next = False

            for step in range(1, total + 1):
                check_idx = (start_idx + step) % total
                candidate_slot = self.slots[check_idx]
                candidate_doc = candidate_slot.get("selected_doc_id")
                if not candidate_doc or candidate_doc not in self.completed_documents:
                    self.current_slot_index = check_idx
                    self.current_page_index = 0
                    self._load_current_document()
                    found_next = True
                    break

            if not found_next:
                self.current_slot_index = len(self.slots)

            return True, True
        else:
            self.current_page_index += 1
            return True, False

    def record_part_result(self, page_id: str, quality_res):
        doc_id = self.get_current_document_id()
        if not doc_id:
            return
            
        part_id, page_index = parse_page_id(page_id)
        self.coverage_map[doc_id][part_id] = {
            "part_id": part_id,
            "ocr_confidence": quality_res.ocr_confidence,
            "anchor_hits": quality_res.anchor_hits
        }
        
        if part_id not in self.part_ocr_texts[doc_id]:
            self.part_ocr_texts[doc_id][part_id] = {}
        self.part_ocr_texts[doc_id][part_id][page_index] = quality_res.ocr_text
        self.completed_pages[doc_id].add(part_id)

    def record_extraction(self, page_id: str, fields_dict: dict, doc_id: Optional[str] = None):
        target_doc_id = doc_id or self.get_current_document_id()
        if not target_doc_id:
            return
        if target_doc_id not in self.document_extracted_data:
            self.document_extracted_data[target_doc_id] = {}
        for k, v in fields_dict.items():
            self.document_extracted_data[target_doc_id][k] = copy.deepcopy(v)

    def mark_page_complete(self, page_id: str):
        pass

    def record_upload(self, page_id: str, filename: str):
        doc_id = self.get_current_document_id()
        if doc_id:
            part_id, page_index = parse_page_id(page_id)
            if doc_id not in self.page_uploads:
                self.page_uploads[doc_id] = {}
            if part_id not in self.page_uploads[doc_id]:
                self.page_uploads[doc_id][part_id] = {}
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
