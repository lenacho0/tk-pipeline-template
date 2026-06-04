#!/usr/bin/env python3
"""
test_structured_storyboard_real.py

用影子测试输出的结构化 shots JSON + 真实 model/product 图片 References，
生成 3x3 分镜图 grid image，验证 content_type-aware prompt 的实际效果。

不对飞书正式表做任何修改，输出结果写到 structured_script_shadow_output/ 目录。
"""

import json, os, sys, time, base64, requests
from pathlib import Path

WORKSPACE     = Path(os.environ.get("WORKSPACE", ".")).resolve()
OUT_DIR       = WORKSPACE / "structured_script_shadow_output"
SCRIPT_DIR    = WORKSPACE / "tk_toolkit_dual"
SHADOW_OUTPUT = WORKSPACE / "structured_script_shadow_output"

sys.path.insert(0, str(SCRIPT_DIR))
from common import *

# ── Sample → token mapping (confirmed working) ────────────────────────────────────
SAMPLE_MAP = {
    "sample_01": {
        "shadow_id": "sample_01",
        "type": "对白主导",
        "model_token": "NKuUbeMdLovpnKxSGRXcfvLnnfw",  # MoMo model
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",  # pet deodorizing spray
    },
    "sample_03": {
        "shadow_id": "sample_03",
        "type": "混合型",
        "model_token": "AWO3bM9azoN8lHxprREcarOin3g",  # YOYO model
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",
    },
    "sample_06": {
        "shadow_id": "sample_06",
        "type": "静默/氛围主导",
        "model_token": "NKuUbeMdLovpnKxSGRXcfvLnnfw",
        "product_token": "U7N7bcgHPogb93xXyHDcsEGOnFd",
    },
}


# ── Image download ─────────────────────────────────────────────────────────────
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


# ── Gemini call with images ───────────────────────────────────────────────────
def get_gemini_credentials():
    """Get Gemini API credentials from config table (same as test_structured_script_shadow_flow.py)."""
    record_id = CONFIG_RECORDS.get("script_gen", "")
    if not record_id:
        return None, None
    token = get_feishu_token()
    config = get_model_config(token, record_id)
    api_key  = (config.get("api_key") or "").strip()
    api_base = (config.get("api_base") or "https://aihubmix.com/gemini").strip()
    return api_key, api_base


def call_gemini_with_images(prompt_text, image_paths, model_name="gemini-3.1-flash-image-preview"):
    from google.genai import types
    from google.genai.types import Part

    parts = []
    for path in image_paths:
        if not os.path.exists(path):
            continue
        with open(path, "rb") as f:
            img_data = f.read()
        parts.append(Part(inline_data={
            "mime_type": "image/png",
            "data": base64.b64encode(img_data).decode("ascii")
        }))

    parts.append(Part(text=prompt_text))

    api_key, api_base = get_gemini_credentials()
    if not api_key:
        raise Exception("Could not get Gemini API key from config")
    client = get_gemini_client(api_key, api_base)

    resp = client.models.generate_content(
        model=model_name,
        contents=[types.Content(role="user", parts=parts)],
        config=types.GenerateContentConfig(response_modalities=["image", "text"])
    )
    return resp


# ── Grid prompt builder ───────────────────────────────────────────────────────
def build_grid_prompt_from_shots(shots, product_ref_note="", model_ref_note=""):
    panel_lines = []
    for i, s in enumerate(shots[:9]):
        panel_lines.append(f"Panel {i+1}: {s.get('prompt_text', s.get('description', ''))}")

    ref_note = ""
    if product_ref_note:
        ref_note += f"\n- Image 1 = Product reference: {product_ref_note}"
    if model_ref_note:
        ref_note += f"\n- Image 2 = Character reference: {model_ref_note}"

    return f"""Create a single 3x3 storyboard grid image in 9:16 vertical portrait format.

REFERENCE IMAGES (attached):{ref_note}

LAYOUT REQUIREMENTS:
- Single image containing exactly 9 panels arranged in a 3x3 grid (3 columns x 3 rows)
- Overall image aspect ratio: 9:16 (vertical portrait, taller than wide)
- Each individual panel aspect ratio: 9:16 (vertical portrait)
- Thin white borders separating all panels
- NO panel numbers, NO text labels, NO numbering on any panel

PANEL DESCRIPTIONS:

{chr(10).join(panel_lines)}"""


