"""pytest tests for satellite_view/webapp.py

Run from the repository root with:
    pip install -e ".[test]"
    pytest -v

## Note: Flask route tests and mocked external API calls can be found below
## the pure function tests. To extend further, consider adding:
## - Tests for `annotate_frame` (GIF label overlay)
## - Tests for `build_search_payload` (STAC query construction)
## - Tests for `build_next_page_request` (pagination logic)
## - Tests for `resolve_search_api` (collection to API URL mapping)
## - Tests for `parse_radius_to_meters` and `point_to_bbox` (new radius input)
## - Mocked tests for `api_export_animation` with real PIL images
"""

import pytest
from unittest.mock import patch, MagicMock
from datetime import date
from urllib.parse import parse_qs, urlparse

from satellite_view.webapp import (
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
    bbox_preview_dimensions,
    build_titiler_preview_url,
    build_planetary_computer_preview_url,
    collection_ids_for,
    parse_search_request,
    dedupe_scenes_by_day,
    refine_scene_sequence,
    compute_timeline_stats,
    resolve_search_api,
    build_search_payload,
    build_next_page_request,
    annotate_frame,
    create_app,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# to_date_input
# ---------------------------------------------------------------------------

def test_to_date_input_basic():
    assert to_date_input(date(2024, 1, 5)) == "2024-01-05"

def test_to_date_input_end_of_year():
    assert to_date_input(date(2023, 12, 31)) == "2023-12-31"


# ---------------------------------------------------------------------------
# build_initial_state
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# clamp_number
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# validate_bbox
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# validate_date_range
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# bbox_area
# ---------------------------------------------------------------------------

def test_bbox_area_basic():
    area = bbox_area([0.0, 0.0, 2.0, 3.0])
    assert area == pytest.approx(6.0)

def test_bbox_area_zero_width():
    assert bbox_area([1.0, 0.0, 1.0, 5.0]) == 0.0

def test_bbox_area_none():
    assert bbox_area(None) == 0.0

def test_bbox_area_empty_list():
    assert bbox_area([]) == 0.0


# ---------------------------------------------------------------------------
# intersect_bboxes
# ---------------------------------------------------------------------------

def test_intersect_bboxes_overlap():
    result = intersect_bboxes([0.0, 0.0, 4.0, 4.0], [2.0, 2.0, 6.0, 6.0])
    assert result == [2.0, 2.0, 4.0, 4.0]

def test_intersect_bboxes_no_overlap():
    result = intersect_bboxes([0.0, 0.0, 1.0, 1.0], [2.0, 2.0, 3.0, 3.0])
    assert result is None

def test_intersect_bboxes_touching_edge():
    result = intersect_bboxes([0.0, 0.0, 2.0, 2.0], [2.0, 0.0, 4.0, 2.0])
    assert result is None

def test_intersect_bboxes_one_none():
    assert intersect_bboxes(None, [0.0, 0.0, 1.0, 1.0]) is None
    assert intersect_bboxes([0.0, 0.0, 1.0, 1.0], None) is None

def test_intersect_bboxes_fully_contained():
    result = intersect_bboxes([0.0, 0.0, 10.0, 10.0], [2.0, 2.0, 5.0, 5.0])
    assert result == [2.0, 2.0, 5.0, 5.0]


# ---------------------------------------------------------------------------
# compute_coverage_score
# ---------------------------------------------------------------------------

def test_compute_coverage_score_full():
    score = compute_coverage_score([0.0, 0.0, 10.0, 10.0], [2.0, 2.0, 5.0, 5.0])
    assert score == pytest.approx(1.0)

def test_compute_coverage_score_none():
    assert compute_coverage_score(None, [0.0, 0.0, 1.0, 1.0]) == 0.0
    assert compute_coverage_score([0.0, 0.0, 1.0, 1.0], None) == 0.0

def test_compute_coverage_score_no_overlap():
    score = compute_coverage_score([0.0, 0.0, 1.0, 1.0], [2.0, 2.0, 3.0, 3.0])
    assert score == 0.0

def test_compute_coverage_score_partial():
    score = compute_coverage_score([0.0, 0.0, 5.0, 4.0], [0.0, 0.0, 10.0, 4.0])
    assert score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# scene_fully_covers_bbox
# ---------------------------------------------------------------------------

def test_scene_fully_covers_bbox_true():
    assert scene_fully_covers_bbox([-1.0, -1.0, 5.0, 5.0], [0.0, 0.0, 4.0, 4.0]) is True

def test_scene_fully_covers_bbox_false():
    assert scene_fully_covers_bbox([1.0, 1.0, 3.0, 3.0], [0.0, 0.0, 4.0, 4.0]) is False

def test_scene_fully_covers_bbox_exact_match():
    assert scene_fully_covers_bbox([0.0, 0.0, 4.0, 4.0], [0.0, 0.0, 4.0, 4.0]) is True

def test_scene_fully_covers_bbox_none():
    assert scene_fully_covers_bbox(None, [0.0, 0.0, 1.0, 1.0]) is False
    assert scene_fully_covers_bbox([0.0, 0.0, 1.0, 1.0], None) is False


# ---------------------------------------------------------------------------
# resolve_frame_source
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# resolve_fallback_preview_url
# ---------------------------------------------------------------------------

def test_resolve_fallback_preview_url_with_preview_image():
    item = {"assets": {"thumbnail": {"href": "http://preview.png"}}, "links": []}
    assert resolve_fallback_preview_url(item) == "http://preview.png"

def test_resolve_fallback_preview_url_no_preview():
    item = _item_with_assets({
        "red": {"href": "http://r"}, "green": {"href": "http://g"}, "blue": {"href": "http://b"}
    })
    assert resolve_fallback_preview_url(item) == ""


# ---------------------------------------------------------------------------
# resolve_renderable_item_url
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# preview render dimensions
# ---------------------------------------------------------------------------

def test_bbox_preview_dimensions_square_bbox():
    assert bbox_preview_dimensions([0.0, 0.0, 1.0, 1.0]) == (900, 900)

def test_bbox_preview_dimensions_wide_bbox_preserves_aspect_ratio():
    assert bbox_preview_dimensions([0.0, 0.0, 2.0, 1.0]) == (1800, 900)

def test_bbox_preview_dimensions_tall_bbox_preserves_aspect_ratio():
    assert bbox_preview_dimensions([0.0, 0.0, 1.0, 2.0]) == (900, 1800)

def test_bbox_preview_dimensions_caps_very_long_bbox():
    assert bbox_preview_dimensions([0.0, 0.0, 10.0, 1.0]) == (4096, 410)

def test_build_titiler_preview_url_uses_aspect_aware_dimensions():
    url = build_titiler_preview_url(
        "http://item.json",
        {"type": "single-asset", "asset_keys": ["visual"]},
        [0.0, 0.0, 2.0, 1.0],
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/1800x900.png")
    assert query["width"] == ["1800"]
    assert query["height"] == ["900"]

def test_build_planetary_computer_preview_url_uses_aspect_aware_dimensions():
    url = build_planetary_computer_preview_url(
        {"collection": "landsat-c2-l2", "id": "scene-1"},
        [0.0, 0.0, 1.0, 2.0],
    )
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.path.endswith("/900x1800.png")
    assert query["width"] == ["900"]
    assert query["height"] == ["1800"]


# ---------------------------------------------------------------------------
# collection_ids_for
# ---------------------------------------------------------------------------

def test_collection_ids_for_sentinel():
    assert collection_ids_for("sentinel-2-l2a") == ["sentinel-2-l2a"]

def test_collection_ids_for_landsat():
    assert collection_ids_for("landsat-c2-l2") == ["landsat-c2-l2"]

def test_collection_ids_for_merged():
    result = collection_ids_for("merged")
    assert "sentinel-2-l2a" in result
    assert "landsat-c2-l2" in result
    assert len(result) == 2


# ---------------------------------------------------------------------------
# parse_search_request
# ---------------------------------------------------------------------------

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
    bad = {**_VALID_PAYLOAD, "bbox": [10.0, 0.0, 5.0, 5.0]}
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


# ---------------------------------------------------------------------------
# resolve_search_api
# ---------------------------------------------------------------------------

def test_resolve_search_api_sentinel_uses_earth_search():
    url = resolve_search_api("sentinel-2-l2a")
    assert "earth-search" in url

def test_resolve_search_api_landsat_uses_planetary_computer():
    url = resolve_search_api("landsat-c2-l2")
    assert "planetarycomputer" in url


# ---------------------------------------------------------------------------
# build_search_payload
# ---------------------------------------------------------------------------

def test_build_search_payload_structure():
    payload = build_search_payload(
        "sentinel-2-l2a", [-10.0, -5.0, 10.0, 5.0],
        "2023-01-01", "2023-12-31", 30, 50
    )
    assert payload["collections"] == ["sentinel-2-l2a"]
    assert payload["bbox"] == [-10.0, -5.0, 10.0, 5.0]
    assert "2023-01-01" in payload["datetime"]
    assert "2023-12-31" in payload["datetime"]
    assert payload["query"]["eo:cloud_cover"]["lte"] == 30

def test_build_search_payload_caps_limit_at_100():
    payload = build_search_payload(
        "sentinel-2-l2a", [-10.0, -5.0, 10.0, 5.0],
        "2023-01-01", "2023-12-31", 30, 500
    )
    assert payload["limit"] == 100

def test_build_search_payload_sorts_ascending():
    payload = build_search_payload(
        "sentinel-2-l2a", [-10.0, -5.0, 10.0, 5.0],
        "2023-01-01", "2023-12-31", 30, 50
    )
    assert payload["sortby"][0]["direction"] == "asc"


# ---------------------------------------------------------------------------
# build_next_page_request
# ---------------------------------------------------------------------------

def test_build_next_page_request_none_link():
    assert build_next_page_request(None, "http://api", {}, 10) is None

def test_build_next_page_request_zero_remaining():
    link = {"href": "http://next", "method": "POST", "body": {}}
    assert build_next_page_request(link, "http://api", {}, 0) is None

def test_build_next_page_request_post():
    link = {"href": "http://next", "method": "POST", "body": {"collections": ["sentinel-2-l2a"]}}
    result = build_next_page_request(link, "http://api", {}, 20)
    assert result is not None
    url, opts = result
    assert url == "http://next"
    assert opts["method"] == "POST"
    assert opts["json"]["limit"] == 20

def test_build_next_page_request_caps_limit_at_100():
    link = {"href": "http://next", "method": "POST", "body": {}}
    _, opts = build_next_page_request(link, "http://api", {}, 500)
    assert opts["json"]["limit"] == 100


# ---------------------------------------------------------------------------
# annotate_frame
# ---------------------------------------------------------------------------

def test_annotate_frame_returns_same_size():
    from PIL import Image
    img = Image.new("RGB", (200, 200), color="blue")
    result = annotate_frame(img, "2023-06-01")
    assert result.size == img.size

def test_annotate_frame_does_not_modify_original():
    from PIL import Image
    img = Image.new("RGB", (200, 200), color="blue")
    original_pixels = list(img.getdata())
    annotate_frame(img, "2023-06-01")
    assert list(img.getdata()) == original_pixels

def test_annotate_frame_returns_different_image():
    from PIL import Image
    img = Image.new("RGB", (200, 200), color="blue")
    result = annotate_frame(img, "2023-06-01")
    assert result is not img


# ---------------------------------------------------------------------------
# dedupe_scenes_by_day
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# refine_scene_sequence
# ---------------------------------------------------------------------------

def test_refine_scene_sequence_empty():
    assert refine_scene_sequence([], "balanced", False) == []

def test_refine_scene_sequence_strict_prefers_full_coverage():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=1.0, scene_id="high"),
        _make_scene("2023-06-02T10:00:00Z", coverage=1.0, scene_id="also_high"),
    ]
    result = refine_scene_sequence(scenes, "strict", False)
    ids = [s["id"] for s in result]
    assert "high" in ids
    assert "also_high" in ids

