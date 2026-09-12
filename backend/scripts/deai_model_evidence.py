"""从 EQ-Bench Creative Writing v3 的页面数据抽取某个模型家族的写作证据，输出 markdown 草稿。

用途：给 app/prompts/deai/models/<family>.prior.md 找实测依据（方法见 models/README.md）。
    python scripts/deai_model_evidence.py grok            # 所有名字含 grok 的模型
    python scripts/deai_model_evidence.py qwen --top 30   # 每类列表最多 30 项
    python scripts/deai_model_evidence.py glm --out glm_evidence.md

数据来源（页面内嵌 JS，非官方 API，结构变了本脚本会失效）：
- creative_writing.js              榜单 CSV（elo / rubric / 篇幅 / 词汇复杂度 / slop / 重复度）+ 每模型高频重复词与短语
- creative_writing_chartdata.js    评审判据雷达（相对同榜模型的强弱项）
- creative_writing_chartdata_style.js  评审最偏爱的风格描述词
只用标准库，不依赖项目代码。英文实测：条目进表时中文形态要自己推断。
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import urllib.request
from html import unescape
from typing import Any

BASE = "https://eqbench.com/"
ASSET_VERSION = "1.0.91"
NUMERIC = ("elo", "rubric", "length", "vocab", "slop", "repetition")
_SECTION_HEADINGS = (
    ("similar", "Most Similar To"),
    ("words", "Top Repetitive Words"),
    ("phrases", "Top Repetitive Phrases"),
    ("bigrams", "Top Bigrams"),
    ("trigrams", "Top Trigrams"),
)


def fetch(path: str, version: str = ASSET_VERSION) -> str:
    req = urllib.request.Request(f"{BASE}{path}?v={version}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 - 固定站点
        return resp.read().decode("utf-8", errors="replace")


def parse_leaderboard(js: str) -> list[dict[str, Any]]:
    """`leaderboardDataCreativeWritingV3 = \\`csv\\`` → 行列表；模型名前的 * 是页面标记，去掉。"""
    match = re.search(r"leaderboardDataCreativeWritingV3\s*=\s*`([^`]*)`", js)
    if not match:
        return []
    rows = []
    for line in match.group(1).splitlines()[1:]:
        cells = [c.strip() for c in line.split(",")]
        if len(cells) < 7 or not cells[0]:
            continue
        try:
            rows.append({
                "model": cells[0].lstrip("*"), "elo": float(cells[1]), "rubric": float(cells[2]),
                "length": int(float(cells[3])), "vocab": float(cells[4]), "slop": float(cells[5]),
                "repetition": float(cells[6]),
            })
        except ValueError:
            continue
    return rows


def medians(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {k: statistics.median(r[k] for r in rows) for k in NUMERIC} if rows else {}


def select_models(rows: list[dict[str, Any]], needle: str) -> list[dict[str, Any]]:
    needle = needle.lower()
    return [r for r in rows if needle in r["model"].lower()]


def _strip_html(fragment: str) -> str:
    text = fragment.replace("\\n", "\n")
    text = re.sub(r"<[^>]+>", "\n", text)
    return unescape(text)


def extract_model_section(js: str, model: str) -> dict[str, list[str]]:
    """页面里每个模型有一段 `##### <model>` 明细；按已知小标题切成列表。找不到该模型返回 {}。"""
    start = js.find(f"##### {model}")
    if start < 0:
        return {}
    end = js.find("##### ", start + 6)
    text = _strip_html(js[start:end if end > 0 else len(js)])
    positions = [(text.find(heading), key, heading) for key, heading in _SECTION_HEADINGS]
    positions = sorted(p for p in positions if p[0] >= 0)
    out: dict[str, list[str]] = {}
    for idx, (pos, key, heading) in enumerate(positions):
        stop = positions[idx + 1][0] if idx + 1 < len(positions) else len(text)
        body = text[pos + len(heading):stop]
        items = [ln.strip().rstrip(":") for ln in body.splitlines()]
        out[key] = [it for it in items if it and it != ":" and not it.endswith("View")]
    return out


def parse_js_object(js: str) -> dict[str, Any]:
    """`const xxx = {...};` → dict（取第一个 { 到最后一个 }）。"""
    start, end = js.find("{"), js.rfind("}")
    return json.loads(js[start:end + 1]) if start >= 0 and end > start else {}


def radar_summary(chart: dict[str, Any], model: str) -> dict[str, list[tuple[str, float]]]:
    entry = chart.get(model) or {}
    radar = entry.get("absoluteRadar") or {}
    return {
        "strengths": [(s["criterion"], s["relativeScore"]) for s in entry.get("strengths") or []],
        "weaknesses": [(w["criterion"], w["relativeScore"]) for w in entry.get("weaknesses") or []],
        "absolute": list(zip(radar.get("labels") or [], radar.get("values") or [])),
    }


def style_words(style: dict[str, Any], model: str, top: int = 20) -> list[str]:
    favored = (style.get(model) or {}).get("mostFavored") or []
    return [item["word"] for item in favored[:top]]


def _vs_median(value: float, median: float) -> str:
    if not median:
        return ""
    delta = (value - median) / median * 100
    return f"{'高于' if delta > 0 else '低于'}中位 {abs(delta):.0f}%"


def render_markdown(
    *, needle: str, rows: list[dict[str, Any]], med: dict[str, float],
    sections: dict[str, dict[str, list[str]]], radars: dict[str, dict[str, list[tuple[str, float]]]],
    styles: dict[str, list[str]], top: int = 20,
) -> str:
    lines = [
        f"# EQ-Bench Creative Writing v3 证据草稿：{needle}",
        "",
        "英文短篇实测（每模型 96 篇，Claude 评审 + 词频统计）。进表时把短语翻成中文形态，并标〔EQ〕。",
        "",
        f"榜单中位：slop {med.get('slop', 0):.2f} · 重复度 {med.get('repetition', 0):.2f} · 篇幅 {med.get('length', 0):.0f} 字符 · 词汇复杂度 {med.get('vocab', 0):.2f}",
        "",
        "| 模型 | Elo | 评分 | 篇幅 | 词汇 | slop | 重复度 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['elo']:.1f} | {r['rubric']:.2f} | {r['length']}（{_vs_median(r['length'], med.get('length', 0))}） "
            f"| {r['vocab']:.2f} | {r['slop']:.2f}（{_vs_median(r['slop'], med.get('slop', 0))}） "
            f"| {r['repetition']:.2f}（{_vs_median(r['repetition'], med.get('repetition', 0))}） |"
        )
    for r in rows:
        name = r["model"]
        lines += ["", f"## {name}"]
        radar = radars.get(name) or {}
        if radar.get("strengths") or radar.get("weaknesses"):
            lines.append("评审判据相对同榜（对数刻度，+ 强 / − 弱）：")
            lines += [f"- + {c} {s:+.2f}" for c, s in radar.get("strengths", [])]
            lines += [f"- − {c} {s:+.2f}" for c, s in radar.get("weaknesses", [])]
        if styles.get(name):
            lines.append(f"风格描述词：{'、'.join(styles[name][:top])}")
        sec = sections.get(name) or {}
        for key, label in (("phrases", "高频重复短语"), ("trigrams", "高频三元组"), ("bigrams", "高频二元组"),
                           ("words", "高频重复词"), ("similar", "slop 画像最接近的模型")):
            if sec.get(key):
                lines.append(f"{label}：{' · '.join(sec[key][:top])}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("needle", help="模型名片段，如 grok / qwen / glm / deepseek")
    parser.add_argument("--top", type=int, default=20, help="每类列表最多列几项")
    parser.add_argument("--version", default=ASSET_VERSION, help="页面资源版本号（?v=）")
    parser.add_argument("--out", help="写到文件；不给则打印")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows 控制台默认 GBK，中文输出会乱码

    lb_js = fetch("creative_writing.js", args.version)
    rows = select_models(parse_leaderboard(lb_js), args.needle)
    if not rows:
        print(f"榜单里没有名字含 {args.needle!r} 的模型", file=sys.stderr)
        return 1
    chart = parse_js_object(fetch("creative_writing_chartdata.js", args.version))
    style = parse_js_object(fetch("creative_writing_chartdata_style.js", args.version))
    md = render_markdown(
        needle=args.needle, rows=rows, med=medians(parse_leaderboard(lb_js)),
        sections={r["model"]: extract_model_section(lb_js, r["model"]) for r in rows},
        radars={r["model"]: radar_summary(chart, r["model"]) for r in rows},
        styles={r["model"]: style_words(style, r["model"], args.top) for r in rows},
        top=args.top,
    )
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(md)
        print(f"已写入 {args.out}")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
