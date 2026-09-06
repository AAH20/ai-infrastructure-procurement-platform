import argparse
import json
from datetime import date
from pathlib import Path

from .engine import evaluate_procurement


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AI infrastructure offers against an evidence-driven RFP")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = evaluate_procurement(json.loads(args.bundle.read_text()), args.as_of)
    rendered = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    print(rendered)


if __name__ == "__main__":
    main()

