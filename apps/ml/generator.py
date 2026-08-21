import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

def generate_winning_creative_script(cluster_id: int, cluster_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyzes a winning cluster of ad creatives and synthesizes a new ad script + AI visual prompt."""
    logger.info(f"Generating winning creative script for Cluster #{cluster_id} ({len(cluster_items)} items)...")
    
    if not cluster_items:
        return {"status": "error", "message": "Cluster contains no items"}

    # Extract aggregated transcripts, titles, and hooks from cluster
    titles = [item.get("title", "") for item in cluster_items if item.get("title")]
    speeches = [item.get("speech_transcript", "") for item in cluster_items if item.get("speech_transcript")]
    ocrs = [item.get("ocr_text", "") for item in cluster_items if item.get("ocr_text")]
    brands = [item.get("brand", "") for item in cluster_items if item.get("brand")]
    
    # Identify top performing media type in cluster
    types = [item.get("type", "video") for item in cluster_items]
    primary_type = max(set(types), key=types.count) if types else "video"
    
    # 1. Synthesize Hook & Value Proposition
    sample_hook = speeches[0] if speeches else (titles[0] if titles else "Discover the ultimate solution today.")
    sample_ocr = ocrs[0] if ocrs else "SPECIAL OFFER 50% OFF"
    
    # 2. Build New Winning Script Structure
    generated_script = f"""
🎬 NEW WINNING AD CREATIVE SCRIPT (Based on Cluster #{cluster_id})

[SCENE 1: HOOK (0-3 SEC)]
• Visual: High-energy opening shot of product in action with bold text overlay.
• Audio / Voiceover: "{sample_hook}"
• On-Screen Text: "{sample_ocr}"

[SCENE 2: PROBLEM & DEMO (3-10 SEC)]
• Visual: Split-screen comparison showing traditional struggle vs modern solution.
• Audio / Voiceover: "Say goodbye to outdated methods. Experience effortless results in just minutes a day."
• On-Screen Text: "100% Guaranteed Results • Rated 4.9/5 ★★★★★"

[SCENE 3: OFFER & CALL TO ACTION (10-15 SEC)]
• Visual: Product hero shot with discount badge and animated swipe-up arrow.
• Audio / Voiceover: "Claim your exclusive offer today before stock runs out!"
• On-Screen Text: "CLAIM 50% OFF TODAY -> SHOP NOW"
""".strip()

    # 3. Generate Image/Video Prompt for Sora / Runway / Midjourney
    ai_visual_prompt = f"Professional commercial advertisement shot of {brands[0] if brands else 'modern product'}, 8k resolution, cinematic lighting, vibrant colors, product-focused composition, hyperrealistic text overlay '{sample_ocr}', 4k hyper-detailed."
    
    return {
        "status": "success",
        "cluster_id": cluster_id,
        "primary_media_type": primary_type,
        "analyzed_items_count": len(cluster_items),
        "cluster_brands": list(set(brands)),
        "generated_script": generated_script,
        "ai_visual_prompt": ai_visual_prompt
    }
