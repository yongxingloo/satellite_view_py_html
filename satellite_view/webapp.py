"""Flask application for searching and previewing satellite timelapse scenes.

This module contains three main responsibilities:
1. Serve the main HTML page and its initial UI state.
2. Search STAC APIs, normalize returned items, and prepare preview URLs.
3. Export the currently selected sequence as a ZIP of frames or an animated GIF.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from flask import Flask, Response, jsonify, render_template, request, send_file
from PIL import Image, ImageDraw
import requests
from requests.adapters import HTTPAdapter


EARTH_SEARCH_API = "https://earth-search.aws.element84.com/v1/search"
PLANETARY_COMPUTER_STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1/search"
PLANETARY_COMPUTER_DATA_API = "https://planetarycomputer.microsoft.com/api/data/v1/item"
TITILER_STAC_API = "https://titiler.xyz/stac/bbox"

DEFAULT_BBOX = [-73.9187, 22.6590, -73.8574, 22.7113]
DEFAULT_CENTER = [22.68515, -73.88805]
DEFAULT_ZOOM = 12
DEFAULT_COLLECTION = "sentinel-2-l2a"
SUPPORTED_COLLECTIONS = {"sentinel-2-l2a", "landsat-c2-l2", "merged"}
SUPPORTED_SEQUENCE_MODES = {"balanced", "strict", "dense"}

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

app = Flask(__name__, template_folder=str(TEMPLATES_DIR), static_folder=str(STATIC_DIR))
EXPORT_SESSION = requests.Session()
EXPORT_SESSION.mount("https://", HTTPAdapter(pool_connections=16, pool_maxsize=16))
EXPORT_SESSION.mount("http://", HTTPAdapter(pool_connections=16, pool_maxsize=16))


def create_app() -> Flask:
    """Return the configured Flask application instance."""
    return app


def to_date_input(value: date) -> str:
    """Format a Python date for use in an HTML ``<input type="date">``.

    Args:
        value: Date object to format.

    Returns:
        The date formatted as ``YYYY-MM-DD``.
    """
    return value.isoformat()


def build_initial_state() -> dict[str, Any]:
    """Build the default UI state injected into the first page render.

    Returns:
        A dictionary containing default map, form, and AOI settings.
    """
    today = date.today()
    return {
        "default_center": DEFAULT_CENTER,
        "default_zoom": DEFAULT_ZOOM,
        "default_bbox": DEFAULT_BBOX,
        "default_collection": DEFAULT_COLLECTION,
        "default_start_date": to_date_input(today - timedelta(days=365)),
        "default_end_date": to_date_input(today),
        "default_cloud": 25,
        "default_limit": 20,
        "default_sequence_mode": "balanced",
    }


def clamp_number(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    """Convert a value to a bounded float.

    Args:
        value: Raw input value to clamp.
        minimum: Lowest allowed value.
        maximum: Highest allowed value.
        fallback: Value used when conversion fails.

    Returns:
        A float constrained to the provided range, or the fallback value.
    """
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(maximum, numeric))


def validate_bbox(raw_bbox: Any) -> list[float]:
    """Validate and normalize a bbox.

    Args:
        raw_bbox: Incoming bbox value from the client.

    Returns:
        A normalized bbox in ``[west, south, east, north]`` order.

    Raises:
        ValueError: If the bbox shape or coordinate order is invalid.
    """
    if not isinstance(raw_bbox, list) or len(raw_bbox) != 4:
        raise ValueError("Bounding box must contain west, south, east, and north values.")
    bbox = [round(float(value), 5) for value in raw_bbox]
    west, south, east, north = bbox
    if west >= east or south >= north:
        raise ValueError("Bounding box coordinates are invalid.")
    return bbox


def validate_date_range(start_date: str, end_date: str) -> tuple[str, str]:
    """Validate ISO date strings and normalize the date range.

    Args:
        start_date: Inclusive start date as ``YYYY-MM-DD``.
        end_date: Inclusive end date as ``YYYY-MM-DD``.

    Returns:
        A tuple containing the normalized start and end date strings.

    Raises:
        ValueError: If either date is invalid or the range is reversed.
    """
    try:
        start = date.fromisoformat(start_date)
        end = date.fromisoformat(end_date)
    except ValueError as exc:
        raise ValueError("Dates must use YYYY-MM-DD.") from exc
    if start > end:
        raise ValueError("Start date must be before end date.")
    return start.isoformat(), end.isoformat()


def bbox_area(bbox: list[float] | None) -> float:
    """Compute the area of a bbox.

    Args:
        bbox: Bounding box in ``[west, south, east, north]`` order.

    Returns:
        The bbox area in geographic coordinate-space units.
    """
    if not bbox:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def intersect_bboxes(a: list[float] | None, b: list[float] | None) -> list[float] | None:
    """Compute the overlap between two bounding boxes.

    Args:
        a: First bbox.
        b: Second bbox.

    Returns:
        The overlapping bbox, or ``None`` if the boxes do not intersect.
    """
    if not a or not b:
        return None
    west = max(a[0], b[0])
    south = max(a[1], b[1])
    east = min(a[2], b[2])
    north = min(a[3], b[3])
    if west >= east or south >= north:
        return None
    return [west, south, east, north]


def compute_coverage_score(scene_bbox: list[float] | None, target_bbox: list[float] | None) -> float:
    """Measure how much of the target AOI is covered by a scene.

    Args:
        scene_bbox: Scene footprint bbox.
        target_bbox: Requested area-of-interest bbox.

    Returns:
        A fractional coverage score between 0 and 1.
    """
    if not scene_bbox or not target_bbox:
        return 0.0
    intersection = intersect_bboxes(scene_bbox, target_bbox)
    target_area = bbox_area(target_bbox)
    if not intersection or target_area == 0:
        return 0.0
    return bbox_area(intersection) / target_area


def scene_fully_covers_bbox(scene_bbox: list[float] | None, target_bbox: list[float] | None) -> bool:
    """Check whether a scene fully contains the target bbox.

    Args:
        scene_bbox: Scene footprint bbox.
        target_bbox: Requested area-of-interest bbox.

    Returns:
        ``True`` if the scene fully covers the target bbox, otherwise ``False``.
    """
    if not scene_bbox or not target_bbox:
        return False
    return (
        scene_bbox[0] <= target_bbox[0]
        and scene_bbox[1] <= target_bbox[1]
        and scene_bbox[2] >= target_bbox[2]
        and scene_bbox[3] >= target_bbox[3]
    )


def resolve_frame_source(item: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the best preview strategy exposed by a STAC item.

    Args:
        item: Raw STAC item.

    Returns:
        A dictionary describing how the item should be rendered, or ``None``
        when no usable preview source is available.
    """
    assets = item.get("assets") or {}
    thumbnail_link = next((link.get("href", "") for link in item.get("links", []) if link.get("rel") == "thumbnail"), "")

    if assets.get("red", {}).get("href") and assets.get("green", {}).get("href") and assets.get("blue", {}).get("href"):
        return {"type": "rgb-bands", "asset_keys": ["red", "green", "blue"]}
    if assets.get("B04", {}).get("href") and assets.get("B03", {}).get("href") and assets.get("B02", {}).get("href"):
        return {"type": "rgb-bands", "asset_keys": ["B04", "B03", "B02"]}
    if assets.get("visual", {}).get("href"):
        return {"type": "single-asset", "asset_keys": ["visual"]}
    if assets.get("image", {}).get("href"):
        return {"type": "single-asset", "asset_keys": ["image"]}

    preview_keys = [
        thumbnail_link,
        assets.get("reduced_resolution_browse", {}).get("href", ""),
        assets.get("rendered_preview", {}).get("href", ""),
        assets.get("overview", {}).get("href", ""),
        assets.get("preview", {}).get("href", ""),
        assets.get("thumbnail", {}).get("href", ""),
    ]
    for href in preview_keys:
        if href:
            return {"type": "preview-image", "href": href}
    return None


