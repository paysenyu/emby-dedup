### Webhook 闭环重设计方案（手动全量同步 + webhook 增量双轨）

#### 1. Summary
- 保留你定义的双轨：  
  - `手动同步` = 全量对账（慢但最稳）。  
  - `webhook` = 日常增量（新增/删除实时维护）。
- 现有主要痛点不是删除接口失败，而是“删除成功确认链路不稳定 + 前端日志语义混淆”。
- 新方案将删除确认改为“三段式”：`DeleteVersion 204` -> `等待Webhook` -> `主动回查Emby兜底`，并把 UI 只展示“每个目标最新状态”。

#### 2. Key Changes
- 删除状态机重构（队列为唯一真相）  
  - 状态固定为：`pending -> in_progress -> done | failed`。  
  - `204/200` 仅表示“请求已受理”，绝不等于成功。  
  - 达到 webhook 等待上限后，执行“主动回查 Emby item 是否存在”：  
    - 不存在：标记 `done`（消息写明 `confirmed by probe`）。  
    - 存在：标记 `failed`（消息写明 `webhook timeout + probe exists`）。
- webhook 处理语义统一  
  - 删除事件（`deep.delete/library.deleted`）：按 `delete_target_item_id -> emby_item_id -> path` 匹配并落 `done`。  
  - 新增事件（`library.new/new/created`）：先入库，再走“延迟批量分析”（30-60 秒防抖），不做每条立即重跑。  
  - 所有 webhook 必须幂等：同一事件重复到达不会重复删除/重复入库。
- 新增“增量分析调度器（防抖）”  
  - webhook 新增事件触发 dirty 标记。  
  - 在窗口期结束后统一跑一次分析。  
  - 若窗口内持续有新增，延后到最后一次事件后再执行。
- 日志与 UI 逻辑（按你已确认）  
  - 执行日志默认“每个删除目标仅保留最新状态”。  
  - 历史状态不默认展示，避免“同目标成功/失败并存”。  
  - 状态展示只由 `delete_status` 驱动，不再由 message 猜测。  
  - “刷新后保留”保留，但只保留“最新态视图”的最近 N 条（建议 20）。

#### 3. Public/Interface Changes
- 后端接口行为（不改现有路由路径）  
  - `GET /delete/queue/status` 返回中保持 `delete_status` 为权威字段。  
  - `message` 增加可识别语义：  
    - `Webhook confirmed delete (...)`  
    - `Confirmed by Emby probe (...)`  
    - `Webhook timeout and Emby item still exists (...)`
- 内部能力扩展  
  - Emby client 增加“按 ItemId 存在性查询”方法（供删除兜底回查）。  
  - webhook 新增事件改为“延迟批量触发分析”而非每条立即分析。

#### 4. Test Plan
- 删除链路  
  - `DeleteVersion=204 + webhook到达` -> `done`。  
  - `DeleteVersion=204 + webhook缺失 + probe不存在` -> `done`。  
  - `DeleteVersion=204 + webhook缺失 + probe存在` -> `failed`。  
  - 重复 webhook 同一 item 不重复写脏数据（幂等）。
- 新增链路  
  - 多条 `library.new` 在窗口内只触发一次分析。  
  - 新增后可在下一次打开 UI 时看到分析结果更新。
- 日志/UI  
  - 同一 `delete_target_item_id` 最终只出现一条最新记录。  
  - 刷新后仍保留最近 N 条最新记录，不出现“旧失败+新成功并排”。
- 回归  
  - token 校验（query 优先，body fallback）与 multipart/json 兼容不退化。  
  - 异常 payload 继续返回安全响应，不抛 500。

#### 5. Assumptions & Defaults
- 手动同步仍为全量校准入口，不被 webhook 替代。  
- 新增事件分析采用“延迟批量触发”，默认窗口 45 秒（可配置）。  
- 删除兜底回查默认在 webhook 超时后立即执行一次（后续可扩展为最多 2 次短间隔回查）。  
- 执行日志默认仅展示“每目标最新状态”。
