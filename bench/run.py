import argparse
import asyncio
import json
import os
import time
from typing import Any

from vaultproxy.detectors.registry import run_rule_detectors
from vaultproxy.gemma_layer import run_gemma_detection
from vaultproxy.merge import merge_spans


def evaluate_set(samples: list[dict[str, Any]], use_gemma: bool = False):
    stats = {}
    false_positives = []
    false_negatives = []
    latencies = []

    for idx, sample in enumerate(samples):
        text = sample["text"]
        gold_spans = sample.get("spans", [])

        t0 = time.perf_counter()
        rule_spans = run_rule_detectors(text)
        if use_gemma:
            gemma_spans, _, _ = asyncio.run(run_gemma_detection(text))
            detected = merge_spans(rule_spans + gemma_spans)
        else:
            detected = merge_spans(rule_spans)
        latency_ms = (time.perf_counter() - t0) * 1000
        latencies.append(latency_ms)

        gold_matched = [False] * len(gold_spans)

        for det in detected:
            dt = det.type
            if dt not in stats:
                stats[dt] = {"tp": 0, "fp": 0, "fn": 0}

            matched = False
            det_val = text[det.start : det.end]
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
                false_positives.append({"sample_index": idx, "type": dt, "text": det_val})

        for i, gold in enumerate(gold_spans):
            if not gold_matched[i]:
                gt = gold["type"]
                if gt not in stats:
                    stats[gt] = {"tp": 0, "fp": 0, "fn": 0}
                stats[gt]["fn"] += 1
                gold_val = text[gold["start"] : gold["end"]] if "start" in gold and "end" in gold else ""
                false_negatives.append({"sample_index": idx, "type": gt, "text": gold_val})

    total_tp = sum(s["tp"] for s in stats.values())
    total_fp = sum(s["fp"] for s in stats.values())
    total_fn = sum(s["fn"] for s in stats.values())

    metrics = {}
    for etype in sorted(stats.keys()):
        s = stats[etype]
        tp, fp, fn = s["tp"], s["fp"], s["fn"]
        p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        metrics[etype] = {
            "precision": round(p, 4),
            "recall": round(r, 4),
            "f1": round(f1, 4),
            "tp": tp,
            "fp": fp,
            "fn": fn,
        }

    overall_p = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    overall_r = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    overall_f1 = 2 * overall_p * overall_r / (overall_p + overall_r) if (overall_p + overall_r) > 0 else 0.0
    mean_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

    return {
        "metrics": metrics,
        "overall": {
            "precision": round(overall_p, 4),
            "recall": round(overall_r, 4),
            "f1": round(overall_f1, 4),
            "tp": total_tp,
            "fp": total_fp,
            "fn": total_fn,
            "mean_latency_ms": round(mean_latency_ms, 2),
        },
        "false_positives": false_positives,
        "false_negatives": false_negatives,
    }


def main():
    parser = argparse.ArgumentParser(description="VaultProxy Benchmark Runner")
    parser.add_argument("--gemma", action="store_true", help="Include Gemma layer detection")
    args = parser.parse_args()

    mode_str = "Rules + Gemma" if args.gemma else "Rules Only"

    # Load generated dataset
    generated_samples = []
    if os.path.exists("bench/dataset.json"):
        with open("bench/dataset.json", encoding="utf-8") as f:
            generated_samples = json.load(f)

    # Load held-out datasets
    heldout_samples = []
    if os.path.exists("bench/heldout.jsonl"):
        with open("bench/heldout.jsonl", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    heldout_samples.append(json.loads(line))

    heldout_v2_samples = []
    if os.path.exists("bench/heldout_v2.jsonl"):
        with open("bench/heldout_v2.jsonl", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    heldout_v2_samples.append(json.loads(line))

    res_gen = evaluate_set(generated_samples, use_gemma=args.gemma) if generated_samples else None
    res_held = evaluate_set(heldout_samples, use_gemma=args.gemma) if heldout_samples else None
    res_held_v2 = evaluate_set(heldout_v2_samples, use_gemma=args.gemma) if heldout_v2_samples else None

    # Write bench/results.json
    results_json = {
        "mode": mode_str,
        "generated": res_gen,
        "heldout": res_held,
        "heldout_v2": res_held_v2,
        "metrics": res_gen["metrics"] if res_gen else {},
        "overall": res_gen["overall"] if res_gen else {},
    }

    with open("bench/results.json", "w", encoding="utf-8") as f:
        json.dump(results_json, f, indent=2)

    # Render RESULTS.md
    lines = []
    lines.append("# VaultProxy Benchmark Results\n")
    lines.append(f"**Evaluation Mode:** {mode_str}\n")

    if res_gen:
        lines.append(f"## Generated Test Dataset ({len(generated_samples)} Samples)\n")
        lines.append("| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |")
        lines.append("|---|---|---|---|---|---|---|")
        for etype, m in res_gen["metrics"].items():
            lines.append(
                f"| {etype} | {m['precision']:.2%} | {m['recall']:.2%} | {m['f1']:.2%} | {m['tp']} | {m['fp']} | {m['fn']} |"
            )
        o = res_gen["overall"]
        lines.append(
            f"| **OVERALL** | **{o['precision']:.2%}** | **{o['recall']:.2%}** | **{o['f1']:.2%}** | **{o['tp']}** | **{o['fp']}** | **{o['fn']}** |\n"
        )
        lines.append(f"**Mean Latency:** {o['mean_latency_ms']} ms\n")

    if res_held:
        lines.append(f"## Held-Out Evaluation Dataset v1 ({len(heldout_samples)} Samples)\n")
        lines.append("| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |")
        lines.append("|---|---|---|---|---|---|---|")
        for etype, m in res_held["metrics"].items():
            lines.append(
                f"| {etype} | {m['precision']:.2%} | {m['recall']:.2%} | {m['f1']:.2%} | {m['tp']} | {m['fp']} | {m['fn']} |"
            )
        o = res_held["overall"]
        lines.append(
            f"| **OVERALL** | **{o['precision']:.2%}** | **{o['recall']:.2%}** | **{o['f1']:.2%}** | **{o['tp']}** | **{o['fp']}** | **{o['fn']}** |\n"
        )
        lines.append(f"**Mean Latency:** {o['mean_latency_ms']} ms\n")

    if res_held_v2:
        lines.append(f"## Held-Out Challenging Dataset v2 ({len(heldout_v2_samples)} Samples)\n")
        lines.append("| Entity Type | Precision | Recall | F1 Score | TP | FP | FN |")
        lines.append("|---|---|---|---|---|---|---|")
        for etype, m in res_held_v2["metrics"].items():
            lines.append(
                f"| {etype} | {m['precision']:.2%} | {m['recall']:.2%} | {m['f1']:.2%} | {m['tp']} | {m['fp']} | {m['fn']} |"
            )
        o = res_held_v2["overall"]
        lines.append(
            f"| **OVERALL** | **{o['precision']:.2%}** | **{o['recall']:.2%}** | **{o['f1']:.2%}** | **{o['tp']}** | **{o['fp']}** | **{o['fn']}** |\n"
        )
        lines.append(f"**Mean Latency:** {o['mean_latency_ms']} ms\n")

    report_md = "\n".join(lines)

    with open("bench/RESULTS.md", "w", encoding="utf-8") as f:
        f.write(report_md)

    print("Benchmark completed successfully.")
    print(report_md)


if __name__ == "__main__":
    main()
