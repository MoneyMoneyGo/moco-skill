---
name: moco
description: "moco 多模型辩论 — 让 4 个 AI 同台答题、互相找错、各自反驳，再综合评分挑出最佳答案。适合方案评估、选型决策、避免单模型偏见。触发：moco、MoCompare、多模型对比、模型 PK、模型辩论、对比回答、几个模型一起答、model debate、compare models。"
---

# moco — Multi-Model Compare & Debate

## Overview

Send the same question to **4 different built-in AI models concurrently**, collect all responses, then run a structured **debate with adjudication**:

1. **Round 1 — Initial Answers**: 4 models answer independently.
2. **Round 2 — Challenges**: Each model reads the other 3 answers and may challenge one of them.
3. **Round 3 — Per-Challenge Rebuttals**: For **every single challenge** (not merged), the challenged model writes a **one-to-one rebuttal** dedicated to that specific challenge.
4. **Round 4 — Judge Adjudication**: A neutral 5th model (not involved in that particular clash) scores each challenge↔rebuttal pair, picks a winner, and writes a short verdict. This replaces the old "auto-pick best answer" heuristic with evidence-based adjudication.

Finally, compose everything (answers + paired clashes + verdicts) into a beautiful HTML comparison page.

**Key UX change**: Challenges and their rebuttals are rendered as **paired clash cards**. Each card has two views:
- *Preview* (default): side-by-side red (challenge) / blue (rebuttal) summary boxes + judge's one-line verdict.
- *Expanded* (on click): full challenge body, full rebuttal body, full judge reasoning — no duplication with preview.

## Workflow

### Step 0: Pre-Run Update Check（银纸 2026-04-27 锁定）

在启动任何 moco 流程（Round 1 发图之前）之前，主智能体**必须**先调用一次：

```bash
python3 <skill_root>/scripts/_gen_moco.py --update-check-only
```

该命令会：
- 读取本地 `<skill_root>/VERSION`
- 拉取远端 `https://raw.githubusercontent.com/MoneyMoneyGo/moco-skill/main/VERSION`
- 对比两者（格式 `YYYY.MM.DD.N`）

**退出码解读与动作**：

| exit | 含义 | 主智能体应该做什么 |
|---|---|---|
| 0 | 本地与远端一致（或本地更新） | 静默继续（不用告知用户）|
| 10 | 远端更新 | **必须**在启动 moco 前告知用户，问 3 个选项：① 立即拉更新再跑 ② 跳过此次更新直接跑 ③ 看 CHANGELOG 再决定；若 CHANGELOG 含 Breaking，**不可静默**，必须强提醒 |
| 11 | 检查失败（离线/超时/URL 404） | 告知用户"Update Check 失败，按当前本地版本继续"，允许继续 |

**选项触发的具体动作**：

- 选项 ①：在 `<skill_root>` 执行 `git pull`（需要 token-in-URL 或 `gh auth setup-git`），pull 成功后继续 moco；失败则降级为选项 ②。
- 选项 ②：直接继续，不改本地版本号；下次跑 moco 会再次弹同一提示。
- 选项 ③：把 `https://github.com/MoneyMoneyGo/moco-skill/blob/main/CHANGELOG.md` 里自 local_version 起的记录贴给用户看，然后再问 ①/②。

**运行日志字段**（主智能体应在当次 moco 的调用日志里记录）：

```json
{
  "update_check": {
    "local_version": "...",
    "latest_version": "...",
    "comparison": "equal" | "remote_newer" | "local_newer" | "unknown",
    "prompt_shown": true|false,
    "user_choice": 1|2|3|null,
    "update_result": "success" | "skipped" | "failed" | null
  }
}
```

**跳过 Update Check 的合法场景**（传 `--skip-update-check`）：

- 回归测试内部调用（`moco-regression-tests/fix-*.json`）
- 离线环境且用户已经确认"知道离线，直接跑"
- 某个 CI/batch 任务明确声明不在乎版本

**Update Check 不阻断渲染**：即便 exit 10/11，主智能体仍然可以继续让 `_gen_moco.py` 正常生成 HTML（只要用户同意选项 ② 或 ③）。Gate 是"告知机制"而不是"强行拦截"——Breaking 强提醒除外。

---

### Step 1: Identify the Question

Extract the user's question from the conversation. If no question is provided, ask what to ask.

