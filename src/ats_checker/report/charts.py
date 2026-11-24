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


# Fixed series colors shared by the chart lines and the table key under it (plotext's own
# legend is drawn on top of the plot and hides data, so we don't use it).
SERIES_COLORS = [(171, 130, 255), (255, 99, 132), (54, 162, 235), (255, 159, 64), (75, 192, 192),
                 (201, 203, 207), (255, 205, 86), (46, 204, 113), (240, 98, 146)]


def series_color(i: int) -> tuple[int, int, int]:
    return SERIES_COLORS[i % len(SERIES_COLORS)]


def series_key(name: str, i: int) -> Text:
    r, g, b = series_color(i)
    t = Text("━━ ", style=f"bold rgb({r},{g},{b})")
    t.append(name)
    return t


def line_chart(series: dict[str, list[float]], labels: list[str], *, title: str, width: int, height: int = 18) -> Text:
    import plotext as plt

    plt.clear_figure()
    plt.plotsize(width, height)
    plt.theme("pro")
    xs = list(range(1, len(labels) + 1))
    # "hd" draws with quadrant blocks (2x2 per cell), which far more terminal/monospace fonts
    # cover than braille, so lines stay aligned.
    # draw in reverse so the first series (Overall) is painted last, on top
    for i, ys in reversed(list(enumerate(series.values()))):
        plt.plot(xs, ys, marker="hd", color=series_color(i))
    plt.xticks(xs, labels)
    lowest = min((v for ys in series.values() for v in ys), default=0)
    plt.ylim(max(0, (lowest // 10) * 10 - 10), 100)
    plt.title(title)
    return Text.from_ansi(plt.build())
