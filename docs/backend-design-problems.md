# 后端设计问题记录

记录于 2026-05-08，覆盖 ReAct loop、确认卡（pending actions）、active offer 三个模块。

---

## 一、ReAct Loop

### 1. Tool results 不走对话格式，多步推理受限 ✅ 已修复

**文件**：`agent_runtime.py`, `providers/bailian.py`

**现象**：每轮 LLM 调用的工具结果被注入到 `context["agent_loop"]["tool_results"]` 这个 flat JSON 字段，LLM 通过读 JSON blob 而非对话历史来理解因果链。标准 ReAct 应是 `assistant（tool_calls）→ tool_result → assistant` 交替轮次。

**修复**：在 `ExtractionInput` 增加 `prior_turns` 字段，`AgentRuntime` 累积每轮的 `(raw_output, tool_results)` 对，bailian provider 把这些转换成真正的多轮 `assistant/user` 消息序列传给 LLM。

---

### 2. Human confirmation 打断 loop 后 continuation 割裂 （暂不修，记录）

**文件**：`pending_actions.py:_run_continuation`

**现象**：用户确认/放弃 pending action 后，`_run_continuation` 启动一个全新的 `AgentRuntime.run()`。新 run 的上下文重新 build，原始 loop 中间状态（如本轮尚未处理的其他问题、已执行的工具链）丢失。

**根因**：loop 遇到 human confirmation 即 return，没有"暂停点恢复"机制。continuation 是近似替代，不是真正的恢复。

**影响**：用户说"中午吃了炒面，顺便帮我规划晚餐"——炒面确认卡弹出后用户确认，continuation 只处理确认结果，"规划晚餐"被遗忘。

**潜在方案**：在 `dialogue_state` 里保存"待续任务"，continuation 时恢复。代价较高，暂不实施。

---

### 3. Loop limit 在执行工具前触发，最后一轮工具永远不运行 ✅ 已修复

**文件**：`agent_runtime.py:_loop_limit_reason`

**现象**：`_loop_limit_reason` 检查 `model_turn >= max_model_turns` 在工具执行**之前**触发。最后一轮 LLM 决定调用工具，但工具从未执行，直接返回"步骤太多"。

**修复**：从 `_loop_limit_reason` 移除 `max_model_turns` 检查，改为在工具执行**之后**检查是否达到最后一轮。工具在最后一轮也能正常执行，结果纳入响应。

---

## 二、确认卡（Pending Actions）

### 4. `update_pending_action` 被错误归入 `HUMAN_CONFIRMATION_TOOL_NAMES` ✅ 已修复

**文件**：`types.py:43`

**现象**：
```python
HUMAN_CONFIRMATION_TOOL_NAMES = RECORD_TOOL_NAMES | {"update_pending_action"}
```
`update_pending_action` 只是更新草稿，不产生新的 pending action。但因为它在这个集合里，只要 update 后状态是 `pending_confirmation`，loop 就停止，LLM 无法接着 commit。

**影响**：破坏"LLM 自动修复草稿 → commit"的流程（如"把份量改成 200g 然后保存"应该一步完成，但实际需要两轮用户交互）。

**修复**：从 `HUMAN_CONFIRMATION_TOOL_NAMES` 移除 `update_pending_action`。

---

### 5. Grounding evidence_text 子串匹配脆弱（暂记录，小优化，有缓解）

**文件**：`extraction_service.py:_grounding_references_active_pending_action`

**现象**：`active_pending_action` grounding 验证用 `evidence_text in json.dumps(action)` 做子串匹配。LLM 生成的 evidence_text 格式稍有差异（数字格式、空格、标点）即失败导致 tool_call 被 reject。

**现有缓解**：系统 prompt 要求 `source_id` 填 `pending_action_id`，`source_id` 匹配优先（不依赖 evidence_text）。LLM 遵循指令时不触发此问题。

**后续**：若实际出现大量误拒，可考虑标准化 evidence_text 后再比较，或提取 pending action 关键字段单独匹配。

---

### 6. `grounding_requires_confirmation` warning 在 update 后残留 ✅ 已不适用

**原文件**：`pending_actions.py:_apply_status_from_draft`

**结论**：全库搜索无任何代码生成 `grounding_requires_confirmation` warning，该 warning 类型已不再产生。问题源头消失，无需处理。

---

### 7. `commit_pending_action` 与 `commit_pending_actions` 功能高度重叠 ✅ 已解决

**原文件**：`types.py`, `extraction_service.py`

**结论**：两个 commit 工具已从 `ToolName` 和工具执行逻辑中完全移除。确认操作改由用户通过 REST API 按钮完成，不再是 LLM 工具调用。system prompt 明确写入"禁止调用 commit_pending_action"。

---

## 三、Active Offer

### 8. Offer 创建失败时静默，无 log ✅ 已修复

**文件**：`dialogue_state.py:active_offer_from_patch`

**现象**：`active_offer_from_patch` 在 offer 缺少 `topic`/`expected_followup`/`surface_text` 时直接返回 `None`，无任何 log。LLM 以为 offer 创建成功，但实际没有，下轮无法承接。

**修复**：在返回 `None` 的各分支增加 `logger.debug`，记录失败原因。

---

### 9. One-turn offer 过期无通知 ✅ 已不适用

**结论**：active_offer 功能已从 `dialogue_state.py` 和 `conversation_context.py` 中完全删除，entire offer 机制不再存在。

---

### 10. Active offer 与 active pending actions 优先级未定义 ✅ 已不适用

**结论**：active_offer 功能已删除，问题不再存在。`prompt_payload.py` 的 `CONTEXT_CONTRACT` 已加入 `active_pending_actions` 完整优先级规则（优先处理确认卡修改/放弃，不相关时在 assistant_text 结尾提醒）。

---

## 四、已知但暂不处理

### 11. `ExtractionService.process_message()` 不在主流程中（保留供测试）

单次 LLM 调用的方法，主流程已由 `AgentRuntime.run()` 替代。但测试中大量使用，保留。

### 12. Continuation 里 `event_message_id` 双重用途（低优先）

`pending_actions.py:_run_continuation` 用同一个 event_message_id 作为 `AgentRuntime.run()` 的 `message_id`，该 ID 既代表事件消息又作为 extraction 的 source_message_id，破坏单一职责。影响面小，暂记录。
