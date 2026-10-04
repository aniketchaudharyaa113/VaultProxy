import sys
import json
import asyncio
import argparse
from typing import List, Dict, Any
from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import run_gemma_detection
from vaultproxy.merge import merge_spans


def evaluate(samples: List[Dict[str, Any]], use_gemma: bool = False):
    stats = {}

    for sample in samples:
        text = sample["text"]
        gold_spans = sample["spans"]

        rule_spans = run_rule_detectors(text)
        if use_gemma:
            gemma_spans, _, _ = asyncio.run(run_gemma_detection(text))
            detected = merge_spans(rule_spans + gemma_spans)
        else:
            detected = merge_spans(rule_spans)

        gold_matched = [False] * len(gold_spans)

        for det in detected:
            dt = det.type
            if dt not in stats:
                stats[dt] = {"tp": 0, "fp": 0, "fn": 0}

            matched = False
            for i, gold in enumerate(gold_spans):
                if not gold_matched[i] and gold["type"] == dt:
                    if det.start < gold["end"] and det.end > gold["start"]:
                        matched = True
                        gold_matched[i] = True
                        break

            if matched:
                stats[dt]["tp"] += 1
            else:
                stats[dt]["fp"] += 1

        for i, gold in enumerate(gold_spans):
            if not gold_matched[i]:
                gt = gold["type"]
                if gt not in stats:
                    stats[gt] = {"tp": 0, "fp": 0, "fn": 0}
                stats[gt]["fn"] += 1

    lines = []
    lines.append("# VaultProxy Benchmark Results\n")
    mode_str = "Rules + Gemma" if use_gemma else "Rules Only"
    lines.append(f"**Evaluation Mode:** {mode_str}\n")
    lines.append("| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |")
    lines.append("|---|---|---|---|---|---|---|")

    json_results = {
        "mode": mode_str,
        "metrics": {},
        "overall": {}
    }

    total_tp = sum(s["tp"] for s in stats.values())
    total_fp = sum(s["fp"] for s in stats.values())
    total_fn = sum(s["fn"] for s in stats.values())

    for etype in sorted(stats.keys()):
        s = stats[etype]
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        lines.append(f"| {etype} | {p:.2%} | {r:.2%} | {f1:.2%} | {tp} | {fp} | {fn} |")
        json_results["metrics"][etype] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn
        }

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0

    lines.append(f"| **OVERALL** | **{overall_p:.2%}** | **{overall_r:.2%}** | **{overall_f1:.2%}** | **{total_tp}** | **{total_fp}** | **{total_fn}** |\n")

    json_results["overall"] = {
        "precision": round(overall_p, 4),
        "recall": round(overall_r, 4),
        "f1": round(overall_f1, 4),
        "tp": total_tp,
        "fp": total_fp,
        "fn": total_fn
    }

    report_content = "\n".join(lines)

    with open("bench/RESULTS.md", "w", encoding="utf-8") as f:
        f.write(report_content)

    with open("bench/results.json", "w", encoding="utf-8") as f:
        json.dump(json_results, f, indent=2)

    print("Benchmark evaluation completed. Results written to bench/RESULTS.md and bench/results.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="VaultProxy Benchmark Runner")
    parser.add_argument("--gemma", action="store_true", help="Include Gemma layer detection")
    args = parser.parse_args()

    with open("bench/dataset.json", "r", encoding="utf-8") as f:
        dataset = json.load(f)

    evaluate(dataset, use_gemma=args.gemma)
