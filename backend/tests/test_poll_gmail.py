import pytest

from scripts.poll_gmail import build_parser


def test_defaults_to_once_false():
    args = build_parser().parse_args([])
    assert args.once is False


def test_once_flag():
    args = build_parser().parse_args(["--once"])
    assert args.once is True


def test_interval_override():
    args = build_parser().parse_args(["--interval", "15"])
    assert args.interval == 15


def test_interval_defaults_to_none_so_config_wins():
    args = build_parser().parse_args([])
    assert args.interval is None