def test_refine_scene_sequence_strict_falls_back_when_no_full_coverage():
    scenes = [
        _make_scene("2023-06-01T10:00:00Z", coverage=0.5, scene_id="medium"),
        _make_scene("2023-06-02T10:00:00Z", coverage=0.3, scene_id="low"),
    ]
    for s in scenes:
        s["full_coverage"] = False
    result = refine_scene_sequence(scenes, "strict", False)
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


# ---------------------------------------------------------------------------
# compute_timeline_stats
# ---------------------------------------------------------------------------

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
    assert stats["average_revisit_days"] is None

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


# ---------------------------------------------------------------------------
# Flask test client
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    flask_app = create_app()
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as client:
        yield client


# ---------------------------------------------------------------------------
# Route: GET /
# ---------------------------------------------------------------------------

def test_index_returns_200(client):
    response = client.get("/")
    assert response.status_code == 200

def test_index_contains_html(client):
    response = client.get("/")
    assert b"<html" in response.data.lower()


# ---------------------------------------------------------------------------
# Route: POST /api/search — validation errors
# ---------------------------------------------------------------------------

def test_search_missing_bbox_returns_400(client):
    response = client.post("/api/search", json={
        "collection": "sentinel-2-l2a",
        "sequence_mode": "balanced",
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
    })
    assert response.status_code == 400

