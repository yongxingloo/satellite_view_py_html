"""pytest tests for app.py

Run from the repository root with:
    pip install -r requirements.txt
    pytest test_webapp.py -v
"""

import pytest
from app import (
    to_date_input,
    build_initial_state,
    clamp_number,
    validate_bbox,
    validate_date_range,
    bbox_area,
    intersect_bboxes,
    compute_coverage_score,
    scene_fully_covers_bbox,
    resolve_frame_source,
    resolve_fallback_preview_url,
    resolve_renderable_item_url,
    collection_ids_for,
    parse_search_request,
    dedupe_scenes_by_day,
    refine_scene_sequence,
    compute_timeline_stats,
)
from datetime import date


def test_to_date_input_basic():
    assert to_date_input(date(2024, 1, 5)) == "2024-01-05"

def test_to_date_input_end_of_year():
    assert to_date_input(date(2023, 12, 31)) == "2023-12-31"


def test_build_initial_state_keys():
    state = build_initial_state()
    for key in ("default_center", "default_zoom", "default_bbox",
                "default_collection", "default_start_date", "default_end_date",
                "default_cloud", "default_limit", "default_sequence_mode"):
        assert key in state

def test_build_initial_state_defaults():
    state = build_initial_state()
    assert state["default_cloud"] == 25
    assert state["default_limit"] == 20
    assert state["default_sequence_mode"] == "balanced"
    assert state["default_collection"] == "sentinel-2-l2a"


def test_clamp_number_within_range():
    assert clamp_number(50, 0, 100, 25) == 50.0

def test_clamp_number_below_min():
    assert clamp_number(-10, 0, 100, 25) == 0.0

def test_clamp_number_above_max():
    assert clamp_number(200, 0, 100, 25) == 100.0

def test_clamp_number_on_boundary():
    assert clamp_number(0, 0, 100, 25) == 0.0
    assert clamp_number(100, 0, 100, 25) == 100.0

def test_clamp_number_non_numeric_uses_fallback():
    assert clamp_number("abc", 0, 100, 25) == 25.0

def test_clamp_number_none_uses_fallback():
    assert clamp_number(None, 0, 100, 25) == 25.0

def test_clamp_number_string_numeric():
    assert clamp_number("42", 0, 100, 25) == 42.0


def test_validate_bbox_valid():
    result = validate_bbox([-10.0, -5.0, 10.0, 5.0])
    assert result == [-10.0, -5.0, 10.0, 5.0]

def test_validate_bbox_rounds_to_5_decimals():
    result = validate_bbox([-10.123456789, -5.0, 10.0, 5.0])
    assert result[0] == round(-10.123456789, 5)

def test_validate_bbox_not_a_list():
    with pytest.raises(ValueError):
        validate_bbox("not a list")

def test_validate_bbox_wrong_length():
    with pytest.raises(ValueError):
        validate_bbox([1, 2, 3])

def test_validate_bbox_west_equals_east():
    with pytest.raises(ValueError):
        validate_bbox([5.0, -5.0, 5.0, 5.0])

def test_validate_bbox_west_greater_than_east():
    with pytest.raises(ValueError):
        validate_bbox([10.0, -5.0, 5.0, 5.0])

def test_validate_bbox_south_equals_north():
    with pytest.raises(ValueError):
        validate_bbox([-10.0, 5.0, 10.0, 5.0])


def test_validate_date_range_valid():
    start, end = validate_date_range("2023-01-01", "2023-12-31")
    assert start == "2023-01-01"
    assert end == "2023-12-31"

def test_validate_date_range_same_day():
    start, end = validate_date_range("2023-06-15", "2023-06-15")
    assert start == end == "2023-06-15"

def test_validate_date_range_reversed():
    with pytest.raises(ValueError):
        validate_date_range("2023-12-31", "2023-01-01")

def test_validate_date_range_invalid_format():
    with pytest.raises(ValueError):
        validate_date_range("01/01/2023", "2023-12-31")

def test_bbox_area_basic():
    area = bbox_area([0.0, 0.0, 2.0, 3.0])
    assert area == pytest.approx(6.0)

def test_bbox_area_zero_width():
    assert bbox_area([1.0, 0.0, 1.0, 5.0]) == 0.0

def test_bbox_area_none():
    assert bbox_area(None) == 0.0

