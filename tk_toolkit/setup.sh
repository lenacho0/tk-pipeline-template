#!/bin/bash
# ============================================================
# TK 爆款内容工具包 - 一键安装
# ============================================================
set -e

echo ""
echo "🚀 TK 爆款内容自动化工具包 - 安装中..."
echo "================================================"
echo ""

# 检查 Python 版本
python3 --version 2>/dev/null || { echo "❌ 请先安装 Python 3.9+"; exit 1; }

# 安装依赖
echo "📦 安装 Python 依赖..."
pip3 install -r requirements.txt

# 创建配置文件
if [ ! -f config.json ]; then
    cp config.json.template config.json
    echo "📝 已创建 config.json（从模板复制）"
else
    echo "⚠️  config.json 已存在，跳过（不覆盖你的配置）"
fi

# 创建工作目录
mkdir -p workspace/tiktok_videos
mkdir -p workspace/storyboard_work
mkdir -p workspace/video_work

echo ""
echo "================================================"
echo "✅ 安装完成！"
echo ""
echo "下一步："
echo "  1. 编辑 config.json —— 填入你的飞书应用凭证、API Token 等"
echo "  2. 运行 python3 tk_healthcheck.py —— 测试所有接口是否正常"
echo "  3. 运行 nohup python3 tk_dispatcher.py >> dispatcher.log 2>&1 &"
echo "     —— 启动后台调度器"
echo ""
echo "详细说明请阅读 README.md"
echo "================================================"