def test_search_invalid_collection_returns_400(client):
    response = client.post("/api/search", json={
        "collection": "fake-collection",
        "bbox": [-10.0, -5.0, 10.0, 5.0],
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
    })
    assert response.status_code == 400

def test_search_reversed_dates_returns_400(client):
    response = client.post("/api/search", json={
        "collection": "sentinel-2-l2a",
        "bbox": [-10.0, -5.0, 10.0, 5.0],
        "start_date": "2023-12-31",
        "end_date": "2023-01-01",
    })
    assert response.status_code == 400

def test_search_invalid_sequence_mode_returns_400(client):
    response = client.post("/api/search", json={
        "collection": "sentinel-2-l2a",
        "sequence_mode": "random",
        "bbox": [-10.0, -5.0, 10.0, 5.0],
        "start_date": "2023-01-01",
        "end_date": "2023-12-31",
    })
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Route: POST /api/search — mocked external call
# ---------------------------------------------------------------------------

def test_search_returns_scenes(client):
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "features": [{
            "id": "scene-001",
            "collection": "sentinel-2-l2a",
            "bbox": [-10.0, -5.0, 10.0, 5.0],
            "geometry": None,
            "properties": {
                "datetime": "2023-06-01T10:00:00Z",
                "eo:cloud_cover": 5,
            },
            "assets": {"thumbnail": {"href": "http://thumb.png"}},
            "links": [{"rel": "self", "href": "http://self"}],
        }],
        "links": [],
    }
    with patch("requests.request", return_value=fake_response):
        response = client.post("/api/search", json={
            "collection": "sentinel-2-l2a",
            "sequence_mode": "balanced",
            "bbox": [-10.0, -5.0, 10.0, 5.0],
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        })
    assert response.status_code == 200
    data = response.get_json()
    assert data["scenes"][0]["id"] == "scene-001"