def test_bbox_area_empty_list():
    assert bbox_area([]) == 0.0


def test_intersect_bboxes_overlap():
    result = intersect_bboxes([0.0, 0.0, 4.0, 4.0], [2.0, 2.0, 6.0, 6.0])
    assert result == [2.0, 2.0, 4.0, 4.0]

def test_intersect_bboxes_no_overlap():
    result = intersect_bboxes([0.0, 0.0, 1.0, 1.0], [2.0, 2.0, 3.0, 3.0])
    assert result is None

def test_intersect_bboxes_touching_edge():
    result = intersect_bboxes([0.0, 0.0, 2.0, 2.0], [2.0, 0.0, 4.0, 2.0])
    assert result is None  # touching but not overlapping

def test_intersect_bboxes_one_none():
    assert intersect_bboxes(None, [0.0, 0.0, 1.0, 1.0]) is None
    assert intersect_bboxes([0.0, 0.0, 1.0, 1.0], None) is None

def test_intersect_bboxes_fully_contained():
    result = intersect_bboxes([0.0, 0.0, 10.0, 10.0], [2.0, 2.0, 5.0, 5.0])
    assert result == [2.0, 2.0, 5.0, 5.0]

def test_compute_coverage_score_full():
    # Scene fully contains target → score == 1.0
    score = compute_coverage_score([0.0, 0.0, 10.0, 10.0], [2.0, 2.0, 5.0, 5.0])
    assert score == pytest.approx(1.0)

def test_compute_coverage_score_none():
    assert compute_coverage_score(None, [0.0, 0.0, 1.0, 1.0]) == 0.0
    assert compute_coverage_score([0.0, 0.0, 1.0, 1.0], None) == 0.0

def test_compute_coverage_score_no_overlap():
    score = compute_coverage_score([0.0, 0.0, 1.0, 1.0], [2.0, 2.0, 3.0, 3.0])
    assert score == 0.0

def test_compute_coverage_score_partial():
    # scene covers half of target
    score = compute_coverage_score([0.0, 0.0, 5.0, 4.0], [0.0, 0.0, 10.0, 4.0])
    assert score == pytest.approx(0.5)

def test_scene_fully_covers_bbox_true():
    assert scene_fully_covers_bbox([-1.0, -1.0, 5.0, 5.0], [0.0, 0.0, 4.0, 4.0]) is True

def test_scene_fully_covers_bbox_false():
    assert scene_fully_covers_bbox([1.0, 1.0, 3.0, 3.0], [0.0, 0.0, 4.0, 4.0]) is False

def test_scene_fully_covers_bbox_exact_match():
    assert scene_fully_covers_bbox([0.0, 0.0, 4.0, 4.0], [0.0, 0.0, 4.0, 4.0]) is True

def test_scene_fully_covers_bbox_none():
    assert scene_fully_covers_bbox(None, [0.0, 0.0, 1.0, 1.0]) is False
    assert scene_fully_covers_bbox([0.0, 0.0, 1.0, 1.0], None) is False


def _item_with_assets(assets):
    return {"assets": assets, "links": []}

def test_resolve_frame_source_rgb_bands_named():
    item = _item_with_assets({
        "red": {"href": "http://r"}, "green": {"href": "http://g"}, "blue": {"href": "http://b"}
    })
    result = resolve_frame_source(item)
    assert result == {"type": "rgb-bands", "asset_keys": ["red", "green", "blue"]}

def test_resolve_frame_source_sentinel_bands():
    item = _item_with_assets({
        "B04": {"href": "http://b4"}, "B03": {"href": "http://b3"}, "B02": {"href": "http://b2"}
    })
    result = resolve_frame_source(item)
    assert result == {"type": "rgb-bands", "asset_keys": ["B04", "B03", "B02"]}

def test_resolve_frame_source_visual_asset():
    item = _item_with_assets({"visual": {"href": "http://vis"}})
    result = resolve_frame_source(item)
    assert result == {"type": "single-asset", "asset_keys": ["visual"]}

def test_resolve_frame_source_thumbnail_link():
    item = {"assets": {}, "links": [{"rel": "thumbnail", "href": "http://thumb.png"}]}
    result = resolve_frame_source(item)
    assert result == {"type": "preview-image", "href": "http://thumb.png"}

