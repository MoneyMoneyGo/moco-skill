# CHANGELOG

版本号格式：`YYYY.MM.DD.N`（N = 同一天第 N 次发布，从 1 起）。

分类：
- **Breaking**：用户必须知道，可能改变已有行为或要求新字段。
- **Behavior**：改变了默认行为但不破坏旧数据。
- **Fix**：修复 bug、文档、边界条件，无行为变化。

---

## 2026.04.27.6 — 极简 vision-header + 内嵌积分消耗参考

### Behavior

- **vision-header 极简化**（方案 A）：删除"输入" label、`vision_mode` pill、4 家 image_seen ✓ 列表，**只保留缩略图**。所有元信息（vision_mode + image_seen 状态）藏进缩略图的 `title` tooltip，hover 可见。`build_vision_header()` 函数从 ~80 行砍到 ~30 行；CSS 删了 `.vision-header-mode` / `.vision-header-seen-*` / `.vision-header-label` 全套。
- **HTML 报告页 footer 新增"📊 积分消耗 ⓘ"入口**：点击弹出 modal，展示 3 张积分消耗参考表（moco 各阶段细节、消耗对照含基准、主流模型单价）。Esc / 遮罩 / ✕ 关闭。所有数字以 token 量级 + 范围给出（±30%），不锁死具体值。
- **新增 `COST_REFERENCE.md`** 在仓库根目录，作为 modal 内容的源头文档，可独立浏览。
- **SKILL.md 加"积分消耗参考"段**，引用 COST_REFERENCE.md + 速览要点。

### 设计原则

- "是否带图"用户从缩略图本身就能看到，不需要文字 label
- vision_mode 是开发者关心的内部状态，不该作为 UI 一等公民
- 异常分支（image_seen=false）已被 V3 校验在 HTML 生成前拦死，所以"✓✓✓✓"是死代码
- 弹窗 modal 复用现有 design tokens（`--text-meta` / `--gap-block-s` / `--hover-bg`），不引入新色板

### Fix

- 13/13 回归 fixture 全绿（含 fix-v1-bad-mode-full）。

---

## 2026.04.27.5 — 默认阵容换血：DeepSeek V3.2 替换 GLM-4.7

### Breaking

- **第 4 家参战模型从 `glm-4.7-ioa` 换为 `deepseek-v3-2-volc-ioa`**。Round 1/2/3 默认阵容现在是：
  - `claude-sonnet-4.6-1m`（Anthropic）
  - `gpt-5.4`（OpenAI）
  - `gemini-3.0-pro`（Google）
  - **`deepseek-v3-2-volc-ioa`**（DeepSeek，新）⭐
- Round 4 裁判 `claude-opus-4.7-1m` 不变。

### 替换原因

1. **GLM-4.7 多模态不稳定**：18:48 真实事故中 GLM 在正式 moco 跑里返回 `image_seen=false`（声称"不支持图片处理"），与同 ID 18:15 探针成功读图的结果矛盾。V3 校验已记录在案。
2. **DeepSeek V3.2 推理能力更强**：在严密推理 + 找茬挑战场景的口碑更适合 moco 的辩论本质。
3. **DeepSeek V3.2 视觉读图实测稳定**：20:22 探针通过——准确识别 Cursor 截图布局、按钮文字、对话主题。
4. **4 家厂商差异最大化**：Anthropic（对话/伦理）+ OpenAI（说明文）+ Google（结构化）+ DeepSeek（严密推理），4 个不同流派覆盖更广。

### Behavior

- Display name "GLM-4.7" → "DeepSeek V3.2"，颜色从 `#6B7280`（灰）改为 `#7C3AED`（紫，DeepSeek 系约定色）。
- 回归 fixture `fix-healthy.json` / `fix-vision-healthy.json` 已更新到新阵容；旧反向 fixture（H1/H2/H3/V1-V5）保留 `glm-4.7-ioa` 不影响测试目的（这些 fixture 测的是规则违反，不测阵容）。

### Migration

