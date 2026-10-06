"""Date/time context helpers for agent runtime prompts and tools."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"

_WEEKDAYS_ZH = [
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
]

_WEEKDAY_INDEX = {
    "星期一": 0,
    "星期二": 1,
    "星期三": 2,
    "星期四": 3,
    "星期五": 4,
    "星期六": 5,
    "星期日": 6,
}


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except Exception:  # noqa: BLE001 - invalid user input falls back safely
        return ZoneInfo(DEFAULT_TIMEZONE)


def _coerce_now(now: datetime | None = None, *, timezone: str = DEFAULT_TIMEZONE) -> datetime:
    tz = _zone(timezone)
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def parse_reference_datetime(
    value: str | None,
    *,
    timezone: str = DEFAULT_TIMEZONE,
) -> datetime | None:
    """Parse an optional ISO reference date supplied by a tool caller."""

    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = f"{raw[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(raw)
        except ValueError:
            return None
        parsed = datetime.combine(parsed_date, datetime.min.time())
    return _coerce_now(parsed, timezone=timezone)


def _weekday_zh(value: date) -> str:
    return _WEEKDAYS_ZH[value.weekday()]


def _date_payload(
    *,
    label: str,
    start: date,
    end: date,
    now: datetime,
    timezone: str,
) -> dict[str, Any]:
    return {
        "success": True,
        "label": label,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "weekday_start": _weekday_zh(start),
        "weekday_end": _weekday_zh(end),
        "timezone": timezone,
        "reference_date": now.date().isoformat(),
        "reference_weekday": _weekday_zh(now.date()),
    }


def _week_start(today: date) -> date:
    return today - timedelta(days=today.weekday())


def _week_range(today: date, *, offset_weeks: int) -> tuple[date, date]:
    start = _week_start(today) + timedelta(days=7 * offset_weeks)
    return start, start + timedelta(days=6)


def _weekend_range(today: date, *, offset_weeks: int) -> tuple[date, date]:
    start = _week_start(today) + timedelta(days=7 * offset_weeks + 5)
    return start, start + timedelta(days=1)


def build_temporal_context(
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Return a compact timezone-aware context for relative date reasoning."""

    current = _coerce_now(now, timezone=timezone)
    today = current.date()
    weekend_start, weekend_end = _weekend_range(today, offset_weeks=0)
    next_week_start, next_week_end = _week_range(today, offset_weeks=1)
    return {
        "now_iso": current.isoformat(),
        "date": today.isoformat(),
        "time": current.strftime("%H:%M:%S"),
        "weekday": _weekday_zh(today),
        "timezone": timezone,
        "today": _date_payload(
            label="今天",
            start=today,
            end=today,
            now=current,
            timezone=timezone,
        ),
        "this_weekend": _date_payload(
            label="本周末",
            start=weekend_start,
            end=weekend_end,
            now=current,
            timezone=timezone,
        ),
        "next_week": _date_payload(
            label="下周",
            start=next_week_start,
            end=next_week_end,
            now=current,
            timezone=timezone,
        ),
    }


