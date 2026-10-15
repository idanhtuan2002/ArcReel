"""The locked M8-F corpus is deterministic, cohort-separated and splits project-disjoint then future-time."""

from __future__ import annotations

from decimal import Decimal

from r2.advanced_creative.lineage import resolve_episode_lineage
from r2.learning.adapters import observe_youtube_days, youtube_rows
from r2.learning.observations import MissingReason
from r2.learning.replay import split_holdout
from tests.fixtures.r2.m8f_corpus import (
    ARMS,
    BASELINE_ARM,
    COHORTS,
    EVALUATION_SHARE,
    HOLDOUT_SALT,
    MISSING_TRAIN_DAY,
    TRAIN_CUTOFF,
    corpus_manifest,
    creative_project,
    episode_script,
    learning_projects,
    manifest_digest,
    requested_days,
    video_id,
    youtube_query,
    youtube_table,
)


def _observations(profile):
    observations = []
    for project in learning_projects(profile):
        lineage = resolve_episode_lineage(project, 1, b"learning")
        for arm in ARMS:
            records = observe_youtube_days(
                video_id=video_id(project, arm),
                query=youtube_query(project, arm),
                requested_days=requested_days(profile, project),
                rows=youtube_rows(youtube_table(profile, project, arm)),
                status="PUBLIC",
                lineage=lineage,
                format_profile_ref=arm,
            )
            observations.extend(item for record in records for item in record.observations)
    return observations


def test_the_manifest_is_deterministic_and_names_every_cohort_input() -> None:
    assert corpus_manifest() == corpus_manifest()
    assert manifest_digest() == manifest_digest()
    cohorts = corpus_manifest()["cohorts"]
    assert set(cohorts) == {profile.value for profile in COHORTS}


def test_cohorts_have_disjoint_projects_and_distinct_scripts() -> None:
    projects = [creative_project(profile) for profile in COHORTS] + [
        name for profile in COHORTS for name in learning_projects(profile)
    ]
    assert len(set(projects)) == len(projects) == 6
    scripts = {episode_script(profile) for profile in COHORTS}
    assert len(scripts) == 2
    assert all(profile.value.encode() in episode_script(profile) for profile in COHORTS)


def test_the_holdout_is_project_disjoint_then_future_time_for_each_cohort() -> None:
    for profile in COHORTS:
        train, holdout = learning_projects(profile)
        split = split_holdout(
            _observations(profile),
            evaluation_share=Decimal(EVALUATION_SHARE),
            train_cutoff=TRAIN_CUTOFF,
            salt=HOLDOUT_SALT,
        )
        assert split.train_projects == (train,)
        assert split.evaluation_projects == (holdout,)
        assert split.train
        assert split.evaluation
        assert all(item.window.ends_at <= TRAIN_CUTOFF for item in split.train)
        assert all(item.window.starts_at > TRAIN_CUTOFF for item in split.evaluation)


def test_the_baseline_train_video_misses_one_day() -> None:
    for profile in COHORTS:
        train, _holdout = learning_projects(profile)
        missing = [
            item for item in _observations(profile) if item.metric_value is None and item.lineage.project_name == train
        ]
        assert missing
        assert {item.format_profile_ref for item in missing} == {BASELINE_ARM}
        assert {item.missing_reason for item in missing} == {MissingReason.MISSING}
        # A Pacific-time day starts at 07:00 or 08:00 UTC on the same date.
        assert {item.window.starts_at.date() for item in missing} == {MISSING_TRAIN_DAY}
