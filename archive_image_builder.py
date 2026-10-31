#!/usr/bin/env python3
"""Prepare and approve artwork for new Stellar Archive destinations.

The builder is intentionally a release-preparation tool for a trusted Mac. It
never deploys, creates a GitHub release, or writes to a running Stargate.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
ARCHIVE = ROOT / "payload" / "stellar-archive"
DEFAULT_WORLDS = ARCHIVE / "data" / "worlds.json"
USER_AGENT = "StellarArchiveImageBuilder/1.0 (+https://github.com/matelv-x/Stellar-Archive)"
OPENAI_IMAGES_URL = "https://api.openai.com/v1/images/generations"
DEFAULT_IMAGE_MODEL = "gpt-image-2.5-flare"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(source: str | Path) -> Any:
    value = str(source)
    if value.startswith(("http://", "https://")):
        request = urllib.request.Request(value, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    return json.loads(Path(source).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_name(value: Any) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())


def address_key(address: list[int]) -> str:
    return "-".join(str(glyph) for glyph in address)


def valid_address(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not value:
        return None
    try:
        address = [int(glyph) for glyph in value]
    except (TypeError, ValueError):
        return None
    return address if all(1 <= glyph <= 39 for glyph in address) else None


def source_entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("destinations"), list):
        return payload["destinations"]
    if isinstance(payload, dict) and "address_book" in payload:
        book = payload["address_book"]
        return list(book.values()) if isinstance(book, dict) else list(book or [])
    if isinstance(payload, dict):
        return list(payload.values())
    if isinstance(payload, list):
        return payload
    raise ValueError("address-book input must be an object, list, or browser export")


def sanitized_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    name = str(entry.get("name") or entry.get("gate_name") or entry.get("gateName") or "").strip()
    address = valid_address(entry.get("storedAddress") or entry.get("gate_address"))
    if not name or not address:
        return None
    category = str(entry.get("category") or entry.get("type") or "fan").lower()
    if category not in {"standard", "fan", "lan"}:
        category = "fan"
    return {"name": name, "category": category, "storedAddress": address}


def detect_candidates(book_payload: Any, archive_payload: dict[str, Any]) -> list[dict[str, Any]]:
    worlds = archive_payload["worlds"]
    candidates: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in source_entries(book_payload):
        entry = sanitized_entry(raw)
        if not entry:
            continue
        name_key = normalize_name(entry["name"])
        key = address_key(entry["storedAddress"])
        identity = (name_key, key)
        if identity in seen:
            continue
        seen.add(identity)
        exact = [world for world in worlds if normalize_name(world["name"]) == name_key and address_key(world["storedAddress"]) == key]
        if exact:
            continue
        same_address = [world for world in worlds if address_key(world["storedAddress"]) == key]
        same_name = [world for world in worlds if normalize_name(world["name"]) == name_key]
        reason = "alias-or-renamed" if same_address else "address-changed" if same_name else "new-address"
        candidates.append({
            **entry,
            "reason": reason,
            "existingMatches": sorted({world["name"] for world in (*same_address, *same_name)}),
        })
    return candidates


def command_detect(args: argparse.Namespace) -> None:
    archive = read_json(args.worlds)
    candidates = detect_candidates(read_json(args.address_book), archive)
    output = {
        "schemaVersion": 1,
        "generatedAt": now_iso(),
        "source": "Archive Image Builder sanitized comparison",
        "archiveRecordCount": len(archive["worlds"]),
        "destinations": candidates,
    }
    write_json(Path(args.output), output)
    print(f"pending={len(candidates)} output={args.output}")


def fetch_text(url: str, *, accept: str = "text/html") -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8", errors="replace")


def strip_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(html.unescape(value).split())


def fandom_research(name: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"action": "query", "list": "search", "srsearch": name, "srlimit": 3, "format": "json", "origin": "*"})
    url = f"https://stargate.fandom.com/api.php?{query}"
    try:
        data = json.loads(fetch_text(url, accept="application/json"))
        results = data.get("query", {}).get("search", [])
        if not results:
            raise ValueError("no result")
        result = results[0]
        title = result.get("title", name)
        extract_query = urllib.parse.urlencode({"action": "parse", "page": title, "prop": "text", "format": "json", "origin": "*"})
        extract_data = json.loads(fetch_text(f"https://stargate.fandom.com/api.php?{extract_query}", accept="application/json"))
        page_html = extract_data.get("parse", {}).get("text", {}).get("*", "")
        paragraphs = [strip_markup(paragraph) for paragraph in re.findall(r"<p[^>]*>(.*?)</p>", page_html, re.I | re.S)]
        extract = " ".join(paragraph for paragraph in paragraphs if len(paragraph) > 80)
        return {
            "source": "Stargate Wiki",
            "status": "candidate",
            "title": title,
            "url": f"https://stargate.fandom.com/wiki/{urllib.parse.quote(str(title).replace(' ', '_'))}",
            "excerpt": (" ".join(extract.split()) or strip_markup(result.get("snippet", "")))[:1800],
        }
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        return {
            "source": "Stargate Wiki",
            "status": "unavailable",
            "url": f"https://stargate.fandom.com/wiki/Special:Search?query={urllib.parse.quote(name)}",
            "error": str(error),
        }


def gateworld_research(name: str) -> dict[str, Any]:
    slug = urllib.parse.quote(name.replace(" ", "_"))
    profile_url = f"https://www.gateworld.net/wiki/{slug}"
    search_url = f"https://www.gateworld.net/wiki/Special:Search?search={urllib.parse.quote(name)}"
    try:
        page = fetch_text(profile_url)
        title = re.search(r"<title>(.*?)</title>", page, re.I | re.S)
        paragraphs = [strip_markup(paragraph) for paragraph in re.findall(r"<p[^>]*>(.*?)</p>", page, re.I | re.S)]
        excerpt = " ".join(paragraph for paragraph in paragraphs if len(paragraph) > 80)[:1800]
        if not excerpt:
            raise ValueError("profile returned no description")
        return {
            "source": "GateWorld",
            "status": "candidate",
            "title": strip_markup(title.group(1)) if title else name,
            "url": profile_url,
            "searchUrl": search_url,
            "excerpt": excerpt[:900],
        }
    except (OSError, ValueError) as error:
        return {"source": "GateWorld", "status": "search-required", "url": search_url, "error": str(error)}


def classify_destination(name: str, evidence: str) -> tuple[str, str, str]:
    text = f"{name} {evidence}".lower()
    rules = [
        (("ship", "vessel", "destiny"), "object", "SPACECRAFT / ARTIST CONCEPT", "ARCHIVE VESSEL"),
        (("base", "outpost", "command", "facility"), "object", "BASE / ARTIST CONCEPT", "ARCHIVE INSTALLATION"),
        (("device", "weapon", "destroyer", "machine"), "object", "DEVICE / ARTIST CONCEPT", "ARCHIVE DEVICE"),
        (("black hole", "singularity"), "planet", "SPACE / SINGULARITY", "ASTRONOMICAL PHENOMENON"),
    ]
    for words, mode, environment, classification in rules:
        if any(word in text for word in words):
            return mode, environment, classification
    return "planet", "PLANETARY / ARTIST CONCEPT", "ARCHIVE WORLD"


def image_prompt(candidate: dict[str, Any], sources: list[dict[str, Any]], mode: str) -> str:
    evidence = " ".join(source.get("excerpt", "") for source in sources if source.get("excerpt"))
    evidence_note = evidence[:1800] or "No reliable visual description was found; create an explicitly fictional independent concept."
    subject = "spacecraft, installation, or device" if mode == "object" else "planetary destination viewed from space"
    return (
        f"Square 1:1 Stellar Archive artwork for {candidate['name']}, a {subject}. "
        f"Research evidence: {evidence_note} "
        "Cinematic realistic science-fiction concept art, one clear centered subject, readable at thumbnail size, "
        "deep dark space background, restrained cyan and warm-gold lighting, physically coherent materials. "
        "No text, letters, numbers, logos, watermark, UI, Stargate glyphs, people, borders, or copyrighted franchise marks. "
        "Do not copy an unrelated franchise design. If evidence is uncertain, make an original fictional reconstruction."
    )


def research_record(candidate: dict[str, Any], *, offline: bool) -> dict[str, Any]:
    sources = [] if offline else [fandom_research(candidate["name"]), gateworld_research(candidate["name"])]
    evidence = " ".join(source.get("excerpt", "") for source in sources)
    mode, environment, classification = classify_destination(candidate["name"], evidence)
    has_evidence = any(source.get("excerpt") for source in sources)
    summary = next((source.get("excerpt") for source in sources if source.get("excerpt")), "")
    return {
        **candidate,
        "sources": sources,
        "visualMode": mode,
        "environment": environment,
        "classification": classification,
        "description": summary or "No verified planetary profile is available for this address-book record. The visual will be an independent fictional concept.",
        "evidenceLevel": "source-candidate" if has_evidence else "fictional-placeholder",
        "prompt": image_prompt(candidate, sources, mode),
        "approval": {"generation": None, "archive": None},
        "imagePath": None,
    }


def approval_html(review: dict[str, Any]) -> str:
    cards = []
    for record in review["destinations"]:
        sources = "".join(
            f'<li><a href="{html.escape(source.get("url", ""), quote=True)}">{html.escape(source["source"])}</a> — {html.escape(source.get("status", ""))}</li>'
            for source in record.get("sources", [])
        ) or "<li>Offline preparation — source research still required.</li>"
        image = f'<img src="{html.escape(record["imagePath"], quote=True)}" alt="Generated candidate">' if record.get("imagePath") else '<div class="placeholder">IMAGE NOT GENERATED</div>'
        cards.append(f'''<article><h2>{html.escape(record["name"])}</h2>{image}<p><b>{html.escape(record["reason"])}</b> · {html.escape(record["category"].upper())} · {" · ".join(map(str, record["storedAddress"]))}</p><p>{html.escape(record["description"])}</p><ul>{sources}</ul><details><summary>Generation prompt</summary><pre>{html.escape(record["prompt"])}</pre></details><p>Generation approval: {html.escape(str(record["approval"]["generation"] or "PENDING"))}<br>Archive approval: {html.escape(str(record["approval"]["archive"] or "PENDING"))}</p></article>''')
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><title>Archive Image Builder review</title><style>body{{margin:0;background:#03111a;color:#d9edf0;font:15px system-ui;padding:28px}}header{{max-width:1100px;margin:auto auto 24px}}main{{max-width:1100px;margin:auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(310px,1fr));gap:18px}}article{{border:1px solid #567f87;background:#061d27;padding:18px}}h1,h2{{font-family:Georgia;color:#efdba9;letter-spacing:.08em}}img,.placeholder{{width:100%;aspect-ratio:1;object-fit:contain;background:#020b14;display:grid;place-items:center;color:#6ba5af}}a{{color:#91e1ef}}pre{{white-space:pre-wrap;font-size:12px}}code{{color:#b8f0f7}}</style><header><h1>Archive Image Builder</h1><p>Review only. This page cannot approve, modify, deploy or publish the Archive.</p><p>Approve from Terminal with <code>python3 archive_image_builder.py approve --review REVIEW.json --id ID --stage generation --yes</code>.</p></header><main>{''.join(cards)}</main></html>'''


def write_review_outputs(review_path: Path, review: dict[str, Any]) -> None:
    write_json(review_path, review)
    review_path.with_suffix(".html").write_text(approval_html(review), encoding="utf-8")


def command_research(args: argparse.Namespace) -> None:
    pending = read_json(args.pending)
    records = [research_record(candidate, offline=args.offline) for candidate in pending.get("destinations", [])]
    review = {"schemaVersion": 1, "generatedAt": now_iso(), "destinations": records}
    output = Path(args.output)
    write_review_outputs(output, review)
    print(f"prepared={len(records)} review={output} html={output.with_suffix('.html')}")


def find_review_record(review: dict[str, Any], record_id: str) -> dict[str, Any]:
    matches = [record for record in review["destinations"] if record_id in {record.get("id"), normalize_name(record["name"]).replace(" ", "-")}]
    if len(matches) != 1:
        raise SystemExit(f"review destination not found or ambiguous: {record_id}")
    return matches[0]


def command_approve(args: argparse.Namespace) -> None:
    if not args.yes:
        raise SystemExit("approval requires --yes after visual/user review")
    review_path = Path(args.review)
    review = read_json(review_path)
    record = find_review_record(review, args.id)
    if args.stage == "archive" and (not record["approval"].get("generation") or not record.get("imagePath")):
        raise SystemExit("archive approval requires generation approval and a generated or imported image")
    record["approval"][args.stage] = now_iso()
    write_review_outputs(review_path, review)
    print(f"approved={args.stage} destination={record['name']}")


def openai_generate(prompt: str, model: str, quality: str) -> bytes:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise SystemExit("OPENAI_API_KEY is not set; the key is never read from a repository file")
    body = json.dumps({"model": model, "prompt": prompt, "n": 1, "size": "1024x1024", "quality": quality, "output_format": "png", "background": "opaque"}).encode()
    request = urllib.request.Request(OPENAI_IMAGES_URL, data=body, method="POST", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        raise SystemExit(f"image API failed: HTTP {error.code}: {detail}") from error
    try:
        return base64.b64decode(payload["data"][0]["b64_json"], validate=True)
    except (KeyError, IndexError, ValueError) as error:
        raise SystemExit("image API response did not contain base64 image data") from error


def command_generate(args: argparse.Namespace) -> None:
    review_path = Path(args.review)
    review = read_json(review_path)
    record = find_review_record(review, args.id)
    if not record["approval"].get("generation"):
        raise SystemExit("generation is locked until explicit generation approval")
    output_dir = review_path.parent / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = normalize_name(record["name"]).replace(" ", "-") or "destination"
    output = output_dir / f"{slug}-candidate-v1.png"
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing candidate: {output}")
    output.write_bytes(openai_generate(record["prompt"], args.model, args.quality))
    if not output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        output.unlink(missing_ok=True)
        raise SystemExit("generated response is not a PNG")
    record["imagePath"] = str(output.relative_to(review_path.parent))
    record["imageModel"] = args.model
    record["imageGeneratedAt"] = now_iso()
    record["approval"]["archive"] = None
    write_review_outputs(review_path, review)
    print(f"generated={output} review_required=true")


def command_import_image(args: argparse.Namespace) -> None:
    review_path = Path(args.review).resolve()
    review = read_json(review_path)
    record = find_review_record(review, args.id)
    if not record["approval"].get("generation"):
        raise SystemExit("image import is locked until explicit generation approval")
    source = Path(args.image).resolve()
    if not source.is_file() or not source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit(f"candidate image is missing or not PNG: {source}")
    output_dir = review_path.parent / "images"
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = normalize_name(record["name"]).replace(" ", "-") or "destination"
    output = output_dir / f"{slug}-candidate-v1.png"
    if output.exists() and not args.force:
        raise SystemExit(f"refusing to overwrite existing candidate: {output}")
    shutil.copyfile(source, output)
    record["imagePath"] = str(output.relative_to(review_path.parent))
    record["imageModel"] = "external-reviewed-import"
    record["imageGeneratedAt"] = now_iso()
    record["approval"]["archive"] = None
    write_review_outputs(review_path, review)
    print(f"imported={output} review_required=true")


def deterministic_visuals(name: str, address: list[int]) -> tuple[int, int, int, int]:
    digest = hashlib.sha256(f"{name}|{address_key(address)}".encode()).digest()
    return int.from_bytes(digest[:4], "big"), digest[4] % 360, 15 + digest[5] % 71, 15 + digest[6] % 69


def next_record_id(worlds: list[dict[str, Any]], category: str, name: str) -> tuple[str, int]:
    indexes = [int(match.group(1)) for world in worlds if (match := re.match(rf"{re.escape(category)}-(\d+)-", world["id"]))]
    index = max(indexes, default=0) + 1
    slug = normalize_name(name).replace(" ", "-") or "destination"
    return f"{category}-{index:03d}-{slug}", index


def append_world_style(path: Path, world: dict[str, Any]) -> None:
    hue = world["hue"]
    shift = 0 if world["category"] in {"standard", "lan"} else world["seed"] % 31 - 15
    line = (
        f".visual-{world['id']}{{--planet-light:hsl({hue} 65% 73%);--planet-mid:hsl({(hue-35)%360} 52% 42%);"
        f"--planet-dark:hsl({(hue+18)%360} 44% 17%);--seed:{world['seed']%17};--planet-image:url('assets/{world['visualAsset']}');"
        f"--planet-shift:{shift}deg}}.position-{world['id']}{{left:{world['x']}%;top:{world['y']}%}}\n"
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def command_apply(args: argparse.Namespace) -> None:
    review_path = Path(args.review).resolve()
    review = read_json(review_path)
    record = find_review_record(review, args.id)
    if not record["approval"].get("archive"):
        raise SystemExit("archive update is locked until explicit archive approval")
    image_source = (review_path.parent / record["imagePath"]).resolve()
    if not image_source.is_file() or not image_source.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise SystemExit(f"approved image is missing or not PNG: {image_source}")
    worlds_path = Path(args.worlds).resolve()
    archive = read_json(worlds_path)
    worlds = archive["worlds"]
    candidate = {"name": record["name"], "category": record["category"], "storedAddress": record["storedAddress"]}
    if not detect_candidates({"destinations": [candidate]}, archive):
        raise SystemExit("destination is already present in the Archive")
    world_id, index = next_record_id(worlds, record["category"], record["name"])
    seed, hue, x, y = deterministic_visuals(record["name"], record["storedAddress"])
    asset_name = f"archive-approved-{world_id}-v1.png"
    asset_target = ARCHIVE / "assets" / asset_name
    if asset_target.exists():
        raise SystemExit(f"refusing to overwrite existing asset: {asset_target}")
    if not args.no_sprite and shutil.which("magick") is None:
        raise SystemExit("ImageMagick 'magick' is required before any Archive file is changed")
    source_refs = [f"{source['source']}: {source.get('title', record['name'])}" for source in record.get("sources", []) if source.get("status") == "candidate"] or ["FAN113 sanitized address book"]
    stored = [int(glyph) for glyph in record["storedAddress"]]
    world = {
        "id": world_id, "name": record["name"], "category": record["category"], "galaxy": "Milky Way",
        "designation": f"{record['category'].upper()} · {index:03d}", "environment": record["environment"],
        "classification": record["classification"], "description": record["description"],
        "evidenceLevel": record["evidenceLevel"], "sourceRefs": source_refs,
        "storedAddress": stored, "verifiedAddress": stored, "fullAddress": [*stored, 1],
        "addressLength": len(stored) + 1, "pointOfOrigin": 1, "addressStatus": "source-preserved",
        "addressNote": "FAN113 source sequence retained; Earth point-of-origin 1 appended for display.",
        "blackHole": False, "online": None,
        "visualStatus": "SOURCE-GUIDED ARTIST RECONSTRUCTION" if record["evidenceLevel"] == "source-candidate" else "FICTIONAL / UNCONFIRMED VISUAL",
        "visualAsset": asset_name, "visualMode": record["visualMode"], "hue": hue, "x": x, "y": y, "seed": seed,
    }
    insert_at = max((position for position, existing in enumerate(worlds) if existing["category"] == world["category"]), default=len(worlds) - 1) + 1
    managed_paths = [worlds_path, worlds_path.with_suffix(".js"), ARCHIVE / "world-styles.css", ARCHIVE / "thumbnail-sprite.css"]
    originals = {path: path.read_bytes() if path.exists() else None for path in managed_paths}
    optimized = ARCHIVE / "assets" / "optimized"
    original_sprites = set(optimized.glob("*.webp")) if optimized.exists() else set()
    try:
        shutil.copyfile(image_source, asset_target)
        worlds.insert(insert_at, world)
        archive["count"] = len(worlds)
        archive["generatedAt"] = dt.date.today().isoformat()
        write_json(worlds_path, archive)
        worlds_path.with_suffix(".js").write_text("window.STELLAR_ARCHIVE_DATA=" + json.dumps(archive, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
        append_world_style(ARCHIVE / "world-styles.css", world)
        if not args.no_sprite:
            subprocess.run([sys.executable, str(ROOT / "build_catalogue_sprite.py")], cwd=ROOT, check=True)
    except BaseException:
        asset_target.unlink(missing_ok=True)
        for path, content in originals.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        if optimized.exists():
            for sprite in set(optimized.glob("*.webp")) - original_sprites:
                sprite.unlink(missing_ok=True)
        raise
    record["appliedAt"] = now_iso()
    record["archiveId"] = world_id
    write_review_outputs(review_path, review)
    print(f"applied={world_id} records={len(worlds)} asset={asset_name} deployment=false release=false")


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest="command", required=True)
    detect = commands.add_parser("detect", help="compare an address-book export with the packaged Archive")
    detect.add_argument("--address-book", required=True)
    detect.add_argument("--worlds", default=str(DEFAULT_WORLDS))
    detect.add_argument("--output", default="work/archive-image-builder/pending.json")
    detect.set_defaults(func=command_detect)
    research = commands.add_parser("research", help="research pending destinations and create an approval page")
    research.add_argument("--pending", required=True)
    research.add_argument("--output", default="work/archive-image-builder/review.json")
    research.add_argument("--offline", action="store_true", help="prepare prompts without contacting research sites")
    research.set_defaults(func=command_research)
    approve = commands.add_parser("approve", help="record explicit generation or Archive approval")
    approve.add_argument("--review", required=True)
    approve.add_argument("--id", required=True, help="record id or normalized destination name")
    approve.add_argument("--stage", choices=("generation", "archive"), required=True)
    approve.add_argument("--yes", action="store_true")
    approve.set_defaults(func=command_approve)
    generate = commands.add_parser("generate", help="generate one explicitly approved candidate image")
    generate.add_argument("--review", required=True)
    generate.add_argument("--id", required=True)
    generate.add_argument("--model", default=os.environ.get("ARCHIVE_IMAGE_MODEL", DEFAULT_IMAGE_MODEL))
    generate.add_argument("--quality", choices=("low", "medium", "high", "xhigh", "max"), default="medium")
    generate.add_argument("--force", action="store_true")
    generate.set_defaults(func=command_generate)
    image_import = commands.add_parser("import-image", help="import one externally generated PNG candidate")
    image_import.add_argument("--review", required=True)
    image_import.add_argument("--id", required=True)
    image_import.add_argument("--image", required=True)
    image_import.add_argument("--force", action="store_true")
    image_import.set_defaults(func=command_import_image)
    apply_command = commands.add_parser("apply", help="add one explicitly approved record to local release sources")
    apply_command.add_argument("--review", required=True)
    apply_command.add_argument("--id", required=True)
    apply_command.add_argument("--worlds", default=str(DEFAULT_WORLDS))
    apply_command.add_argument("--no-sprite", action="store_true", help=argparse.SUPPRESS)
    apply_command.set_defaults(func=command_apply)
    return cli


def main() -> None:
    args = parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
