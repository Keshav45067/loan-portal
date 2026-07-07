from confidence_router import route_slot
from extraction import SlotResult

def test_route_slot_critical():
    slot_def = {"criticality": "critical"}
    bands = {
        "critical": { "accept": 0.92, "confirm": 0.75 },
        "standard": { "accept": 0.85, "confirm": 0.65 }
    }
    
    # Accept
    res = route_slot(SlotResult("doc_aadhaar_name", "Amit", 0.95, {}), slot_def, bands)
    assert res == "accept"
    
    # Confirm
    res = route_slot(SlotResult("doc_aadhaar_name", "Amit", 0.80, {}), slot_def, bands)
    assert res == "confirm"
    
    # Retake
    res = route_slot(SlotResult("doc_aadhaar_name", "Amit", 0.70, {}), slot_def, bands)
    assert res == "retake"

def test_route_slot_standard():
    slot_def = {"criticality": "standard"}
    bands = {
        "critical": { "accept": 0.92, "confirm": 0.75 },
        "standard": { "accept": 0.85, "confirm": 0.65 }
    }
    
    # Accept
    res = route_slot(SlotResult("gender", "MALE", 0.88, {}), slot_def, bands)
    assert res == "accept"
    
    # Confirm
    res = route_slot(SlotResult("gender", "MALE", 0.70, {}), slot_def, bands)
    assert res == "confirm"
    
    # Retake
    res = route_slot(SlotResult("gender", "MALE", 0.60, {}), slot_def, bands)
    assert res == "retake"

def test_route_slot_invalid():
    slot_def = {"criticality": "critical"}
    bands = {"critical": {"accept": 0.92, "confirm": 0.75}}
    
    # None value -> retake
    res = route_slot(SlotResult("name", None, 0.95, {}), slot_def, bands)
    assert res == "retake"
    
    # 0 confidence -> retake
    res = route_slot(SlotResult("name", "Amit", 0.0, {}), slot_def, bands)
    assert res == "retake"