def test_resolve_frame_source_no_assets():
    item = {"assets": {}, "links": []}
    assert resolve_frame_source(item) is None


def test_resolve_fallback_preview_url_with_preview_image():
    item = {"assets": {"thumbnail": {"href": "http://preview.png"}}, "links": []}
    assert resolve_fallback_preview_url(item) == "http://preview.png"

def test_resolve_fallback_preview_url_no_preview():
    item = _item_with_assets({
        "red": {"href": "http://r"}, "green": {"href": "http://g"}, "blue": {"href": "http://b"}
    })
    # RGB bands → not a preview-image type → empty string
    assert resolve_fallback_preview_url(item) == ""


def test_resolve_renderable_item_url_self_link():
    item = {"links": [{"rel": "self", "href": "http://self.link"}], "collection": "sentinel-2-l2a"}
    assert resolve_renderable_item_url(item) == "http://self.link"

def test_resolve_renderable_item_url_landsat_via():
    item = {
        "collection": "landsat-c2-l2",
        "links": [
            {"rel": "via", "href": "https://example.com/landsat-c2l2-sr/item"},
            {"rel": "self", "href": "http://self.link"},
        ],
    }
    assert "landsat-c2l2-sr" in resolve_renderable_item_url(item)

def test_resolve_renderable_item_url_no_links():
    item = {"links": [], "collection": "sentinel-2-l2a"}
    assert resolve_renderable_item_url(item) == ""


def test_collection_ids_for_sentinel():
    assert collection_ids_for("sentinel-2-l2a") == ["sentinel-2-l2a"]

def test_collection_ids_for_landsat():
    assert collection_ids_for("landsat-c2-l2") == ["landsat-c2-l2"]

def test_collection_ids_for_merged():
    result = collection_ids_for("merged")
    assert "sentinel-2-l2a" in result
    assert "landsat-c2-l2" in result
    assert len(result) == 2


_VALID_PAYLOAD = {
    "collection": "sentinel-2-l2a",
    "sequence_mode": "balanced",
    "bbox": [-10.0, -5.0, 10.0, 5.0],
    "start_date": "2023-01-01",
    "end_date": "2023-12-31",
    "max_cloud": 30,
    "limit": 50,
}

def test_parse_search_request_valid():
    result = parse_search_request(_VALID_PAYLOAD)
    assert result["collection"] == "sentinel-2-l2a"
    assert result["bbox"] == [-10.0, -5.0, 10.0, 5.0]
    assert result["max_cloud"] == 30
    assert result["limit"] == 50

def test_parse_search_request_invalid_collection():
    bad = {**_VALID_PAYLOAD, "collection": "unsupported-thing"}
    with pytest.raises(ValueError):
        parse_search_request(bad)

def test_parse_search_request_invalid_sequence_mode():
    bad = {**_VALID_PAYLOAD, "sequence_mode": "random"}
    with pytest.raises(ValueError):
        parse_search_request(bad)

def test_parse_search_request_invalid_bbox():
    bad = {**_VALID_PAYLOAD, "bbox": [10.0, 0.0, 5.0, 5.0]}  # west > east
    with pytest.raises(ValueError):
        parse_search_request(bad)

def test_parse_search_request_clamps_cloud():
    payload = {**_VALID_PAYLOAD, "max_cloud": 999}
    result = parse_search_request(payload)
    assert result["max_cloud"] == 100

def test_parse_search_request_clamps_limit():
    payload = {**_VALID_PAYLOAD, "limit": 1}
    result = parse_search_request(payload)
    assert result["limit"] == 5


def _make_scene(dt, cloud=10, coverage=1.0, scene_id="s1", collection="sentinel-2-l2a"):
    return {
        "id": scene_id,
        "datetime": dt,
        "cloud_cover": cloud,
        "coverage_score": coverage,
        "collection": collection,
        "frame_url": "http://x",
        "full_coverage": True,
    }

def test_dedupe_scenes_by_day_keeps_best_coverage():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=0.5, scene_id="a"),
        _make_scene("2023-06-01T14:00:00Z", coverage=0.9, scene_id="b"),
    ]
    result = dedupe_scenes_by_day(scenes, merged_mode=False)
    assert len(result) == 1
    assert result[0]["id"] == "b"

