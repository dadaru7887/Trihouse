"""Time-axis checks for the fall comparison, on the 1-second labelled frames.

    from vision_ai.models.perception.trainer.fall_sequence import (
        confirm_table, emergency_loso)

    confirm_table(rows, models, split="test")      # E3: what the 1 s confirm removes
    emergency_loso(rows, min_recall=0.85)          # E4: 5 s escalation, by session

Flow: order each session's people by the timestamp in the frame name
(`..._t0040-00s`) -> link the same person across consecutive frames into a
track -> feed each track's per-frame decisions to the runtime's own
FallMonitor (robot/perception/fall_monitor.py, timings from realtime.yaml) ->
count frames, fall runs and escalations.

What this is and is not:

* Labelled frames are 1 s apart, so "1 s later" is the next frame. What the
  camera saw between two labelled frames is unknown, so counts are an
  approximation in both directions.
* The runtime's 5-frame median is not applied: at 1 frame per second it would
  be a 5-second smoother the runtime never runs. Per-frame scores are used.
* A gap longer than `max_gap` seconds ends a track; nothing is assumed about
  the unseen stretch.
* Motion (m_t <= 0.015) cannot be measured between frames 1 s apart. E3 keeps
  it False (the monitor stops at FALLEN); E4 sets it True, so every
  escalation count is an upper bound on what the runtime would raise.
* Identity comes from the ground-truth boxes, never from the classifier.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Iterable

from vision_ai.models.perception.trainer.fall_model import fit_candidates
from vision_ai.models.perception.trainer.fall_trainer import _select_threshold
from vision_ai.robot.perception.fall_monitor import FallMonitor, FallState, MonitorConfig

_STAMP = re.compile(r"_t(\d{4})-(\d{2})s")
REALTIME_CONFIG = Path(__file__).resolve().parents[3] / "robot" / "configs" / "realtime.yaml"
MAX_GAP_SECONDS = 1.0
LINK_IOU = 0.1                     # same person in the next frame, 1 s later
CONFIRMED = {FallState.FALLEN.value, FallState.IMMOBILE.value,
             FallState.EMERGENCY_CANDIDATE.value}


def monitor_config(path: Path = REALTIME_CONFIG) -> MonitorConfig:
    """The timings the robot runs with, read from realtime.yaml."""
    import yaml

    section = yaml.safe_load(Path(path).read_text(encoding="utf-8"))["monitor"]
    return MonitorConfig(**{k: float(v) for k, v in section.items()
                            if k in MonitorConfig.__dataclass_fields__})


def timestamp_of(image: str) -> float | None:
    """Seconds into the source video, from the frame name; None if absent."""
    match = _STAMP.search(image)
    return int(match.group(1)) + int(match.group(2)) / 100 if match else None


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def tracks(rows: Iterable[dict], max_gap: float = MAX_GAP_SECONDS) -> list[list[dict]]:
    """Link each session's labelled people across consecutive frames.

    Greedy by ground-truth box IoU between one frame and the next; a frame
    with one person following a frame with one person is linked regardless,
    since there is nobody else it could be. Rows without a timestamp are left
    out.
    """
    by_episode: dict[str, dict[float, list[dict]]] = {}
    for row in rows:
        t = timestamp_of(row["image"])
        if t is not None:
            by_episode.setdefault(row["episode"], {}).setdefault(t, []).append(row)
    out: list[list[dict]] = []
    for frames in by_episode.values():
        active: list[list[dict]] = []
        previous = None
        for t in sorted(frames):
            people = frames[t]
            if previous is None or t - previous > max_gap:
                active = []
            pairs = sorted(((_iou(track[-1]["box"], row["box"]), i, j)
                            for i, track in enumerate(active) for j, row in enumerate(people)),
                           reverse=True)
            linked, used_tracks, used_rows = [], set(), set()
            for iou, i, j in pairs:
                alone = len(active) == 1 and len(people) == 1
                if i in used_tracks or j in used_rows or (iou < LINK_IOU and not alone):
                    continue
                active[i].append(people[j])
                linked.append(active[i])
                used_tracks.add(i)
                used_rows.add(j)
            for j, row in enumerate(people):
                if j not in used_rows:
                    track = [row]
                    out.append(track)
                    linked.append(track)
            active, previous = linked, t
    return out


def _states(track: list[dict], decide: Callable[[dict], bool], config: MonitorConfig,
            low_motion: bool) -> list[dict]:
    """Run the runtime state machine over one track; one result per frame."""
    monitor = FallMonitor(config)
    return [monitor.advance(timestamp_of(row["image"]), bool(decide(row)), low_motion)
            for row in track]


def _fall_runs(track: list[dict]) -> list[list[int]]:
    """Indices of each run of consecutive Fallen-labelled frames in a track."""
    runs, current = [], None
    for i, row in enumerate(track):
        if row["fallen"]:
            if current is None:
                current = []
                runs.append(current)
            current.append(i)
        else:
            current = None
    return runs


def _decider(group: str, threshold: float) -> Callable[[dict], bool]:
    """Called fallen at `threshold`; a person the model did not measure never is."""
    return lambda row: row.get("features") is not None and row["scores"][group] >= threshold


def confirm_summary(track_list: list[list[dict]], decide: Callable[[dict], bool],
                    config: MonitorConfig) -> dict[str, Any]:
    """Frame-level calls against the calls left once the 1 s confirm has run."""
    out = {"tracks": len(track_list), "frames": 0,
           "frame_fp": 0, "frame_tp": 0, "confirmed_fp": 0, "confirmed_tp": 0,
           "false_confirmations": 0, "fall_runs": 0, "fall_runs_confirmed": 0,
           "fall_runs_single_frame": 0}
    for track in track_list:
        states = [s["state"] for s in _states(track, decide, config, low_motion=False)]
        for row, state in zip(track, states):
            called, confirmed = bool(decide(row)), state in CONFIRMED
            out["frames"] += 1
            key = "tp" if row["fallen"] else "fp"
            out[f"frame_{key}"] += called
            out[f"confirmed_{key}"] += confirmed
        # A stretch spent confirmed with no Fallen label in it is a false confirmation.
        stretch: list[int] = []
        for i, state in enumerate(states + [None]):
            if state in CONFIRMED:
                stretch.append(i)
            elif stretch:
                out["false_confirmations"] += not any(track[k]["fallen"] for k in stretch)
                stretch = []
        for run in _fall_runs(track):
            out["fall_runs"] += 1
            out["fall_runs_single_frame"] += len(run) == 1
            out["fall_runs_confirmed"] += any(states[i] in CONFIRMED for i in run)
    return out


def confirm_table(rows: list[dict], models: dict, split: str = "test",
                  config: MonitorConfig | None = None) -> dict[str, Any]:
    """E3, per group at its recall-floor threshold, on one split."""
    config = config or monitor_config()
    track_list = tracks([r for r in rows if r["split"] == split])
    return {group: {"threshold": info["threshold_recall_floor"],
                    **confirm_summary(track_list,
                                      _decider(group, info["threshold_recall_floor"]), config)}
            for group, info in models.items()}


def _escalations(track_list: list[list[dict]], decide: Callable[[dict], bool],
                 config: MonitorConfig) -> dict[str, Any]:
    """Escalations against fall runs long enough for a perfect classifier to escalate."""
    oracle = lambda row: row["fallen"]
    out = {"eligible_events": 0, "reached": 0, "latency_seconds": [],
           "false_alarms": 0, "standing_seconds": 0, "short_fall_runs": 0}
    for track in track_list:
        perfect = _states(track, oracle, config, low_motion=True)
        called = _states(track, decide, config, low_motion=True)
        in_run = set()
        for run in _fall_runs(track):
            in_run.update(run)
            if not any(perfect[i]["event"] for i in run):
                out["short_fall_runs"] += 1
                continue
            out["eligible_events"] += 1
            hit = next((i for i in run if called[i]["event"]), None)
            if hit is not None:
                out["reached"] += 1
                out["latency_seconds"].append(round(
                    timestamp_of(track[hit]["image"]) - timestamp_of(track[run[0]]["image"]), 2))
        out["false_alarms"] += sum(1 for i, s in enumerate(called) if s["event"] and i not in in_run)
        out["standing_seconds"] += sum(1 for row in track if not row["fallen"])
    return out


def emergency_loso(rows: list[dict], groups: dict[str, Iterable[str]],
                   min_recall: float, config: MonitorConfig | None = None) -> dict[str, Any]:
    """E4: every session scored by a model that never saw it.

    For each held-out session: fit SUM on the others; pick the threshold on
    out-of-fold scores from an inner leave-one-session-out over those same
    others (never on the held-out one); score the held-out session and run
    the monitor with motion assumed low.
    """
    config = config or monitor_config()
    measurable = [r for r in rows if r["features"] is not None]
    episodes = sorted({r["episode"] for r in rows})
    out: dict[str, Any] = {"sessions": episodes, "monitor": {
        "fall_confirm_seconds": config.fall_confirm_seconds,
        "immobile_seconds": config.immobile_seconds,
        "recovery_confirm_seconds": config.recovery_confirm_seconds}}
    for group, names in groups.items():
        names = tuple(names)
        total = {"eligible_events": 0, "reached": 0, "latency_seconds": [],
                 "false_alarms": 0, "standing_seconds": 0, "short_fall_runs": 0}
        per_session = {}
        for held in episodes:
            train = [r for r in measurable if r["episode"] != held]
            inner_scores, inner_labels = [], []
            for inner in sorted({r["episode"] for r in train}):
                fit_rows = [r for r in train if r["episode"] != inner]
                if len({r["fallen"] for r in fit_rows}) < 2:
                    continue
                model = fit_candidates(fit_rows, modes=names)["sum"]
                for r in train:
                    if r["episode"] == inner:
                        inner_scores.append(model.score(r["features"]))
                        inner_labels.append(int(r["fallen"]))
            threshold, _, _ = _select_threshold(inner_labels, inner_scores, min_recall)
            model = fit_candidates(train, modes=names)["sum"]
            scored = {id(r): model.score(r["features"]) for r in measurable if r["episode"] == held}
            decide = lambda row, s=scored, t=threshold: id(row) in s and s[id(row)] >= t
            result = _escalations(tracks([r for r in rows if r["episode"] == held]),
                                  decide, config)
            per_session[held] = {"threshold": threshold, **result}
            for key in total:
                total[key] = total[key] + result[key]
        out[group] = {"total": total, "per_session": per_session}
    return out
