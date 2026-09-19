import asyncio

from load_generator.config import get_settings
from load_generator.runner import run_load


def main() -> None:
    summary = asyncio.run(run_load(get_settings()))
    print(summary.model_dump_json())


if __name__ == "__main__":
    main()
