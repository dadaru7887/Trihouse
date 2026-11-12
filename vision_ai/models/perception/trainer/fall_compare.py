"""Compare three fall-feature sets on the same people, split and training recipe.

    # ground-truth masks
    python -m vision_ai.models.perception.trainer.fall_compare \
        --export data/pinky_camera/fallen \
        --merged data/pinky_camera/merged_export_split \
        --masks gt --out runs/fall_compare/gt

    # YOLOE masks; a labelled person YOLOE missed counts as a missed fall
    python -m vision_ai.models.perception.trainer.fall_compare \
        --export data/pinky_camera/fallen \
        --merged data/pinky_camera/merged_export_split \
        --masks predicted --weights <experiment>/selected_model.json \
        --out runs/fall_compare/predicted

Groups (see data_loader/fall/compare_rows.py):

    A  upstream five: aspect, PCA angle, centroid y, person IoU, obstacle IoU
    B  normalised aspect ratio r
    C  r + axis horizontality h

Flow: build rows -> fit each group with `fall_model.fit_candidates` (one
LogisticRegression, scaler from train only, wrapped in SumModel) -> pick two
thresholds on valid (recall floor then best precision; best F1) -> score test
once at those fixed thresholds -> compare A vs C and B vs C -> write
rows.jsonl, report.json, report.md and case sheets under --out.

Scope: single-image posture classification. No temporal smoothing.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from vision_ai.data_loader.fall.compare_rows import GROUPS, build_rows, context_audit
from vision_ai.models.perception.trainer.fall_model import fit_candidates
from vision_ai.models.perception.trainer.fall_trainer import (
    THRESHOLD_CANDIDATES, _scores, _select_threshold,
)

# Recall floor of the existing fall trainer; used when no other target is set.
DEFAULT_MIN_RECALL = 0.85
# Representative cases drawn per category.
CASES_PER_SHEET = 6


def _f1(scored: dict) -> float:
    """F1 from a _scores() dict."""
    p, r = scored["precision"], scored["recall"]
    return round(2 * p * r / (p + r), 6) if p + r else 0.0


def _metrics(labels: Sequence[int], decisions: Sequence[int]) -> dict:
    """Precision, recall, F1 and TP/FP/FN/TN counts."""
    scored = _scores(list(labels), list(decisions))
    scored["f1"] = _f1(scored)
    scored["true_negative"] = sum(1 for y, d in zip(labels, decisions) if y == 0 and d == 0)
    return scored


def _candidates(probabilities) -> list[float]:
    """Every distinct valid score, ascending: each is one reachable operating point.

    Used instead of a fixed 0.05 grid so that a model whose probabilities sit
    on a different scale is not handicapped by where the grid lines fall.
    """
    return sorted({round(float(p), 6) for p in probabilities})


def _floor_threshold(labels, probabilities, min_recall: float) -> tuple[float, dict, bool]:
    """Most precise candidate meeting the recall floor; ties keep the lowest.

    Same rule as fall_trainer._select_threshold, over `_candidates`. With no
    candidate meeting the floor, the highest-recall one is returned with False.
    """
    rows = [(t, _metrics(labels, [int(p >= t) for p in probabilities]))
            for t in _candidates(probabilities)]
    passing = [row for row in rows if row[1]["recall"] >= min_recall]
    if passing:
        t, scored = max(passing, key=lambda row: (row[1]["precision"], row[1]["recall"]))
        return t, scored, True
    t, scored = max(rows, key=lambda row: (row[1]["recall"], row[1]["precision"]))
    return t, scored, False


def _f1_threshold(labels, probabilities, candidates=None) -> tuple[float, dict]:
    """Candidate with the highest valid F1; ties keep the lowest threshold."""
    best = None
    for candidate in candidates if candidates is not None else _candidates(probabilities):
        scored = _metrics(labels, [int(p >= candidate) for p in probabilities])
        if best is None or scored["f1"] > best[1]["f1"]:
            best = (candidate, scored)
    return best


def _curve(labels, probabilities) -> list[dict]:
    """Valid precision/recall/F1 on the 0.05 grid, for plotting."""
    return [{"threshold": t, **_metrics(labels, [int(p >= t) for p in probabilities])}
            for t in THRESHOLD_CANDIDATES]


def _binom_p(b: int, c: int) -> float | None:
    """Exact two-sided McNemar p-value for b vs c discordant pairs."""
    if b + c == 0:
        return None
    from scipy.stats import binomtest

    return round(float(binomtest(b, b + c, 0.5).pvalue), 6)


def fit_and_score(rows: list[dict], min_recall: float) -> tuple[dict[str, Any], dict]:
    """Fit every group, choose thresholds on valid, and score each row.

    Adds `scores[group]` to every measurable row. Returns (per-group summary
    with thresholds and valid curves, fitted SumModel per group).
    """
    measurable = [r for r in rows if r["features"] is not None]
    train = [r for r in measurable if r["split"] == "train"]
    valid = [r for r in measurable if r["split"] == "valid"]
    out, fitted = {}, {}
    for group, names in GROUPS.items():
        # fit_candidates z-scores with train statistics only and fits one
        # LogisticRegression(max_iter=1000) per call -- identical for A, B, C.
        model = fitted[group] = fit_candidates(train, modes=names)["sum"]
        for row in measurable:
            row.setdefault("scores", {})[group] = model.score(row["features"])
        labels = [int(r["fallen"]) for r in valid]
        probabilities = [r["scores"][group] for r in valid]
        threshold, at_floor, floor_met = _floor_threshold(labels, probabilities, min_recall)
        f1_threshold, at_f1 = _f1_threshold(labels, probabilities)
        # The existing trainer's 0.05 grid, kept for reference only.
        grid_t, grid_scored, grid_met = _select_threshold(labels, probabilities, min_recall)
        out[group] = {
            "features": list(model.features), "dropped": list(model.dropped),
            "train_mean": [round(float(v), 6) for v in model.mean],
            "train_std": [round(float(v), 6) for v in model.std],
            "weights": [round(float(v), 6) for v in model.weights],
            "bias": round(float(model.bias), 6),
            "threshold_recall_floor": threshold, "recall_floor_met": floor_met,
            "threshold_f1": f1_threshold,
            "valid_at_recall_floor": {**at_floor, "f1": _f1(at_floor)},
            "valid_at_f1": at_f1,
            "reference_grid": {"threshold_recall_floor": grid_t, "recall_floor_met": grid_met,
                               "valid": {**grid_scored, "f1": _f1(grid_scored)}},
            "valid_curve": _curve(labels, probabilities),
        }
    return out, fitted


def _decide(row: dict, group: str, threshold: float) -> int:
    """1 if this row is called fallen; an unmeasured row is never called."""
    if row.get("features") is None:
        return 0
    return int(row["scores"][group] >= threshold)


def evaluate(rows: list[dict], models: dict, split: str = "test") -> dict[str, Any]:
    """Test metrics per group at both fixed thresholds.

    `classifier` uses only measured rows. `end_to_end` uses every labelled
    person, so a person YOLOE missed is a false negative when fallen.
    """
    subset = [r for r in rows if r["split"] == split]
    measured = [r for r in subset if r["features"] is not None]
    out = {}
    for group, info in models.items():
        out[group] = {}
        for key in ("threshold_recall_floor", "threshold_f1"):
            t = info[key]
            out[group][key] = {
                "threshold": t,
                "classifier": _metrics([int(r["fallen"]) for r in measured],
                                       [_decide(r, group, t) for r in measured]),
                "end_to_end": _metrics([int(r["fallen"]) for r in subset],
                                       [_decide(r, group, t) for r in subset]),
            }
    return out


def flips(rows: list[dict], models: dict, left: str, right: str,
          key: str = "threshold_recall_floor", split: str = "test") -> dict[str, Any]:
    """Instances whose call changes from `left` to `right` at their own thresholds."""
    t_left, t_right = models[left][key], models[right][key]
    groups = {"gained_tp": [], "lost_tp": [], "new_fp": [], "removed_fp": []}
    for row in rows:
        if row["split"] != split or row["features"] is None:
            continue
        a, b = _decide(row, left, t_left), _decide(row, right, t_right)
        if a == b:
            continue
        name = ("gained_tp" if b else "lost_tp") if row["fallen"] else ("new_fp" if b else "removed_fp")
        groups[name].append({
            "image": row["image"], "episode": row["episode"], "instance": row["instance"],
            "r": round(row["features"]["aspect_ratio"], 4),
            "h": round(row["features"]["axis_horizontality"], 4),
            f"score_{left}": round(row["scores"][left], 4),
            f"score_{right}": round(row["scores"][right], 4)})
    summary = {k: len(v) for k, v in groups.items()}
    summary["mcnemar_p_fallen"] = _binom_p(summary["gained_tp"], summary["lost_tp"])
    summary["mcnemar_p_upright"] = _binom_p(summary["new_fp"], summary["removed_fp"])
    return {"thresholds": {left: t_left, right: t_right}, "counts": summary, "cases": groups}


def unmatched_alarms(unmatched: list[dict], models: dict, fitted: dict,
                     split: str = "test") -> dict:
    """How many unlabelled predicted people each group would call fallen."""
    subset = [u for u in unmatched if u["split"] == split and u["features"] is not None]
    out = {"predicted_people_without_label": len(subset)}
    for group, info in models.items():
        out[group] = sum(1 for u in subset if fitted[group].score(u["features"])
                         >= info["threshold_recall_floor"])
    return out


def render_cases(rows: list[dict], export_root: Path, out_dir: Path, categories: dict,
                 models: dict) -> dict[str, str]:
    """One PNG sheet per category: crops with outlines and each group's call."""
    import cv2
    import numpy as np

    index = {(r["image"], r["instance"]): r for r in rows}
    written = {}
    out_dir.mkdir(parents=True, exist_ok=True)
    for category, items in categories.items():
        tiles = []
        for item in items[:CASES_PER_SHEET]:
            row = index[(item["image"], item["instance"])]
            frame = cv2.imread(str(export_root / row["image"]))
            h, w = frame.shape[:2]
            label = (export_root / row["image"]).with_suffix(".txt")
            label = label.parent.parent / "labels" / label.name
            parts = label.read_text(encoding="utf-8").splitlines()[row["instance"]].split()[1:]
            poly = (np.asarray(parts, float).reshape(-1, 2) * [w, h]).astype(np.int32)
            cv2.polylines(frame, [poly], True, (0, 255, 0), 2)           # label: green
            if row.get("pred_polygon"):
                pred = (np.asarray(row["pred_polygon"]) * [w, h]).astype(np.int32)
                cv2.polylines(frame, [pred], True, (0, 255, 255), 1)     # YOLOE: yellow
            x0, y0, x1, y1 = row["box"]
            pad = 0.6 * max(x1 - x0, y1 - y0) + 0.05
            cx0, cy0 = int(max(0, (x0 - pad) * w)), int(max(0, (y0 - pad) * h))
            cx1, cy1 = int(min(w, (x1 + pad) * w)), int(min(h, (y1 + pad) * h))
            crop = cv2.resize(frame[cy0:cy1, cx0:cx1], (320, 240))
            caption = [f"{row['episode']} {'FALLEN' if row['fallen'] else 'standing'}",
                       f"r={row['features']['aspect_ratio']:.2f} h={row['features']['axis_horizontality']:.2f}",
                       " ".join(f"{g}:{row['scores'][g]:.2f}{'*' if row['scores'][g] >= models[g]['threshold_recall_floor'] else ''}"
                                for g in models)]
            band = np.zeros((60, 320, 3), np.uint8)
            for i, text in enumerate(caption):
                cv2.putText(band, text, (4, 16 + 19 * i), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                            (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(np.vstack([crop, band]))
        if not tiles:
            continue
        while len(tiles) % 3:
            tiles.append(np.zeros_like(tiles[0]))
        sheet = np.vstack([np.hstack(tiles[i:i + 3]) for i in range(0, len(tiles), 3)])
        path = out_dir / f"{category}.png"
        cv2.imwrite(str(path), sheet)
        written[category] = str(path)
    return written


def _case_categories(rows: list[dict], models: dict, bc: dict) -> dict[str, list[dict]]:
    """Representative instances: B->C flips, A vs C disagreements, misses by all."""
    def decided(row, g):
        return _decide(row, g, models[g]["threshold_recall_floor"])

    test = [r for r in rows if r["split"] == "test" and r["features"] is not None]
    pick = lambda pred: [{"image": r["image"], "instance": r["instance"]} for r in test if pred(r)]
    return {
        "B_to_C_gained_tp": bc["cases"]["gained_tp"],
        "B_to_C_new_fp": bc["cases"]["new_fp"],
        "A_right_C_wrong": pick(lambda r: decided(r, "A") == int(r["fallen"]) != decided(r, "C")),
        "C_right_A_wrong": pick(lambda r: decided(r, "C") == int(r["fallen"]) != decided(r, "A")),
        "all_missed_falls": pick(lambda r: r["fallen"] and not any(decided(r, g) for g in models)),
    }


def _fmt(m: dict) -> str:
    """One markdown table cell group: R / P / F1 / TP / FP / FN."""
    return (f"{m['recall']:.3f} | {m['precision']:.3f} | {m['f1']:.3f} | "
            f"{m['true_positive']} | {m['false_positive']} | {m['false_negative']}")


def write_markdown(report: dict, path: Path) -> None:
    """Human-readable summary of report.json, in Korean."""
    lines = [f"# 쓰러짐 자세 분류 특징 비교 — {report['masks']} 마스크", "",
             "검증 범위: 이미지 단위(단일 프레임) 자세 분류. 시간축 판단은 포함하지 않는다.", "",
             "## 데이터 분할 (세션 단위)", ""]
    for split, episodes in report["build"]["sessions"].items():
        n = report["counts"][split]
        lines.append(f"- **{split}**: {', '.join(episodes)} — 사람 {n['persons']} "
                     f"(Fallen {n['fallen']}), 특징 측정 {n['measured']}")
    lines += ["", f"제외: {json.dumps(report['build']['skipped'], ensure_ascii=False)}", ""]
    lines += ["## 검증 세트에서 고른 임계값", "",
              "후보는 valid 점수의 고유값 전체. 괄호는 기존 0.05 그리드로 골랐을 때(참고).", "",
              "| 모델 | 학습에 쓰인 특징 | 학습 분산 0으로 제외 | 임계값(Recall≥%.2f) | 충족 | valid R / P | 임계값(F1 최대) | valid F1 |" % report["min_recall"],
              "|---|---|---|---|---|---|---|---|"]
    for g, m in report["models"].items():
        v, ref = m["valid_at_recall_floor"], m["reference_grid"]
        lines.append(f"| {g} | {', '.join(m['features'])} | {', '.join(m['dropped']) or '-'} | "
                     f"{m['threshold_recall_floor']:.4f} ({ref['threshold_recall_floor']}) | "
                     f"{'예' if m['recall_floor_met'] else '아니오'} | {v['recall']:.3f} / {v['precision']:.3f} | "
                     f"{m['threshold_f1']:.4f} | {m['valid_at_f1']['f1']:.3f} |")
    for scope in ("classifier", "end_to_end"):
        if scope == "end_to_end" and report["masks"] == "gt":
            continue
        title = ("분류기 (검출된 사람만)" if scope == "classifier"
                 else "전체 자세 감지 (검출 누락 = 쓰러짐 미탐)")
        for key, label in (("threshold_recall_floor", "Recall 기준 임계값"), ("threshold_f1", "F1 최대 임계값")):
            lines += ["", f"## 테스트 — {title}, {label}", "",
                      "| 모델 | 임계값 | Recall | Precision | F1 | TP | FP | FN |", "|---|---|---|---|---|---|---|---|"]
            for g, res in report["test"].items():
                lines.append(f"| {g} | {res[key]['threshold']} | {_fmt(res[key][scope])} |")
    lines += ["", "## A ↔ C (5개 → 2개)", "", "| 임계값 | ΔRecall | ΔPrecision | ΔF1 | ΔTP | ΔFP | ΔFN |", "|---|---|---|---|---|---|---|"]
    for key, d in report["a_vs_c"]["delta"].items():
        lines.append(f"| {key} | {d['recall']:+.3f} | {d['precision']:+.3f} | {d['f1']:+.3f} | "
                     f"{d['true_positive']:+d} | {d['false_positive']:+d} | {d['false_negative']:+d} |")
    c = report["a_vs_c"]["flips"]["counts"]
    lines.append(f"\n인스턴스 단위 A→C: 새로 잡힌 쓰러짐 {c['gained_tp']}, 놓친 쓰러짐 {c['lost_tp']}, "
                 f"새 오탐 {c['new_fp']}, 사라진 오탐 {c['removed_fp']} "
                 f"(McNemar p: 쓰러짐 {c['mcnemar_p_fallen']}, 서 있음 {c['mcnemar_p_upright']})")
    c = report["b_vs_c"]["counts"]
    lines += ["", "## B ↔ C (h 추가)", "",
              f"새로 잡힌 쓰러짐 **{c['gained_tp']}**, 새로 놓친 쓰러짐 {c['lost_tp']}, "
              f"새로 생긴 오탐 **{c['new_fp']}**, 사라진 오탐 {c['removed_fp']} "
              f"(McNemar p: 쓰러짐 {c['mcnemar_p_fallen']}, 서 있음 {c['mcnemar_p_upright']}). "
              "McNemar는 인스턴스 독립을 가정하므로 같은 세션 프레임끼리 상관된 이 데이터에서는 낙관적이다.", ""]
    for name in ("gained_tp", "new_fp"):
        for item in report["b_vs_c"]["cases"][name]:
            lines.append(f"- {name}: `{item['image']}` #{item['instance']} r={item['r']} h={item['h']} "
                         f"B={item['score_B']} C={item['score_C']}")
    if report.get("unmatched_alarms"):
        u = report["unmatched_alarms"]
        lines += ["", "## 라벨 없는 예측 사람 (참고, 위 지표에 미포함)", "",
                  f"test에서 라벨과 매칭되지 않은 YOLOE person {u['predicted_people_without_label']}개 중 "
                  f"쓰러짐으로 판정: A {u['A']}, B {u['B']}, C {u['C']}"]
    lines += ["", "## 접촉 특징 입력 점검 (A)", "", "| 세션 | split | 사람 | Fallen | 사람 IoU>0 | 장애물 IoU>0 |", "|---|---|---|---|---|---|"]
    for ep, a in report["context_audit"].items():
        lines.append(f"| {ep} | {a['split']} | {a['persons']} | {a['fallen']} | "
                     f"{a['person_contact_nonzero']} | {a['obstacle_contact_nonzero']} |")
    lines += ["", "## 대표 사례", ""] + [f"- {k}: `{v}`" for k, v in report["case_sheets"].items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(export_root: Path, out_dir: Path, masks: str = "gt", weights: Path | None = None,
        merged_root: Path | None = None, min_recall: float = DEFAULT_MIN_RECALL,
        device: str = "auto") -> dict[str, Any]:
    """Run the whole comparison for one mask source and write its outputs."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, unmatched, build = build_rows(export_root, masks=masks, weights=weights,
                                        merged_root=merged_root, device=device)
    models, fitted = fit_and_score(rows, min_recall)
    test = evaluate(rows, models)
    delta = {}
    for key in ("threshold_recall_floor", "threshold_f1"):
        scope = "end_to_end" if masks == "predicted" else "classifier"
        a, c = test["A"][key][scope], test["C"][key][scope]
        delta[key] = {m: round(c[m] - a[m], 6) if isinstance(a[m], float) else c[m] - a[m]
                      for m in ("recall", "precision", "f1", "true_positive",
                                "false_positive", "false_negative")}
    bc = flips(rows, models, "B", "C")
    counts = {}
    for split in ("train", "valid", "test"):
        subset = [r for r in rows if r["split"] == split]
        counts[split] = {"persons": len(subset), "fallen": sum(r["fallen"] for r in subset),
                         "measured": sum(r["features"] is not None for r in subset),
                         "undetected": sum(not r["detected"] for r in subset),
                         "undetected_fallen": sum(r["fallen"] and not r["detected"] for r in subset)}
    report = {
        "masks": masks, "min_recall": min_recall, "build": build, "counts": counts,
        "models": models, "test": test,
        "a_vs_c": {"delta": delta, "flips": flips(rows, models, "A", "C")},
        "b_vs_c": bc,
        "unmatched_alarms": (unmatched_alarms(unmatched, models, fitted)
                             if masks == "predicted" else None),
        "context_audit": context_audit(rows),
    }
    report["case_sheets"] = render_cases(rows, Path(export_root), out_dir / "cases",
                                         _case_categories(rows, models, bc), models)
    with (out_dir / "rows.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out_dir / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                         encoding="utf-8")
    write_markdown(report, out_dir / "report.md")
    return report


def build_parser() -> argparse.ArgumentParser:
    """Command line: which export, which merge, which masks, where to write."""
    parser = argparse.ArgumentParser(description="Compare fall feature sets A/B/C")
    parser.add_argument("--export", type=Path, required=True,
                        help="Roboflow fallen export (Fallen/Obstacle/Standing)")
    parser.add_argument("--merged", type=Path,
                        help="Merged dataset the detector trained on; must agree with the export split")
    parser.add_argument("--masks", choices=("gt", "predicted"), default="gt")
    parser.add_argument("--weights", type=Path, help="best.pt or selected_model.json, for --masks predicted")
    parser.add_argument("--out", type=Path, required=True, help="Output directory")
    parser.add_argument("--min-recall", type=float, default=DEFAULT_MIN_RECALL,
                        help="Recall floor for the primary threshold on valid")
    parser.add_argument("--device", default="auto", help="auto, cpu, mps or a GPU index")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run and print the markdown summary."""
    args = build_parser().parse_args(argv)
    run(args.export, args.out, masks=args.masks, weights=args.weights,
        merged_root=args.merged, min_recall=args.min_recall, device=args.device)
    print((args.out / "report.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