### Step 2: Select Models

**Default model lineup (unless user specifies otherwise)**:

| # | Display Name | Color | Provider | **WorkBuddy `model` ID** |
|---|--------------|-------|----------|--------------------------|
| 1 | Claude Sonnet | `#D97706` | Anthropic | `claude-sonnet-4.6-1m` |
| 2 | GPT-5.4 | `#10A37F` | OpenAI | `gpt-5.4` |
| 3 | Gemini 3.0 Pro | `#4285F4` | Google | `gemini-3.0-pro` |
| 4 | GLM-4.7 | `#6B7280` | Zhipu | `glm-4.7-ioa` |

**CRITICAL — Real model routing is mandatory (HARD-CODED, 银纸 2026-04-27 决定)**:
- WorkBuddy 的 `Agent` 工具实际上支持 **任意内置模型 ID**（不只是简化文档里写的 `default/lite/reasoning`）。
- moco **必须** 在每次 `Agent` 调用时显式传入对应的真实 `model` ID，**禁止** `default/lite/reasoning/空字符串`。
- **默认锁定阵容（写死）**：Round 1/2/3 必须分别使用 `claude-sonnet-4.6-1m`、`gpt-5.4`、`gemini-3.0-pro`、`glm-4.7-ioa`；Round 4 裁判必须使用 `claude-opus-4.7-1m`。
- **何时可以更换默认阵容**：仅以下两种情况——（a）WorkBuddy 接入了新模型，且用户明确表示要试新模型；（b）用户在当次提问中明确指定了模型 ID/名称。其余任何情况都必须使用上述写死的 5 个 ID，无需再次询问用户。
- 当 (a)/(b) 触发时，必须先用 AskUserQuestion 与用户确认新阵容，确认后再开跑。

**🛡 Pre-flight 校验（运行前强制检查，不通过直接中止）**：

在 Step 3 实际发起任何 Agent 调用 **之前**，主智能体必须执行以下两项校验。任意一项失败 → 立即停止 moco，向用户输出错误并询问是否换阵容；**禁止**继续执行 Round 1。

1. **占位模型禁用**：扫描即将下发的全部 5 个 `Agent.model` 取值（4 个参战 + 1 个裁判）。若任一值 ∈ `{"default", "lite", "reasoning", ""}` → 报错：
   ```
   ❌ moco pre-flight failed: model "<offending value>" 是占位模型，不允许参与多模型辩论。
   ```
2. **参战模型唯一性**：将 Round 1 的 4 个 `model` ID 去重。若去重后数量 < 4 → 报错：
   ```
   ❌ moco pre-flight failed: Round 1 的 4 个 model 必须互不相同，当前去重后只剩 N 个。
   重复 ID: [...]
   ```

校验通过后，才允许进入并发调用。

**🕒 UTC 字段获取规则（强制，银纸 2026-04-27 决定）**：

每轮 Agent prompt 都含 `{"declared_model":..., "utc":...}` 声明行。`utc` 字段必须是子 Agent **自己实时取的真实时间戳**，不允许伪造、抄示例、复用。

任何 Round（1/2/3/4）的子 Agent prompt 末尾都必须显式包含以下硬规则段：

```
UTC 字段获取规则（强制）：
- 你必须在自己的 Agent 进程里通过 Bash 工具执行：
    date -u +"%Y-%m-%dT%H:%M:%SZ"
  把命令的真实输出作为 utc 字段值。
- 禁止抄 prompt 里出现的任何示例时间。
- 禁止使用占位符（如 <current UTC ISO 8601>）/ 估算 / 复用上一次的时间戳。
- 如果你的运行环境无法执行 Bash，必须把 utc 设为字符串 "unavailable"，绝不允许伪造。
```

**事后水印检查（不阻断，仅高亮提示）**：

收齐 Round 1 的 4 个 utc 后，主智能体必须做一次同步水印检查：
- 若 4 路 utc 完全一致（精确到秒）→ 在调用日志里高亮 `⚠ utc-sync-watermark: Round1`，并提醒用户 utc 字段可能不可信，不能用于法证分析。
- 同样规则适用于 Round 2/3/4 的多路并发。
- 不阻断执行，因为某些子 Agent 可能确实没有 Bash 能力（其 utc 应为 "unavailable"）。

