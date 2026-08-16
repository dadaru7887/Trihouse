"""ACT 정책 로더와 결정적 fake episode.

P0는 실제 ACT checkpoint를 갖고 있지 않다. `config/act.simulation.yaml`이
repo/revision/profile을 모두 `UNCONFIGURED`로 두므로 로더는 fake 정책만
만들고 실제 motion을 절대 켜지 않는다. hardware mode는 세 값이 모두 실제
값으로 지정되었을 때만 열린다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


UNCONFIGURED = "UNCONFIGURED"
FAKE_MODEL_LINEAGE = "fake-act/p0-v1"
FAKE_STAGES = ("OBSERVE", "POLICY", "GRASP", "VERIFY", "HANDOVER")
FAKE_MODES = ("deterministic_fake", "simulation")


class ActConfigurationError(ValueError):
    """하드웨어 정책을 열기에 충분한 설정이 없다."""


@dataclass(frozen=True)
class ActEpisodeStage:
    name: str
    sequence_no: int
    model_lineage: str


@dataclass(frozen=True)
class ActEpisode:
    command_uuid: str
    assignment_revision: int
    stages: tuple[ActEpisodeStage, ...]
    model_lineage: str
    real_motion_emitted: bool = False


@dataclass(frozen=True)
class ActPolicy:
    repo_id: str
    revision: str
    profile: str
    mode: str
    model_lineage: str
    stage_names: tuple[str, ...] = field(default=FAKE_STAGES)

    @property
    def is_fake(self) -> bool:
        return self.mode == "deterministic_fake"

    @property
    def real_motion_enabled(self) -> bool:
        """설정이 완전하고 hardware mode일 때만 실제 motion이 열린다."""
        return not self.is_fake and self.mode == "hardware" and _fully_specified(
            self.repo_id, self.revision, self.profile
        )

    def run_episode(
        self, *, command_uuid: str, assignment_revision: int
    ) -> ActEpisode:
        """같은 입력이면 항상 같은 stage 열을 낸다."""
        if not command_uuid.strip():
            raise ValueError("command_uuid is required")
        if assignment_revision <= 0:
            raise ValueError("assignment_revision must be positive")
        stages = tuple(
            ActEpisodeStage(
                name=name, sequence_no=index, model_lineage=self.model_lineage
            )
            for index, name in enumerate(self.stage_names, start=1)
        )
        return ActEpisode(
            command_uuid=command_uuid.strip(),
            assignment_revision=assignment_revision,
            stages=stages,
            model_lineage=self.model_lineage,
            real_motion_emitted=False,
        )


class ActPolicyLoader:
    """설정 파일이나 명시된 값에서만 정책을 만든다."""

    def load(
        self,
        *,
        repo_id: str,
        mode: str,
        revision: str = UNCONFIGURED,
        profile: str = UNCONFIGURED,
        model_lineage: str = FAKE_MODEL_LINEAGE,
        stages: tuple[str, ...] = FAKE_STAGES,
    ) -> ActPolicy:
        normalized = mode.strip()
        # `simulation`은 시뮬레이션 스택이 쓰는 이름이고 설정 파일은
        # `deterministic_fake`로 적는다. 둘 다 같은 fake 정책을 만든다.
        if normalized in FAKE_MODES:
            normalized = "deterministic_fake"
            return ActPolicy(
                repo_id=repo_id,
                revision=revision,
                profile=profile,
                mode=normalized,
                model_lineage=FAKE_MODEL_LINEAGE,
                stage_names=tuple(stages),
            )
        if normalized != "hardware":
            raise ActConfigurationError(f"unsupported ACT mode: {mode}")
        if not _fully_specified(repo_id, revision, profile):
            raise ActConfigurationError(
                "hardware mode requires a fully specified repo ID, revision, "
                "and profile"
            )
        return ActPolicy(
            repo_id=repo_id.strip(),
            revision=revision.strip(),
            profile=profile.strip(),
            mode=normalized,
            model_lineage=model_lineage,
            stage_names=tuple(stages),
        )

    def load_file(self, path: Path | str) -> ActPolicy:
        return self.load(**_read_config(Path(path)))


def _fully_specified(*values: str) -> bool:
    return all(
        isinstance(value, str) and value.strip() and value.strip() != UNCONFIGURED
        for value in values
    )


def _read_config(path: Path) -> dict[str, Any]:
    document = _parse_yaml(path.read_text(encoding="utf-8"))
    stages = document.get("stages") or list(FAKE_STAGES)
    return {
        "repo_id": str(document.get("repo_id", UNCONFIGURED)),
        "revision": str(document.get("revision", UNCONFIGURED)),
        "profile": str(document.get("profile", UNCONFIGURED)),
        "mode": str(document.get("mode", "deterministic_fake")),
        "model_lineage": str(document.get("model_lineage", FAKE_MODEL_LINEAGE)),
        "stages": tuple(str(stage) for stage in stages),
    }


def _parse_yaml(text: str) -> Mapping[str, Any]:
    """PyYAML 없이도 읽을 수 있는 최소 스칼라/리스트 파서."""
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ModuleNotFoundError:
        pass

    document: dict[str, Any] = {}
    current_list: list[str] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("- ") and current_list is not None:
            current_list.append(line.lstrip()[2:].strip())
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key, value = key.strip(), value.strip()
        if not value:
            current_list = []
            document[key] = current_list
        else:
            current_list = None
            document[key] = value
    return document


__all__ = [
    "ActConfigurationError",
    "ActEpisode",
    "ActEpisodeStage",
    "ActPolicy",
    "ActPolicyLoader",
    "FAKE_MODEL_LINEAGE",
    "FAKE_MODES",
    "FAKE_STAGES",
    "UNCONFIGURED",
]