def resolve_fallback_preview_url(item: dict[str, Any]) -> str:
    """Resolve a plain preview image URL for a STAC item.

    Args:
        item: Raw STAC item.

    Returns:
        A preview image URL, or an empty string when none is available.
    """
    source = resolve_frame_source(item)
    if source and source["type"] == "preview-image":
        return source["href"]
    return ""


def resolve_renderable_item_url(item: dict[str, Any]) -> str:
    """Choose the STAC item URL used by downstream preview services.

    Args:
        item: Raw STAC item.

    Returns:
        The preferred item URL, or an empty string when none is suitable.
    """
    links = item.get("links") or []
    if item.get("collection") == "landsat-c2-l2":
        via_link = next(
            (
                link.get("href", "")
                for link in links
                if link.get("rel") == "via" and "landsat-c2l2-sr" in link.get("href", "").lower()
            ),
            "",
        )
        if via_link:
            return via_link
    return next((link.get("href", "") for link in links if link.get("rel") == "self"), "")


def build_titiler_preview_url(item_url: str, source: dict[str, Any], bbox: list[float]) -> str:
    """Build a TiTiler preview URL for one scene.

    Args:
        item_url: STAC item URL to render from.
        source: Rendering strategy returned by ``resolve_frame_source``.
        bbox: Requested area-of-interest bbox.

    Returns:
        A TiTiler URL that renders the requested AOI.
    """
    bbox_path = ",".join(f"{value:.5f}" for value in bbox)
    params: list[tuple[str, str]] = [
        ("url", item_url),
        ("width", "900"),
        ("height", "900"),
        ("rescale", "0,4000"),
        ("coord_crs", "epsg:4326"),
        ("dst_crs", "epsg:4326"),
    ]
    for asset_key in source["asset_keys"]:
        params.append(("assets", asset_key))
    if source["type"] == "rgb-bands":
        params.append(("asset_as_band", "true"))
        params.extend([("rescale", "0,4000"), ("rescale", "0,4000")])
    prepared = requests.PreparedRequest()
    prepared.prepare_url(f"{TITILER_STAC_API}/{bbox_path}/900x900.png", params)
    return prepared.url or ""


