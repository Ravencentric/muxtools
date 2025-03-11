import os
import json
from typing import Any
from math import trunc
from pathlib import Path
from fractions import Fraction
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_DOWN
from video_timestamps import FPSTimestamps, RoundingMethod, TextFileTimestamps, VideoTimestamps, ABCTimestamps, TimeType

from ..utils.types import PathLike, TimeScale, VideoMeta, TimeSourceT, TimeScaleT
from ..utils.log import info, warn, crit, debug, error
from ..utils.dataclass import fraction_hook
from ..utils.files import ensure_path_exists, get_workdir, ensure_path, is_video_file
from ..utils.env import get_setup_attr

__all__: list[str] = [
    "mpls_timestamp_to_timedelta",
    "format_timedelta",
    "timedelta_from_formatted",
    "get_timemeta_from_video",
    "resolve_timesource_and_scale",
    "TimeType",
    "ABCTimestamps",
]


def mpls_timestamp_to_timedelta(timestamp: int) -> timedelta:
    """
    Converts a mpls timestamp (from BDMV Playlist files) to a timedelta.

    :param timestamp:       The mpls timestamp

    :return:                The resulting timedelta
    """
    seconds = Decimal(timestamp) / Decimal(45000)
    return timedelta(seconds=float(seconds))


def get_timemeta_from_video(video_file: PathLike, out_file: PathLike | None = None, caller: Any | None = None) -> VideoMeta:
    video_file = ensure_path_exists(video_file, get_timemeta_from_video)
    if not out_file:
        out_file = get_workdir() / f"{video_file.stem}_meta.json"

    out_file = ensure_path(out_file, get_timemeta_from_video)
    if not out_file.exists() or out_file.stat().st_size < 1:
        info(f"Generating timestamps for '{video_file.name}'...", caller)
        timestamps = VideoTimestamps.from_video_file(video_file)
        meta = VideoMeta(timestamps.pts_list, timestamps.fps, timestamps.time_scale, str(video_file.resolve()))
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(meta.to_json())
    else:
        with open(out_file, "r", encoding="utf-8") as f:
            meta_json = json.loads(f.read(), object_hook=fraction_hook)
            meta = VideoMeta(**meta_json)
            debug(f"Reusing existing timestamps for '{video_file.name}'", caller)
    return meta


def resolve_timesource_and_scale(
    timesource: PathLike | Fraction | float | list[int] | VideoMeta | ABCTimestamps | None = None,
    timescale: TimeScale | Fraction | int | None = None,
    rounding_method: RoundingMethod = RoundingMethod.ROUND,
    allow_warn: bool = True,
    fetch_from_setup: bool = False,
    caller: Any | None = None,
) -> ABCTimestamps:
    if fetch_from_setup:
        if timesource is None and (setup_timesource := get_setup_attr("sub_timesource", None)) is not None:
            if not isinstance(setup_timesource, TimeSourceT):
                raise error("Invalid timesource type in Setup!", caller)
            debug("Using default timesource from setup.", caller)
            timesource = setup_timesource
        if timescale is None and (setup_timescale := get_setup_attr("sub_timescale", None)) is not None:
            if not isinstance(setup_timescale, TimeScaleT):
                raise error("Invalid timescale type in Setup!", caller)
            debug("Using default timescale from setup.", caller)
            timescale = setup_timescale

    def check_timescale(timescale) -> Fraction:
        if not timescale:
            if allow_warn:
                warn("No timescale was given, defaulting to Matroska scaling.", caller)
            timescale = Fraction(1000)
        return Fraction(timescale)

    if timesource is None:
        if allow_warn:
            warn("No timesource was given, generating timestamps for FPS (24000/1001).", caller)
        timescale = check_timescale(timescale)
        return FPSTimestamps(rounding_method, timescale, Fraction(24000, 1001))

    if isinstance(timesource, VideoMeta):
        return VideoTimestamps(timesource.pts, timesource.timescale, fps=timesource.fps, rounding_method=rounding_method)

    if isinstance(timesource, ABCTimestamps):
        return timesource

    if isinstance(timesource, PathLike):
        if isinstance(timesource, Path) or os.path.isfile(timesource):
            timesource = ensure_path(timesource, caller)
            is_video = is_video_file(timesource)

            if is_video:
                meta = get_timemeta_from_video(timesource, caller=caller)
                return VideoTimestamps(meta.pts, meta.timescale, fps=meta.fps, rounding_method=rounding_method)
            else:
                timescale = check_timescale(timescale)
                return TextFileTimestamps(timesource, timescale, rounding_method=rounding_method)

    elif isinstance(timesource, list) and isinstance(timesource[0], int):
        timescale = check_timescale(timescale)
        return VideoTimestamps(timesource, timescale, rounding_method=rounding_method)

    if isinstance(timesource, float) or isinstance(timesource, str) or isinstance(timesource, Fraction):
        fps = Fraction(timesource)
        timescale = check_timescale(timescale)
        return FPSTimestamps(rounding_method, timescale, fps)

    raise crit("Invalid timesource passed!", caller)


def format_timedelta(time: timedelta, precision: int = 3) -> str:
    """
    Formats a timedelta to hh:mm:ss.s[*precision] and pads with 0 if there aren't more numbers to work with.
    Mostly to be used for ogm/xml files.

    :param time:        The timedelta
    :param precision:   3 = milliseconds, 6 = microseconds, 9 = nanoseconds

    :return:            The formatted string
    """
    dec = Decimal(time.total_seconds())
    pattern = "." + "".join(["0"] * (precision - 1)) + "1"
    rounded = float(dec.quantize(Decimal(pattern), rounding=ROUND_HALF_DOWN))
    s = trunc(rounded)
    m = s // 60
    s %= 60
    h = m // 60
    m %= 60
    return f"{h:02d}:{m:02d}:{s:02d}.{str(rounded).split('.')[1].ljust(precision, '0')}"


def timedelta_from_formatted(formatted: str) -> timedelta:
    """
    Parses a string with the format of hh:mm:ss.sss
    Mostly to be used for ogm/xml files.

    :param formatted:       The timestamp string

    :return:                The parsed timedelta
    """
    # 00:05:25.534...
    split = formatted.split(":")
    seconds = Decimal(split[0]) * Decimal(3600)
    seconds = seconds + (Decimal(split[1]) * Decimal(60))
    seconds = seconds + (Decimal(split[2]))
    return timedelta(seconds=seconds.__float__())
