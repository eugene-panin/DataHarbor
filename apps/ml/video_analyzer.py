import logging
import os
import tempfile
from typing import Any

import cv2
import requests

from apps.ml.embeddings import generate_multimodal_embedding
from apps.ml.ocr import extract_ocr_from_image
from apps.ml.transcription import transcribe_audio_from_url_or_file

logger = logging.getLogger(__name__)

def extract_keyframes_from_video(video_path: str, max_frames: int = 5) -> list[str]:
    """Extracts keyframes from a video at uniform intervals and saves them as temp JPG files."""
    frame_paths = []
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        logger.error(f"Failed to open video file: {video_path}")
        return frame_paths
        
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    duration_sec = total_frames / fps
    
    logger.info(f"Analyzing video properties: {total_frames} frames, {fps:.1f} FPS, Duration: {duration_sec:.1f}s")
    
    if total_frames <= 0:
        cap.release()
        return frame_paths
        
    step = max(1, total_frames // max_frames)
    
    for i in range(0, total_frames, step):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue
            
        temp_img = tempfile.NamedTemporaryFile(delete=False, suffix=f"_frame_{i}.jpg")
        cv2.imwrite(temp_img.name, frame)
        temp_img.close()
        frame_paths.append(temp_img.name)
        
        if len(frame_paths) >= max_frames:
            break
            
    cap.release()
    logger.info(f"Extracted {len(frame_paths)} keyframes for visual OCR inspection.")
    return frame_paths

def analyze_full_video(video_source: str, brand_name: str = "Test Brand") -> dict[str, Any]:
    """Performs 360-degree multimodal analysis of a video (Speech Audio + Keyframe Visual OCR + Vector Embedding)."""
    logger.info(f"=== STARTING FULL MULTIMODAL VIDEO ANALYSIS FOR: {video_source} ===")
    
    local_file_path = video_source
    temp_file_created = False
    
    if video_source.startswith("http://") or video_source.startswith("https://"):
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        local_file_path = temp_file.name
        temp_file_created = True
        temp_file.close()
        
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        res = requests.get(video_source, headers=headers, stream=True, allow_redirects=True, timeout=30)
        with open(local_file_path, "wb") as f:
            for chunk in res.iter_content(chunk_size=65536):
                if chunk:
                    f.write(chunk)
                    
    # 1. AUDIO ANALYSIS (Faster-Whisper Speech Recognition)
    logger.info("--- Phase 1: Audio Speech Transcription (Whisper) ---")
    speech_result = transcribe_audio_from_url_or_file(local_file_path)
    speech_transcript = speech_result.get("transcript", "")
    language = speech_result.get("language", "unknown")
    
    # 2. VISUAL ANALYSIS (Keyframe Extraction & EasyOCR)
    logger.info("--- Phase 2: Visual Frame Extraction & OCR (EasyOCR) ---")
    frame_paths = extract_keyframes_from_video(local_file_path, max_frames=4)
    ocr_texts = []
    
    for idx, fpath in enumerate(frame_paths):
        try:
            ocr_res = extract_ocr_from_image(fpath)
            txt = ocr_res.get("ocr_text", "").strip()
            if txt and txt not in ocr_texts:
                ocr_texts.append(txt)
        finally:
            if os.path.exists(fpath):
                os.remove(fpath)
                
    combined_ocr_text = " | ".join(ocr_texts)
    logger.info(f"Aggregated Visual Frame OCR Text: '{combined_ocr_text}'")
    
    # 3. VECTOR EMBEDDING (512d OpenCLIP / SentenceTransformers)
    logger.info("--- Phase 3: Multimodal 512d Vector Generation ---")
    full_context = f"Brand: {brand_name} | Speech: {speech_transcript} | OnScreen Text: {combined_ocr_text}"
    vector_embedding = generate_multimodal_embedding(full_context, media_type="video")
    
    analysis_report = {
        "status": "success",
        "brand_name": brand_name,
        "language_detected": language,
        "speech_transcript": speech_transcript,
        "visual_ocr_text": combined_ocr_text,
        "full_semantic_payload": full_context,
        "embedding_vector_dim": len(vector_embedding),
        "embedding_vector_sample": vector_embedding[:5] # First 5 dims
    }
    
    if temp_file_created and os.path.exists(local_file_path):
        try:
            os.remove(local_file_path)
        except Exception:
            pass
            
    return analysis_report