def build_planetary_computer_preview_url(item: dict[str, Any], bbox: list[float]) -> str:
    """Build a Planetary Computer preview URL for Landsat scenes.

    Args:
        item: Raw Landsat STAC item.
        bbox: Requested area-of-interest bbox.

    Returns:
        A Planetary Computer preview URL.
    """
    bbox_path = ",".join(f"{value:.5f}" for value in bbox)
    params = [
        ("collection", item["collection"]),
        ("item", item["id"]),
        ("width", "900"),
        ("height", "900"),
        ("format", "png"),
        ("coord_crs", "epsg:4326"),
        ("dst_crs", "epsg:4326"),
        ("color_formula", "gamma RGB 2.7, saturation 1.5, sigmoidal RGB 15 0.55"),
        ("assets", "red"),
        ("assets", "green"),
        ("assets", "blue"),
        ("asset_as_band", "true"),
    ]
    prepared = requests.PreparedRequest()
    prepared.prepare_url(f"{PLANETARY_COMPUTER_DATA_API}/bbox/{bbox_path}/900x900.png", params)
    return prepared.url or ""


def resolve_frame_url(item: dict[str, Any], bbox: list[float]) -> str:
    """Resolve the best frame URL for a scene preview.

    Args:
        item: Raw STAC item.
        bbox: Requested area-of-interest bbox.

    Returns:
        The preferred preview URL, or an empty string if rendering is unavailable.
    """
    frame_source = resolve_frame_source(item)
    if not frame_source:
        return ""
    if item.get("collection") == "landsat-c2-l2":
        return build_planetary_computer_preview_url(item, bbox)
    item_url = resolve_renderable_item_url(item)
    if item_url and frame_source["type"] in {"rgb-bands", "single-asset"}:
        return build_titiler_preview_url(item_url, frame_source, bbox)
    if frame_source["type"] == "preview-image" and frame_source["href"].startswith(("http://", "https://")):
        return frame_source["href"]
    return ""


