"""Offline VLM prompt comparison: same frames, same YOLOE detections, same Qwen
settings, one answer per prompt version, saved for labelling and scoring.

    python -m vision_ai.tooling.vlm_prompt_compare \
        --dataset data/pinky_camera/merged_export_split --split valid \
        --weights experiments/<stamp>/selected_model.json \
        --versions current v1 v2 --out runs/vlm_prompt_compare/valid

Flow: order each recording's frames by the time in the file name -> YOLOE
predict for the objects, and YOLOE + ByteTrack (reset at each new recording,
the frames taken as consecutive) for their ids -> `worker.detection_evidence`,
the robot's own conversion ->
match the labelled (ground-truth) objects to detections by box IoU
-> detections.jsonl -> every version on one loaded Qwen, frame by frame
-> responses.jsonl -> review.csv, overlays/, summary.json.

review.csv has one row per labelled object (plus one per detection that
matches no label). `risk_label` starts as the --draft-version answer; correct
it against overlays/ and the image. That column, keyed by gt_object_id, is the
answer key the scoring step will read.

Why two passes: after its first frame ByteTrack holds back a newly seen object
until it is seen again. At the robot's 15 fps that is one frame; on frames 1 s
apart an object that just appeared or moved far would vanish from the VLM's
input. So the objects come from predict, and an object the tracker did not
return keeps track_id null.

Re-running reuses detections.jsonl and skips (image, version) pairs already in
responses.jsonl, so an interrupted run resumes and a new version is added.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import re
from pathlib import Path
from typing import Any

from vision_ai.robot.recovery.worker import (
    GOAL_TEXT, DetectionEvidence, box_iou, detection_evidence, link_observations,
    validated_observations,
)

_EPISODE = re.compile(r"dataset_video_(\d{8}_\d{6})")
_STAMP = re.compile(r"_t(\d{4})-(\d{2})s")
MATCH_IOU = 0.5                  # box IoU for "this detection is that labelled object"


def detect(dataset: Path, split: str, weights: Path, device: str) -> list[dict[str, Any]]:
    """One row per frame: its detections (as the robot sees them) and its labelled
    objects, each labelled object matched to at most one detection."""
    import cv2
    import yaml

    from vision_ai.data_loader.fall.compare_rows import parse_label
    from vision_ai.models.perception.detector import Detector, DetectorConfig

    names = yaml.safe_load((dataset / "data.yaml").read_text(encoding="utf-8"))["names"]
    person_id = names.index("person")
    detector = Detector(weights, DetectorConfig(person_class_id=person_id, device=device))
    tracker = Detector(weights, DetectorConfig(person_class_id=person_id, device=device, tracking=True))
    tracker.load()

    def order(path: Path):
        """(recording, seconds into it, name); None where the name does not say."""
        episode, stamp = _EPISODE.search(path.name), _STAMP.search(path.name)
        return (episode[1] if episode else None,
                int(stamp[1]) + int(stamp[2]) / 100 if stamp else None, path.name)

    frames = sorted(((order(p), p) for p in (dataset / split / "images").iterdir()),
                    key=lambda item: (item[0][0] or "~", item[0][1] or 0.0, item[0][2]))
    rows, current_episode = [], object()
    for (episode, seconds, _), path in frames:
        if episode != current_episode or episode is None:
            tracker.reset_tracking()
            current_episode = episode
        frame = cv2.imread(str(path))
        tracked = detection_evidence(tracker.detect(frame), person_class_id=person_id)
        evidence = [dataclasses.replace(e, track_id=next(
                        (t.track_id for t in tracked
                         if box_iou(t.bbox_xyxy_norm, e.bbox_xyxy_norm) >= MATCH_IOU), None))
                    for e in detection_evidence(detector.detect(frame), person_class_id=person_id)]
        if episode is None or seconds is None:           # no frame order: no track
            evidence = [dataclasses.replace(e, track_id=None) for e in evidence]

        label = dataset / split / "labels" / f"{path.stem}.txt"
        truth = [{"class_name": class_name, "bbox_xyxy_norm": [
                      min(x for x, _ in points), min(y for _, y in points),
                      max(x for x, _ in points), max(y for _, y in points)]}
                 for class_name, points in parse_label(label.read_text(encoding="utf-8"), names) or []]
        truth.sort(key=lambda t: t["bbox_xyxy_norm"][0] + t["bbox_xyxy_norm"][2])

        pairs = sorted(((box_iou(t["bbox_xyxy_norm"], e.bbox_xyxy_norm), ti, ei)
                        for ti, t in enumerate(truth) for ei, e in enumerate(evidence)), reverse=True)
        taken_t, taken_e = set(), set()
        for number, item in enumerate(truth, start=1):
            item.update(gt_object_id=f"g{number}", region_id=None, iou=0.0)
        for iou, ti, ei in pairs:
            if iou >= MATCH_IOU and ti not in taken_t and ei not in taken_e:
                taken_t.add(ti)
                taken_e.add(ei)
                truth[ti].update(region_id=evidence[ei].region_id, iou=round(iou, 3))
        rows.append({"image": f"{split}/images/{path.name}", "episode": episode, "t_s": seconds,
                     "detections": [dataclasses.asdict(e) for e in evidence], "gt": truth})
    return rows


def ask_vlm(rows: list[dict], dataset: Path, versions: list[str], revision: str, out: Path) -> None:
    """Append one line per (frame, version) to responses.jsonl, skipping those done.

    A frame with no detection is skipped: the robot never asks the VLM then.
    """
    import cv2

    from vision_ai.models.recovery.vlm_interpreter import QwenVlmInterpreter

    path = out / "responses.jsonl"
    done = {(r["image"], r["version"]) for r in _read_jsonl(path)}
    vlm = QwenVlmInterpreter(revision)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            evidence = [DetectionEvidence(**{**d, "bbox_xyxy_norm": tuple(d["bbox_xyxy_norm"])})
                        for d in row["detections"]]
            todo = [v for v in versions if (row["image"], v) not in done]
            if not evidence or not todo:
                continue
            frame = cv2.imread(str(dataset / row["image"]))
            for version in todo:
                result = vlm.interpret(frame, evidence, GOAL_TEXT, version=version)
                observations = result.get("observations")
                answers = ([o for o in observations if isinstance(o, dict)]
                           if isinstance(observations, list) else [])
                linked = link_observations(answers, evidence)
                handle.write(json.dumps({
                    "image": row["image"], "version": version, "revision": revision,
                    "valid": validated_observations(result) is not None,
                    "linked": {evidence[i].region_id: o for i, o in linked.items()},
                    "result": result,
                }, ensure_ascii=False) + "\n")
                handle.flush()


def write_outputs(rows: list[dict], dataset: Path, versions: list[str], draft: str, out: Path) -> dict:
    """review.csv, overlays/ and summary.json from detections and responses."""
    import cv2

    answers = {(r["image"], r["version"]): r for r in _read_jsonl(out / "responses.jsonl")}
    columns = ["image", "episode", "t_s", "gt_object_id", "gt_class", "region_id", "track_id",
               "pred_class", "yoloe_confidence", "match_iou"]
    for version in versions:
        columns += [f"{version}_risk", f"{version}_confidence", f"{version}_evidence"]
    columns += ["risk_label", "label_note"]

    (out / "overlays").mkdir(exist_ok=True)
    with (out / "review.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            by_region = {d["region_id"]: d for d in row["detections"]}
            matched = {g["region_id"] for g in row["gt"]}
            entries = [(g, by_region.get(g["region_id"])) for g in row["gt"]]
            entries += [(None, d) for d in row["detections"] if d["region_id"] not in matched]
            for gt, det in entries:
                line = {"image": row["image"], "episode": row["episode"], "t_s": row["t_s"],
                        "gt_object_id": gt["gt_object_id"] if gt else "",
                        "gt_class": gt["class_name"] if gt else "(no label)",
                        "match_iou": gt["iou"] if gt else ""}
                if det:
                    line.update(region_id=det["region_id"], track_id=det["track_id"] or "",
                                pred_class=det["class_name"],
                                yoloe_confidence=round(det["confidence"], 3))
                    for version in versions:
                        answer = answers.get((row["image"], version), {}).get("linked", {}).get(det["region_id"], {})
                        line.update({f"{version}_risk": answer.get("risk", ""),
                                     f"{version}_confidence": answer.get("confidence", ""),
                                     f"{version}_evidence": answer.get("evidence", "")})
                line["risk_label"] = line.get(f"{draft}_risk", "") if draft != "none" else ""
                writer.writerow(line)

            image = cv2.imread(str(dataset / row["image"]))
            h, w = image.shape[:2]
            for color, items, text in (((60, 200, 60), row["gt"], lambda g: g["gt_object_id"]),
                                       ((0, 140, 255), row["detections"],
                                        lambda d: f'{d["region_id"]} #{d["track_id"] or "-"} '
                                                  f'{d["class_name"]} {d["confidence"]:.2f}')):
                for item in items:
                    x0, y0, x1, y1 = item["bbox_xyxy_norm"]
                    p0, p1 = (int(x0 * w), int(y0 * h)), (int(x1 * w), int(y1 * h))
                    cv2.rectangle(image, p0, p1, color, 2)
                    cv2.putText(image, text(item), (p0[0] + 2, max(p0[1] - 4, 12)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)
            cv2.imwrite(str(out / "overlays" / Path(row["image"]).name), image)

    summary = {}
    for version in versions:
        got = [answers[(r["image"], version)] for r in rows if (r["image"], version) in answers]
        regions = sum(len(r["detections"]) for r in rows if (r["image"], version) in answers)
        answered = sum(len(a["linked"]) for a in got)
        results = [a["result"] for a in got]
        summary[version] = {
            "frames": len(got),
            "json_valid_rate": _rate(sum(a["valid"] for a in got), len(got)),
            "truncated": sum(bool(r.get("truncated")) for r in results),
            "regions": regions,
            "region_missing_rate": _rate(regions - answered, regions),
            "unlinked_observations": sum(
                len(r.get("observations") or []) for r in results
                if isinstance(r.get("observations"), list)) - answered,
            "mean_output_tokens": _rate(sum(r.get("output_tokens", 0) for r in results), len(results)),
            "mean_seconds": _rate(sum(r.get("seconds", 0) for r in results), len(results)),
        }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()] if path.is_file() else []


def _rate(part: float, whole: float) -> float | None:
    return round(part / whole, 4) if whole else None


def main(argv: list[str] | None = None) -> int:
    """Detect (once), ask every version, write the review files; print the summary."""
    from vision_ai.models.recovery.vlm_interpreter import load_prompts

    parser = argparse.ArgumentParser(description="Compare VLM prompt versions offline")
    parser.add_argument("--dataset", type=Path, required=True, help="merged_export_split")
    parser.add_argument("--split", default="valid", choices=("train", "valid", "test"))
    parser.add_argument("--weights", type=Path, help="YOLOE best.pt or selected_model.json; "
                                                     "needed until detections.jsonl exists")
    parser.add_argument("--versions", nargs="+", help="default: every version in prompts.yaml")
    parser.add_argument("--draft-version", default="v1",
                        help="answers copied into risk_label as a starting point, or 'none'")
    parser.add_argument("--revision", default=os.environ.get("VLM_MODEL_REVISION", "main"))
    parser.add_argument("--device", default="auto")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    versions = args.versions or list(load_prompts()["versions"])
    args.out.mkdir(parents=True, exist_ok=True)
    detections_path = args.out / "detections.jsonl"
    rows = _read_jsonl(detections_path)
    if not rows:
        if args.weights is None:
            parser.error("--weights is needed to build detections.jsonl")
        rows = detect(args.dataset, args.split, args.weights, args.device)
        detections_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    ask_vlm(rows, args.dataset, versions, args.revision, args.out)
    summary = write_outputs(rows, args.dataset, versions, args.draft_version, args.out)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
