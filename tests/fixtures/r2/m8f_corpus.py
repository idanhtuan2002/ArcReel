"""The locked M8-F evaluation corpus (DEC-F-1): pure, deterministic and database-free.

Each M6 profile cohort has one creative project, whose episode-1 script is built from Golden B's
profile scenes, and two learning projects (train and holdout). Each learning project holds one
YouTube Analytics ``dimensions=day`` result table per format arm. Train days fall before the
protocol's registration and holdout days after it, so the holdout is project-disjoint and then
future-time (spec §9). Every value is synthetic. The corpus demonstrates the mechanism and makes no
claim about real audiences or cultural representativeness.

``corpus_manifest`` lists the digest of every input; the evaluation protocol locks its digest.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.adaptation import AdaptationProfileId
from tests.fixtures.r2.m6_dual_profile_corpus import _screenplay_scenes

CORPUS_VERSION = "m8f-corpus@1"
COHORTS = (AdaptationProfileId.WESTERN_GENERIC, AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN)
SLUGS = {AdaptationProfileId.WESTERN_GENERIC: "western", AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: "shuang"}
SHOTS = (("SH01", "MASTER"), ("SH02", "REVERSE"))
BASELINE_ARM = "landscape-16x9@1"
TREATMENT_ARM = "vertical-9x16@1"
ARMS = (BASELINE_ARM, TREATMENT_ARM)
TRAIN_DAYS = tuple(date(2026, 9, 1) + timedelta(days=index) for index in range(14))
HOLDOUT_DAYS = tuple(date(2026, 11, 2) + timedelta(days=index) for index in range(14))
TRAIN_CUTOFF = datetime(2026, 10, 1, tzinfo=UTC)
# ``split_holdout`` assigns whole projects by a salted name hash. This is the first salt in the series
# ``m8f-holdout@<n>`` that sends each cohort's holdout project to evaluation and its train project to
# train; it depends only on project names.
HOLDOUT_SALT = "m8f-holdout@2"
EVALUATION_SHARE = "0.5"
# One synthetic lift per cohort, applied to the treatment arm's daily views.
_LIFT = {AdaptationProfileId.WESTERN_GENERIC: 0.20, AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: 0.15}
_BASE_VIEWS = {AdaptationProfileId.WESTERN_GENERIC: 400, AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN: 650}
# The baseline train video has no row on this day, so its views are counted as MISSING.
MISSING_TRAIN_DAY = TRAIN_DAYS[5]


def creative_project(profile: AdaptationProfileId) -> str:
    return f"m8f-{SLUGS[profile]}"


def learning_projects(profile: AdaptationProfileId) -> tuple[str, str]:
    """``(train, holdout)`` project names of a cohort."""
    return f"m8f-{SLUGS[profile]}-train", f"m8f-{SLUGS[profile]}-holdout"


def episode_script(profile: AdaptationProfileId) -> bytes:
    """The episode-1 host script: Golden B's profile scenes and the two shots the workflows use."""
    scenes = [
        {"scene_id": scene.scene_id, "dramatic_text": scene.dramatic_text} for scene in _screenplay_scenes(profile)
    ]
    script = {
        "episode": 1,
        "title": f"M8-F {SLUGS[profile]} cohort",
        "profile": profile.value,
        "scenes": scenes,
        "shots": [{"shot_id": shot, "role": role} for shot, role in SHOTS],
    }
    return json.dumps(script, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def video_id(project: str, arm: str) -> str:
    return f"{project}-{arm.split('@', 1)[0]}"


def youtube_query(project: str, arm: str) -> dict[str, str]:
    return {"ids": "channel==MINE", "dimensions": "day", "filters": f"video=={video_id(project, arm)}"}


def _views(profile: AdaptationProfileId, arm: str, index: int, *, holdout: bool) -> int:
    base = _BASE_VIEWS[profile] + (index * 37) % 23 - 11 + (5 if holdout else 0)
    return round(base * (1 + _LIFT[profile])) if arm == TREATMENT_ARM else base


def youtube_table(profile: AdaptationProfileId, project: str, arm: str) -> dict[str, object]:
    """One video's ``youtubeAnalytics#resultTable`` over the project's days."""
    holdout = project == learning_projects(profile)[1]
    rows: list[list[object]] = []
    for index, day in enumerate(HOLDOUT_DAYS if holdout else TRAIN_DAYS):
        if not holdout and arm == BASELINE_ARM and day == MISSING_TRAIN_DAY:
            continue
        views = _views(profile, arm, index, holdout=holdout)
        rows.append([day.isoformat(), views, views * 2, 140 + index % 9])
    return {
        "kind": "youtubeAnalytics#resultTable",
        "columnHeaders": [
            {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
            {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "estimatedMinutesWatched", "columnType": "METRIC", "dataType": "INTEGER"},
            {"name": "averageViewDuration", "columnType": "METRIC", "dataType": "INTEGER"},
        ],
        "rows": rows,
    }


def requested_days(profile: AdaptationProfileId, project: str) -> tuple[date, ...]:
    return HOLDOUT_DAYS if project == learning_projects(profile)[1] else TRAIN_DAYS


def corpus_manifest() -> dict[str, object]:
    """The digest of every corpus input, keyed by cohort; no database or clock is read."""
    cohorts: dict[str, object] = {}
    for profile in COHORTS:
        learning = {
            project: {arm: digest_canonical(youtube_table(profile, project, arm)) for arm in ARMS}
            for project in learning_projects(profile)
        }
        cohorts[profile.value] = {
            "creative_project": creative_project(profile),
            "episode_script_sha256": "sha256:" + hashlib.sha256(episode_script(profile)).hexdigest(),
            "shots": [list(shot) for shot in SHOTS],
            "learning_projects": learning,
        }
    return {
        "corpus_version": CORPUS_VERSION,
        "arms": {"baseline": BASELINE_ARM, "treatment": TREATMENT_ARM},
        "train_days": [TRAIN_DAYS[0].isoformat(), TRAIN_DAYS[-1].isoformat()],
        "holdout_days": [HOLDOUT_DAYS[0].isoformat(), HOLDOUT_DAYS[-1].isoformat()],
        "missing_train_day": MISSING_TRAIN_DAY.isoformat(),
        "train_cutoff": TRAIN_CUTOFF.isoformat(),
        "holdout_salt": HOLDOUT_SALT,
        "evaluation_share": EVALUATION_SHARE,
        "cohorts": cohorts,
    }


def manifest_digest() -> str:
    return digest_canonical(corpus_manifest())