def map_feature_to_scene(feature: dict[str, Any], requested_collection_id: str, bbox: list[float]) -> dict[str, Any]:
    """Normalize a STAC item into the frontend scene shape.

    Args:
        feature: Raw STAC item feature.
        requested_collection_id: Collection requested by the client.
        bbox: Requested area-of-interest bbox.

    Returns:
        A normalized scene dictionary used by the frontend.
    """
    properties = feature.get("properties") or {}
    scene_date = properties.get("datetime") or properties.get("start_datetime") or ""
    cloud_cover = properties.get("eo:cloud_cover")
    cloud_value = float(cloud_cover) if isinstance(cloud_cover, (int, float)) else None
    item_bbox = feature.get("bbox")
    collection = feature.get("collection") or requested_collection_id

    return {
        "id": feature.get("id", "unknown-scene"),
        "collection": collection,
        "provider": properties.get("platform") or properties.get("constellation") or "Satellite scene",
        "datetime": scene_date,
        "cloud_cover": cloud_value,
        "geometry": feature.get("geometry"),
        "bbox": item_bbox,
        "coverage_score": compute_coverage_score(item_bbox, bbox),
        "full_coverage": scene_fully_covers_bbox(item_bbox, bbox),
        "tile_id": properties.get("s2:tile_id") or properties.get("mgrs:tile") or "",
        "frame_url": resolve_frame_url(feature, bbox),
        "fallback_frame_url": resolve_fallback_preview_url(feature),
        "browser_url": next((link.get("href", "") for link in feature.get("links", []) if link.get("rel") == "self"), ""),
    }


def resolve_search_api(collection_id: str) -> str:
    """Map a collection identifier to its STAC search endpoint.

    Args:
        collection_id: Collection identifier selected by the user.

    Returns:
        The base STAC API URL for the collection.
    """
    return PLANETARY_COMPUTER_STAC_API if collection_id == "landsat-c2-l2" else EARTH_SEARCH_API


def build_search_payload(collection_id: str, bbox: list[float], start_date: str, end_date: str, max_cloud: int, limit: int) -> dict[str, Any]:
    """Build the base STAC POST payload for a collection search.

    Args:
        collection_id: Collection identifier to search.
        bbox: Requested area-of-interest bbox.
        start_date: Inclusive start date.
        end_date: Inclusive end date.
        max_cloud: Maximum allowed cloud percentage.
        limit: Maximum number of results to request.

    Returns:
        A JSON-serializable STAC search payload.
    """
    return {
        "collections": [collection_id],
        "bbox": bbox,
        "datetime": f"{start_date}T00:00:00Z/{end_date}T23:59:59Z",
        "limit": min(limit, 100),
        "sortby": [{"field": "properties.datetime", "direction": "asc"}],
        "query": {"eo:cloud_cover": {"lte": max_cloud}},
    }


def build_next_page_request(next_link: dict[str, Any] | None, fallback_url: str, fallback_payload: dict[str, Any], remaining_limit: int) -> tuple[str, dict[str, Any]] | None:
    """Convert a STAC ``next`` link into the next request to issue.

    Args:
        next_link: STAC pagination link from the previous response.
        fallback_url: Base search URL used when the next link is relative.
        fallback_payload: Base payload used when the next link omits a body.
        remaining_limit: Number of remaining scenes still needed.

    Returns:
        A tuple of ``(url, request_options)`` or ``None`` when pagination stops.
    """
    if not next_link or not next_link.get("href") or remaining_limit <= 0:
        return None

    method = (next_link.get("method") or ("POST" if next_link.get("body") else "GET")).upper()
    if method == "GET":
        prepared = requests.PreparedRequest()
        prepared.prepare_url(next_link["href"], {"limit": min(remaining_limit, 100)})
        return prepared.url or next_link["href"], {"method": "GET", "timeout": 60}

    payload = dict(next_link.get("body") or fallback_payload)
    payload["limit"] = min(remaining_limit, 100)
    return next_link["href"], {"method": "POST", "json": payload, "timeout": 60}