- 历史 debate-data.json 含 `model_id="glm-4.7-ioa"` 仍可正常渲染（不会被任何校验拦下，因为它不是占位模型）。
- 如果你的工作区有自定义脚本调 moco，把 GLM 那一路 Agent.model 改成 `deepseek-v3-2-volc-ioa` 即可。

---

## 2026.04.27.4 — 砍掉 vision_mode=full（误读修正）

### Breaking

- **删除 `vision_mode=full`**。`VALID_VISION_MODES` 从 `{full, r1_only, none}` 收缩为 `{r1_only, none}`。任何使用 `vision_mode=full` 的 debate-data.json 现在会被 V1 校验拦下（exit 3），错误信息明确指出迁移路径：使用 `r1_only` + `needs_image_for_rebuttal` 替代。
- **删除 V3 校验里 `{"full", "r1_only"}` 集合判断**，改成只检查 `r1_only`。
- **删除 HTML vision_header 的 FULL 标签 / CSS / Python label map**。

### 背景与决策

- 18:32 银纸的原话："1) v1 先支持图片输入，先跑通 vision_mode=full；2) 默认切到 vision_mode=r1_only..." —— **"先跑通 full"是 v1 开发阶段的验证路径**（先把最暴力的全程带图跑通，确认可行性），**不是要长期保留 full 作为用户档**。
- 当时我（写 SKILL.md 的）误读为"保留 full 作为可选档"，导致 `VALID_VISION_MODES` 多了一档。
- 19:51 银纸指出："为什么会需要全程都带图？我开始的时候没有提出这个诉求吧？" 决定砍 full。

### 替代路径

- 之前需要 `full` 的"个别 clash 必须看图"场景，现在用 **R3 局部回传机制** 覆盖：挑战方在 R2 声明 `needs_image_for_rebuttal=true`，被挑战方在 R3 反驳调用里就会带图（V4/V5 校验保证不滥用）。
- 这等同于"按 clash 升级到 full 子集"，比把整场 moco 都开 full 更精细、更省 token。

### Fix

- SKILL.md 多模态段措辞简化：原"主智能体默认走 r1_only，除非用户显式说全程带图才切 full" → 改为"有图 → r1_only；没图 → none。无判断、无询问。"
- 新增回归 fixture `fix-v1-bad-mode-full.json`，验证 full 现在确实被 V1 拦下。

---

## 2026.04.27.3 — 视口宽度提醒（默认 1280px）

### Behavior

- **HTML 新增 viewport-hint 横幅**：当浏览器视口 < 1081px 时（即响应式单列模式触发阈值），顶部粘性横幅显示"当前窗口 Npx，建议拉宽到 1280px"；拉宽后自动消失；用户点 × 可关闭本次会话。
- **`_gen_moco.py` 输出新增一行推荐提示**：生成 HTML 成功后打印"💡 推荐在浏览器以 ≥ 1280px 宽度打开"。
- **SKILL.md Step 9 指令强化**：主智能体调 `preview_url` 后必须在文字回复里显式提示用户推荐宽度。

### 背景

网页无法"命令浏览器打开多大窗口"（浏览器安全策略），所以通过 (1) HTML 横幅自我提醒 + (2) stderr 提示 + (3) SKILL.md 指令告知 三层机制来保证用户默认看到"主卡左 + 3 次卡右"的推荐布局。

---

## 2026.04.27.2 — Pre-Run Update Check 生效

### Behavior

- **SKILL.md 新增 Step 0 段**，要求主智能体在启动 moco 前调用 `python3 _gen_moco.py --update-check-only`，退出码 0/10/11 各有明确动作：相等静默、远端更新弹 3 选 1（含 CHANGELOG 链接）、检查失败告警但允许继续。
- **`_gen_moco.py` 新增两个 CLI flag**：`--update-check-only`（只检查不渲染，退出码专用 0/10/11）和 `--skip-update-check`（回归测试/离线场景跳过）。
- **Update Check 不阻断渲染**：即便远端有更新，主智能体仍可继续渲染，Gate 是"告知机制"而非强行拦截。Breaking 改动除外——必须强提醒。

### Fix

- 修复 `--data` / `--output` 在 `--update-check-only` 时不应为必填参数。

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
