import pytest
from google_flow_mcp.models.credit_calculator import (
    calc_video_credits,
    calc_task_credits,
    parse_quantity_multiplier,
)


def test_parse_quantity_multiplier():
    assert parse_quantity_multiplier("x1") == 1
    assert parse_quantity_multiplier("x2") == 2
    assert parse_quantity_multiplier("x4") == 4
    assert parse_quantity_multiplier(" 3 ") == 3
    assert parse_quantity_multiplier(2) == 2
    assert parse_quantity_multiplier(None) == 1
    assert parse_quantity_multiplier("") == 1


def test_calc_video_credits_omni():
    # Omni 360p = 6 credits
    assert calc_video_credits(model_name="Omni 1.1 Flash", resolution="360p", quantity="x1") == 6
    # Omni 720p = 12 credits
    assert calc_video_credits(model_name="Omni 1.1 Flash", resolution="720p", quantity="x1") == 12
    # Omni default resolution = 12 credits
    assert calc_video_credits(model_name="Omni", resolution="", quantity="x1") == 12
    # Omni 720p x2 = 24 credits
    assert calc_video_credits(model_name="Omni 1.1 Flash", resolution="720p", quantity="x2") == 24
    # Omni 360p x4 = 24 credits
    assert calc_video_credits(model_name="Omni 1.1 Flash", resolution="360p", quantity="x4") == 24


def test_calc_video_credits_veo():
    # Veo Lite = 10 credits
    assert calc_video_credits(model_name="Veo 3.1 - Lite", quantity="x1") == 10
    assert calc_video_credits(model_name="veo lite", quantity="x2") == 20

    # Veo Fast = 20 credits
    assert calc_video_credits(model_name="Veo 3.1 - Fast", quantity="x1") == 20
    assert calc_video_credits(model_name="fast", quantity="x3") == 60

    # Veo Quality = 100 credits
    assert calc_video_credits(model_name="Veo 3.1 - Quality", quantity="x1") == 100
    assert calc_video_credits(model_name="quality", quantity="x2") == 200


def test_calc_task_credits():
    cost_omni = calc_task_credits("video_create", {"model_name": "Omni 1.1 Flash", "resolution": "720p", "quantity": "x1"})
    assert cost_omni == 12

    cost_veo = calc_task_credits("video", {"model_name": "Veo 3.1 - Lite", "quantity": "x1"})
    assert cost_veo == 10

    cost_image = calc_task_credits("image_create", {})
    assert cost_image == 1