def fetch_paginated_scenes_for_collection(collection_id: str, bbox: list[float], start_date: str, end_date: str, max_cloud: int, limit: int) -> list[dict[str, Any]]:
    """Fetch paginated STAC search results for one collection.

    Args:
        collection_id: Collection identifier to search.
        bbox: Requested area-of-interest bbox.
        start_date: Inclusive start date.
        end_date: Inclusive end date.
        max_cloud: Maximum allowed cloud percentage.
        limit: Maximum number of normalized scenes to return.

    Returns:
        A list of normalized scene dictionaries.
    """
    base_url = resolve_search_api(collection_id)
    initial_payload = build_search_payload(collection_id, bbox, start_date, end_date, max_cloud, limit)
    next_request: tuple[str, dict[str, Any]] | None = (
        base_url,
        {"method": "POST", "json": initial_payload, "timeout": 60},
    )
    features: list[dict[str, Any]] = []

    while next_request and len(features) < limit:
        url, options = next_request
        response = requests.request(url=url, **options)
        response.raise_for_status()
        data = response.json()
        page_features = data.get("features") or []
        remaining = limit - len(features)
        features.extend(page_features[:remaining])
        next_link = next((link for link in data.get("links", []) if link.get("rel") == "next"), None)
        next_request = build_next_page_request(next_link, base_url, initial_payload, limit - len(features))

    return [map_feature_to_scene(feature, collection_id, bbox) for feature in features]


def dedupe_scenes_by_day(scenes: list[dict[str, Any]], merged_mode: bool) -> list[dict[str, Any]]:
    """Keep only the best scene per day.

    Args:
        scenes: Candidate normalized scenes.
        merged_mode: Whether the merged collection mode is active.

    Returns:
        A chronologically sorted list with redundant same-day scenes removed.
    """
    best_by_day: dict[str, dict[str, Any]] = {}
    for scene in scenes:
        base_day_key = scene["datetime"][:10] if scene["datetime"] else scene["id"]
        day_key = f"{base_day_key}:{scene['collection']}" if merged_mode else base_day_key
        existing = best_by_day.get(day_key)
        if not existing:
            best_by_day[day_key] = scene
            continue
        scene_cloud = scene["cloud_cover"] if scene["cloud_cover"] is not None else float("inf")
        existing_cloud = existing["cloud_cover"] if existing["cloud_cover"] is not None else float("inf")
        if scene["coverage_score"] > existing["coverage_score"] or (
            scene["coverage_score"] == existing["coverage_score"] and scene_cloud < existing_cloud
        ):
            best_by_day[day_key] = scene
    return sorted(best_by_day.values(), key=lambda item: item.get("datetime") or "")


def refine_scene_sequence(scenes: list[dict[str, Any]], sequence_mode: str, merged_mode: bool) -> list[dict[str, Any]]:
    """Filter and order scenes into a timelapse-friendly sequence.

    Args:
        scenes: Candidate normalized scenes.
        sequence_mode: Filtering mode selected by the user.
        merged_mode: Whether the merged collection mode is active.

    Returns:
        A filtered, chronologically sorted list of scenes for playback.
    """
    if not scenes:
        return []

    frame_ready = [scene for scene in scenes if scene["frame_url"]]
    usable = frame_ready or scenes

    if sequence_mode == "strict":
        full_coverage = [scene for scene in usable if scene["full_coverage"]]
        coverage_pool = full_coverage or [scene for scene in usable if scene["coverage_score"] > 0.92]
        filtered = coverage_pool or [scene for scene in usable if scene["coverage_score"] > 0]
    elif sequence_mode == "balanced":
        filtered = [scene for scene in usable if scene["coverage_score"] > 0.72] or [scene for scene in usable if scene["coverage_score"] > 0]
    else:
        filtered = [scene for scene in usable if scene["coverage_score"] > 0]

    reduced = filtered if sequence_mode == "dense" else dedupe_scenes_by_day(filtered or usable, merged_mode)
    return sorted(reduced, key=lambda item: item.get("datetime") or "")


