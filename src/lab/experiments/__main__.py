"""Allow ``python -m lab.experiments`` as an alias for the baseline."""

from lab.experiments.baseline import main

if __name__ == "__main__":
    raise SystemExit(main())