**不可落地的方案**（避免 LLM 复抄）：
- "由平台注入 request 时间戳" — WorkBuddy Agent 工具目前不会自动注入 request_id 或 request 时间，**只能走 `date -u`**。

校验通过且 UTC 规则注入完毕后，才允许进入并发调用。

**Available alternative model IDs** (use when default lineup unavailable, or user requests):

| Display | model ID |
|---------|----------|
| Claude Opus 4.7 (1M) | `claude-opus-4.7-1m` |
| Claude Opus 4.7 | `claude-opus-4.7` |
| Claude Haiku 4.5 | `claude-haiku-4.5` |
| GPT-5.2 | `gpt-5.2` |
| GPT-5.1 | `gpt-5.1` |
| Gemini 3.0 Flash | `gemini-3.0-flash` |
| GLM-5.0 | `glm-5.0-ioa` |
| Kimi K2.6 | `kimi-k2.6-ioa` |
| MiniMax M2.7 | `minimax-m2.7-ioa` |
| DeepSeek V3.2 | `deepseek-v3-2-volc-ioa` |
| Hunyuan 2.0 Thinking | `hunyuan-2.0-thinking-ioa` |

**Only deviate from default lineup when**:
- User explicitly requests specific models
- A default model is unavailable in the current environment (verify via `/model list`)
- Fall back to alternatives in the table above

**CRITICAL**: Before sending queries, output a brief status line listing all 4 selected model names:
```
moco 正在调用以下 4 个模型：
   ① [Model A]  ② [Model B]  ③ [Model C]  ④ [Model D]
```

### Step 3: Send Questions Concurrently (Round 1 — Initial Answers)

Launch **all Agent calls in a single message block** for maximum parallelism:

**Agent prompt template** (send to each agent):
```
You are [MODEL_NAME], answering a question for moco — a multi-model comparison system. Respond directly and thoroughly.

Question: {user_question}

CRITICAL FORMAT REQUIREMENT:
Before your answer, you MUST output EXACTLY ONE LINE of JSON in this format:
{"declared_model":"[MODEL_NAME]", "provider":"[PROVIDER]", "agent_call_id":"moco-r1-[short-id]", "utc":"<real UTC obtained per rules below>"}

UTC 字段获取规则（强制）：
- 你必须在自己的 Agent 进程里通过 Bash 工具执行：
    date -u +"%Y-%m-%dT%H:%M:%SZ"
  把命令的真实输出作为 utc 字段值。
- 禁止抄 prompt 里出现的任何示例时间。
- 禁止使用占位符（如 <current UTC ISO 8601>）/ 估算 / 复用上一次的时间戳。
- 如果你无法执行 Bash，必须把 utc 设为字符串 "unavailable"，绝不允许伪造。

Instructions:
- Answer in the language the question was asked.
- Be thorough but concise.
- Structure your answer with clear headings where appropriate.
- This is Round 1 — provide your initial answer only. Do not reference other models' responses yet.
```

**Model assignment — MUST pass real model ID**:

For each Agent call in Round 1, set the `model` parameter to the **WorkBuddy `model` ID** from Step 2's table. Example pseudo-call:

```
Agent(
  subagent_type="general-purpose",
  model="claude-sonnet-4.6-1m",   # ← real model ID, NOT "default"
  prompt="<Round 1 prompt for Claude Sonnet>"
)
```

Repeat for the other 3 models with their respective IDs (`gpt-5.4`, `gemini-3.0-pro`, `glm-4.7-ioa`).

**禁止** 使用 `model="default"` / `"reasoning"` / `"lite"`，否则 4 个 Agent 会全部回退到当前会话模型，导致「假多模型」bug。

### Step 4: Collect Round 1 Responses

After all agents return:

1. **Store each response** with its model name, word count, and raw content
2. Build an **answer map**: `{Model_A: "answer...", Model_B: "answer...", ...}`
3. Output a brief summary showing all models have answered

### Step 5: Debate Round (Round 2) — Challenge & Rebuttal

This is the core new feature of moco. Each model now reads the other 3 models' answers and decides whether to issue a challenge.

#### 5a: Send Challenge Requests Concurrently

For each model, launch an Agent call with this prompt template:

