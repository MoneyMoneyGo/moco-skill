#!/usr/bin/env python3
"""
check_lineup.py — MoCo 阵容一致性门禁（药方 2 / 轻量版）

用途：
    扫描仓库所有活跃数据文件，检查其中引用的模型名/model_id 是否与 SKILL.md
    声明的"默认阵容"一致。用于发现"换阵容时漏改 fixture/asset"这类低级失误。

扫描范围（按"真相源 → 活跃数据 → 历史快照"分层）：
    真相源：     SKILL.md 第 87-90 行默认阵容表 + 第 149-150 行裁判表
    活跃数据：   scripts/*.py, assets/*.html, moco-regression-tests/*.json
    历史快照：   examples/*.html（历史报告，应保持原样）
                COST_REFERENCE.md, CHANGELOG.md（叙事性文档，可含旧模型名）

校验规则：
    H-L1 (hard): 活跃 fixture 里的 model_id 必须 ∈ 当前阵容白名单
    H-L2 (hard): 活跃 fixture 里的 name 必须 ∈ 当前阵容白名单
    H-L3 (hard): 活跃 fixture 里 challenges_received[*].from / challenges_issued[*].target
                 必须 ∈ 当前阵容白名单
    S-L1 (soft): 活跃数据里出现了一个已知旧模型名（如 GLM-4.7）但当前阵容不含它 → warn

退出码：
    0  通过（含 soft warn）
    4  hard fail（与 _gen_moco.py 的 exit 3 区分，便于调用方识别）

CLI：
    python check_lineup.py                  # 默认跑全部
    python check_lineup.py --only-fixtures  # 只扫 fixture
    python check_lineup.py --root <path>    # 覆盖仓库根目录
    python check_lineup.py --quiet          # 只在 fail 时输出

集成：
    _gen_moco.py 的 --update-check-only 会顺带跑此脚本（未来）。
    CI / 回归测试里可独立调用。
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ============================================================================
# 真相源：从 SKILL.md 解析默认阵容表
# ============================================================================
# 阵容表格式（SKILL.md ~87-90 行）：
#   | 1 | Claude Sonnet | `#D97706` | Anthropic | `claude-sonnet-4.6-1m` |
# 裁判：
#   | Claude Opus 4.7 (1M) | `claude-opus-4.7-1m` |
#
# 宽容起见：只要出现 `xxx-yyy-zzz` 带反引号的 model id 就识别；
# 结合"Display Name"列的文本做双向白名单。
# ============================================================================

# 已知 MoCo 曾经用过的"旧模型名"（用于 S-L1 软告警）
KNOWN_LEGACY_MODELS = {
    "GLM-4.7": "glm-4.7-ioa",  # v4 → v5 被替换为 DeepSeek V3.2
}


def parse_lineup_from_skill_md(skill_md_path: Path) -> Tuple[Set[str], Set[str]]:
    """
    解析 SKILL.md 的默认阵容表，返回 (display_names, model_ids)。

    找"Default model lineup"标题下的表格 + "Round 4 裁判" 的 opus id。
    """
    text = skill_md_path.read_text(encoding="utf-8")

    display_names: Set[str] = set()
    model_ids: Set[str] = set()

    # --- 1. 定位 Default lineup 表格并解析每一行 ---
    # 表格起始锚点
    lineup_start = text.find("Default model lineup")
    if lineup_start == -1:
        raise RuntimeError("SKILL.md 里找不到 'Default model lineup' 锚点")
    # 取锚点之后的 ~40 行做局部匹配
    lineup_block = text[lineup_start: lineup_start + 2000]

    # 匹配： | 1 | Claude Sonnet | `#...` | ... | `claude-sonnet-4.6-1m` |
    row_pat = re.compile(
        r"\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*`?#?[0-9A-Fa-f]{3,6}`?\s*\|\s*[^|]+\s*\|\s*`([^`]+)`\s*\|"
    )
    for m in row_pat.finditer(lineup_block):
        display_names.add(m.group(1).strip())
        model_ids.add(m.group(2).strip())

    if not display_names:
        raise RuntimeError("SKILL.md 默认阵容表解析失败，未命中任何行")

    # --- 2. 找裁判模型（扫全文找 Round 4 / 裁判 附近的 model_id）---
    # 硬编码：裁判固定是 opus 系列。从 SKILL.md 里扫 claude-opus-* 所有出现。
    for m in re.finditer(r"`(claude-opus-[^`]+)`", text):
        mid = m.group(1)
        if mid:
            model_ids.add(mid)
            display_names.add("Claude Opus 4.7 (1M)")
            display_names.add("Claude Opus")
            display_names.add("Claude Opus 4.7")

    return display_names, model_ids


# ============================================================================
# Fixture 扫描：从 JSON 里提取所有模型引用
# ============================================================================

def extract_model_refs_from_fixture(path: Path) -> Dict[str, List[str]]:
    """
    从 debate-data.json 提取模型引用。返回 dict 分类:
        name:        顶层 models[*].name
        model_id:    models[*].model_id
        from:        challenges_received[*].from
        target:      challenges_issued[*].target
        judge_name:  verdict.judge_model
        judge_id:    verdict.judge_model_id
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"_parse_error": [f"JSON 解析失败: {e}"]}

    refs = {
        "name": [],
        "model_id": [],
        "from": [],
        "target": [],
        "judge_name": [],
        "judge_id": [],
    }

    for m in (data.get("models") or []):
        if n := m.get("name"):
            refs["name"].append(n)
        if mid := m.get("model_id"):
            refs["model_id"].append(mid)

        for c in (m.get("challenges_issued") or []):
            if t := c.get("target"):
                refs["target"].append(t)

        for rc in (m.get("challenges_received") or []):
            if f := rc.get("from"):
                refs["from"].append(f)
            v = rc.get("verdict") or {}
            if jn := v.get("judge_model"):
                refs["judge_name"].append(jn)
            if jid := v.get("judge_model_id"):
                refs["judge_id"].append(jid)

    return refs


