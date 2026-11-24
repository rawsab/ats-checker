from __future__ import annotations

from rich.text import Text

SPARK = "▁▂▃▄▅▆▇█"


def color(score: float) -> str:
    if score >= 85:
        return "green"
    if score >= 70:
        return "yellow3"
    if score >= 55:
        return "dark_orange"
    return "red"


def grade(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Okay"
    if score >= 55:
        return "Needs work"
    return "At risk"


def bar(score: float, width: int = 28) -> Text:
    """Horizontal bar with eighth-block precision."""
    filled = max(0.0, min(score, 100.0)) / 100 * width
    full = int(filled)
    part = int((filled - full) * 8)
    t = Text("█" * full, style=color(score))
    if part and full < width:
        t.append(" ▏▎▍▌▋▊▉"[part], style=color(score))
    t.append("·" * (width - full - (1 if part and full < width else 0)), style="grey30")
    return t


def sparkline(values: list[float], lo: float = 0, hi: float = 100) -> Text:
    t = Text()
    for v in values:
        idx = int((v - lo) / (hi - lo or 1) * (len(SPARK) - 1))
        t.append(SPARK[max(0, min(idx, len(SPARK) - 1))], style=color(v))
    return t


def delta(cur: float, prev: float | None) -> Text:
    if prev is None:
        return Text("")
    d = cur - prev
    if abs(d) < 0.5:
        return Text("  ±0", style="grey50")
    return Text(f"{'▲' if d > 0 else '▼'}{abs(d):4.1f}", style="green" if d > 0 else "red")


def line_chart(series: dict[str, list[float]], labels: list[str], *, title: str, width: int, height: int = 18) -> Text:
    import plotext as plt

    plt.clear_figure()
    plt.plotsize(width, height)
    plt.theme("pro")
    xs = list(range(1, len(labels) + 1))
    for i, (name, ys) in enumerate(series.items()):
        plt.plot(xs, ys, label=name, marker="hd" if i == 0 else "braille")
    plt.xticks(xs, labels)
    lowest = min((v for ys in series.values() for v in ys), default=0)
    plt.ylim(max(0, (lowest // 10) * 10 - 10), 100)
    plt.title(title)
    return Text.from_ansi(plt.build())
