import pytest
from PIL import Image
import io
from quality_metrics import QualityReport
from recovery_engine import decide_recovery, apply_recovery, RecoveryDecision

def test_decide_recovery_rotation():
    report = QualityReport(
        blur=250.0,
        brightness=0.5,
        contrast=0.2,
        noise=0.01,
        glare=0.01,
        shadow=0.01,
        rotation=5.0,  # rotated
        resolution={"width": 100, "height": 100}
    )
    policy = {"allow_deskew": True}
    decisions = decide_recovery(report, policy)
    assert len(decisions) == 1
    assert decisions[0].action == "auto_deskew"

def test_decide_recovery_blur_floor():
    report = QualityReport(
        blur=15.0,  # below unrecoverable floor 30.0
        brightness=0.5,
        contrast=0.2,
        noise=0.01,
        glare=0.01,
        shadow=0.01,
        rotation=0.0,
        resolution={"width": 100, "height": 100}
    )
    policy = {"allow_sharpen": True}
    decisions = decide_recovery(report, policy)
    # Under the floor, it returns empty (pipeline translates it directly to RETRY_USER without trying to recover)
    assert len(decisions) == 0

def test_decide_recovery_cap():
    report = QualityReport(
        blur=50.0,      # needs sharpen
        brightness=0.1,  # needs gamma
        contrast=0.05,  # needs contrast
        noise=0.05,
        glare=0.10,     # needs glare removal
        shadow=0.20,
        rotation=10.0,  # needs deskew
        resolution={"width": 100, "height": 100}
    )
    policy = {
        "allow_deskew": True,
        "allow_gamma": True,
        "allow_glare_removal": True,
        "allow_contrast_enhancement": True,
        "allow_sharpen": True
    }
    decisions = decide_recovery(report, policy)
    # Capped at 3 actions
    assert len(decisions) == 3

def test_apply_recovery_modifies_bytes():
    # Make a simple 10x10 white image
    img = Image.new('RGB', (10, 10), color='white')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    data = img_bytes.getvalue()
    
    # Let's apply a mock gamma decision
    decisions = [RecoveryDecision("gamma", "too dark")]
    recovered_data = apply_recovery(data, decisions)
    
    assert isinstance(recovered_data, bytes)
    assert len(recovered_data) > 0
