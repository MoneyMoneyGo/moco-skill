# CHANGELOG

版本号格式：`YYYY.MM.DD.N`（N = 同一天第 N 次发布，从 1 起）。

分类：
- **Breaking**：用户必须知道，可能改变已有行为或要求新字段。
- **Behavior**：改变了默认行为但不破坏旧数据。
- **Fix**：修复 bug、文档、边界条件，无行为变化。

---

## 2026.04.27.1 — 初始公开版

### Breaking

- **写死 4 家默认阵容**（Round 1/2/3）：`claude-sonnet-4.6-1m` / `gpt-5.4` / `gemini-3.0-pro` / `glm-4.7-ioa`。Round 4 裁判：`claude-opus-4.7-1m`。禁止传 `default / lite / reasoning / ""`，否则 Pre-flight 直接中止。触发更换默认阵容的条件仅两种：(a) WorkBuddy 接入新模型且用户要试；(b) 用户当次明确指定。
- **`_gen_moco.py` 内置 `validate_debate_data()`**，渲染 HTML 前做硬关卡，失败 exit 3：
  - H1：`model_id` 不能是 `default/lite/reasoning/""`。
  - H2：Round 1 的 `model_id` 互不相同。
  - H3：`verdict.judge_model_id` 不能与参战 lineup 重叠。
  - H4：有 rebuttal 的 clash 必须有完整 verdict（`winner ∈ {challenge, rebuttal, draw}`）。
- **多模态 `vision_mode` 字段**（新问题带图时必填）：
  - 合法值 `full / r1_only / none`。`smart` v1 不实现。
  - 默认 `r1_only`：Round 1 四家全员看图，R2/R3/R4 默认纯文本，仅 `needs_image_for_rebuttal=true` 的 clash 才允许 R3 局部回传图。
  - 5 条硬校验（V1-V5）失败直接 exit 3。

### Behavior

- **UTC 字段硬规则**：每个子 Agent 必须自己跑 `date -u +"%Y-%m-%dT%H:%M:%SZ"`，禁止抄示例/占位符/复用旧值；无 Bash 时填 `"unavailable"`，不允许伪造。收齐后主智能体做"同步水印"软告警（S3）。
- **debate-data.json schema 扩展**：
  - 顶层新增 `run_start` / `run_end` / `vision_mode` / `question_image_paths[]`。
  - 每 model 新增 `model_id` / `utc` / `image_seen`。
  - 每 verdict 新增 `judge_model_id`。
  - 每 `challenges_received[*]` 新增 `needs_image_for_rebuttal` / `image_dispute_detail` / `image_attached_for_rebuttal`。
- **主卡辩论面板头部加战绩条**：与副卡同源渲染 `N 次挑战 · 全部成立/扛住 + 颜色格子`，替换原孤立的 `N 条`。
- **HTML 头部加 vision 透明展示**：原图缩略图 + vision_mode 标签 + 4 家 ✓/✗ 所见状态，读者一眼可见本次 moco 多模态的真实情况。
- `challenges_issued[*]` 使用 `target` 而非 `to`（原有约定，写入 debate-data.json 时请用 `target`）。

### Fix

- 旧数据（v1/v2，无 `model_id` / `utc` / vision 字段）不会被新校验误伤：V1-V5 仅在声明了 `vision_mode` 或 `question_image_paths` 时启用；H1-H3 遇到缺 `model_id` 走 S1 软告警而非 hard fail。
- 修复"4 路并发 R1 utc 完全一致"的同步水印问题——在 prompt 模板里强制每个子 Agent 自己用 Bash 取真实 UTC。
- 修复"4 路 `model="default"` 导致实际全走当前会话底层模型"的假多模型回归——Pre-flight 校验 + H1 代码兜底。

### 工程提示

- 系统 `/usr/bin/git` 在本机被 Xcode shim 拦截（exit 69）。发布/推送时使用 `/Applications/Xcode.app/Contents/Developer/usr/bin/git`，或配 gh 托管的 token-in-URL 临时方案。
- Python 托管路径：`/Users/soy/.workbuddy/binaries/python/versions/3.13.12/bin/python3`。
