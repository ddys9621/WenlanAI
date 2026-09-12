"""去 AI 味金标准回归：用一批"人写"和一批"AI 写"的章节，检验措辞层本地指标能不能把两者分开。

没有这一步，每次调词表 / 阈值 / prompt 都是盲调。跑法（在 backend/ 目录）：
    python scripts/deai_goldset.py --human D:/corpus/human --ai D:/corpus/ai
    python scripts/deai_goldset.py --root D:/corpus            # root 下有 human/ 与 ai/ 两个子目录
    python scripts/deai_goldset.py --root D:/corpus --out goldset_report.md

每个目录里一个 .txt / .md 文件算一章（建议每组 ≥ 8 章、同题材、同长度量级）。输出每个指标在两组的均值 ± 标准差、
方向是否符合预期（HC3：人类句长标准差高、连词密度低、语气词密度高…），以及秩 AUC——0.5 = 分不开，越接近 1 越能分。

只看指标层，不调 LLM（免费、可复现）。要评 7 轮 LLM 诊断本身，在应用里对同一批章节跑诊断后比较 findings_count 即可。
"""
from __future__ import annotations

import argparse
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/

from app.services.deai_metrics import compute_metrics  # noqa: E402

# 指标 → 预期方向（"ai_high" = AI 偏高，"human_high" = 人类偏高），来自 07_style_zh.md 的语料参考
EXPECTED = {
    "sentence_len_std": "human_high",
    "flat_runs": "ai_high",
    "conjunctions_per_k": "ai_high",
    "particles_per_k": "human_high",
    "filter_words_per_k": "ai_high",
    "machine_phrase_total": "ai_high",
    "machine_phrase_clusters": "ai_high",
    "contrast_frames": "ai_high",
    "disyllabic_fillers": "ai_high",
    "tag_variety": "ai_high",
    "paragraph_len_cv": "human_high",
    "quote_end_ratio": "ai_high",
}


def load_group(folder: Path) -> list[tuple[str, dict]]:
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in {".txt", ".md"})
    return [(p.name, compute_metrics(p.read_text(encoding="utf-8", errors="replace"))["metrics"]) for p in files]


def rank_auc(ai_values: list[float], human_values: list[float]) -> float:
    """P(AI 样本 > 人类样本)，平局算 0.5；样本为空返回 0.5。"""
    if not ai_values or not human_values:
        return 0.5
    wins = sum(1.0 if a > h else 0.5 if a == h else 0.0 for a in ai_values for h in human_values)
    return wins / (len(ai_values) * len(human_values))


def fmt(values: list[float]) -> str:
    if not values:
        return "-"
    mean = statistics.fmean(values)
    std = statistics.pstdev(values) if len(values) > 1 else 0.0
    return f"{mean:.2f} ± {std:.2f}"


def build_report(human: list[tuple[str, dict]], ai: list[tuple[str, dict]]) -> str:
    rows = []
    for key, expected in EXPECTED.items():
        hv = [m[key] for _, m in human if isinstance(m.get(key), (int, float))]
        av = [m[key] for _, m in ai if isinstance(m.get(key), (int, float))]
        auc = rank_auc(av, hv)
        # 按预期方向折算成"分离度"：预期 AI 偏高时 auc 本身，预期人类偏高时 1-auc
        separation = auc if expected == "ai_high" else 1 - auc
        verdict = "符合" if separation > 0.6 else "反向" if separation < 0.4 else "分不开"
        rows.append((separation, key, expected, fmt(hv), fmt(av), auc, verdict))
    rows.sort(key=lambda r: -r[0])
    lines = [
        f"# 去 AI 味指标金标准报告",
        "",
        f"人写 {len(human)} 章，AI 写 {len(ai)} 章。分离度 = 按预期方向折算的秩 AUC（0.5 分不开，>0.6 有用，<0.4 方向反了）。",
        "",
        "| 指标 | 预期 | 人写 均值±σ | AI 均值±σ | AUC(AI>人) | 分离度 | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for separation, key, expected, h, a, auc, verdict in rows:
        lines.append(f"| {key} | {'AI 偏高' if expected == 'ai_high' else '人类偏高'} | {h} | {a} | {auc:.2f} | {separation:.2f} | {verdict} |")
    useful = [r[1] for r in rows if r[0] > 0.6]
    reversed_ = [r[1] for r in rows if r[0] < 0.4]
    lines += [
        "",
        f"能分开的指标（{len(useful)}）：{'、'.join(useful) or '无'}",
        f"方向反了的指标（{len(reversed_)}）：{'、'.join(reversed_) or '无'} —— 若非语料问题，应从 07_style_zh.md 与 deai_metrics 的提示里降权",
        "",
        "注意：n 小时 AUC 抖动大；两组题材 / 篇幅不一致会把差异归到错误的地方。",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, help="含 human/ 与 ai/ 子目录的根目录")
    parser.add_argument("--human", type=Path, help="人写章节目录")
    parser.add_argument("--ai", type=Path, help="AI 写章节目录")
    parser.add_argument("--out", type=Path, help="把报告写到这个 markdown 文件")
    args = parser.parse_args()
    human_dir = args.human or (args.root / "human" if args.root else None)
    ai_dir = args.ai or (args.root / "ai" if args.root else None)
    if not human_dir or not ai_dir or not human_dir.is_dir() or not ai_dir.is_dir():
        parser.error("需要 --root <dir>（含 human/ ai/）或同时给 --human 与 --ai 两个目录")
    report = build_report(load_group(human_dir), load_group(ai_dir))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"已写入 {args.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