# ── Save image from Gemini response ────────────────────────────────────────────
def save_image_from_response(resp, out_path):
    for candidate in getattr(resp, "candidates", []):
        for part in candidate.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                data = part.inline_data.data
                binary = base64.b64decode(data) if isinstance(data, str) else data
                with open(out_path, "wb") as f:
                    f.write(binary)
                print(f"  Saved image: {out_path} ({os.path.getsize(out_path):,} bytes)")
                return True
    print("  WARNING: No image in response")
    return False


# ── Main test pipeline ─────────────────────────────────────────────────────────
def test_sample(sample_key, cfg):
    shadow_id = cfg["shadow_id"]
    print(f"\n{'='*60}")
    print(f"Testing: {sample_key} ({shadow_id})")
    print(f"{'='*60}")

    task_dir = SHADOW_OUTPUT / f"{shadow_id}_real_test"
    task_dir.mkdir(exist_ok=True)

    # Load structured shots
    shots_file = SHADOW_OUTPUT / shadow_id / "storyboard_shots.json"
    if not shots_file.exists():
        print(f"  ERROR: {shots_file} not found")
        return None

    with open(shots_file) as f:
        shots_data = json.load(f)

    shots = shots_data.get("shots", [])
    print(f"  Loaded {len(shots)} structured shots")

    from collections import Counter
    ct = Counter(s.get("content_type_influenced_by", "?") for s in shots)
    print(f"  Shot distribution: {dict(ct)}")

    model_token    = cfg.get("model_token", "")
    product_token  = cfg.get("product_token", "")

    # Download reference images
    model_path   = task_dir / "reference_model.png"
    product_path = task_dir / "reference_product.png"
    img_paths = []

    if model_token:
        ok = download_media(model_token, str(model_path))
        print(f"  Model image: {'OK' if ok else 'FAILED'} ({model_path.name})")
        if ok:
            img_paths.append(str(model_path))

    if product_token:
        ok = download_media(product_token, str(product_path))
        print(f"  Product image: {'OK' if ok else 'FAILED'} ({product_path.name})")
        if ok:
            img_paths.insert(0, str(product_path))

    if not img_paths:
        print("  ERROR: No reference images available")
        return None

    # Build grid prompt
    product_ref_note = "white pet deodorizing spray bottle, 300ml" if product_token else ""
    model_ref_note   = "Thai woman and/or cat character" if model_token else ""
    grid_prompt = build_grid_prompt_from_shots(shots, product_ref_note, model_ref_note)

    with open(task_dir / "grid_prompt_used.txt", "w", encoding="utf-8") as f:
        f.write(grid_prompt)

    # Save shots used
    with open(task_dir / "shots_used.json", "w", encoding="utf-8") as f:
        json.dump(shots_data, f, ensure_ascii=False, indent=2)

    # Generate
    print(f"  Generating storyboard grid with {len(img_paths)} ref images...")
    try:
        resp = call_gemini_with_images(grid_prompt, img_paths)
        grid_path = task_dir / "storyboard_grid.png"
        ok = save_image_from_response(resp, str(grid_path))
        if not ok:
            return None
    except Exception as e:
        print(f"  ERROR: {e}")
        import traceback
        traceback.print_exc()
        return None

    print(f"  ✅ Complete: {grid_path}")
    return str(grid_path)


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
            results[key] = {"status": "success" if path else "failed", "grid_path": path}
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
            results[key] = {"status": "error", "error": str(e)}

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    for k, v in results.items():
        icon = "✅" if v.get("status") == "success" else "❌"
        path = v.get("grid_path", "")
        print(f"  {icon} {k}: {v.get('status')}" + (f" -> {path}" if path else ""))


if __name__ == "__main__":
    main()
