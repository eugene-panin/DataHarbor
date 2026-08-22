import logging
import os
import tempfile
from typing import Any

import requests

logger = logging.getLogger(__name__)

def check_gpu_support() -> bool:
    """Checks if CUDA or Apple Metal MPS GPU acceleration is available."""
    try:
        import torch
        if torch.cuda.is_available():
            return True
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return True
    except Exception:
        pass
    return False

def extract_ocr_from_image(image_input: str | Any) -> dict[str, Any]:
    """Extracts text embedded in banner images or video frame thumbnails via EasyOCR with GPU/MPS acceleration."""
    logger.info("Extracting OCR text from image source...")
    
    local_file_path = image_input
    temp_file_created = False
    
    # If URL, download to temp file
    if isinstance(image_input, str) and (image_input.startswith("http://") or image_input.startswith("https://")):
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
            local_file_path = temp_file.name
            temp_file_created = True
            temp_file.close()
            
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
            res = requests.get(image_input, headers=headers, timeout=15)
            with open(local_file_path, "wb") as f:
                f.write(res.content)
        except Exception as e:
            logger.error(f"Failed to download image from {image_input}: {e}")
            return {"status": "error", "ocr_text": "", "error": str(e)}

    try:
        from apps.ml import require_ml

        require_ml("easyocr")
        import easyocr
        use_gpu = check_gpu_support()
        logger.info(f"Running EasyOCR with hardware GPU acceleration: {use_gpu}")

        # Try Latin languages first (en, de, fr, es, it)
        try:
            reader = easyocr.Reader(['en', 'de', 'fr', 'es', 'it'], gpu=use_gpu)
            results = reader.readtext(local_file_path, detail=0)
        except Exception:
            # Fallback to Cyrillic + English
            reader = easyocr.Reader(['en', 'ru'], gpu=use_gpu)
            results = reader.readtext(local_file_path, detail=0)
            
        ocr_text = " ".join([str(t).strip() for t in results if str(t).strip()])
        
        logger.info(f"OCR Extraction Complete! Detected Text: '{ocr_text}'")
        return {
            "status": "success",
            "ocr_text": ocr_text,
            "detected_words_count": len(results),
            "gpu_accelerated": use_gpu
        }
    except Exception as e:
        logger.error(f"EasyOCR extraction error: {e}")
        return {
            "status": "error",
            "ocr_text": "",
            "error": str(e)
        }
    finally:
        if temp_file_created and isinstance(local_file_path, str) and os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except Exception:
                pass