```
You are [MODEL_NAME] in moco's Debate Round. You have already answered a question. Now you will read the other 3 models' answers.

Original Question: {user_question}

Your Answer: {your_answer}

Other Models' Answers:
- [Model_X]: {model_x_answer}
- [Model_Y]: {model_y_answer}
- [Model_Z]: {model_z_answer}

Your task:
1. Carefully read ALL three other models' answers.
2. Decide whether ANY of them contains:
   - Logical fallacies or reasoning errors
   - Factual inaccuracies or outdated information
   - Missing critical perspectives
   - Flawed conclusions despite correct premises
   - Dangerous advice or misleading claims
3. You MAY challenge at most ONE model, OR choose NOT to challenge anyone (if you think all answers are reasonable).

If you want to challenge, output EXACTLY in this JSON format (nothing else):
{"challenged_model": "[Model Name]", "challenge_reason": "[Brief reason]", "challenge_detail": "[Detailed critique pointing out specific issues]"}

If you do NOT want to challenge anyone, output EXACTLY:
{"challenged_model": null, "challenge_reason": null, "challenge_detail": null}

Before either of the above lines, you MUST first emit ONE LINE of declaration JSON:
{"declared_model":"[MODEL_NAME]", "provider":"[PROVIDER]", "agent_call_id":"moco-r2-[short-id]", "utc":"<real UTC>"}

UTC 字段获取规则（强制）：
- 必须自己 Bash 跑 `date -u +"%Y-%m-%dT%H:%M:%SZ"`，输出原样填入。
- 禁止抄 prompt 示例时间、禁止占位符、禁止复用上一次时间戳。
- 无 Bash 能力时填 "unavailable"，绝不允许伪造。

IMPORTANT:
- Be constructive and specific. Quote the exact problematic content when possible.
- Do not challenge just to challenge — only if there is a genuine error or weakness.
- Your decision is yours alone — use your own judgment.
```

**Launch all 4 challenge agents concurrently in one message block.**

**Model assignment (same rule as Round 1)**: Each challenge Agent call MUST pass the **same `model` ID** as the model it represents. e.g. when issuing a challenge from Claude Sonnet's perspective, use `model="claude-sonnet-4.6-1m"`.

#### 5b: Process Challenges

After all challenge agents return:

1. Parse each response to extract `challenged_model`, `challenge_reason`, `challenge_detail`
2. Build a **challenge map**
3. Identify which models were challenged (may be 0–4)
4. For each challenged model, prepare a rebuttal request

#### 5c: Send Per-Challenge Rebuttal Requests Concurrently

**IMPORTANT — one-to-one rebuttal rule**: If a model receives multiple challenges, write **one dedicated rebuttal per challenge** (N challenges → N rebuttals), NOT a single merged rebuttal. This preserves the clash pairing required by the UI.

For **each challenge** (iterate over every `(challenger, target)` pair), launch an Agent call:

```
You are [TARGET_MODEL_NAME] in moco's Debate Round. [CHALLENGER_MODEL_NAME] has challenged a specific point in your answer.

Original Question: {user_question}

Your Original Answer: {your_answer}

Challenge from [CHALLENGER_MODEL_NAME]:
Reason: {challenge_reason}
Detailed Critique: {challenge_detail}

Your task:
Write ONE focused rebuttal responding ONLY to this specific challenge (not to any other challenges you may have received). Guidelines:
- Address the specific points raised by this challenger
- If the challenger found a real error, acknowledge it gracefully and explain/correct it
- If you disagree, explain why with evidence or reasoning
- Keep your rebuttal focused and professional — no personal attacks
- 200–400 words is usually ideal

Additionally, provide a one-line summary (≤ 40 Chinese chars or ~25 words) capturing your core rebuttal stance — this will be shown in the preview card.

Before the rebuttal JSON, you MUST first emit ONE LINE of declaration JSON:
{"declared_model":"[TARGET_MODEL_NAME]", "provider":"[PROVIDER]", "agent_call_id":"moco-r3-[defender]-vs-[challenger]", "utc":"<real UTC>"}

UTC 字段获取规则（强制）：
- 必须自己 Bash 跑 `date -u +"%Y-%m-%dT%H:%M:%SZ"`，输出原样填入。
- 禁止抄 prompt 示例时间、禁止占位符、禁止复用上一次时间戳。
- 无 Bash 能力时填 "unavailable"，绝不允许伪造。

Output JSON in this exact format (no extra text):
{"rebuttal": "[full rebuttal markdown]", "rebuttal_summary": "[≤ 40 字要点]"}
```

