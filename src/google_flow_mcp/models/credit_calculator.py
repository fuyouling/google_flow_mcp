import re
from typing import Any, Dict
from loguru import logger


def parse_quantity_multiplier(quantity: Any) -> int:
    """Parse quantity string like 'x1', 'x2', 'x4' or int into an integer multiplier."""
    if isinstance(quantity, int):
        return max(1, quantity)
    if not quantity:
        return 1
    q_str = str(quantity).strip().lower()
    match = re.search(r"(\d+)", q_str)
    if match:
        try:
            return max(1, int(match.group(1)))
        except ValueError:
            return 1
    return 1


def calc_video_credits(
    model_name: str = "Omni 1.1 Flash",
    resolution: str = "720p",
    quantity: str = "x1",
) -> int:
    """
    Calculate required credits for a video generation task based on model, resolution, and quantity.

    Credit Rules:
    - Omni 1.1 Flash:
      - 360p: 6 credits
      - 720p (default): 12 credits
    - Veo 3.1 - Lite: 10 credits
    - Veo 3.1 - Fast: 20 credits
    - Veo 3.1 - Quality: 100 credits
    - Multiplier: base_credits * quantity
    """
    m_lower = (model_name or "").lower().strip()
    res_lower = (resolution or "720p").lower().strip()

    if "omni" in m_lower:
        if "360" in res_lower:
            base_credits = 6
        else:
            base_credits = 12
    elif "quality" in m_lower:
        base_credits = 100
    elif "fast" in m_lower:
        base_credits = 20
    elif "lite" in m_lower or "veo" in m_lower:
        base_credits = 10
    else:
        # Default fallback
        base_credits = 12

    multiplier = parse_quantity_multiplier(quantity)
    total_credits = base_credits * multiplier
    logger.debug(
        f"calc_video_credits: model={model_name}, resolution={resolution}, quantity={quantity} "
        f"-> base={base_credits} * {multiplier} = {total_credits}"
    )
    return total_credits


def calc_task_credits(task_type: str, params: Dict[str, Any]) -> int:
    """Generic entry point to calculate credit cost for any generation task."""
    tt = (task_type or "").lower()
    if "video" in tt:
        model = params.get("model_name", "Omni 1.1 Flash")
        resolution = params.get("resolution", "720p")
        quantity = params.get("quantity", "x1")
        return calc_video_credits(model, resolution, quantity)
    # Default for image or character creation if any in future
    return 1
