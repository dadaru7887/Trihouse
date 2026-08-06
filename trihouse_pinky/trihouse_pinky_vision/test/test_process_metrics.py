import pytest

from trihouse_pinky_vision.process_metrics import (
    EncodedBitrateSampler,
    FfmpegProgressParser,
)


def test_progress_parser_emits_complete_machine_record():
    parser = FfmpegProgressParser()

    lines = [
        'frame=76\n',
        'fps=15.0\n',
        'out_time_us=5000000\n',
        'progress=continue\n',
    ]
    samples = [sample for line in lines if (sample := parser.feed(line))]

    assert len(samples) == 1
    assert samples[0].frame_count == 76
    assert samples[0].reported_fps == 15.0
    assert samples[0].out_time_seconds == 5.0


def test_progress_parser_ignores_logs_and_incomplete_records():
    parser = FfmpegProgressParser()

    assert parser.feed('[rtsp @ 0x1] connection established\n') is None
    assert parser.feed('frame=not-a-number\n') is None
    assert parser.feed('progress=continue\n') is None


def test_bitrate_sampler_calculates_kilobits_per_second_from_byte_delta():
    sampler = EncodedBitrateSampler()

    assert sampler.sample(1_000_000, 10.0) == 0.0
    assert sampler.unavailable_reason == 'warmup'
    assert sampler.sample(1_250_000, 11.0) == pytest.approx(2000.0)
    assert sampler.unavailable_reason == ''


def test_bitrate_sampler_returns_unavailable_for_bad_interval_or_counter_reset():
    sampler = EncodedBitrateSampler()

    assert sampler.sample(None, 1.0) == 0.0
    assert sampler.unavailable_reason == 'byte_counter_unavailable'
    assert sampler.sample(1000, 2.0) == 0.0
    assert sampler.unavailable_reason == 'warmup'
    assert sampler.sample(2000, 2.0) == 0.0
    assert sampler.unavailable_reason == 'invalid_interval'
    assert sampler.sample(500, 3.0) == 0.0
    assert sampler.unavailable_reason == 'counter_reset'
