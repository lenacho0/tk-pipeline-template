#!/usr/bin/env python3
"""
test_structured_storyboard_real_v2.py

用影子测试输出的结构化 shots JSON + 正式链路 build_structured_grid_prompt，
生成 3x3 分镜图 grid image，验证 content_type-aware 正式 prompt 的实际效果。

✅ 使用 tk_storyboard.py 的正式 prompt 约束体系（CL1-CL5）
✅ 使用 build_structured_grid_prompt 生成带 content_type 语义的 grid prompt
不对飞书正式表做任何修改，输出结果写到 structured_script_shadow_output/*_real_test_v2/
"""

import json, os, sys, time, base64, requests
from pathlib import Path
from google.genai import types

WORKSPACE     = Path(os.environ.get("WORKSPACE", "/Users/ryanlynn/.openclaw/workspace-tk"))
OUT_DIR       = WORKSPACE / "structured_script_shadow_output"
SCRIPT_DIR    = WORKSPACE / "tk_toolkit_dual"
SHADOW_OUTPUT = WORKSPACE / "structured_script_shadow_output"

sys.path.insert(0, str(SCRIPT_DIR))
from common import *
from tk_storyboard import build_structured_grid_prompt, render_storyboard_image

# ── Sample → token mapping ────────────────────────────────────────────────────
SAMPLE_MAP = {
    "sample_01": {
        "shadow_id": "sample_01",
        "type": "对白主导",
        "style": "混合",
        "model_token": "NKuUbeMdLovpnKxSGRXcfvLnnfw",
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",
    },
    "sample_03": {
        "shadow_id": "sample_03",
        "type": "混合型",
        "style": "混合",
        "model_token": "AWO3bM9azoN8lHxprREcarOin3g",
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",
    },
    "sample_06": {
        "shadow_id": "sample_06",
        "type": "静默/氛围主导",
        "style": "混合",
        "model_token": "NKuUbeMdLovpnKxSGRXcfvLnnfw",
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",
    },
}


def download_media(file_token, save_path):
    url = f"https://open.feishu.cn/open-apis/drive/v1/medias/{file_token}/download"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {get_feishu_token()}"},
        timeout=60,
        stream=True
    )
    if resp.status_code == 200:
        with open(save_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        return True
    return False


def test_sample(sample_key, cfg):
    shadow_id = cfg["shadow_id"]
    style     = cfg.get("style", "混合")
    print(f"\n{'='*60}")
    print(f"Testing: {sample_key} ({shadow_id}) [style={style}]")
    print(f"{'='*60}")

    task_dir = SHADOW_OUTPUT / f"{shadow_id}_real_test_v2"
    task_dir.mkdir(exist_ok=True)

    # Load structured shots from shadow output
    shots_file = SHADOW_OUTPUT / shadow_id / "storyboard_shots.json"
    if not shots_file.exists():
        raise FileNotFoundError(f"{shots_file} not found")

    with open(shots_file) as f:
        shots_data = json.load(f)
    shots = shots_data.get("shots", [])
    print(f"  Loaded {len(shots)} structured shots")

    from collections import Counter
    ct = Counter(s.get("content_type_influenced_by", "?") for s in shots)
    print(f"  Shot distribution: {dict(ct)}")

    # Download reference images
    model_token   = cfg.get("model_token", "")
    product_token = cfg.get("product_token", "")
    model_path   = task_dir / "reference_model.png"
    product_path = task_dir / "reference_product.png"

    if model_token:
        ok = download_media(model_token, str(model_path))
        print(f"  Model image: {'OK' if ok else 'FAILED'} ({os.path.getsize(str(model_path)):,} bytes)")
    if product_token:
        ok = download_media(product_token, str(product_path))
        print(f"  Product image: {'OK' if ok else 'FAILED'} ({os.path.getsize(str(product_path)):,} bytes)")

    if not os.path.exists(product_path) or os.path.getsize(str(product_path)) < 1000:
        raise Exception("Product image missing")

    # ── Build grid prompt using the FORMAL pipeline function ──
    grid_prompt = build_structured_grid_prompt(shots, style=style)
    with open(task_dir / "grid_prompt_used.txt", "w", encoding="utf-8") as f:
        f.write(grid_prompt)
    print(f"  Grid prompt built: {len(grid_prompt):,} chars")

    # Save shots used
    with open(task_dir / "shots_used.json", "w", encoding="utf-8") as f:
        json.dump(shots_data, f, ensure_ascii=False, indent=2)

    # ── Get Gemini credentials from config table (same as tk_storyboard.py) ──
    token = get_feishu_token()
    config = get_model_config(token, CONFIG_RECORDS["storyboard"])
    api_key  = config["api_key"]
    api_base = config["api_base"]
    model_name = config["model"]   # gemini-3.1-flash-image-preview

    print(f"  Using model: {model_name} via {api_base}")

    from google import genai
    client = genai.Client(api_key=api_key, http_options={'base_url': api_base})

    # Upload reference images
    product_file = client.files.upload(file=str(product_path))
    parts = [types.Part.from_uri(file_uri=product_file.uri, mime_type="image/png")]
    if os.path.exists(str(model_path)) and os.path.getsize(str(model_path)) > 1000:
        model_file = client.files.upload(file=str(model_path))
        parts.append(types.Part.from_uri(file_uri=model_file.uri, mime_type="image/png"))
        print(f"  Uploaded: model={model_file.uri[-40:]}")

    # ── Render grid image ──
    out_path = task_dir / "storyboard_grid.png"
    print(f"  Generating grid image...")
    try:
        result = render_storyboard_image(client, model_name, parts, grid_prompt, str(out_path))
        print(f"  ✅ Complete: {out_path} ({os.path.getsize(str(out_path)):,} bytes)")
        return str(out_path)
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    samples_to_run = []
    if args.sample and args.sample in SAMPLE_MAP:
        samples_to_run = [(args.sample, SAMPLE_MAP[args.sample])]
    elif args.all:
        samples_to_run = list(SAMPLE_MAP.items())
    else:
        samples_to_run = [(k, v) for k, v in SAMPLE_MAP.items()]

    results = {}
    for key, cfg in samples_to_run:
        try:
            path = test_sample(key, cfg)
            results[key] = {"status": "success", "grid_path": path}
        except Exception as e:
            print(f"  ERROR: {e}")
            results[key] = {"status": "error", "error": str(e)}

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for k, v in results.items():
        icon = "✅" if v.get("status") == "success" else "❌"
        path = v.get("grid_path", "")
        print(f"  {icon} {k}: {v.get('status')}" + (f"\n      -> {path}" if path else ""))


if __name__ == "__main__":
    main()
