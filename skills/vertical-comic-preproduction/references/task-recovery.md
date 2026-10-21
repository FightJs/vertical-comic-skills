# 总控等待、收尾与恢复

本机制管理已授权的子任务，不创建子agent、不提交生图、不增加预算。总控仍在当前轮次使用宿主的等待工具。协调JSON是检查点，不能唤醒会话或发送系统通知；不得声称“结束会话后后台会自动继续”。

## 接线

prepare/receive在显示目录旁建立`00_任务协调/coordination.json`。旧RV通过安装版脚本初始化旁路目录；不替换冻结工具，不重建RV。先登记当前已有子任务（包括非必要但仍在写入的任务），没有子任务时清单可以为空；不得靠空清单隐瞒活动写入者。登记后按宿主真实ID等待，不重复派发。

```text
python scripts/task_coordination.py init --directory <RV/00_任务协调> --display <RV/00_显示进度>
python scripts/task_coordination.py event --directory <协调目录> --revision <当前revision> --event <事件JSON>
python scripts/task_coordination.py resume --directory <协调目录>
python scripts/task_coordination.py finish-check --directory <协调目录> --revision <当前revision> --zip <正式ZIP>
```

`event_id`由调用者生成且重试保持相同；同ID相同内容幂等，同ID不同内容拒绝。每次新事件携带当前revision，旧总控写入被拒绝，不覆盖新记录。事件仅由总控写入；子agent汇报观察和产物，不直接改协调JSON。证据格式均为`{"path":"绝对文件路径","sha256":"实际SHA256"}`。事件支持：

- `register`：task_id、host_id（实际宿主agent/线程/会话标识）、assignment、required（默认true）。记录RUNNING。职责须写准确书话格范围；普通子任务不等同持久线程，不混用标识或工具。
- `observe`：task_id、status、evidence、artifacts。status为RUNNING/UNKNOWN/RESULT_READY/FAILED/STOPPED。evidence保存真实宿主查询结果与来源；RESULT_READY只在确认执行结束且有实际成果时使用，artifacts为成果引用数组。失联不推定停止，超时不推定失败。
- `accept`：task_id、evidence、reviewer、conclusion。执行者结束后，总控实际核对成果与原门禁，再保存验收证据；不是复制子agent的“完成”一句话。失败项继续修复并更新观察，不提前accept。
- `checkpoint`：next_action、evidence。保存当前未完成工作及恢复依据，不授予执行权限。

`resume`只读取，返回各任务、阻塞与下一步。恢复时必须先查询宿主现态，再登记observe；不能因为记录显示RUNNING就假定旧会话还活着，不能因为工具找不到就重发。确认旧写入者停止前不换owner。图像请求另按原生产账本处理UNKNOWN、占槽及预算，协调状态不取消远端请求。

`finish-check`先核对全部已登记任务：必要任务须ACCEPTED；非必要任务也必须ACCEPTED或有证据确认STOPPED。随后调用原production_progress.complete实际验证ZIP及准确源范围，绑定ZIP哈希后返回READY_TO_DELIVER。失败则继续处理；READY_TO_DELIVER只表示可交付，不表示用户已收到。最终答复附真实ZIP。任一新事件清除旧收尾记录。新运行不能直接调用显示complete绕过协调检查，旧无协调目录运行保留原兼容路径。

该检查无法发现未登记的agent，也不能从Python层阻止模型发送最终答复；总控必须登记完整任务清单并遵守收尾顺序。它不是生产写入锁，不保护未遵循协议的外部写入者。最终验收期间停止新增工作；必要的新工作登记后重做收尾。

## 宿主能力与自动跟进边界

当前会话可用的等待工具能等待活跃子agent或已yield的工具cell；使用对应宿主工具，保持同一调用，不能重新创建原Promise。超时后继续推进/等待，不结束轮次。普通子agent工具未提供跨结束轮次、应用关闭后的持久唤醒保证。

桌面宿主若提供heartbeat定时跟进，也不代表能恢复旧子agent、内存Promise或发送已送达的系统通知。默认不创建。用户明确要求自动跟进时，先核验同线程唤醒、原任务可访问性、双总控竞争、应用关闭/休眠以及通知送达，再在明确支持的范围启用；不支持时记录为未验证，不用shell后台循环或自动生图重试替代。该能力测试不在日常生产中偷偷进行。

当前交付能力：持久化检查点、主动轮次内等待、恢复对账、收尾检查。自动唤醒和离线通知尚未验证，不作为完成承诺。
