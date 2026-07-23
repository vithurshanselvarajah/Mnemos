from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert buffalo_s to RKNN")
    parser.add_argument("--model", default="buffalo_s", help="InsightFace model name")
    parser.add_argument("--out", required=True, help="Output .rknn path")
    parser.add_argument(
        "--target",
        default="rk3588",
        choices=["rk3588", "rk3568", "rk3566", "rv1103", "rv1106"],
        help="Target Rockchip SoC platform",
    )
    raise NotImplementedError(
        "RKNN conversion pipeline is a TODO — see variants/rockchip/convert.py"
    )


if __name__ == "__main__":
    raise SystemExit(main())