def test_dedupe_scenes_by_day_keeps_lowest_cloud_when_equal_coverage():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", cloud=20, coverage=1.0, scene_id="a"),
        _make_scene("2023-06-01T14:00:00Z", cloud=5, coverage=1.0, scene_id="b"),
    ]
    result = dedupe_scenes_by_day(scenes, merged_mode=False)
    assert len(result) == 1
    assert result[0]["id"] == "b"

def test_dedupe_scenes_by_day_different_days():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", scene_id="a"),
        _make_scene("2023-06-02T10:00:00Z", scene_id="b"),
    ]
    result = dedupe_scenes_by_day(scenes, merged_mode=False)
    assert len(result) == 2

def test_dedupe_scenes_by_day_merged_mode_keeps_per_collection():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", scene_id="s2", collection="sentinel-2-l2a"),
        _make_scene("2023-06-01T10:00:00Z", scene_id="ls", collection="landsat-c2-l2"),
    ]
    result = dedupe_scenes_by_day(scenes, merged_mode=True)
    assert len(result) == 2


def test_refine_scene_sequence_empty():
    assert refine_scene_sequence([], "balanced", False) == []

def test_refine_scene_sequence_strict_prefers_full_coverage():
    # strict mode prefers full_coverage=True scenes first.
    # When no scene has full coverage it falls back to coverage > 0.92,
    # then coverage > 0, so any scene with any overlap is kept as a last resort.
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=1.0, scene_id="high"),
        _make_scene("2023-06-02T10:00:00Z", coverage=1.0, scene_id="also_high"),
    ]
    # Both have full_coverage=True from _make_scene; both should appear.
    result = refine_scene_sequence(scenes, "strict", False)
    ids = [s["id"] for s in result]
    assert "high" in ids
    assert "also_high" in ids

def test_refine_scene_sequence_strict_falls_back_when_no_full_coverage():
    # No scene has full_coverage=True; strict falls back to coverage > 0.
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=0.5, scene_id="medium"),
        _make_scene("2023-06-02T10:00:00Z", coverage=0.3, scene_id="low"),
    ]
    for s in scenes:
        s["full_coverage"] = False
    result = refine_scene_sequence(scenes, "strict", False)
    # Fallback keeps scenes with coverage > 0
    assert len(result) > 0

def test_refine_scene_sequence_balanced_includes_medium_coverage():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=0.8, scene_id="medium"),
        _make_scene("2023-06-02T10:00:00Z", coverage=0.3, scene_id="low"),
    ]
    result = refine_scene_sequence(scenes, "balanced", False)
    ids = [s["id"] for s in result]
    assert "medium" in ids

def test_refine_scene_sequence_sorted_chronologically():
    scenes = [
        _make_scene("2023-06-03T10:00:00Z", scene_id="c"),
        _make_scene("2023-06-01T10:00:00Z", scene_id="a"),
        _make_scene("2023-06-02T10:00:00Z", scene_id="b"),
    ]
    result = refine_scene_sequence(scenes, "dense", False)
    assert [s["id"] for s in result] == ["a", "b", "c"]


def test_compute_timeline_stats_empty():
    stats = compute_timeline_stats([])
    assert stats["scene_count"] == 0
    assert stats["range_label"] == "--"
    assert stats["average_revisit_days"] is None
    assert stats["average_cloud_cover"] is None

def test_compute_timeline_stats_single_scene():
    scenes = [_make_scene("2023-06-01T10:00:00Z", cloud=5)]
    stats = compute_timeline_stats(scenes)
    assert stats["scene_count"] == 1
    assert stats["average_cloud_cover"] == 5.0
    assert stats["average_revisit_days"] is None  # no gap with one scene

def test_compute_timeline_stats_multiple_scenes():
    scenes = [
        _make_scene("2023-06-01T00:00:00Z", cloud=10, scene_id="a"),
        _make_scene("2023-06-11T00:00:00Z", cloud=20, scene_id="b"),
    ]
    stats = compute_timeline_stats(scenes)
    assert stats["scene_count"] == 2
    assert stats["average_revisit_days"] == 10.0
    assert stats["average_cloud_cover"] == pytest.approx(15.0)

def test_compute_timeline_stats_no_cloud_data():
    scenes = [_make_scene("2023-06-01T00:00:00Z", cloud=None)]
    stats = compute_timeline_stats(scenes)
    assert stats["average_cloud_cover"] is None