def test_search_returns_stats(client):
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "features": [{
            "id": "scene-001",
            "collection": "sentinel-2-l2a",
            "bbox": [-10.0, -5.0, 10.0, 5.0],
            "geometry": None,
            "properties": {
                "datetime": "2023-06-01T10:00:00Z",
                "eo:cloud_cover": 5,
            },
            "assets": {"thumbnail": {"href": "http://thumb.png"}},
            "links": [{"rel": "self", "href": "http://self"}],
        }],
        "links": [],
    }
    with patch("requests.request", return_value=fake_response):
        response = client.post("/api/search", json={
            "collection": "sentinel-2-l2a",
            "sequence_mode": "balanced",
            "bbox": [-10.0, -5.0, 10.0, 5.0],
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
        })
    data = response.get_json()
    assert "stats" in data
    assert data["stats"]["scene_count"] == 1


# ---------------------------------------------------------------------------
# Route: POST /api/export/frames
# ---------------------------------------------------------------------------

def test_export_frames_no_scenes_returns_400(client):
    response = client.post("/api/export/frames", json={"scenes": []})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# Route: POST /api/export/animation
# ---------------------------------------------------------------------------

def test_export_animation_too_few_scenes_returns_400(client):
    response = client.post("/api/export/animation", json={
        "scenes": [{"frame_url": "http://x", "id": "s1"}]
    })
    assert response.status_code == 400

def test_export_animation_no_scenes_returns_400(client):
    response = client.post("/api/export/animation", json={"scenes": []})
    assert response.status_code == 400
