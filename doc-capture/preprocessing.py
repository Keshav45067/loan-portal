import io
from typing import List
from PIL import Image, ImageEnhance, ImageFilter

def auto_deskew(img: Image.Image) -> Image.Image:
    # Basic stub. Real deskew needs OpenCV or similar, but for now we'll just return it.
    return img

def remove_glare(img: Image.Image) -> Image.Image:
    # A simple way to reduce highlights without cv2 is lowering contrast slightly
    # and dropping brightness.
    enhancer = ImageEnhance.Brightness(img)
    img = enhancer.enhance(0.9)
    enhancer2 = ImageEnhance.Contrast(img)
    return enhancer2.enhance(0.95)

def enhance_contrast(img: Image.Image) -> Image.Image:
    enhancer = ImageEnhance.Contrast(img)
    return enhancer.enhance(1.2)

def crop_to_overlay(img: Image.Image) -> Image.Image:
    # Basic stub for center crop if requested
    # We assume the frontend already sent a decent crop, so we might just trim edges
    w, h = img.size
    margin_w = int(w * 0.05)
    margin_h = int(h * 0.05)
    return img.crop((margin_w, margin_h, w - margin_w, h - margin_h))

def sharpen(img: Image.Image) -> Image.Image:
    return img.filter(ImageFilter.SHARPEN)

PREPROCESSORS = {
    "auto_deskew": auto_deskew,
    "remove_glare": remove_glare,
    "enhance_contrast": enhance_contrast,
    "crop_to_overlay": crop_to_overlay,
    "sharpen": sharpen,
}

def preprocess_image(image_bytes: bytes, flags: List[str]) -> bytes:
    if not flags:
        return image_bytes
        
    try:
        img = Image.open(io.BytesIO(image_bytes))
        
        # Convert to RGB if needed (e.g. RGBA)
        if img.mode != 'RGB':
            img = img.convert('RGB')
            
        for flag in flags:
            func = PREPROCESSORS.get(flag)
            if func:
                img = func(img)
                
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=85)
        return out.getvalue()
    except Exception:
        # Fallback to original bytes on error
        return image_bytes