def build_temporal_context_prompt(
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> str:
    """Build the runtime prompt block that grounds relative dates."""

    ctx = build_temporal_context(now=now, timezone=timezone)
    weekend = ctx["this_weekend"]
    next_week = ctx["next_week"]
    hour_bucket = f"{int(str(ctx['time']).split(':', 1)[0]):02d}点时段"
    return (
        "\n\n## 当前基准日期\n"
        f"- 当前：{ctx['date']} {ctx['weekday']} {hour_bucket} ({ctx['timezone']})\n"
        f"- 本周末：{weekend['start_date']}({weekend['weekday_start']})"
        f" ~ {weekend['end_date']}({weekend['weekday_end']})\n"
        f"- 下周：{next_week['start_date']}({next_week['weekday_start']})"
        f" ~ {next_week['end_date']}({next_week['weekday_end']})\n"
        "- 今天、明天、本周末、下周三、最近等相对日期表达，"
        "必须以上述基准进行解释。\n"
        "- 在天气、新闻、日程、预约等日期重要的外部查询前，"
        "如有需要，请使用 resolve_relative_date 工具确认 ISO 日期范围。\n"
        "- 对于精确到分钟的当前时间、截止时间、预约可用性等时间精度"
        "重要的任务，请使用 current_datetime 工具确认。"
    )


def _compact_expression(value: str) -> str:
    return "".join(value.lower().split())


def _resolve_weekday(
    compact: str,
    *,
    today: date,
) -> tuple[str, date] | None:
    for token, weekday_index in sorted(_WEEKDAY_INDEX.items(), key=lambda item: -len(item[0])):
        if token not in compact:
            continue
        if "下周" in compact or "下星期" in compact:
            week_offset = 1
            label_prefix = "下周"
        elif "本周" in compact or "本星期" in compact:
            week_offset = 0
            label_prefix = "本周"
        elif "上周" in compact or "上星期" in compact:
            week_offset = -1
            label_prefix = "上周"
        else:
            base = today + timedelta(days=(weekday_index - today.weekday()) % 7)
            weekday_label = token
            return weekday_label, base

        start = _week_start(today) + timedelta(days=7 * week_offset)
        weekday_label = token
        return f"{label_prefix} {weekday_label}", start + timedelta(days=weekday_index)
    return None


def resolve_relative_date_expression(
    expression: str,
    *,
    now: datetime | None = None,
    timezone: str = DEFAULT_TIMEZONE,
) -> dict[str, Any]:
    """Resolve common relative date expressions into an ISO date range."""

    current = _coerce_now(now, timezone=timezone)
    today = current.date()
    compact = (
        _compact_expression(expression)
        .replace("下星期", "下周")
        .replace("本星期", "本周")
        .replace("上星期", "上周")
    )
    for digit in "一二三四五六日天":
        compact = compact.replace(f"周{digit}", f"星期{digit}")
    compact = compact.replace("星期天", "星期日")

    if not compact:
        return {
            "success": False,
            "error": "EMPTY_EXPRESSION",
            "message": "日期表达为空。",
            "timezone": timezone,
            "reference_date": today.isoformat(),
            "reference_weekday": _weekday_zh(today),
        }

    if "昨天" in compact:
        target = today - timedelta(days=1)
        return _date_payload(label="昨天", start=target, end=target, now=current, timezone=timezone)
    if "今天" in compact:
        return _date_payload(label="今天", start=today, end=today, now=current, timezone=timezone)
    if "后天" in compact:
        target = today + timedelta(days=2)
        return _date_payload(label="后天", start=target, end=target, now=current, timezone=timezone)
    if "明天" in compact:
        target = today + timedelta(days=1)
        return _date_payload(label="明天", start=target, end=target, now=current, timezone=timezone)

    if "周末" in compact:
        offset = 1 if "下" in compact else -1 if "上" in compact else 0
        start, end = _weekend_range(today, offset_weeks=offset)
        label = "下周末" if offset == 1 else "上周末" if offset == -1 else "本周末"
        return _date_payload(label=label, start=start, end=end, now=current, timezone=timezone)

    if "下周" in compact or "下星期" in compact:
        start, end = _week_range(today, offset_weeks=1)
        weekday_result = _resolve_weekday(compact, today=today)
        if weekday_result is not None:
            label, target = weekday_result
            return _date_payload(
                label=label,
                start=target,
                end=target,
                now=current,
                timezone=timezone,
            )
        return _date_payload(label="下周", start=start, end=end, now=current, timezone=timezone)

    if "本周" in compact or "本星期" in compact:
        start, end = _week_range(today, offset_weeks=0)
        weekday_result = _resolve_weekday(compact, today=today)
        if weekday_result is not None:
            label, target = weekday_result
            return _date_payload(
                label=label,
                start=target,
                end=target,
                now=current,
                timezone=timezone,
            )
        return _date_payload(label="本周", start=start, end=end, now=current, timezone=timezone)

    if "最近" in compact or "最新" in compact:
        start = today - timedelta(days=6)
        return _date_payload(
            label="过去 7 天",
            start=start,
            end=today,
            now=current,
            timezone=timezone,
        )

    weekday_result = _resolve_weekday(compact, today=today)
    if weekday_result is not None:
        label, target = weekday_result
        return _date_payload(label=label, start=target, end=target, now=current, timezone=timezone)

    return {
        "success": False,
        "error": "UNRESOLVED_RELATIVE_DATE",
        "message": "未找到支持的相对日期表达。",
        "expression": expression,
        "timezone": timezone,
        "reference_date": today.isoformat(),
        "reference_weekday": _weekday_zh(today),
    }