def compute_timeline_stats(scenes: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute summary metrics shown in the timeline analytics panel.

    Args:
        scenes: Normalized scenes currently shown in the results.

    Returns:
        A dictionary containing counts, date range text, revisit time, and cloud
        summary values for the frontend stats cards.
    """
    if not scenes:
        return {
            "scene_count": 0,
            "range_label": "--",
            "average_revisit_days": None,
            "average_cloud_cover": None,
        }

    dates = [datetime.fromisoformat(scene["datetime"].replace("Z", "+00:00")) for scene in scenes if scene.get("datetime")]
    sorted_dates = sorted(dates)
    revisit_values = [
        (sorted_dates[index] - sorted_dates[index - 1]).days
        for index in range(1, len(sorted_dates))
        if (sorted_dates[index] - sorted_dates[index - 1]).days >= 0
    ]
    clouds = [scene["cloud_cover"] for scene in scenes if scene["cloud_cover"] is not None]
    return {
        "scene_count": len(scenes),
        "range_label": f"{sorted_dates[0].date().isoformat()} to {sorted_dates[-1].date().isoformat()}" if sorted_dates else "--",
        "average_revisit_days": round(sum(revisit_values) / len(revisit_values), 1) if revisit_values else None,
        "average_cloud_cover": round(sum(clouds) / len(clouds), 1) if clouds else None,
    }


def collection_ids_for(value: str) -> list[str]:
    """Expand the selected collection option into concrete collection IDs.

    Args:
        value: Collection value coming from the UI.

    Returns:
        One or more collection IDs to search.
    """
    return ["sentinel-2-l2a", "landsat-c2-l2"] if value == "merged" else [value]


def parse_search_request(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the JSON payload sent by the search form.

    Args:
        data: Raw JSON payload from the client.

    Returns:
        A validated search request dictionary.

    Raises:
        ValueError: If collection, sequence mode, bbox, or dates are invalid.
    """
    collection = data.get("collection", DEFAULT_COLLECTION)
    if collection not in SUPPORTED_COLLECTIONS:
        raise ValueError("Collection is not supported.")

    sequence_mode = data.get("sequence_mode", "balanced")
    if sequence_mode not in SUPPORTED_SEQUENCE_MODES:
        raise ValueError("Sequence mode is not supported.")

    bbox = validate_bbox(data.get("bbox"))
    start_date, end_date = validate_date_range(data.get("start_date", ""), data.get("end_date", ""))
    max_cloud = int(clamp_number(data.get("max_cloud"), 0, 100, 25))
    limit = int(clamp_number(data.get("limit"), 5, 500, 120))

    return {
        "collection": collection,
        "sequence_mode": sequence_mode,
        "bbox": bbox,
        "start_date": start_date,
        "end_date": end_date,
        "max_cloud": max_cloud,
        "limit": limit,
    }


def download_bytes(url: str) -> tuple[bytes, str]:
    """Download one remote preview asset.

    Args:
        url: Remote preview URL.

    Returns:
        A tuple containing the raw response bytes and a practical file extension.
    """
    response = EXPORT_SESSION.get(url, timeout=120)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "")
    extension = ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        extension = ".jpg"
    elif "webp" in content_type:
        extension = ".webp"
    return response.content, extension


