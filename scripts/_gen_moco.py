#!/usr/bin/env python3
"""Generate moco HTML page from 4 model answers + debate data.

Usage:
    python3 _gen_moco.py --data <path/to/debate-data.json> --output <path/to/moco-YYYYMMDD.html>

Optional:
    --template <path>   Override template path (default: ../assets/compare-template.html)
    --md2html  <path>   Override md2html.py path (default: ./md2html.py, sibling)
    --python   <path>   Python interpreter for md2html subprocess (default: current sys.executable)
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _parse_args():
    p = argparse.ArgumentParser(description="Generate moco HTML page.")
    p.add_argument("--data", help="Path to debate-data.json (required unless --update-check-only)")
    p.add_argument("--output", help="Path to write the generated HTML (required unless --update-check-only)")
    p.add_argument("--template", default=None,
                   help="Path to compare-template.html (default: <skill_root>/assets/compare-template.html)")
    p.add_argument("--md2html", default=None,
                   help="Path to md2html.py (default: ./md2html.py next to this script)")
    p.add_argument("--python", default=sys.executable,
                   help="Python interpreter to run md2html (default: current sys.executable)")
    p.add_argument("--skip-update-check", action="store_true",
                   help="Skip Pre-Run Update Check (use when offline or in regression tests).")
    p.add_argument("--update-check-only", action="store_true",
                   help="Only run update check and exit (no HTML rendering). "
                        "Exit 0 = up to date or user skipped; Exit 10 = update available; "
                        "Exit 11 = check failed (e.g. offline).")
    args = p.parse_args()
    # Post-validate: --data / --output required unless --update-check-only
    if not args.update_check_only:
        if not args.data or not args.output:
            p.error("--data and --output are required (unless --update-check-only is set).")
    return args


_ARGS = _parse_args()
_SCRIPT_DIR = Path(__file__).resolve().parent
_SKILL_ROOT = _SCRIPT_DIR.parent


# ---------------------------------------------------------------------------
# Pre-Run Update Check (走法 A：与 GitHub 远端 VERSION 对比)
# ---------------------------------------------------------------------------
# 本地版本源：<skill_root>/VERSION 文件（单行，格式 YYYY.MM.DD.N）
# 远端版本源：https://raw.githubusercontent.com/MoneyMoneyGo/moco-skill/main/VERSION
# 本函数 *只报告* 结果，不自作主张更新——是否 pull 由主智能体跟用户协商决定。
#
# 退出码（仅当 --update-check-only 时使用）：
#   0  本地 == 远端，或 --skip-update-check
#   10 远端 > 本地，需要用户决策
#   11 检查失败（离线、超时、URL 404 等） —— 此时主智能体应告警但允许继续
# ---------------------------------------------------------------------------
MOCO_VERSION_LOCAL_PATH = _SKILL_ROOT / "VERSION"
MOCO_VERSION_REMOTE_URL = "https://raw.githubusercontent.com/MoneyMoneyGo/moco-skill/main/VERSION"


def _read_local_version():
    try:
        return MOCO_VERSION_LOCAL_PATH.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None


def _fetch_remote_version(timeout=5):
    """Fetch remote VERSION with short timeout; return (version_str | None, error_str | None)."""
    import urllib.request
    import urllib.error
    try:
        req = urllib.request.Request(
            MOCO_VERSION_REMOTE_URL,
            headers={"User-Agent": "moco-update-check/1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8").strip(), None
    except urllib.error.URLError as e:
        return None, f"network error: {e.reason}"
    except Exception as e:
        return None, f"fetch failed: {e}"


def _version_tuple(v):
    """Parse 'YYYY.MM.DD.N' into a comparable tuple; returns None if malformed."""
    try:
        parts = [int(x) for x in v.strip().split(".")]
        return tuple(parts) if len(parts) >= 3 else None
    except (ValueError, AttributeError):
        return None


def check_update_gate():
    """Compare local VERSION vs remote VERSION. Returns a status dict — does NOT exit by itself.

    Caller (main flow or --update-check-only) decides what to do based on the dict.
    """
    status = {
        "local_version": _read_local_version(),
        "latest_version": None,
        "comparison": None,   # 'equal' | 'local_newer' | 'remote_newer' | 'unknown'
        "error": None,
    }
    if status["local_version"] is None:
        status["error"] = f"local VERSION file not found at {MOCO_VERSION_LOCAL_PATH}"
        status["comparison"] = "unknown"
        return status

    remote, err = _fetch_remote_version()
    if err is not None:
        status["error"] = err
        status["comparison"] = "unknown"
        return status

    status["latest_version"] = remote
    local_t = _version_tuple(status["local_version"])
    remote_t = _version_tuple(status["latest_version"])
    if local_t is None or remote_t is None:
        status["error"] = "version parse failed"
        status["comparison"] = "unknown"
        return status

    if local_t == remote_t:
        status["comparison"] = "equal"
    elif local_t > remote_t:
        status["comparison"] = "local_newer"
    else:
        status["comparison"] = "remote_newer"
    return status


def _run_update_check_and_maybe_exit():
    """Called unconditionally at script start (unless --skip-update-check).

    For normal runs: print a short notice to stderr, never block.
    For --update-check-only: exit with the structured code.
    """
    if _ARGS.skip_update_check:
        if _ARGS.update_check_only:
            sys.stderr.write("(update check skipped by --skip-update-check)\n")
            sys.exit(0)
        return

    status = check_update_gate()
    # Render a concise one-line report to stderr (always visible to orchestrator)
    if status["comparison"] == "equal":
        msg = f"✓ moco up to date (v{status['local_version']})"
    elif status["comparison"] == "remote_newer":
        msg = (
            f"⚠ moco update available: local v{status['local_version']} → "
            f"remote v{status['latest_version']}. "
            f"See https://github.com/MoneyMoneyGo/moco-skill/blob/main/CHANGELOG.md"
        )
    elif status["comparison"] == "local_newer":
        msg = (
            f"ℹ moco local v{status['local_version']} is newer than remote "
            f"v{status['latest_version']} (unreleased work?). Continuing."
        )
    else:
        msg = (
            f"⚠ moco update check failed: {status['error']}. "
            f"Local v{status['local_version']}. Continuing offline."
        )
    sys.stderr.write(msg + "\n")

    if _ARGS.update_check_only:
        code = {
            "equal":        0,
            "remote_newer": 10,
            "local_newer":  0,
            "unknown":      11,
        }[status["comparison"]]
        sys.exit(code)


_run_update_check_and_maybe_exit()
# ---------------------------------------------------------------------------

TEMPLATE_PATH = str(Path(_ARGS.template) if _ARGS.template else _SKILL_ROOT / "assets" / "compare-template.html")
MD2HTML = str(Path(_ARGS.md2html) if _ARGS.md2html else _SCRIPT_DIR / "md2html.py")
DEBATE_DATA = str(Path(_ARGS.data))
OUTPUT_PATH = str(Path(_ARGS.output))
MANAGED_PYTHON = _ARGS.python

# Sanity checks
for _label, _path in (("template", TEMPLATE_PATH), ("md2html", MD2HTML), ("data", DEBATE_DATA)):
    if not Path(_path).exists():
        sys.stderr.write(f"ERROR: {_label} not found: {_path}\n")
        sys.exit(2)

# Ensure output directory exists
Path(OUTPUT_PATH).parent.mkdir(parents=True, exist_ok=True)

# Load debate data from external JSON
with open(DEBATE_DATA, "r", encoding="utf-8") as f:
    DATA = json.load(f)


# ---------------------------------------------------------------------------
# validate_debate_data — schema 与运行时硬校验（银纸 2026-04-27 决定下沉到代码）
#
# 设计原则：
#   - 严格卡死真错误（占位模型、Round1 model_id 重复、judge 与参战重叠、verdict 缺失）
#     → 直接 sys.exit(3)，HTML 不生成。
#   - 软告警可疑现象（utc 同步水印、缺 utc/model_id、缺 run_start/run_end）
#     → stderr 打印 ⚠ 但继续执行。
#   - 对历史数据兼容：缺失新增字段（model_id / utc / run_start/end）只告警不阻断。
#
# 失败时退出码：
#   3 = pre-flight hard fail
#   2 = file not found（已有逻辑）
# ---------------------------------------------------------------------------
FORBIDDEN_MODEL_IDS = {"default", "lite", "reasoning", ""}
VALID_VISION_MODES = {"r1_only", "none"}  # 银纸 2026-04-27 19:51 决定砍 full（CHANGELOG 2026.04.27.4）


def _hard_fail(msg):
    sys.stderr.write(f"\n❌ moco validation failed:\n   {msg}\n\n")
    sys.exit(3)


def _warn(msg):
    sys.stderr.write(f"⚠ moco warn: {msg}\n")


def validate_debate_data(data):
    """Validate debate-data.json before rendering.

    Hard checks (exit 3):
      H1. Each model.model_id NOT in FORBIDDEN_MODEL_IDS (if present)
      H2. Round 1 model_ids deduped count == len(models) (if model_id present)
      H3. judge_model_id (per verdict) NOT in lineup model_ids (if both present)
      H4. Every challenges_received[*] with a non-null rebuttal MUST have a verdict
          object containing winner ∈ {"challenge","rebuttal","draw"}.

    Soft checks (warn):
      S1. Missing model_id field on any model → can't enforce H1/H2/H3.
      S2. Missing utc field on any model.
      S3. Round 1 utc values fully identical (sync watermark).
      S4. Top-level run_start / run_end missing.
    """
    models = data.get("models", [])
    if not isinstance(models, list) or not models:
        _hard_fail("debate-data.json must contain a non-empty 'models' list.")

    # ----- Soft S1/S2: collect model_ids and utcs, warn if missing -----
    model_ids = []
    utcs = []
    missing_model_id = []
    missing_utc = []
    for m in models:
        mid = m.get("model_id")
        if mid is None:
            missing_model_id.append(m.get("name", "<unnamed>"))
        else:
            model_ids.append(mid)
        u = m.get("utc")
        if u is None:
            missing_utc.append(m.get("name", "<unnamed>"))
        else:
            utcs.append(u)

    if missing_model_id:
        _warn(f"S1 missing model_id on: {missing_model_id} — skipping H1/H2/H3 enforcement for those.")
    if missing_utc:
        _warn(f"S2 missing utc on: {missing_utc}")

    # ----- Hard H1: forbidden placeholder model IDs -----
    bad = [mid for mid in model_ids if mid in FORBIDDEN_MODEL_IDS]
    if bad:
        _hard_fail(
            f"H1 forbidden placeholder model_id detected: {bad}. "
            f"moco requires real provider model IDs (e.g. 'claude-sonnet-4.6-1m'), "
            f"not 'default/lite/reasoning'."
        )

    # ----- Hard H2: Round 1 model_ids must be unique -----
    if model_ids and len(set(model_ids)) < len(model_ids):
        from collections import Counter
        dup = [mid for mid, n in Counter(model_ids).items() if n > 1]
        _hard_fail(
            f"H2 Round 1 model_ids must be distinct, but duplicates found: {dup}. "
            f"全部 {len(model_ids)} 路 → 去重后只剩 {len(set(model_ids))} 路。"
        )

    # ----- Hard H3: judge model must NOT be one of the lineup -----
    judge_ids = set()
    for m in models:
        for rc in m.get("challenges_received", []) or []:
            v = rc.get("verdict") or {}
            jid = v.get("judge_model_id")
            if jid:
                judge_ids.add(jid)
    overlap = judge_ids & set(model_ids)
    if overlap:
        _hard_fail(
            f"H3 judge model overlaps with lineup: {overlap}. "
            f"裁判必须是参战 4 家之外的独立模型，否则无法对自己参与过的 clash 中立评判。"
        )

    # ----- Hard H4: every (challenge + rebuttal) clash MUST have a verdict -----
    missing_verdicts = []
    bad_winners = []
    for m in models:
        for rc in m.get("challenges_received", []) or []:
            has_rebuttal = bool(rc.get("rebuttal"))
            v = rc.get("verdict")
            if has_rebuttal and not v:
                missing_verdicts.append(
                    f"{rc.get('from', '?')} → {m.get('name', '?')}"
                )
            elif v and v.get("winner") not in {"challenge", "rebuttal", "draw"}:
                bad_winners.append(
                    f"{rc.get('from', '?')} → {m.get('name', '?')}: "
                    f"winner={v.get('winner')!r}"
                )
    if missing_verdicts:
        _hard_fail(
            f"H4 missing verdict on these clashes (challenge+rebuttal exist but no judge ruling): "
            f"{missing_verdicts}"
        )
    if bad_winners:
        _hard_fail(
            f"H4 invalid verdict.winner value (must be 'challenge'|'rebuttal'|'draw'): "
            f"{bad_winners}"
        )

    # ----- Soft S3: utc sync watermark -----
    if len(utcs) >= 2 and len(set(utcs)) == 1:
        _warn(
            f"S3 utc-sync-watermark: all {len(utcs)} models reported identical utc='{utcs[0]}'. "
            f"This means the utc field was likely fabricated or copied from the prompt example. "
            f"Sub-agents must run `date -u` themselves; current data is NOT audit-grade."
        )

    # ----- Soft S4: run_start / run_end on top -----
    if not data.get("run_start"):
        _warn("S4 missing top-level 'run_start' (ISO 8601 UTC of orchestration start).")
    if not data.get("run_end"):
        _warn("S4 missing top-level 'run_end' (ISO 8601 UTC of orchestration end).")

    # =========================================================================
    # V1-V5: vision (multimodal) hard checks — 银纸 2026-04-27 18:32 锁定
    # 仅当顶层声明 vision_mode 字段（即"显式进入多模态模式"）时启用 V1-V5。
    # 旧的纯文本 debate-data.json（无 vision_mode 字段）跳过 vision 校验，向后兼容。
    # =========================================================================
    vision_mode = data.get("vision_mode")
    image_paths = data.get("question_image_paths") or []

    # 启用条件：声明了 vision_mode 字段 OR 给了图片路径
    vision_active = (vision_mode is not None) or bool(image_paths)

    if vision_active:
        # ----- Hard V1: vision_mode 取值合法 -----
        if vision_mode not in VALID_VISION_MODES:
            _hard_fail(
                f"V1 invalid vision_mode={vision_mode!r}. "
                f"Must be one of {sorted(VALID_VISION_MODES)}. "
                f"Note: 'full' was removed at v2026.04.27.4 (use r1_only + needs_image_for_rebuttal "
                f"for image-dispute clashes); 'smart' was never implemented."
            )

        # ----- Hard V2: 有图必须开 vision 模式 -----
        if image_paths and vision_mode == "none":
            _hard_fail(
                f"V2 question_image_paths is non-empty ({len(image_paths)} 张图) "
                f"but vision_mode='none'. 有图就必须开 full 或 r1_only。"
            )

        # ----- Hard V3: 有图模式下，4 家 image_seen 必须全部为 true -----
        # 这是硬约束 B 的代码层兜底：缺字段或任一家未看到，整场都不可信。
        if image_paths and vision_mode == "r1_only":
            missing_image_seen = []
            not_seen = []
            for m in models:
                if "image_seen" not in m:
                    missing_image_seen.append(m.get("name", "<unnamed>"))
                elif m.get("image_seen") is not True:
                    not_seen.append(
                        f"{m.get('name', '<unnamed>')}={m.get('image_seen')!r}"
                    )
            if missing_image_seen:
                _hard_fail(
                    f"V3 missing image_seen field on: {missing_image_seen}. "
                    f"vision_mode={vision_mode} 下每家 model 必须显式声明 image_seen (true/false)。"
                )
            if not_seen:
                _hard_fail(
                    f"V3 not all models reported image_seen=true: {not_seen}. "
                    f"任何一家未看到原图，整场 moco 都失去了'真多模态'意义，HTML 不生成。"
                )

        # ----- Hard V4: R3 image_attached_for_rebuttal 必须有 R2 needs_image flag 支撑 -----
        # 防止"反驳偷偷加图"事故：只有挑战方在 R2 显式声明 needs_image_for_rebuttal=true，
        # R3 反驳才允许 image_attached_for_rebuttal=true。
        v4_violations = []
        for m in models:
            for rc in m.get("challenges_received", []) or []:
                attached = rc.get("image_attached_for_rebuttal", False)
                needs = rc.get("needs_image_for_rebuttal", False)
                if attached and not needs:
                    v4_violations.append(
                        f"{rc.get('from', '?')} → {m.get('name', '?')}: "
                        f"R3 attached image but R2 did not declare needs_image_for_rebuttal=true"
                    )
        if v4_violations:
            _hard_fail(f"V4 unauthorized image attachment in rebuttals: {v4_violations}")

        # ----- Hard V5: r1_only 模式下若 needs_image_for_rebuttal=true 必须真的回传 -----
        # 防止"声明了需要图但实际没传"的半截事故。
        if vision_mode == "r1_only":
            v5_violations = []
            for m in models:
                for rc in m.get("challenges_received", []) or []:
                    needs = rc.get("needs_image_for_rebuttal", False)
                    attached = rc.get("image_attached_for_rebuttal", False)
                    if needs and not attached:
                        v5_violations.append(
                            f"{rc.get('from', '?')} → {m.get('name', '?')}: "
                            f"R2 needs_image_for_rebuttal=true but R3 image_attached_for_rebuttal=false"
                        )
            if v5_violations:
                _hard_fail(
                    f"V5 r1_only mode: declared image-dispute clashes did not actually re-attach image: "
                    f"{v5_violations}"
                )

    # ----- Pass -----
    sys.stderr.write(
        f"✓ moco validation passed: {len(models)} models, "
        f"{sum(len(m.get('challenges_received') or []) for m in models)} clashes verified.\n"
    )


validate_debate_data(DATA)
# ---------------------------------------------------------------------------

QUESTION = DATA["question"]
TIMESTAMP = DATA["timestamp"]
MODELS = DATA["models"]
WINNER_MODEL = DATA["winner_model"]
# winner_reason 拆成两段：compare 模式只看答案质量，debate 模式才呈现辩论表现。
# 兼容旧数据：若新字段缺失，fallback 到老 winner_reason 单字段（两个 mode 显示同样文字）。
_LEGACY_REASON = DATA.get("winner_reason", "")
WINNER_REASON_COMPARE = DATA.get("winner_reason_compare") or _LEGACY_REASON
WINNER_REASON_DEBATE = DATA.get("winner_reason_debate") or _LEGACY_REASON

# vision 字段（v1 多模态加固字段）
VISION_MODE = DATA.get("vision_mode")  # None = 旧数据/纯文本场景
QUESTION_IMAGE_PATHS = DATA.get("question_image_paths") or []


def md_to_html(md_text):
    """Convert markdown to HTML using the md2html script."""
    result = subprocess.run(
        [MANAGED_PYTHON, MD2HTML, "--text", md_text],
        capture_output=True, text=True, timeout=30
    )
    return result.stdout.strip()


def build_roster():
    items = []
    for m in MODELS:
        items.append(
            f'<div class="roster-item">'
            f'<span class="roster-dot" style="background:{m["color"]}"></span>'
            f'{m["name"]}'
            f'</div>'
        )
    return "\n".join(items)


def build_vision_header():
    """硬约束 B 渲染：原图缩略图 + vision_mode 标签 + 4 家 image_seen 状态。

    渲染策略：
    - 旧数据（无 vision_mode 字段且无 question_image_paths）→ 返回空字符串，不破坏布局。
    - vision_mode=none 但又没图 → 也返回空字符串。
    - 否则渲染完整的 vision-header strip。
    """
    if not VISION_MODE and not QUESTION_IMAGE_PATHS:
        return ""
    if VISION_MODE == "none" and not QUESTION_IMAGE_PATHS:
        return ""

    # 缩略图：用 file:// 相对路径直接引用本地图（HTML 在工作区，图也在工作区）
    thumbs_html = ""
    if QUESTION_IMAGE_PATHS:
        thumb_imgs = []
        for p in QUESTION_IMAGE_PATHS:
            # 提取 basename，让 HTML 用相对路径加载（前提是 HTML 与图同目录或子目录可访问）
            from pathlib import Path as _P
            rel = _P(p).name
            esc = html_escape(rel)
            full_esc = html_escape(p)
            thumb_imgs.append(
                f'<a href="{full_esc}" target="_blank" rel="noopener" title="点击查看原图">'
                f'<img class="vision-header-thumb" src="{full_esc}" alt="原始问题图：{esc}" />'
                f'</a>'
            )
        thumbs_html = (
            f'<div class="vision-header-thumbs">'
            f'<span class="vision-header-label">输入</span>'
            + "".join(thumb_imgs)
            + '</div>'
        )

    # vision_mode 标签
    mode = VISION_MODE or "none"
    mode_label_map = {
        "r1_only": "R1_ONLY · 仅首轮带图",
        "none":    "NONE · 纯文本",
    }
    mode_html = (
        f'<span class="vision-header-label">vision_mode</span>'
        f'<span class="vision-header-mode vision-header-mode--{mode}">'
        f'{mode_label_map.get(mode, mode)}'
        f'</span>'
    )

    # image_seen 状态：4 家逐一渲染 ✓/✗ 符号
    seen_items = []
    for m in MODELS:
        name = m.get("name", "?")
        seen = m.get("image_seen")
        if seen is True:
            sym = '<span class="ok">✓</span>'
        elif seen is False:
            sym = '<span class="ng">✗</span>'
        else:
            sym = '<span class="ng">?</span>'
        seen_items.append(
            f'<span class="vision-header-seen-item">{sym} {html_escape(name)}</span>'
        )
    seen_html = (
        f'<div class="vision-header-seen">'
        f'<span class="vision-header-label">各家所见</span>'
        + "".join(seen_items)
        + '</div>'
    )

    return (
        f'<div class="vision-header">'
        f'{thumbs_html}'
        f'<div class="vision-header-mode-wrap">{mode_html}</div>'
        f'{seen_html}'
        f'</div>'
    )


def build_debate_summary():
    """渲染 debate-summary 横条。
    结构：.debate-summary > .debate-summary-icon + .debate-summary-text
    核心：不仅 sum up "谁打了谁"，还要给出"战果"——读者要的是判决，不是动作列表。
    文案 = 格局骨架（围攻/对攻/一言堂/连锁）+ 战果叙事（由 verdict 判决驱动）。
    """
    # 汇总所有挑战边 (challenger, target)
    edges = []
    for m in MODELS:
        for c in m.get("challenges_issued", []):
            edges.append((m["name"], c["target"]))
    total = len(edges)

    if total == 0:
        return (
            '<div class="debate-summary">'
            '<span class="debate-summary-icon">🤝</span>'
            '<span class="debate-summary-text"><strong>辩论结果：</strong>'
            f'{len(MODELS)} 家互相审阅后一致认可，无人出手</span>'
            '</div>'
        )

    # 构建 (challenger, target) -> winner 映射
    # target 的 challenges_received[from=challenger].verdict.winner
    verdict_map = {}
    for m in MODELS:
        for c in m.get("challenges_received", []):
            frm = c.get("from")
            v = c.get("verdict") or {}
            w = v.get("winner")  # challenge | rebuttal | draw
            if frm and w:
                verdict_map[(frm, m["name"])] = w

    def verdict_of(a, b):
        """战果视角：挑战者 a 对 b 这场——返回 challenge/rebuttal/draw/unknown。"""
        return verdict_map.get((a, b), "unknown")

    # 统计入度 / 出度
    in_deg = {}
    out_deg = {}
    for a, b in edges:
        out_deg[a] = out_deg.get(a, 0) + 1
        in_deg[b] = in_deg.get(b, 0) + 1
    edge_set = set(edges)

    hot_target, hot_in = max(in_deg.items(), key=lambda kv: kv[1])
    challengers = sorted({a for a, _ in edges})

    # ===== 格局 + 战果 =====
    if hot_in >= 2:
        # 围攻：统计 hot_target 作为防守方的战绩
        incoming = [(a, hot_target) for a, b in edges if b == hot_target]
        results = [verdict_of(a, b) for a, b in incoming]
        atk_win = results.count("challenge")
        def_win = results.count("rebuttal")
        draws = results.count("draw")
        siege_count = len(incoming)

        # 战果叙事：从围攻方视角描述 hot_target 的处境
        verdict_text = _siege_verdict(hot_target, atk_win, def_win, draws, siege_count)

        summary = (
            f"{_pretty_count(siege_count)}围攻 <strong>{hot_target}</strong>，"
            f"{verdict_text}"
        )

        # 回手段去除：原本的"；反手挑 Y 未能得手"和下方辩论面板的"展开/收起"动作
        # 在读感上容易混淆（动词"挑/回怼"和交互"展开/收起"），摘要横条聚焦核心格局
        # 与战果即可，回手的具体胜负会在对应 clash 里呈现。

    elif any((b, a) in edge_set for a, b in edges):
        # 对攻：双向边
        pair = next((a, b) for a, b in edges if (b, a) in edge_set and a < b)
        a, b = pair
        r1 = verdict_of(a, b)  # a 挑 b
        r2 = verdict_of(b, a)  # b 挑 a
        verdict_text = _clash_verdict(a, b, r1, r2)
        summary = f"<strong>{a}</strong> 与 <strong>{b}</strong> 正面互掐，{verdict_text}"
        others = sorted({c for c, _ in edges} - {a, b})
        if others:
            summary += f"（{('、'.join(others))} 在旁敲边鼓）"

    elif len(challengers) == 1:
        # 一言堂
        lone = challengers[0]
        lone_edges = [(a, b) for a, b in edges if a == lone]
        results = [verdict_of(a, b) for a, b in lone_edges]
        hit = results.count("challenge")
        miss = results.count("rebuttal")
        draw = results.count("draw")
        verdict_text = _solo_verdict(hit, miss, draw, len(lone_edges))
        summary = (
            f"仅 <strong>{lone}</strong> 出手，{verdict_text}，其余按兵不动"
        )

    else:
        # 连锁：每家各打一场，没有焦点
        results = [verdict_of(a, b) for a, b in edges]
        hit = results.count("challenge")
        miss = results.count("rebuttal")
        draw = results.count("draw")
        verdict_text = _chain_verdict(hit, miss, draw, len(edges))
        summary = (
            f"{('、'.join(challengers))} 多线开火，{verdict_text}"
        )

    return (
        '<div class="debate-summary">'
        '<span class="debate-summary-icon">⚔️</span>'
        '<span class="debate-summary-text">'
        f'<strong>辩论结果：</strong>{summary}'
        '</span>'
        '</div>'
    )


def _siege_verdict(target, atk_win, def_win, draws, total):
    """围攻战果：atk_win=挑战方赢的场次, def_win=target 守住的场次, draws=平局数。
    从 target（防守方）视角叙事更自然。"""
    # 所有场次一边倒
    if atk_win == total:
        return f"{target} 全面落败"
    if def_win == total:
        return f"{target} 逐一化解"
    if draws == total:
        return f"各有道理、未分胜负"
    # 混合：用实际动作词而非数字
    parts = []
    if def_win:
        parts.append(f"守住 {def_win} 场")
    if draws:
        parts.append(f"打平 {draws} 场")
    if atk_win:
        parts.append(f"失守 {atk_win} 场")
    return f"{target} " + "、".join(parts)


def _counter_verdict(actor, targets, win, lost, draw):
    """回手战果：actor 反挑 targets 的结果。"""
    tgt_str = "、".join(f"<strong>{t}</strong>" for t in targets)
    if win and not lost and not draw:
        return f"反手挑 {tgt_str} 成功得手"
    if lost and not win and not draw:
        return f"反手挑 {tgt_str} 未能得手"
    if draw and not win and not lost:
        return f"反手挑 {tgt_str} 打成平手"
    # 混合
    return f"反手挑 {tgt_str} 互有胜负"


def _clash_verdict(a, b, r1, r2):
    """对攻战果：r1=a挑b结果, r2=b挑a结果。"""
    # a 赢场数
    a_score = (1 if r1 == "challenge" else 0) + (1 if r2 == "rebuttal" else 0)
    b_score = (1 if r2 == "challenge" else 0) + (1 if r1 == "rebuttal" else 0)
    if a_score > b_score:
        return f"<strong>{a}</strong> 占上风"
    if b_score > a_score:
        return f"<strong>{b}</strong> 占上风"
    return "打成平手"


def _solo_verdict(hit, miss, draw, total):
    if hit == total:
        return f"全部命中"
    if miss == total:
        return f"全被驳回"
    if draw == total:
        return f"均未定论"
    parts = []
    if hit:
        parts.append(f"{hit} 发命中")
    if miss:
        parts.append(f"{miss} 发被驳回")
    if draw:
        parts.append(f"{draw} 发打平")
    return "、".join(parts)


def _chain_verdict(hit, miss, draw, total):
    if hit > miss and hit >= draw:
        return "挑战方整体占优"
    if miss > hit and miss >= draw:
        return "防守方整体占优"
    return "胜负交错、未见单边压制"


def _pretty_count(n):
    """数字转中文量词：2→两家、3→三家、4→四家、其他→N 家。
    口语化，避免"2 家围攻"这种别扭读法。"""
    return {2: "两家", 3: "三家", 4: "四家", 5: "五家"}.get(n, f"{n} 家")


def html_escape(text):
    """Escape HTML special chars."""
    return (text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;"))


def md_to_html_safe(md_text):
    """Convert markdown to HTML, returns escaped fallback on failure."""
    try:
        result = md_to_html(md_text)
        return result if result else f"<p>{html_escape(md_text)}</p>"
    except Exception:
        return f"<p>{html_escape(md_text)}</p>"


def truncate(text, max_len=120):
    """Truncate text to max_len chars, adding ... if cut."""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[:max_len-3].rstrip("，。！？、；：\n ") + "…"


def strip_markdown(text):
    """Strip common markdown syntax (inline + structural) for plain-text display."""
    import re
    if not text:
        return ""
    # # headings (structural — must strip first)
    text = re.sub(r'^#{1,6}\s+', '', text)
    text = re.sub(r'\s+#{1,6}\s+', ' ', text)
    # - list markers and numbered lists
    text = re.sub(r'^[-*+]\s+', '', text)
    text = re.sub(r'^\d+\.\s+', '', text)
    # > blockquotes
    text = re.sub(r'^>?\s?', '', text)
    # **bold**, *italic*, __underline__, ~~strikethrough~~
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'~~([^~]+)~~', r'\1', text)
    # `code`
    text = re.sub(r'`([^`]+)`', r'\1', text)
    # [text](url) → text
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # ![alt](url) → [图片]
    text = re.sub(r'!\[([^\]]*)\]\([^)]+\)', '[图片]', text)
    return text


def condense_answer(raw_text, max_chars=380):
    """Condense a long answer into key insights (~max_chars), preserving structure."""
    lines = raw_text.strip().split('\n')
    insights = []
    for line in lines:
        line = line.strip()
        # 跳过空行 / heading / 代码围栏 / 表格分隔行 / 表格内容行
        if (not line
                or line.startswith(('#', '```', '|---'))
                or line == '|'
                or (line.startswith('|') and '---' not in line)):
            continue
        # Keep content paragraphs and list items
        if len(line) >= 15:
            clean = strip_markdown(line)
            if len(clean) >= 15:
                insights.append(clean)
        if sum(len(s) for s in insights) >= max_chars:
            break

    if not insights:
        # Fallback: clean every line and join
        cleaned_lines = []
        for line in raw_text.strip().split('\n'):
            line = line.strip()
            if not line or line.startswith('```'):
                continue
            cleaned = strip_markdown(line)
            if len(cleaned) >= 8:
                cleaned_lines.append(cleaned)
        if cleaned_lines:
            combined = ' '.join(cleaned_lines)
            return truncate(combined, max_chars)
        return strip_markdown(truncate(raw_text.replace('\n', ' '), max_chars))

    result = []
    total = 0
    for s in insights:
        if total + len(s) > max_chars + 60:
            break
        result.append(s)
        total += len(s)

    text = '\n\n'.join(result)
    if len(text) > max_chars + 80:
        text = truncate(text, max_chars + 80)
    return text


def _make_summary(raw_text, provided_summary="", max_chars=80):
    """Produce a short one-liner summary for preview boxes.
    Priority: provided_summary > first sentence of stripped raw_text > truncated raw_text.
    """
    if provided_summary and provided_summary.strip():
        return truncate(strip_markdown(provided_summary.strip()), max_chars)
    if not raw_text or not raw_text.strip():
        return ""
    # Take first substantive sentence / line
    plain = strip_markdown(raw_text.strip())
    # Split on Chinese/English sentence terminators
    import re
    parts = re.split(r'(?<=[。！？!?])\s+', plain.replace('\n', ' '))
    first = parts[0] if parts else plain
    if len(first) < 15 and len(parts) > 1:
        # First fragment too short, merge with next
        first = first + parts[1]
    return truncate(first, max_chars)


def _render_verdict_preview(verdict, judge_name=""):
    """Render a compact verdict line in preview mode.
    设计：
    - 红/蓝卡内已由「胜」胶囊标明胜方（两边都没胶囊 = 平局）
    - 因此这里不再重复挂"挑战方胜出"tag；只保留判词摘要
    - 前缀 `🎯 裁判 · {judge_name}：` 强化"第 5 方中立裁判"身份
    """
    if not verdict or not isinstance(verdict, dict):
        return ""
    reasoning = verdict.get("reasoning", "")
    reasoning_short = truncate(strip_markdown(reasoning), 70) if reasoning else ""
    if not reasoning_short:
        return ""

    judge = judge_name or verdict.get("judge_model", "") or ""
    prefix_html = (
        f'<span class="debate-verdict-prefix">'
        f'<span class="debate-verdict-prefix-icon">🎯</span>'
        f'裁判 · <strong>{html_escape(judge)}</strong>：'
        f'</span>'
    ) if judge else ''

    return (
        '<div class="debate-verdict-preview">'
        f'{prefix_html}'
        f'<span class="debate-verdict-summary">{html_escape(reasoning_short)}</span>'
        '</div>'
    )


def _render_verdict_full(verdict, judge_name=""):
    """Render the judge's full reasoning in expanded view.
    同预览：不再重复"挑战方胜出"tag（胜方已挂在红/蓝块角），
    只用 `🎯 裁判 · {judge_name}：` 前缀 + 完整判词。
    展开态是深度信息区，保留得分数字 `红分 : 蓝分`，用户点开就是想看细节。
    """
    if not verdict or not isinstance(verdict, dict):
        return ""
    reasoning = verdict.get("reasoning", "")
    if not reasoning:
        return ""

    judge = judge_name or verdict.get("judge_model", "") or ""

    # 得分（仅展开态保留，预览态已精简掉）
    # 设计：不做"比分牌"（胶囊+冒号=体育赛果，与"裁判判词"的司法感错位），
    # 改为 header 右侧的 inline meta 文字："说服力  挑战方 9 / 反驳方 7"。
    # 三个细节都是为了消除"挑战 9"被读成"挑战了 9 次"的歧义：
    #   - 前缀"说服力"点明这是**对辩论内容的打分**，不是次数/动作
    #   - "挑战方 / 反驳方"（带"方"）是名词，不会被读成动词
    #   - 分隔符用 / 而非 ·，明确是并列评分对照
    # 胜负由红/蓝块上的「胜」胶囊表达；这里的数字是"判罚依据"，应冷静。
    sc = verdict.get("score_challenge")
    sr = verdict.get("score_rebuttal")
    score_html = ""
    if isinstance(sc, (int, float)) and isinstance(sr, (int, float)):
        score_html = (
            f'<span class="debate-verdict-score">'
            f'<span class="debate-verdict-score-label">说服力</span>'
            f'<span class="debate-verdict-score-item debate-verdict-score-item--challenge">'
            f'挑战方 <span class="debate-verdict-score-num">{sc}</span>'
            f'</span>'
            f'<span class="debate-verdict-score-sep">/</span>'
            f'<span class="debate-verdict-score-item debate-verdict-score-item--rebuttal">'
            f'反驳方 <span class="debate-verdict-score-num">{sr}</span>'
            f'</span>'
            f'</span>'
        )

    header_html = (
        f'<div class="debate-verdict-full-header">'
        f'<span class="debate-verdict-prefix-icon">🎯</span>'
        f'<span>裁判 · <strong>{html_escape(judge)}</strong></span>'
        f'{score_html}'
        f'</div>'
    ) if judge else ''

    return (
        '<div class="debate-verdict-full">'
        f'{header_html}'
        f'<div class="debate-verdict-full-body">{md_to_html_safe(reasoning)}</div>'
        '</div>'
    )


def _render_winner_pill(role):
    """把「胜」胶囊挂在原先"得分 N"的位置（块 header 右侧）。
    role: 'challenge' | 'rebuttal'
    平局两边都不挂，读者自然推断出是平局。
    """
    return f'<span class="debate-winner-pill debate-winner-pill--{role}">胜</span>'


def _render_debate_item(challenger_name, defender_name,
                        challenge_reason, challenge_detail, challenge_summary,
                        rebuttal_body, rebuttal_summary, verdict,
                        judge_name=""):
    """Render ONE debate-item.
    Preview:
      红蓝左右两栏（延续对攻感）→ header 右侧挂「胜」胶囊（平局两边都没）
      → 下方一行：🎯 裁判 · XX：判词摘要
    Expanded (上下堆叠，人类阅读习惯)：
      挑战方完整观点 → 反驳完整观点 → 裁判完整判词
    """
    # Preview summaries
    _ch_summary_text = _make_summary(challenge_detail or challenge_reason,
                                     provided_summary=challenge_summary,
                                     max_chars=90)
    _rb_summary_text = _make_summary(rebuttal_body,
                                     provided_summary=rebuttal_summary,
                                     max_chars=90)
    _ch_summary_html = html_escape(_ch_summary_text) if _ch_summary_text else '<em style="color:var(--text-light)">（未提供要点）</em>'
    _rb_summary_html = html_escape(_rb_summary_text) if _rb_summary_text else '<em style="color:var(--text-light)">（未反驳）</em>'

    # Full content
    _ch_detail_html = md_to_html_safe(challenge_detail) if challenge_detail else f'<p>{html_escape(challenge_reason)}</p>'
    _rb_body_html = md_to_html_safe(rebuttal_body) if rebuttal_body else '<p><em>（被挑战方未反驳）</em></p>'
    _rb_reason_html = (
        html_escape(strip_markdown(rebuttal_summary))
        if rebuttal_summary
        else '<em style="color:var(--text-light)">（未提供反驳要点）</em>'
    )

    # Winner pill (only the winner gets one; draw = neither side)
    _winner = (verdict or {}).get("winner", "")
    _ch_pill = _render_winner_pill("challenge") if _winner == "challenge" else ""
    _rb_pill = _render_winner_pill("rebuttal") if _winner == "rebuttal" else ""

    _verdict_preview_html = _render_verdict_preview(verdict, judge_name)
    _verdict_full_html = _render_verdict_full(verdict, judge_name)

    return (
        '<div class="debate-item">'
        # ---------- PREVIEW ----------
        '<div class="debate-clash-preview">'
        '<div class="debate-clash-grid">'
        # 红方 (挑战方 · XXX)
        '<div class="debate-clash-cell debate-clash-cell--challenge">'
        '<div class="debate-clash-cell-header">'
        '<span class="debate-clash-icon">→</span>'
        f'<span class="debate-clash-role">挑战方 · <strong>{html_escape(challenger_name)}</strong></span>'
        f'{_ch_pill}'
        '</div>'
        f'<div class="debate-clash-summary">{_ch_summary_html}</div>'
        '</div>'
        # 蓝方 (反驳 · 卡主，不重复写名，卡主名已在卡头)
        '<div class="debate-clash-cell debate-clash-cell--rebuttal">'
        '<div class="debate-clash-cell-header">'
        '<span class="debate-clash-icon">↩</span>'
        '<span class="debate-clash-role">反驳</span>'
        f'{_rb_pill}'
        '</div>'
        f'<div class="debate-clash-summary">{_rb_summary_html}</div>'
        '</div>'
        '</div>'
        f'{_verdict_preview_html}'
        '<div class="debate-expand-trigger">查看完整观点</div>'
        '</div>'
        # ---------- EXPANDED (上下堆叠：挑战完整 → 反驳完整 → 裁判判词) ----------
        '<div class="debate-clash-full">'
        # 挑战完整
        '<div class="debate-clash-full-block debate-clash-full-block--challenge">'
        '<div class="debate-clash-full-header">'
        '<span class="debate-clash-icon">→</span>'
        f'<span class="debate-clash-role">挑战方 · <strong>{html_escape(challenger_name)}</strong></span>'
        f'{_ch_pill}'
        '</div>'
        f'<div class="debate-clash-full-reason">{html_escape(strip_markdown(challenge_reason))}</div>'
        f'<div class="debate-clash-full-body">{_ch_detail_html}</div>'
        '</div>'
        # 反驳完整
        '<div class="debate-clash-full-block debate-clash-full-block--rebuttal">'
        '<div class="debate-clash-full-header">'
        '<span class="debate-clash-icon">↩</span>'
        '<span class="debate-clash-role">反驳</span>'
        f'{_rb_pill}'
        '</div>'
        f'<div class="debate-clash-full-reason">{_rb_reason_html}</div>'
        f'<div class="debate-clash-full-body">{_rb_body_html}</div>'
        '</div>'
        # 裁判判词
        f'{_verdict_full_html}'
        '</div>'
        '</div>'
    )


def _build_debate_records():
    """Build per-model "观点战绩" records for the sidebar record strip.

    视角：副卡的主语是"这个模型的观点"，所以战绩条只统计**这个观点被挑战了多少次、
    每次的胜负如何**。模型主动出去挑战别人的记录**不计入**自己的副卡——那是
    别人副卡的上下文。

    Returns: {model_name: {"challenged": int, "upheld": int, "draws": int, "outcomes": list[str]}}
      - challenged: 这条观点被挑战的总次数（全貌）
      - upheld:    这些挑战里被裁判判定"成立"的次数（可信度降低的证据）
      - draws:     这些挑战里被裁判判定"打和"的次数（悬置，双方各执一词）
      - outcomes:  按 challenges_received 顺序记录的逐次结果，用于格子条按场染色：
                   "lose" = 挑战成立（观点被攻破）
                   "win"  = 挑战被扛住（观点站住）
                   "tie"  = 打和

    Verdict 存储规则：A 挑战 B → verdict 在 B.challenges_received[from=A].verdict 里
    - winner == "challenge" → 挑战成立 → upheld += 1, outcomes += "lose"
    - winner == "rebuttal"  → 反驳扛住 → outcomes += "win"
    - winner == "draw"      → 打和    → draws += 1,  outcomes += "tie"
    - winner 缺失           → 视为 "win"（保守地按"扛住"处理，避免误标红）
    """
    records = {
        m["name"]: {"challenged": 0, "upheld": 0, "draws": 0, "outcomes": []}
        for m in MODELS
    }

    for defender in MODELS:
        for rc in defender.get("challenges_received", []):
            verdict = rc.get("verdict") or {}
            winner = verdict.get("winner", "")
            rec = records[defender["name"]]
            rec["challenged"] += 1
            if winner == "challenge":
                rec["upheld"] += 1
                rec["outcomes"].append("lose")
            elif winner == "draw":
                rec["draws"] += 1
                rec["outcomes"].append("tie")
            else:
                # rebuttal 或缺失：算作扛住
                rec["outcomes"].append("win")

    return records


def _render_debate_stat_inline(record):
    """渲染一段"战绩信息条" — 用于主卡辩论面板 header 和副卡战绩条共享同一信息。

    输出结构：[ N 次挑战 · 后缀文案 ] [ ●●● 颜色格子条 ]
    与 _render_debate_record_strip 的差别仅在外层 wrapper 类名：
      - 副卡战绩用：.card-debate-record（已有 CSS）
      - 主卡 header 用：.debate-panel-stat（新加 CSS，与 header 横排居右）

    返回内部 HTML 片段（text + bar），调用方决定外壳。
    """
    challenged = record.get("challenged", 0)
    upheld = record.get("upheld", 0)
    draws = record.get("draws", 0)
    outcomes = record.get("outcomes", [])

    if challenged == 0:
        text_html = (
            '<span class="card-record-text">'
            '<span class="card-record-upheld suffix-strong-hold">未被挑战 ✌️</span>'
            '</span>'
        )
        bar_html = ''
    else:
        if upheld == 0 and draws == 0:
            suffix = "全部扛住"
        elif upheld == challenged:
            suffix = "全部成立"
        elif draws == challenged:
            suffix = "全部打和"
        elif upheld > 0:
            suffix = f"{upheld} 次成立"
        else:
            suffix = f"{draws} 次打和"

        text_html = (
            f'<span class="card-record-text">'
            f'{challenged} 次挑战 · '
            f'<span class="card-record-upheld suffix-neutral">{suffix}</span>'
            f'</span>'
        )

        _OUTCOME_CLASS = {"lose": "fill-lose", "win": "fill-win", "tie": "fill-tie"}
        cells = []
        for oc in outcomes[:3]:
            cls = _OUTCOME_CLASS.get(oc, "fill-win")
            cells.append(f'<span class="card-record-bar-cell {cls}"></span>')
        cells_html = ''.join(cells)
        bar_html = f'<div class="card-record-bar">{cells_html}</div>'

    return text_html + bar_html


def _render_debate_record_strip(model_name, record):
    """渲染副卡的"观点战绩条" (L2 信息密度)。

    用色规则：
    - 未被挑战 → 文字绿 + ✌️，无格子
    - 被挑战过 → 文字灰；右侧格子条按场染色：
        · 红 fill-lose = 挑战成立（观点被攻破）
        · 绿 fill-win  = 挑战被扛住（观点站住）
        · 灰 fill-tie  = 打和（双方各执一词）
      文字后缀只做聚合陈述（不重复用字重强调结果，强调由格子颜色承担）。

    文案（术语统一为"挑战"，不再用"质疑"）：
    - 未被挑战 ✌️
    - N 次挑战 · 全部扛住         （upheld=0 且 draws=0）
    - N 次挑战 · 全部成立         （upheld=N）
    - N 次挑战 · 全部打和         （draws=N）
    - N 次挑战 · M 次成立         （混合：成立为主，可能掺打和/扛住）
    - N 次挑战 · M 次打和         （混合：有打和但没成立）

    格子：每场一格（封顶 3 格，超出仅显示前 3 格——颜色仍按真实顺序）
    """
    # 复用 _render_debate_stat_inline 生成内部 text+bar HTML（副卡用同一份逻辑）
    inner_html = _render_debate_stat_inline(record)
    return (
        f'<div class="card-debate-record">'
        f'{inner_html}'
        f'</div>'
    )


def build_cards():
    cards = []
    debate_records = _build_debate_records()
    for i, m in enumerate(MODELS):
        is_winner = m["name"] == WINNER_MODEL
        winner_class = ' recommended' if is_winner else ''
        winner_tag = (
            '<span class="recommended-tag">⭐ 推荐</span>' if is_winner else ''
        )
        word_count = len(m["answer"])

        # Convert answer to HTML (both condensed and full versions)
        full_answer_html = md_to_html_safe(m["answer"])
        condensed_text = condense_answer(m["answer"])
        condensed_html = md_to_html_safe(condensed_text)
        # Core thesis: prefer the curated one-liner; fallback to first paragraph
        core_thesis = m.get("core_thesis", "").strip()
        if core_thesis:
            summary_html = f"<p>{html_escape(core_thesis)}</p>"
        else:
            summary_html = md_to_html_safe(condense_answer(m["answer"], max_chars=160))

        # Build debate panel
        debate_html = ""
        has_debate = False
        challenges_out = m.get("challenges_issued", [])
        challenges_in = m.get("challenges_received", [])

        # Build cross-model lookup: target_model_name -> list of (challenger_name, challenge_data)
        _incoming_challenges = {}
        for other_m in MODELS:
            for c in other_m.get("challenges_issued", []):
                tgt = c["target"]
                if tgt not in _incoming_challenges:
                    _incoming_challenges[tgt] = []
                _incoming_challenges[tgt].append((other_m["name"], c))

        # Merge: incoming challenges (from lookup) + received rebuttals (from challenges_received)
        # Each debate_item = one attack on this model + its rebuttal (if any), all in one place
        _my_incoming = _incoming_challenges.get(m["name"], [])
        has_debate = bool(_my_incoming) or bool(challenges_in)

        debate_items = ""
        if has_debate:
            # New layout (Round 3 verdict-aware):
            # Each debate-item = one challenger → this model pairing, containing
            #   1) preview: red(挑战要点) | blue(反驳要点) side by side + verdict summary
            #   2) expanded: full challenge body + full rebuttal body + full verdict
            # 收起时只显示要点；展开时只显示完整观点（不重复预览要点）

            # 先解析裁判名（所有 clash 共用同一个裁判，取第一个有 verdict 的）
            _judge_name = ""
            for _rc in challenges_in:
                _v = _rc.get("verdict")
                if _v and isinstance(_v, dict) and _v.get("judge_model"):
                    _judge_name = _v["judge_model"]
                    break

            _seen_challengers = set()
            # Primary loop: use _my_incoming (canonical order from all challengers' challenges_issued)
            for _challenger_name, _ch in _my_incoming:
                _seen_challengers.add(_challenger_name)
                # Match back to challenges_received[from=_challenger_name] for rebuttal/verdict
                _matched_rc = None
                for _rc in challenges_in:
                    if _rc["from"] == _challenger_name:
                        _matched_rc = _rc
                        break
                debate_items += _render_debate_item(
                    challenger_name=_challenger_name,
                    defender_name=m["name"],
                    challenge_reason=_ch.get("reason", ""),
                    challenge_detail=_ch.get("detail", ""),
                    challenge_summary=_ch.get("challenge_summary", _ch.get("summary", "")),
                    rebuttal_body=(_matched_rc or {}).get("rebuttal", ""),
                    rebuttal_summary=(_matched_rc or {}).get("rebuttal_summary", ""),
                    verdict=(_matched_rc or {}).get("verdict"),
                    judge_name=_judge_name,
                )

            # Safety net: any challenges_received not covered by _my_incoming
            # (e.g. stale data where challenger.challenges_issued was pruned)
            for _rc in challenges_in:
                if _rc["from"] in _seen_challengers:
                    continue
                debate_items += _render_debate_item(
                    challenger_name=_rc["from"],
                    defender_name=m["name"],
                    challenge_reason=_rc.get("reason", ""),
                    challenge_detail=_rc.get("detail", ""),
                    challenge_summary=_rc.get("challenge_summary", ""),
                    rebuttal_body=_rc.get("rebuttal", ""),
                    rebuttal_summary=_rc.get("rebuttal_summary", ""),
                    verdict=_rc.get("verdict"),
                    judge_name=_judge_name,
                )

            # debate items 始终展开（panel.open 状态由模板 CSS 控制 display:block）
            debate_count = len(debate_items.split('<div class="debate-item">')) - 1
            # 战绩信息（与副卡同源）：N 次挑战 · 后缀 + 颜色格子
            _stat_inner = _render_debate_stat_inline(debate_records.get(m["name"], {}))
            # 裁判名已在每条判词前缀里呈现，panel header 不再重复挂 badge
            debate_html = (
                f'<div class="debate-panel has-content">'
                f'<div class="debate-panel-header open">'
                f'<span class="icon">⚔️</span>'
                f'<span>辩论面板</span>'
                f'<span class="debate-panel-stat">{_stat_inner}</span>'
                f'</div>'
                f'<div class="debate-items">'
                f'{debate_items}'
                f'</div>'
                f'</div>'
            )
        else:
            # 未被挑战 → 主卡也明确显示这条状态（与副卡保持一致）
            debate_html = (
                f'<div class="debate-panel no-content">'
                f'<div class="no-debate-inline">未被挑战 ✌️</div>'
                f'</div>'
            )

        # Card collapse state
        collapse_class = '' if is_winner else ' collapsed'
        # 卡头结构：左 = badge + 名称 + 字数 + 推荐标；右 = 分享按钮 + "主卡查看"提示
        # expand-hint 文案统一输出"主卡查看"，显隐由 CSS 按 .recommended / :not(.collapsed) 控制
        header_left = (
            f'<span class="model-badge" style="background:{m["color"]}"></span>'
            f'<span class="model-name">{m["name"]}</span>'
            f'<span class="word-count">{word_count} 字</span>'
            f'{winner_tag}'
        )
        header_right = (
            f'<button class="header-share-btn" data-model="{m["name"]}" title="分享此回答">'
            f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f'<path d="M4 12v8a2 2 0 002 2h12a2 2 0 002-2v-8"/>'
            f'<polyline points="16 6 12 2 8 6"/>'
            f'<line x1="12" y1="2" x2="12" y2="15"/>'
            f'</svg>分享此回答</button>'
            f'<span class="expand-hint">主卡查看</span>'
        )

        card = (
            f'<div class="card{winner_class}{collapse_class}" data-model="{m["name"]}">'
            f'<div class="card-header">'
            f'<div class="header-left">{header_left}</div>'
            f'<div class="header-right">{header_right}</div>'
            f'</div>'
            f'<div class="card-summary-wrap">'
            f'<div class="card-summary-title">核心观点</div>'
            f'<div class="card-summary-text"><div class="condensed-answer">{summary_html}</div></div>'
            f'</div>'
            f'{_render_debate_record_strip(m["name"], debate_records.get(m["name"], {"items": [], "wins": 0, "losses": 0, "draws": 0}))}'
            f'<div class="card-body"><div class="card-full">'
            f'<div class="answer-section">'
            f'<div class="answer-content">'
            f'<div class="condensed-answer">{condensed_html}</div>'
            f'</div>'
            f'<div class="full-answer">{full_answer_html}</div>'
            f'<button class="answer-toggle" data-wc="{word_count}">展开回答 · {word_count} 字</button>'
            f'</div>'
            f'{debate_html}'
            f'</div></div>'
            f'</div>'
        )
        cards.append((is_winner, card))
    
    # Assemble: hero card first, then sidebar wrapping collapsed cards
    hero_card = ""
    sidebar_cards = []
    for is_winner, card in cards:
        if is_winner:
            hero_card = card
        else:
            sidebar_cards.append(card)
    
    if sidebar_cards:
        sidebar_html = '<div class="sidebar">' + "\n".join(sidebar_cards) + '</div>'
        return hero_card + "\n" + sidebar_html
    return hero_card


# === MAIN ===
with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
    template = f.read()

template = template.replace("{{QUESTION}}", QUESTION)
template = template.replace("{{TIMESTAMP}}", TIMESTAMP)
template = template.replace("{{VISION_HEADER}}", build_vision_header())
template = template.replace("{{ROSTER_ITEMS}}", build_roster())
template = template.replace("{{DEBATE_SUMMARY}}", build_debate_summary())
template = template.replace("{{WINNER_MODEL}}", WINNER_MODEL)
template = template.replace("{{WINNER_REASON_COMPARE}}", WINNER_REASON_COMPARE)
template = template.replace("{{WINNER_REASON_DEBATE}}", WINNER_REASON_DEBATE)
template = template.replace("{{CARDS}}", build_cards())

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(template)

print(f"OK: {OUTPUT_PATH}")
print(f"   💡 推荐在浏览器以 ≥ 1280px 宽度打开，可看到'主卡左 + 3 次卡右'的完整布局（< 1081px 会触发响应式单列）。")
