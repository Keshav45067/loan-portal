import re
from datetime import datetime
from typing import Tuple, Optional, Any, Dict, List
from log_utils.logger import get_logger

logger = get_logger("doc-capture")

class ValidationResult:
    def __init__(self, is_valid: bool, error_key: str = "", field_id: str = ""):
        self.is_valid = is_valid
        self.error_key = error_key
        self.field_id = field_id

class ValidationEngine:
    
    # Custom validation functions
    @staticmethod
    def _min_years(dob_value: str, min_age: int) -> bool:
        if not dob_value:
            return False
        try:
            # Assume DOB is in DD/MM/YYYY since date format was checked earlier
            parts = dob_value.split('/')
            if len(parts) != 3:
                return False
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            dob = datetime(y, m, d)
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age >= int(min_age)
        except Exception:
            return False

    @staticmethod
    def _max_years(dob_value: str, max_age: int) -> bool:
        if not dob_value:
            return False
        try:
            parts = dob_value.split('/')
            if len(parts) != 3:
                return False
            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
            dob = datetime(y, m, d)
            today = datetime.now()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            return age <= int(max_age)
        except Exception:
            return False

    @staticmethod
    def _min_value(value: Any, minimum: float) -> bool:
        try:
            return float(value) >= float(minimum)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _max_value(value: Any, maximum: float) -> bool:
        try:
            return float(value) <= float(maximum)
        except (ValueError, TypeError):
            return False

    @staticmethod
    def _min_length(value: str, length: int) -> bool:
        return len(str(value)) >= int(length)

    @staticmethod
    def _max_length(value: str, length: int) -> bool:
        return len(str(value)) <= int(length)

    def _get_validation_func(self, func_name: str):
        mapping = {
            "min_years": self._min_years,
            "max_years": self._max_years,
            "min_value": self._min_value,
            "max_value": self._max_value,
            "min_length": self._min_length,
            "max_length": self._max_length,
        }
        return mapping.get(func_name)

    def validate_page(self, fields_config: List[dict], extracted_data: Dict[str, dict]) -> ValidationResult:
        """
        Implements the exact 10-step validation process.
        """
        for field in fields_config:
            f_id = field.get("field_id")
            f_type = field.get("type", "string")
            is_mandatory = field.get("is_mandatory", False)
            field_conf_threshold = field.get("confidence_threshold", 0.0)
            
            ext_field = extracted_data.get(f_id, {})
            val = ext_field.get("value")
            conf = ext_field.get("confidence", 0.0)
            
            # Step 1: Check if exists or null
            if val is None or val == "":
                if not is_mandatory:
                    continue  # Skip to next field
                else:
                    return ValidationResult(False, "error_missing", f_id)
            
            # Step 2: Confidence check if mandatory
            if is_mandatory:
                if conf < field_conf_threshold:
                    return ValidationResult(False, "error_missing", f_id)
            
            # Step 3: Date type check
            if f_type == "date":
                fmt = field.get("date_format", "DD/MM/YYYY")
                # Basic safe parsing without crashing
                valid_date = False
                try:
                    if fmt == "DD/MM/YYYY":
                        parts = val.split('/')
                        if len(parts) == 3:
                            d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                            if 1 <= d <= 31 and 1 <= m <= 12 and 1900 <= y <= 2100:
                                valid_date = True
                except Exception:
                    pass
                    
                if not valid_date:
                    return ValidationResult(False, "error_invalid_format", f_id)
            
            # Step 4: Regex check (if not date, though regex could apply to anything)
            regex = field.get("regex")
            if regex:
                try:
                    if not re.search(regex, str(val)):
                        return ValidationResult(False, "error_invalid_format", f_id)
                except Exception as e:
                    logger.error(f"Invalid regex for {f_id}: {e}")
            
            # Step 5: Custom validations
            validations = field.get("validations", {})
            for func_name, args in validations.items():
                if not isinstance(args, list) or len(args) < 2:
                    continue
                    
                error_prompt_key = args[-1]
                func_args = args[:-1]
                
                func = self._get_validation_func(func_name)
                if func:
                    # Pass the value as first arg, then the rest
                    if not func(val, *func_args):
                        return ValidationResult(False, error_prompt_key, f_id)
                        
        return ValidationResult(True)

validation_engine = ValidationEngine()
