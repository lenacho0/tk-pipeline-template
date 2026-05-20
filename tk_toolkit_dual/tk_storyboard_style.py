"""Storyboard style policy helpers for the handwritten shot pipeline."""


STYLE_REALISTIC = "全写实"
STYLE_MIXED = "混合（产品写实+角色动画）"
STYLE_ANIMATED = "全动画"


def normalize_storyboard_style(raw_style):
    text = str(raw_style or "").strip()
    compact = text.replace(" ", "")
    if "全动画" in compact or "动画" == compact:
        return STYLE_ANIMATED
    if "全写实" in compact or "真实" in compact or "写实" == compact or "实拍" in compact:
        return STYLE_REALISTIC
    if "混合" in compact or "产品写实" in compact:
        return STYLE_MIXED
    return STYLE_MIXED


def resolve_storyboard_style_policy(raw_style):
    style = normalize_storyboard_style(raw_style)
    common_rules = [
        "产品包装始终严格写实锚定：保持参考图的盒型、颜色、logo、标签、剂量标识、包装比例，不得卡通化或重设计。",
        "不得让风格改变剧情、口播、产品使用方式、镜头顺序或 CTA；风格只影响视觉材质、光影和角色/环境表现。",
        "不生成字幕、贴纸、水印、UI 或气泡文字；屏幕文字只作为后期叠加信息，不进入图片模型生成。",
        "主人不露完整脸、不 lip-sync；如果需要出现主人，只露下半脸、身体、手或弱化背景。",
        "宠物说话时必须保持可见说话主体：宠物面对镜头或与角色互动，表情和口型服务口播。",
    ]
    style_specific = {
        STYLE_REALISTIC: [
            "整体为泰国真实 UGC 广告感：宠物、主人、环境、道具和产品都保持真实摄影质感。",
            "保留手机竖屏、自然手持、真实家庭/门口/生活场景，不要变成棚拍海报或卡通画面。",
        ],
        STYLE_MIXED: [
            "产品包装写实；宠物可轻微拟人或 3D 动画化，但不要幼稚卡通化。",
            "环境保持真实 TikTok 商拍感，光影可更干净精致，仍像真实泰国家庭场景。",
        ],
        STYLE_ANIMATED: [
            "角色和环境采用高级 3D Disney/Pixar 向动画商业短片风格，有体积感、材质感和电影化光影。",
            "产品包装仍严格写实，不得动画化、插画化、软萌化或改变包装文字和剂量标识。",
        ],
    }[style]
    rules = common_rules + style_specific
    return {
        "style": style,
        "prompt_rules": "\n".join(f"- {rule}" for rule in rules),
        "rules": rules,
    }


def format_style_policy_for_prompt(raw_style):
    policy = resolve_storyboard_style_policy(raw_style)
    return f"""## 分镜风格策略
- 标准化风格：{policy["style"]}
{policy["prompt_rules"]}""".strip()
