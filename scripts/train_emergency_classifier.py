#!/usr/bin/env python
"""OPTIONAL: fine-tune DistilBERT as a local emergency classifier.

The production emergency detector is patterns + an LLM judge. This script
trains a CPU-servable alternative so the two approaches can be compared on
accuracy, latency, and cost (see README). Designed for a free Colab T4 —
do not run training on a laptop.

    pip install transformers datasets torch scikit-learn pyyaml
    python scripts/train_emergency_classifier.py --cases redteam/cases --epochs 4

Training data: the red-team emergency cases (positives) and benign cases
(negatives). ~90 examples is small — augment with paraphrases before trusting
the numbers, and treat this as a latency/cost baseline, not a final model.
"""

import argparse
from pathlib import Path

import yaml


def load_examples(cases_dir: Path) -> tuple[list[str], list[int]]:
    texts, labels = [], []
    for case in yaml.safe_load((cases_dir / "emergency.yaml").read_text()):
        texts.append(case["input"])
        labels.append(1)
    for case in yaml.safe_load((cases_dir / "benign.yaml").read_text()):
        texts.append(case["input"])
        labels.append(0)
    return texts, labels


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", default="redteam/cases")
    parser.add_argument("--model", default="distilbert-base-uncased")
    parser.add_argument("--epochs", type=int, default=4)
    parser.add_argument("--out", default="emergency_classifier")
    args = parser.parse_args()

    import numpy as np
    import torch
    from datasets import Dataset
    from sklearn.metrics import f1_score
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    if not torch.cuda.is_available():
        print("WARNING: no GPU detected — run this on Colab, not a laptop.")

    texts, labels = load_examples(Path(args.cases))
    dataset = Dataset.from_dict({"text": texts, "label": labels}).train_test_split(
        test_size=0.2, seed=42, stratify_by_column=None
    )

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tokenized = dataset.map(
        lambda batch: tokenizer(
            batch["text"], truncation=True, padding="max_length", max_length=64
        ),
        batched=True,
    )

    model = AutoModelForSequenceClassification.from_pretrained(args.model, num_labels=2)

    def metrics(eval_pred):
        logits, y = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {"f1": f1_score(y, preds)}

    trainer = Trainer(
        model=model,
        args=TrainingArguments(
            output_dir=args.out,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=16,
            eval_strategy="epoch",
            logging_steps=10,
            report_to="none",
        ),
        train_dataset=tokenized["train"],
        eval_dataset=tokenized["test"],
        compute_metrics=metrics,
    )
    trainer.train()
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"saved to {args.out}/ — compare vs the LLM judge on accuracy, latency, cost")


if __name__ == "__main__":
    main()
