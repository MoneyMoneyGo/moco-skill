# MoCo — Multi-Model Compare & Debate

> 让 4 个 AI 同台答题、互相找错、各自反驳，再综合评分挑出最佳答案。
> 适合方案评估 / 选型决策 / 避免单模型偏见。

一个 [WorkBuddy](https://www.codebuddy.cn/) Skill，由[银纸](https://github.com/MoneyMoneyGo)制作。

---

## 🚀 在 WorkBuddy 里一键安装

跟 WorkBuddy 说这句话就行：

```
帮我装 MoneyMoneyGo/moco-skill
```

主智能体会自动帮你 clone 到 `~/.workbuddy/skills/moco`，立即可用。

---

## 💬 怎么触发

装好后，在 WorkBuddy 里说以下任一种：

- `moco: 如何更好地训练逻辑能力？`
- `模型 PK: React vs Vue 我该选哪个？`
- `几个 AI 一起答：这段 SQL 有什么问题？`
- `多模型对比: 给我起 5 个产品名`

MoCo 会：

1. **Round 1**：4 个内置模型并发答题（Claude Sonnet / GPT 5.4 / Gemini 3.0 Pro / DeepSeek V3.2）
2. **Round 2**：互相挑错
3. **Round 3**：被挑战的一方反驳
4. **Round 4**：Claude Opus 4.7 (1M) 作为裁判独立评判每场挑战
5. 生成一份可视化 HTML 报告

---

## 📊 消耗参考

MoCo 一次约等于 **~250-700 积分**（≈ 25× 单次质询），详细见 [COST_REFERENCE.md](./COST_REFERENCE.md)。企业版 WorkBuddy 月配额 10 万积分 / 人，够你跑 150+ 次。

> 🧑‍💻 **省积分小贴士**：把 WorkBuddy 顶部选择器切到 `claude-sonnet-4.6-1m`，MoCo 的主智能体编排成本自动减半，不影响参战阵容质量。

---

## 📁 这个 repo 里有什么

| 文件 | 用途 |
|---|---|
| `SKILL.md` | 主智能体编排规则（WorkBuddy 读这个来执行 MoCo） |
| `scripts/_gen_moco.py` | HTML 报告生成器 + 数据校验（H1-H4 硬校验 + S1-S5 软告警 + V1-V5 多模态校验） |
| `scripts/check_lineup.py` | 阵容一致性门禁（换模型时守门员） |
| `assets/compare-template.html` | HTML 报告模板 |
| `examples/` | 历史示例报告 |
| `moco-regression-tests/` | 回归测试 fixture（13 份正负样本） |
| `COST_REFERENCE.md` | 积分消耗参考表 |
| `CHANGELOG.md` | 版本变更记录 |

---

## 🔗 相关

- 项目主页：<https://github.com/MoneyMoneyGo/moco-skill>
- WorkBuddy 文档：<https://www.codebuddy.cn/docs/workbuddy/Overview>
- 问题反馈：[Issues](https://github.com/MoneyMoneyGo/moco-skill/issues)

---

*Powered by Claude · Made by [银纸](https://github.com/MoneyMoneyGo) · Licensed under MIT*