**Launch all rebuttal agents concurrently** — one per challenge, not one per challenged model.

**Model assignment**: Each rebuttal MUST be generated by **the defender's own model** — pass `model="<defender's WorkBuddy model ID>"` (e.g. when GLM-4.7 is rebutting, use `model="glm-4.7-ioa"`).

#### 5d: Collect Rebuttals

Store each rebuttal linked to its specific `(challenger, defender)` pair in `challenges_received[*]`. Schema:

```json
{
  "from": "ChallengerName",
  "reason": "...",
  "detail": "...",
  "rebuttal": "...",
  "rebuttal_summary": "≤ 40 字要点"
}
```

Also store `challenge_summary` on the challenger side if you asked for it in Round 2 (optional — generator has a fallback that auto-extracts).

### Step 6: Judge Adjudication Round (Round 4)

For **every clash** (= one `(challenger → defender)` pair with both a challenge and a rebuttal), invoke a **neutral 5th model as judge**:

**Judge selection rule (必须是参战 4 家之外的第 5 个模型)**:
- 裁判**必须是参战 4 家之外的独立模型**，不允许从参战 4 家里"借"一个兼任——否则裁判对自己参与过的 clash 无法真正中立。
- 默认裁判候选（按可用性优先级，**附 WorkBuddy model ID**）：
  1. `claude-opus-4.7-1m` （Claude Opus 4.7 1M）
  2. `claude-opus-4.7`
  3. `gpt-5.4`（仅当 GPT 不在参战名单时）
  4. `gemini-3.0-pro`（仅当 Gemini 不在参战名单时）
- 选第一个**不在参战 4 家名单中**的可用模型，作为本次 moco 的统一裁判。
- 同一场 moco 的所有 clash 应使用**同一个裁判**（保证评分尺度一致）。
- 兜底候选：`kimi-k2.6-ioa` / `minimax-m2.7-ioa` / `deepseek-v3-2-volc-ioa` / `hunyuan-2.0-thinking-ioa`，要求不在参战名单里。
- 裁判模型名（display name）需要写入每条 `verdict.judge_model`。

**Agent call must pass `model="<judge model ID>"`** — 同 Round 1/2/3 规则，禁止使用 `default/lite/reasoning`。

For each clash, launch an Agent call:

```
You are acting as a NEUTRAL JUDGE in moco's adjudication round. Two models have clashed on a question. Your job is to score the clash impartially.

Original Question: {user_question}

--- Challenge from [CHALLENGER_MODEL_NAME] ---
Reason: {challenge_reason}
Detailed Critique: {challenge_detail}

--- Rebuttal from [DEFENDER_MODEL_NAME] ---
{rebuttal_body}

Scoring guidelines:
- Score both sides on factual accuracy, logical rigor, relevance to the original question, and fairness (no strawmanning).
- Use a 1–10 integer scale for each side. A tie is allowed.
- Pick a winner: "challenge" (the critique is more valid), "rebuttal" (the defense holds up), or "draw".
- Write a SHORT reasoning (≤ 120 Chinese chars or ~80 words) explaining your verdict with specifics — cite what tipped the decision.

Output JSON in this exact format (no extra text):
{
  "score_challenge": <int 1-10>,
  "score_rebuttal": <int 1-10>,
  "winner": "challenge" | "rebuttal" | "draw",
  "reasoning": "[≤ 120 字判词，具体点出关键依据]"
}

Before the verdict JSON, you MUST first emit ONE LINE of declaration JSON:
{"declared_model":"[JUDGE_MODEL_NAME]", "provider":"[PROVIDER]", "agent_call_id":"moco-r4-judge-clashN", "utc":"<real UTC>"}

UTC 字段获取规则（强制）：
- 必须自己 Bash 跑 `date -u +"%Y-%m-%dT%H:%M:%SZ"`，输出原样填入。
- 禁止抄 prompt 示例时间、禁止占位符、禁止复用上一次时间戳。
- 无 Bash 能力时填 "unavailable"，绝不允许伪造。
```

**Launch all judge agents concurrently**.

#### Store verdicts

Attach each judge result to its matching `challenges_received` entry as a `verdict` object:

