import logging
import os
import tempfile
from typing import Any

import requests

logger = logging.getLogger(__name__)

def resolve_whisper_device() -> tuple[str, str]:
    """Auto-detects optimal device and compute_type for Faster-Whisper (CUDA/MPS/CPU)."""
    try:
        import torch
        if torch.cuda.is_available():
            logger.info("NVIDIA CUDA detected for Faster-Whisper (device='cuda', compute_type='float16')")
            return "cuda", "float16"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("Apple Silicon Metal MPS detected for Faster-Whisper (device='auto', compute_type='int8')")
            return "auto", "int8"
    except Exception:
        pass
    return "cpu", "int8"

def transcribe_audio_from_url_or_file(source_path_or_url: str) -> dict[str, Any]:
    """Downloads video/audio from URL or local file, runs Faster-Whisper with hardware acceleration, and returns exact speech transcript."""
    logger.info(f"Transcribing audio/video from: {source_path_or_url}")
    
    local_file_path = source_path_or_url
    temp_file_created = False
    
    # If source is HTTP URL, download to temp file
    if source_path_or_url.startswith("http://") or source_path_or_url.startswith("https://"):
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            local_file_path = temp_file.name
            temp_file_created = True
            temp_file.close()
            
            logger.info(f"Downloading video stream to temp file: {local_file_path}")
            headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"}
            res = requests.get(source_path_or_url, headers=headers, stream=True, allow_redirects=True, timeout=30)
            with open(local_file_path, "wb") as f:
                for chunk in res.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)
            logger.info(f"Downloaded {os.path.getsize(local_file_path)} bytes for transcription")
        except Exception as e:
            logger.error(f"Failed to download video from {source_path_or_url}: {e}")
            return {"status": "error", "transcript": "", "error": str(e)}

    try:
        from apps.ml import require_ml

        require_ml("faster_whisper")
        from faster_whisper import WhisperModel
        device, compute_type = resolve_whisper_device()
        logger.info(f"Loading Faster-Whisper ('tiny') model on device='{device}', compute_type='{compute_type}'...")
        model = WhisperModel("tiny", device=device, compute_type=compute_type)
        
        segments, info = model.transcribe(local_file_path, beam_size=5)
        transcript_text = " ".join([segment.text.strip() for segment in segments if segment.text.strip()])
        
        logger.info(f"Whisper Transcription Complete! Language: {info.language}, Score: {info.language_probability:.2f}")
        logger.info(f"Transcript Text: '{transcript_text}'")
        
        return {
            "status": "success",
            "transcript": transcript_text,
            "language": info.language,
            "language_probability": round(info.language_probability, 3),
            "device": device
        }
    except Exception as e:
        logger.error(f"Faster-Whisper transcription error: {e}")
        return {
            "status": "error",
            "transcript": "",
            "error": str(e)
        }
    finally:
        if temp_file_created and os.path.exists(local_file_path):
            try:
                os.remove(local_file_path)
            except Exception:
                pass