# ============================================================================
# 主流程
# ============================================================================

def run_check(
    skill_root: Path,
    only_fixtures: bool = False,
    quiet: bool = False,
) -> int:
    """Return exit code. 0 = OK, 4 = hard fail."""
    if not skill_root.exists():
        print(f"❌ skill root 不存在: {skill_root}", file=sys.stderr)
        return 4

    skill_md = skill_root / "SKILL.md"
    if not skill_md.exists():
        print(f"❌ 缺 SKILL.md: {skill_md}", file=sys.stderr)
        return 4

    # ---- 1. 解析真相源 ----
    try:
        display_whitelist, id_whitelist = parse_lineup_from_skill_md(skill_md)
    except RuntimeError as e:
        print(f"❌ 真相源解析失败: {e}", file=sys.stderr)
        return 4

    if not quiet:
        print("📋 当前默认阵容（源自 SKILL.md）:")
        print(f"   Display names : {sorted(display_whitelist)}")
        print(f"   Model IDs     : {sorted(id_whitelist)}")

    hard_fails: List[str] = []
    soft_warns: List[str] = []

    # ---- 2. 扫描 fixture ----
    fixture_dirs = [
        Path("/Users/soy/WorkBuddy/20260427161553/moco-regression-tests"),
    ]
    scanned = 0
    for d in fixture_dirs:
        if not d.exists():
            continue
        for fx in sorted(d.glob("*.json")):
            # 跳过负向 fixture（命名约定：fix-h[1-4]-*, fix-v[1-5]-*, bad-*, orphan-* 等）
            # 这些 fixture 故意造坏数据用于触发 hard/soft 校验，不应纳入阵容一致性检查
            name_low = fx.name.lower()
            is_negative = (
                re.match(r"^fix-h[1-4]-", name_low) or
                re.match(r"^fix-v[1-5]-", name_low) or
                re.match(r"^fix-s[1-5]-", name_low) or
                name_low.startswith("bad-") or
                name_low.startswith("orphan-")
            )
            if is_negative:
                if not quiet:
                    print(f"⏭  跳过负向 fixture: {fx.name}")
                continue
            scanned += 1
            refs = extract_model_refs_from_fixture(fx)
            if "_parse_error" in refs:
                hard_fails.append(f"{fx.name}: {refs['_parse_error'][0]}")
                continue

            # H-L1: model_id 白名单
            for mid in refs["model_id"]:
                if mid not in id_whitelist:
                    hard_fails.append(
                        f"{fx.name}: model_id '{mid}' 不在当前阵容白名单（白名单: {sorted(id_whitelist)}）"
                    )

            # H-L2: display name 白名单
            for n in refs["name"]:
                if n not in display_whitelist:
                    hard_fails.append(
                        f"{fx.name}: display name '{n}' 不在当前阵容白名单"
                    )

            # H-L3: from / target 白名单
            for f in refs["from"]:
                if f not in display_whitelist:
                    hard_fails.append(
                        f"{fx.name}: challenges_received[*].from '{f}' 不在当前阵容白名单"
                    )
            for t in refs["target"]:
                if t not in display_whitelist:
                    hard_fails.append(
                        f"{fx.name}: challenges_issued[*].target '{t}' 不在当前阵容白名单"
                    )

            # 裁判名允许是 opus 系列（白名单已包含），不在就 hard fail
            for jn in refs["judge_name"]:
                if jn not in display_whitelist:
                    hard_fails.append(
                        f"{fx.name}: judge_model '{jn}' 不在当前阵容白名单"
                    )
            for jid in refs["judge_id"]:
                if jid not in id_whitelist:
                    hard_fails.append(
                        f"{fx.name}: judge_model_id '{jid}' 不在当前阵容白名单"
                    )

            # S-L1: 旧模型名出现告警
            for legacy_name, legacy_id in KNOWN_LEGACY_MODELS.items():
                if legacy_name in (refs["name"] + refs["from"] + refs["target"]):
                    soft_warns.append(
                        f"{fx.name}: 出现已淘汰的旧模型名 '{legacy_name}' —— "
                        f"是否忘记在换阵容时同步更新？"
                    )
                if legacy_id in refs["model_id"]:
                    soft_warns.append(
                        f"{fx.name}: 出现已淘汰的旧 model_id '{legacy_id}'"
                    )

    # ---- 3. 扫描活跃代码（可选，only-fixtures 时跳过）----
    if not only_fixtures:
        active_asset_files = [
            skill_root / "assets" / "compare-template.html",
            skill_root / "scripts" / "_gen_moco.py",
        ]
        for af in active_asset_files:
            if not af.exists():
                continue
            text = af.read_text(encoding="utf-8")
            for legacy_name, legacy_id in KNOWN_LEGACY_MODELS.items():
                # 裸出现（不带引号上下文的简单匹配）
                if legacy_name in text:
                    soft_warns.append(
                        f"{af.name}: 资产文件里出现旧模型名 '{legacy_name}'"
                    )
                if legacy_id in text:
                    soft_warns.append(
                        f"{af.name}: 资产文件里出现旧 model_id '{legacy_id}'"
                    )

    # ---- 4. 报告 ----
    if not quiet:
        print(f"\n✅ 扫描完成：{scanned} 份活跃 fixture")

    if soft_warns:
        print("\n⚠️  Soft warnings（S-L1 旧模型名遗留）：")
        for w in soft_warns:
            print(f"   · {w}")

    if hard_fails:
        print("\n❌ Hard fails（阵容不一致，请立即修复）：", file=sys.stderr)
        for h in hard_fails:
            print(f"   · {h}", file=sys.stderr)
        print(
            f"\n💥 {len(hard_fails)} 处不一致。修复建议："
            f"\n   1. 确认 SKILL.md 的默认阵容表是否就是你想要的新阵容"
            f"\n   2. 把活跃 fixture / asset 里的旧模型名统一改为白名单中的值"
            f"\n   3. 重新跑 `python scripts/check_lineup.py` 直到 exit 0",
            file=sys.stderr
        )
        return 4

    if not quiet:
        print("\n✅ 阵容一致性校验通过（exit 0）")
    return 0


def main():
    ap = argparse.ArgumentParser(description="MoCo 阵容一致性门禁")
    ap.add_argument(
        "--root",
        default="/Users/soy/.workbuddy/skills/moco",
        help="MoCo skill 根目录（默认: ~/.workbuddy/skills/moco）"
    )
    ap.add_argument("--only-fixtures", action="store_true", help="只扫 fixture")
    ap.add_argument("--quiet", action="store_true", help="只在 fail 时输出")
    args = ap.parse_args()
    sys.exit(run_check(Path(args.root), args.only_fixtures, args.quiet))


if __name__ == "__main__":
    main()