```json
{
  "from": "Challenger",
  "reason": "...",
  "detail": "...",
  "rebuttal": "...",
  "rebuttal_summary": "...",
  "verdict": {
    "judge_model": "Claude Opus",
    "score_challenge": 7,
    "score_rebuttal": 6,
    "winner": "challenge",
    "reasoning": "挑战方指出的吉尼斯数字错误是硬伤，反驳方虽承认但对伪精确百分比的解释仍偏弱。"
  }
}
```

If there is no rebuttal for a challenge (defender didn't reply), skip the verdict for that clash (or set `verdict: null`).

### Step 7: Evaluate All Responses (Post-Adjudication)

Use the judge verdicts as primary evidence, weighted alongside the original criteria:

| Criterion | Weight | What to Look For |
|-----------|--------|------------------|
| Completeness | 20% | Does it fully address the question? |
| Accuracy/Factual correctness | 20% | Are facts correct? (verdicts directly inform this) |
| Clarity & structure | 12% | Is it well-organized? |
| Depth of insight | 10% | Beyond surface-level analysis |
| Practical usefulness | 8% | Can user act on this info? |
| **Debate performance** | **30%** | Aggregate of judge verdicts: wins as challenger + wins as defender + average scores. A model that issues well-founded challenges AND successfully defends against attacks wins here. |

Pick the highest-scoring response as "Recommended".

**核心原则 — 辩论是辅助，答案质量是主线**：Debate 占 30% 权重不等于辩论维度可以喧宾夺主。最终判词（`winner_reason_*`）和呈现给用户的语言**永远以答案本身为主线**，辩论表现作为补充论据出现。具体要求见 Step 8 的 schema 说明。

### Step 8: Generate Multimodal Comparison Page

Build an HTML page using `assets/compare-template.html` as base. The page MUST include initial answers, paired clashes (challenge + rebuttal), and judge verdicts.

**HTML generation steps:**
1. Write the consolidated debate data into a JSON file at the workspace, e.g. `debate-data.json`. Required schema: `{question, timestamp, models[], winner_model, winner_reason_compare, winner_reason_debate}`. Each model entry includes `name`, `color`, `answer`, optional `core_thesis`, and `challenges_issued` / `challenges_received` arrays. Each `challenges_received[*]` MUST contain the `verdict` object (or `null` if no rebuttal was written).

   **CRITICAL — winner_reason 双字段铁律（辩论是辅助，答案质量是主线）**：
   - `winner_reason_compare`：**只讲答案本身的质量**——结论是否稳健、结构是否清晰、引用是否权威、表格是否合理等。**禁止**出现"辩论环节"、"挑战"、"反驳"、"未被挑战"等任何辩论维度的描述。compare 模式下用户根本看不到辩论环节，提到就是信息穿模。长度 ~50 字以内。
   - `winner_reason_debate`：**必须答案质量主线在前，辩论辅助在后**。结构固定为：`[答案本身的核心优点]；辩论环节进一步加分——[在挑战中精准命中什么 / 在反驳中如何化解攻击 / 是否未被挑战]。` 不允许把辩论表现作为开场。长度 ~80 字以内。
   - 兼容性：旧数据若只有 `winner_reason` 单字段，generator 会自动 fallback 到该字段渲染两个 mode（不推荐，新生成必须双字段）。
2. Run the generator:
   ```bash
   python3 <skill_root>/scripts/_gen_moco.py \
     --data <workspace>/debate-data.json \
     --output <workspace>/moco-{timestamp}.html
   ```
   The generator resolves the template (`assets/compare-template.html`) and `md2html.py` automatically from the skill directory. Override with `--template`, `--md2html`, or `--python` only when needed.
3. The generator handles: Markdown→HTML conversion via `scripts/md2html.py`, recommended-card highlighting, and debate panel composition.
4. Present the resulting HTML with `preview_url`.
5. Deliver via `deliver_attachments`.

**Page layout must show**:
- Header: original question + timestamp + "⚔️ Debate Mode" badge
- Model roster bar: all 4 model names with color badges
- Winner banner: which model is recommended + one-line why
- Card grid: 4 cards side-by-side (responsive)
  - Each card:
    - Model name badge, word count, full initial answer (HTML)
    - **Debate Panel** — one **clash card per incoming challenge** (one-to-one). Each clash card has two views:
      - *Preview* (default): 🔴 challenge summary (red box, left) | 🔵 rebuttal summary (blue box, right) | 🎯 judge verdict (1 line: winner + scores)
      - *Expanded* (click "查看完整观点"): full challenge body + full rebuttal body + full judge reasoning (no duplication with preview)
    - "Recommended" star if winner
- Footer: generation metadata + debate summary stats

### Step 9: Deliver Results

1. Show preview via `preview_url`
2. Deliver HTML file via `deliver_attachments`
3. In text summary, briefly mention:
   - The 4 models compared
   - Which challenges were issued and between whom
   - Which model is recommended and why
   - Any notable debate moments

## debate-data.json schema 加固字段（银纸 2026-04-27 决定下沉到代码）

为了让 `_gen_moco.py` 能在渲染前硬卡死规则失守，主智能体写 debate-data.json 时**必须**填以下字段（缺失只软告警，但建议都填）：

**顶层新增**：
- `run_start`（必填，建议）：ISO 8601 UTC，主智能体调度首发 Round 1 之前 Bash 跑一次 `date -u`。
- `run_end`（必填，建议）：ISO 8601 UTC，所有 Round 4 收齐后再跑一次 `date -u`。

**每个 model 新增**：
- `model_id`（必填）：例如 `claude-sonnet-4.6-1m`、`gpt-5.4`。**这是 H1/H2/H3 校验的依据**，缺失则三条硬校验跳过（变软告警）。
- `utc`（必填，建议）：从该 model 在 Round 1 输出的声明 JSON 里提取，必须是子 Agent 真跑 `date -u` 的输出。

**每个 verdict 新增**：
- `judge_model_id`（必填）：例如 `claude-opus-4.7-1m`，让 H3 校验能确认裁判没踩到参战名单。

`_gen_moco.py` 校验等级：
- **Hard fail（exit 3，HTML 不生成）**：H1 model_id 是 default/lite/reasoning/""；H2 Round 1 model_id 重复；H3 judge_model_id ∈ lineup；H4 有 rebuttal 但缺 verdict 或 winner 取值非法。
- **Soft warn（exit 0，stderr 提示）**：S1 缺 model_id；S2 缺 utc；S3 全部 utc 完全相同（同步水印）；S4 缺 run_start/run_end。

## 多模态：vision_mode 策略（银纸 2026-04-27 18:32 锁定）

moco 支持图片提问。完整路径：用户给图 → 主智能体把图保存到工作区 → Round 1 prompt 模板里附图路径 → 4 家子 Agent 自己 `Read` 工具读图 → 各自基于真图答题 → Round 2/3/4 默认仅传文本，仅"图像事实争议"clash 才回传图。

### vision_mode 取值

| 取值 | 含义 | 何时用 |
|---|---|---|
| `full` | 4 家在 Round 1/2/3/4 全程都附图 | 图本身高度复杂、所有挑战都涉及图像细节 |
| `r1_only`（默认）| 只有 Round 1 附图，R2/3/4 默认纯文本 | 大多数场景；token 成本最低、信息无损 |
| `none` | 不传图（纯文本场景）| 没有图时的默认值；有图时不允许 |
| ~~`smart`~~ | 智能判定是否需要图 | **v1 不实现**，由 `_gen_moco.py` V1 校验拦截 |

主智能体默认走 `r1_only`，除非用户显式说"全程带图"才切 `full`。

### Round 1 prompt 模板新增（多模态版）

```
You are [MODEL_NAME], answering for moco — a multi-model comparison system.

Question: {user_question}
Question images: {paths_joined_by_comma_or_newline}

CRITICAL FORMAT REQUIREMENT:
Before your answer, output EXACTLY ONE LINE of declaration JSON:
{"declared_model":"[MODEL_NAME]", "provider":"[PROVIDER]", "agent_call_id":"moco-r1-[id]",
 "utc":"<real UTC>", "image_seen": true|false}

UTC 字段获取规则（强制）：自己 Bash 跑 `date -u +"%Y-%m-%dT%H:%M:%SZ"`。

IMAGE 字段获取规则（强制）：
- 你必须先用 Read 工具读取上面给出的每个图片路径。
- 如果你能真正"看到"图（Read 返回了图像而非 base64 错误），把 image_seen 设为 true，并基于图回答问题。
- 如果你只拿到 base64 / 路径错误 / 任何无法理解图的状态，必须把 image_seen 设为 false 并明确说明你没看到图。
- 禁止伪装看到图后脑补回答。一旦 image_seen=false 被检测到，整场 moco 会被 V3 校验拦下。

Instructions:
- 答案严格回应 question + 图片内容。
- 不要扩展任务（不要替我做 4 家辩论编排，那是主智能体的事）。
- Round 1 only — 不参考其他模型的答案。
```

### Round 2 challenge JSON 新增字段（硬约束 A）

```json
{
  "challenged_model": "GPT-5.4",
  "challenge_reason": "...",
  "challenge_detail": "...",
  "challenge_summary": "...",
  "needs_image_for_rebuttal": true,
  "image_dispute_detail": "GPT 把图里的红框说成蓝框了，反驳方需要回看原图核对"
}
```

- `needs_image_for_rebuttal`（必填，bool）：本次挑战是否涉及"图像事实争议"。**只有 true 时才允许 Round 3 反驳调用回传原图**。
- `image_dispute_detail`（条件必填）：当 `needs_image_for_rebuttal=true` 时必填，简述争议的图像点。
- 默认应为 false（节省成本）。挑战方为了让自己的挑战立得住，只在确实需要时才设 true。
- 如果挑战方为省钱不声明，反驳方手里没图、反驳质量会低、裁判会判他输 → **反向激励挑战方诚实声明**。

### Round 3 反驳调用规则

- 检查对应 R2 challenge 的 `needs_image_for_rebuttal` 字段：
  - `true` → R3 prompt 里附图路径，反驳方 Agent 必须读图。生成的 rebuttal 数据里加 `image_attached_for_rebuttal: true`。
  - `false`（默认）→ R3 prompt 不带图，反驳方只针对挑战的文本内容反驳。生成的 rebuttal 数据里加 `image_attached_for_rebuttal: false`。
- `_gen_moco.py` 的 V4/V5 校验会拦下"声明了 needs_image 但实际没传"或"没声明却偷偷传图"的事故。

### debate-data.json 多模态字段（顶层 + model + clash）

**顶层新增**：
- `vision_mode`（必填）：`"full"` / `"r1_only"` / `"none"`。有图必须 full 或 r1_only。
- `question_image_paths`（必填，数组）：所有原图的绝对路径。

**每个 model 新增**：
- `image_seen`（必填，bool）：该 model 在 Round 1 是否真看到了图。任一为 false → 整场 V3 校验拦下。

**每个 challenges_received[*] 新增**：
- `needs_image_for_rebuttal`（默认 false）
- `image_dispute_detail`（条件必填）
- `image_attached_for_rebuttal`（必填，bool）：R3 反驳时实际是否回传了图。

### V1-V5 vision 校验（`_gen_moco.py`）

| 编号 | 检查 | 失败时 |
|---|---|---|
| V1 | `vision_mode ∈ {full, r1_only, none}` | exit 3 |
| V2 | 有图但 vision_mode=none | exit 3 |
| V3 | 4 家 image_seen 必须全为 true | exit 3 |
| V4 | R3 attached image 但 R2 没声明 needs | exit 3 |
| V5 | r1_only 模式下声明了 needs 但实际没传 | exit 3 |

## Model Color Scheme

Use these colors for model badges:
- Claude / Anthropic models: `#D97706` (amber)
- GPT / OpenAI models: `#10A37F` (green)
- Gemini / Google models: `#4285F4` (blue)
- DeepSeek models: `#7C3AED` (purple)
- Qwen / Alibaba models: `#E11D48` (rose)
- Other models: `#6B7280` (gray)

## Resources

### scripts/
- `_gen_moco.py`: Main HTML generator. Reads a `debate-data.json` and renders the final `moco-{timestamp}.html` using the template and `md2html.py`. CLI: `--data`, `--output` (required); `--template`, `--md2html`, `--python` (optional).
- `md2html.py`: Lightweight Markdown-to-HTML converter supporting headings, lists, code blocks, tables, blockquotes, bold/italic, links, images, and math notation.

### assets/
- `compare-template.html`: Light-themed HTML template with responsive card grid, multimodal content rendering, recommended-answer highlighting, and debate panel UI.