def download_many(urls: list[str]) -> list[tuple[bytes, str]]:
    """Download multiple remote assets in parallel.

    Args:
        urls: Remote preview URLs to download.

    Returns:
        A list of ``(bytes, extension)`` tuples in the same order as the input.
    """
    if not urls:
        return []

    max_workers = min(8, max(2, len(urls)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        return list(executor.map(download_bytes, urls))


def fetch_animation_frames(frame_urls: list[str]) -> list[Image.Image]:
    """Download and decode all frames needed for GIF export.

    Args:
        frame_urls: Preview URLs to use as animation frames.

    Returns:
        A list of RGB Pillow images ready for annotation/export.
    """
    frames: list[Image.Image] = []
    for image_bytes, _ in download_many(frame_urls):
        with Image.open(BytesIO(image_bytes)) as image:
            frames.append(image.convert("RGB"))
    return frames


def annotate_frame(image: Image.Image, label: str) -> Image.Image:
    """Overlay scene metadata onto a frame before animation export.

    Args:
        image: Decoded frame image.
        label: Text label to draw onto the frame.

    Returns:
        A copy of the frame image with the label overlay applied.
    """
    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    draw.rectangle((18, image.height - 66, min(image.width - 18, 460), image.height - 18), fill=(8, 17, 31, 180))
    draw.text((32, image.height - 56), label, fill=(237, 245, 255))
    return annotated


# -----------------------------
# Point-to-bbox helpers & API
# -----------------------------
MAX_RADIUS_METERS = 100000  # safety cap to avoid terribly large AOIs
MIN_RADIUS_METERS = 10  # avoid tiny AOIs smaller than typical satellite pixel resolution
_METERS_PER_DEGREE_LAT = 111320.0


def parse_radius_to_meters(raw: Any) -> float:
    """Parse a radius input (e.g. '500', '500m', '1.2km') into meters.

    Args:
        raw: Raw radius value from the client.

    Returns:
        Radius in meters.

    Raises:
        ValueError: If the value cannot be parsed or is out of range.
    """
    if raw is None:
        raise ValueError("Radius is required.")
    s = str(raw).strip().lower()
    if not s:
        raise ValueError("Radius is required.")
    try:
        if s.endswith("km"):
            value = float(s[:-2]) * 1000.0
        elif s.endswith("m"):
            value = float(s[:-1])
        else:
            value = float(s)
    except ValueError as exc:
        raise ValueError("Radius must be a number optionally suffixed with 'm' or 'km'.") from exc
    if value <= 0:
        raise ValueError("Radius must be positive.")
    if value < MIN_RADIUS_METERS:
        raise ValueError(f"Radius is too small (min {MIN_RADIUS_METERS} m).")
    if value > MAX_RADIUS_METERS:
        raise ValueError(f"Radius is too large (max {MAX_RADIUS_METERS} m).")
    return value


def point_to_bbox(lat: float, lon: float, radius_m: float) -> list[float]:
    """Compute a square bbox (west,south,east,north) centered on (lat,lon).

    Uses a simple equirectangular approximation converting meters to degrees.
    This is sufficient for the small-to-moderate radii this UI expects.
    """
    # convert lat delta (degrees)
    delta_lat = radius_m / _METERS_PER_DEGREE_LAT
    # convert lon delta accounting for latitude compression
    lon_factor = max(cos(radians(lat)), 1e-6)
    delta_lon = radius_m / (_METERS_PER_DEGREE_LAT * lon_factor)
    west = lon - delta_lon
    south = lat - delta_lat
    east = lon + delta_lon
    north = lat + delta_lat
    return [round(west, 5), round(south, 5), round(east, 5), round(north, 5)]


@app.post("/api/resolve_point")
def api_resolve_point() -> Response:
    """Resolve a lat/lon + radius into a normalized bbox.

    Expected JSON body: { "lat": "47.37", "lon": "8.54", "radius": "500m" }

    Returns JSON: { "bbox": [west, south, east, north], "center": [lon, lat] }
    """
    try:
        data = request.get_json(force=True, silent=False) or {}
        raw_lat = data.get("lat")
        raw_lon = data.get("lon")
        raw_radius = data.get("radius")
        if raw_lat is None or raw_lon is None or raw_radius is None:
            raise ValueError("lat, lon and radius are required fields")
        lat = float(str(raw_lat).strip())
        lon = float(str(raw_lon).strip())
        if not (-90.0 <= lat <= 90.0) or not (-180.0 <= lon <= 180.0):
            raise ValueError("Latitude must be between -90 and 90 and longitude between -180 and 180.")
        radius_m = parse_radius_to_meters(raw_radius)
        bbox = point_to_bbox(lat, lon, radius_m)
        # validate bbox ordering
        validate_bbox(bbox)
        return jsonify({"bbox": bbox, "center": [round(lon, 5), round(lat, 5)]})
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.get("/")
def index() -> str:
    """Render the main application page.

    Returns:
        The rendered HTML page.
    """
    return render_template("index.html", initial_state=build_initial_state())


@app.post("/api/search")
def api_search() -> Response:
    """Search STAC catalogs and return normalized scene results.

    Returns:
        A Flask JSON response containing normalized scenes and timeline stats.
    """
    try:
        payload = parse_search_request(request.get_json(force=True, silent=False) or {})
        scene_sets = [
            fetch_paginated_scenes_for_collection(
                collection_id=collection_id,
                bbox=payload["bbox"],
                start_date=payload["start_date"],
                end_date=payload["end_date"],
                max_cloud=payload["max_cloud"],
                limit=payload["limit"],
            )
            for collection_id in collection_ids_for(payload["collection"])
        ]
        combined = [scene for scene_set in scene_sets for scene in scene_set]
        refined = refine_scene_sequence(
            scenes=combined,
            sequence_mode=payload["sequence_mode"],
            merged_mode=payload["collection"] == "merged",
        )
        return jsonify(
            {
                "bbox": payload["bbox"],
                "scenes": refined,
                "stats": compute_timeline_stats(refined),
                "search": payload,
            }
        )
    except requests.HTTPError as exc:
        upstream_status = exc.response.status_code if exc.response is not None else 502
        return jsonify({"error": f"Remote catalog request failed with HTTP {upstream_status}."}), 502
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.RequestException as exc:
        return jsonify({"error": f"Could not reach remote catalog service: {exc}"}), 502


@app.post("/api/export/frames")
def api_export_frames() -> Response:
    """Download the current frame set and return it as a ZIP archive.

    Returns:
        A Flask file response containing a ZIP archive of frame images.
    """
    data = request.get_json(force=True, silent=False) or {}
    scenes = data.get("scenes") or []
    frame_scenes = [scene for scene in scenes if scene.get("frame_url")]
    if not frame_scenes:
        return jsonify({"error": "No scenes with downloadable frames were provided."}), 400

    downloaded_frames = download_many([scene["frame_url"] for scene in frame_scenes])
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for index, (scene, downloaded_frame) in enumerate(zip(frame_scenes, downloaded_frames, strict=True), start=1):
            image_bytes, extension = downloaded_frame
            scene_date = (scene.get("datetime") or "unknown-date")[:10]
            archive.writestr(f"{index:03d}_{scene_date}_{scene['id']}{extension}", image_bytes)
    buffer.seek(0)
    return send_file(buffer, mimetype="application/zip", as_attachment=True, download_name="satellite_frames.zip")


@app.post("/api/export/animation")
def api_export_animation() -> Response:
    """Render the current frame set into an animated GIF.

    Returns:
        A Flask file response containing an animated GIF export.
    """
    data = request.get_json(force=True, silent=False) or {}
    scenes = data.get("scenes") or []
    fps = int(clamp_number(data.get("fps"), 1, 6, 2))
    frame_scenes = [scene for scene in scenes if scene.get("frame_url")]
    if len(frame_scenes) < 2:
        return jsonify({"error": "At least two renderable scenes are required for animation export."}), 400

    frames = fetch_animation_frames([scene["frame_url"] for scene in frame_scenes])
    labelled_frames = []
    for image, scene in zip(frames, frame_scenes, strict=True):
        label = f"{(scene.get('datetime') or '')[:10]}  {scene['id']}"
        labelled_frames.append(annotate_frame(image, label))

    buffer = BytesIO()
    duration_ms = int(1000 / fps)
    labelled_frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=labelled_frames[1:],
        duration=duration_ms,
        loop=0,
    )
    buffer.seek(0)
    return send_file(buffer, mimetype="image/gif", as_attachment=True, download_name="satellite_timelapse.gif")


if __name__ == "__main__":
    create_app().run(host="127.0.0.1", port=5000, debug=False)
