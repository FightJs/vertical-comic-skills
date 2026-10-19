# 执行者两级监控：worker_watchdog_v1

只用于启用 `incremental_runtime_v1` 的新任务或已显式迁移的任务。总控监控每话唯一执行者；不再增加监控agent。阈值按**无实际进展时间**计：准备/镜头/包及图片自审/诊断默认5分钟T1、12分钟T2；单个已提交但未返回的生图请求默认15分钟T1、30分钟T2。阶段总耗时可报告，但持续有真实进展时不强制跳过。

`watch-check`另报 `stage_elapsed_seconds` 和 `idle_seconds`；阶段总耗时只供总控评估瓶颈，不触发自动跳过。超过两级阈值后也只影响调度决策，不把用户待审时间算成执行者怠工。

T1发一次明确提示，要求执行者说明当前阻塞、立即可完成的下一步和在途请求。T2由总控检查真实状态：先读本话状态、许可和实际返回；再处理独立就绪格或其他话，延后可选工作；本话若已完成本地实际审查，则交回总控做适用的跨话比较。只有旧执行者已停止写入、检查点保存、没有RESERVED/IN_FLIGHT许可和RESULT_UNKNOWN格，且新执行者能按原批准依据及原轮次预算继续时，才考虑换owner。换owner后仍用原 `parallel_dispatch.py` 的唯一owner、carry_forward和完整预检；不要只改worker_id或共享epoch。真正共享版本变化继续按冻结合同办理。

总控可用 `python <scripts>/parallel_dispatch.py --state <本话/00_输入审计/生产流程.json> --handoff-check --old-writer-stopped` 作只读交接前检查；只有真实停止旧写入后才传最后一个标志。这个检查不换owner、不批准旧图或新请求，下一执行者仍要重新通过原门禁。

## 真实进展与去重

每话在 `00_输入审计/worker_watchdog.json` 保留轻量进展账本，不复制图或参考。进入阶段时先登记一次 `stage_started`；之后只有保存并校验实际审计文件、资产、镜头、包、请求证据、图片、六项QA、诊断或本话验收，才能登记相应事件。提交请求与返图、审图是不同事件。QA的FAIL也是一次完成的审查，但不把图标为通过。文件路径必须在本话目录内，SHA256须匹配；同一阶段、类型、路径和内容的重复登记不会重置时钟。反复读取、口头心跳、调用计划、未保存的候选不算进展。

`production_runtime.py --action watch-progress --watch-event <事件.json> --state <本话/00_输入审计/生产流程.json>` 登记。事件示例：

```json
{
  "stage": "shot_design",
  "kind": "shot_saved",
  "blocker_id": "B:P012",
  "wait_kind": "NONE",
  "evidence": {"path": "01_镜头改编_CANDIDATE/镜头改编表.json", "sha256": "真实文件SHA256"}
}
```

阶段有 `input_audit`, `visual_assets`, `shot_design`, `package`, `generation`, `image_review`, `repair`, `delivery`。等待类型有 `NONE`, `HUMAN_A/B/PACKAGE/C/D/STATE`, `CROSS_EPISODE`, `SERVICE`, `DEPENDENCY`。记录人工待审时按真实门禁选择对应类型；待人确认不触发执行者空闲警报。跨话等待如果本话图片和QA已完整，记录 `local_episode_complete:true`；执行者提交本话结果后结束本轮任务，由总控维持跨话复核，不在执行者里空转。

总控在等待子agent时使用不超过60秒的有界等待，然后检查有变化的话与到阈值的话；收到实际完成/待审事件立即处理，避免空转轮询。运行 `--action watch-check`；返回的事件ID只有**实际发送了提示**才写入数组文件并用 `--action watch-ack --watch-alert-ids <ID数组.json>` 确认；重启后同一阻塞点的T1/T2不会重复催促。请求事件ID也可用于合并 `async_generation.js` 的 `onLongRequest(job,item,level)` 实时通知。T2输出是诊断建议，不是跳过许可。`--independent-work-pending` 仅当已查有可独立推进事项时使用；有在途请求而无独立工作时，阶段空闲计时暂停，请求自身继续计时。

```text
python <scripts>/production_runtime.py --state <本话/00_输入审计/生产流程.json> --action watch-check
python <scripts>/production_runtime.py --state <本话/00_输入审计/生产流程.json> --action watch-ack --watch-alert-ids <已实际发送的事件ID数组.json>
```

`runHalfWave` 传 `onLongRequest`，并把配置中的请求秒数乘1000作为 `requestWarningMs` / `requestEscalationMs`。回调可通知总控，却不能释放并发槽、取消或重复提交原请求；原Promise和保存回调继续。请求结果未知先查证，禁止自动重试。`dispatch_pause:true` 由总控在本话job中设置，仅阻止新请求，既有许可、真实返回和QA仍要收尾；解除后重新运行完整预检。

被跳过的只可是不影响必需证据的可选工作或当前受阻格以外的独立就绪工作。A/B/包、首次实图状态、C/D、真实前格依赖、规则记忆、六项QA及唯一自动修正预算始终有效。技术PASS、监控建议、静默、等待超时都不能代替用户批准。

监控报告应区分服务在途、等待保存、待QA、依赖/人工等待与输入/运行故障，基于实际保存事件定位下一动作。没有新证据不反复询问owner；先恢复可操作的独立就绪工作。技术门禁失败不是视觉FAIL，不能据此自动重发。onPersisted可保存真实保存完成时间，T1/T2仍不撤销在途Promise、扩大授权或回收未知槽。
