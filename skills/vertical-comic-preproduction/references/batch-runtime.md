# 固定批次版本与容量租约

本流程用于新整话RV。当前安装代码只维护和创建快照；生产读取本批唯一快照中的五件套、参考文档和规则正文。安装目录以后更新不影响本批。恢复继续用原manifest，快照被改HOLD；不要修改旧RV哈希或逐话复制检查器。

## 开批一次创建

```text
python <安装scripts>/runtime_snapshot.py --destination <本批总控目录/运行快照> --config <使用配置.json>
python <快照scripts>/init_preproduction.py --config <使用配置.json> --runtime-snapshot <运行快照/manifest.json> --output <本话新RV> --book <书名> --episode <话号> --backend codex_builtin_imagegen
```

第一条只运行一次，保存返回的manifest路径/哈希与scripts路径；各话共用。所有后续检查、规则读取及Skill正文均从快照路径运行或读取，不混用安装版。快照保持skills/<五个目录>结构，跨skill相对链接仍有效。规则root改为快照memory，索引和正文内容不改；保留原来源。初始化仅建未批准模板。旧配置未启用新策略仍按原合同；启用snapshot_policy时缺少--runtime-snapshot会拒绝初始化。

备份与快照不复制生产原图，使用文件副本而非指向可写安装文件的硬链接。原图/参考优先共享只读来源，保持准确原路径/哈希；空间不足先暂停新提交并保存已返回图，不删除其他项目或会话。

## 总控分配一次容量

保留现有parallel_episodes_v1、jobs、frozen_inputs、shared_files和实际核定max_inflight。新配置runtime.dispatch_policy=episode_slot_lease_v1，每话仍有唯一owner、active_batch_id=EPISODE和本话max_inflight。总控准备覆盖所有job_id的额度JSON，未分配为0；全局合计不超过核定容量：

```text
python <scripts>/slot_leases.py --control <共享control.json> --expected-sha256 <当前control哈希> --allocations <各job额度.json>
```

总控单写control；分配后各话不写共享control。每话调用原批量入口领取本话租约内的唯一请求回执：

```text
python <scripts>/episode_dispatch_queue.py --state <本话生产流程.json> --expected-state-sha256 <当前状态哈希> --expected-control-sha256 <当前control哈希>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action compile --panels <reserved返回格号>
```

租约模式把permit账本放本话state.dispatch_ledger；原包、轮次和attempt仍准确绑定，旧共享permit模式完全按原合同。编译通过后用原commit登记IN_FLIGHT，脚本在同一次本话原子事务把对应回执从RESERVED推进到IN_FLIGHT；随后立即实际调用一次。这个状态表示已进入提交窗口，不证明服务已收到。该窗口崩溃先查原请求，不能自动重发。

真实返回保存、原参数/输出及执行证据核验后，用原commit登记GENERATED，同时本话回执成为COMPLETED并绑定输出哈希；实际生图槽释放，不等模型审图。CALL_FAILED沿原真实失败证据登记，RESULT_UNKNOWN继续占槽，不按超时回收。实际看图之后再登记VISUAL_PASS/FAIL，回调不填PASS。取消也不证明原请求未执行，须核查在途。

编译失败且仍为RESERVED、PENDING/REPAIR_AUTHORIZED的确定未提交请求，才可释放并恢复原包：

```text
python <scripts>/slot_leases.py --state <生产流程.json> --expected-sha256 <当前状态哈希> --release-panels <准确格号>
```

租约内完成槽自动可复用，不再向根节点逐请求同步RESERVED/IN_FLIGHT/COMPLETED。新的就绪格仍完整预检，不能拿旧compile结果调用变化后的包。

## 重新分配与异常

第一版固定额度，按实际空闲事件再分配，不轮询抢占。重新分配替换所有租约，先停止旧写入者并保存状态，确认没有任何预留/在途/未知请求，再用--old-writers-stopped和真实control哈希调用allocate。旧账本和租约历史保留，旧回执不改名升级；旧epoch返回继续原carry-forward要求。

快照不会让会话在休眠、退出或中断后自动后台运行。恢复核验快照、state、真实输出和未知请求，再按原授权继续。T1/T2只诊断，不增加预算、不伪造批准、不释放未知槽。人工等待不催执行者；本话仅等跨话比较时交回总控结束本轮。

## 原未知请求查证

未知请求保持原attempt和调用证据。找回真实输出或有实际服务证据确认无输出时，准备unknown_result_resolution_v1报告：panel_id、attempt_id、round_id、original_call_evidence与原状态一致，status=REVIEWED，reviewer/evidence/source_locator，service_evidence为真实查证文件引用；conclusion只用RESULT_RECOVERED或CONFIRMED_NO_OUTPUT。

使用原commit附加--resolution <本话相对报告路径>和准确updates。找回图仍验证完整实际输入/执行/输出证据，确认无输出仍须新CALL_FAILED证据；原未知记录和查证报告保留。仅查不到返回或超时不能作无输出结论；此入口不重发、不加新attempt、不重置预算。

## 同一范围的权威上下文

新运行在production_runtime与整话门禁中共用scoped_inputs.resolve_context：核对源序/计划后读取准确范围的基准、镜头和进度。它只读，不从当前镜头重写历史attempt的package_manifest、实际输入、输出或QA。恢复、预检和交付均从冻结入口执行；安装目录修改不进入既有快照。上下文或版本错误先修技术依据，不按视觉失败触发生图。


总控任务记录、真实等待、收尾检查与中断恢复统一见[任务协调与恢复](task-recovery.md)。新运行最终交付使用task_coordination.py finish-check，不能以进度摘要、子任务口头完成或等待超时结束轮次。
