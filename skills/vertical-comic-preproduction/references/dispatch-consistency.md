# 派单一致性与短锁协议

普通RV继续原锁路径。`runtime_capabilities.json`声明可选 `managed_immutable_dispatch_v1`，默认关闭；安装新版、候选目录或头文件存在均不会启用。只有实际确认旧写入者停止、输入发布后不可变、保存器使用统一入口的整话租约运行，且剩余请求已完整技术准备时，才可显式准入。平台CI与正式发布状态见本版本发行说明，本地通过不能替代三平台验收。

## 一致性基础与支持范围

使用不可变输入版本及受锁状态引用。所有参与者遵守“候选可编辑、已采用版本只新增”；不允许编辑器或未知脚本继续覆盖活动输入。SHA256名称、只读属性和Python审计钩子都不是操作系统安全沙箱。不能证明写入协议时保持旧路径；已有新协议标记的运行遇到不支持入口则HOLD，不删标记或恢复旧state降级。

短锁只支持 `episode_slot_lease_v1`，本话回执、请求ID与账本在同一次state原子替换中提交。旧共享permit的两文件模式保持原实现。共享control及本话state仍按原路径排序取得 `.dispatch.lock` / `.runtime.lock`。预检不持这两把锁；提交只复核完整state/control版本、准入身份并写回执。批准撤销、暂停、取消、租约变化及QA/返回均会改变对应完整版本，因此旧预检作废。首版不裁剪“无关字段”，默认不重试，显式最多重试两次；只重新校验，绝不重发生图。

`managed_dispatch.py`是新协议唯一受支持的运行入口。原 `reserve_ready()`、状态写入、租约、批准、配置和接包入口在其受控上下文之外拒绝新标记；null、false和未知policy也拒绝。内部上下文只允许本次核验过的准确admission ID，不能成为跨话全局绕过。

## 阶段2：不可变发布基础

`dispatch_publication.py`保存精确bytes，manifest绑定书话、完整成员、大小和哈希。内容寻址版本只新增，拒绝链接、成员变化、非法名称、大小写别名及路径越界。发布区独立加锁；不得在共享调度锁内遍历全部输入。

`candidate.json`仍只是候选头；CAS包含revision和前一头哈希，A→B→A不能复用旧令牌。候选发布本身不授予批准或生产许可。未引用版本保留，不自行删除。生产权威来自准入协议、实际门禁与原子state/ledger提交，不来自候选status。

## 阶段3A：批准权威写入

`authority_updates.py:update_approvals()`保留真实proof字节，发布新索引及撤销记录，再一次CAS绑定state。撤销按原证明的规范化内容指纹作用于索引、嵌入proof及原委托下的执行者决定；再次登记同一proof不能复活。新决定必须有新的准确消息证明。脚本不认证消息，不生成用户批准，也不提供全书原子撤销。

新证据使用原子不覆盖硬链接发布，不支持时HOLD。建立 `authority_policy=locked_authority_v1` 后，状态提交、返修、诊断、释放和批准使用相同排序的共享/本话锁。首次策略切换被旧预读遗漏时，锁内拒绝，不反序补锁。实际toolchain和冻结入口必须匹配，不能用新安装脚本给旧冻结writer加策略标记。

撤销与IN_FLIGHT登记竞争时，先完成者落账，后者旧state CAS失败。撤销先完成则重新检查仍拒绝新提交；提交先完成则后续撤销保留原attempt和占槽，不能据此断定服务没有收到请求。

## 阶段3B：固定读取闭包与候选绑定

`immutable_inputs.py capture/replay`经标准读取事务、并行上下文及 `staged_workflow.evaluate()`执行真实门禁，保存精确文件字节、原逻辑路径和查询结果。读取事务结束并复核后才发布。覆盖已观察到的文件、缺失、目录成员与过滤条件、链接解析目标、实际规则/工具及检查模式选项；批准无匹配绑定固定索引正文和准确查询范围。未访问的分支不假定覆盖，新增查询HOLD，无实时补读。

重放保留原逻辑身份和批准字节，仅底层I/O及PIL读取投影副本，重新执行原门禁，不存跨命令PASS，不把候选模式当正式权限。实际执行toolchain必须匹配。读取失败保持粘性，不能被上层捕获后继续放行。审计钩子仅用于受信检查器旁路检测，不保证捕获任意原生扩展、预开句柄或全部元数据操作。快照含本机绝对逻辑路径；跨机器/系统先接包重绑定，再捕获。

候选 `bind` 在锁外重放完整reservation范围，锁内复核state/control/head并写独立 `input_read_head.json`，避免自引用哈希。`head_status()`诊断过期，不能代替完整发布校验。它仍返回 `BOUND_NOT_DISPATCHABLE`；不作为新协议准入命令。

### 剩余写入者的收敛边界

| 环节 | 受支持入口及约束 |
|---|---|
| 创作/审查生成器 | 在新候选路径制作；准入时冻结实际读取闭包。禁止覆盖采用的旧文件。原四项全局输入、规则、工具、owner/epoch及运行合同在同一准入job保持固定。需要变更时显式建立新运行并保留历史尝试与预算；不能借短锁热换冻结引用。 |
| 批准/撤销 | `managed_dispatch.py --action approvals`复用authority版本发布与锁；不直接编辑approval_index/gates。 |
| 暂停/HOLD/取消 | `--action control`复用control_updates，锁住完整owner集合并提供准确哈希，只改允许的停止控制；取消不静默恢复。 |
| 租约/释放 | `--action allocate/release`复用原真实租约约束；活动、已提交或未知请求不能按超时回收，也不能转移owner/epoch。 |
| 图片/请求/响应/QA文件 | `--action evidence`接收真实来源路径和准确SHA，保存 `managed-<内容SHA>.<扩展名>`，保留原父目录及相对解析基准，以不覆盖硬链接发布；原文不改写。调用方据返回引用构造下一份实际证据。普通可变结果文件不准入。 |
| 返回/QA | `--action save`先原子保存稳定save_id的真实updates意图，再走原commit完整门禁。最多三次重读状态处理CAS冲突，只重试登记，不重发生图。相同save_id不同内容拒绝；同内容已落账返回UPDATES_ALREADY_SAVED。 |
| 返修/诊断 | `--action repair/diagnosis`复用原轮次、失败证据与预算门禁，新授权/包/诊断先独占发布；不允许旧返回覆盖新attempt。 |
| 工具/规则更新、接包 | 建立新的冻结版本，不能给活动RV热替换。配置/接包不自动带入新协议标记；已有调用的迁移须独立记录。 |

原始准入输入字节及正负查询在每次入口核对；新结果、批准和修正使用新路径及受锁state引用。单次核验共享只读事务减少工具/基准的重复计算，事务在任何生产写入前结束。新协议对未知写入者没有额外承诺，不能仅填写声明后让旧保存器继续改JSON。

## 阶段3C：短锁领取与宿主接线

CLI统一形式：`python -B managed_dispatch.py --state <本话状态> --action <操作> --arguments <准确参数JSON>`。不从自然语言推断参数，不调用图片工具。

`admit`必须提供当前 `expected_state`、`expected_control`、`old_writers_stopped=true`、`immutable_inputs=true`、`saver_protocol=exclusive_evidence_v1`及实际reason。拒绝活动预约、在途、未知请求及仍须补包/等待前图的未就绪范围；这些运行保持旧路径，不加标记。记录原状态哈希、原control版本及基础快照。准入state标记与基础快照一并绑定；未知/旧工具拒绝。准入确认仅在确实满足条件时填写，不替用户或宿主编造。

`reserve`提供两份当前哈希、稳定 `request_id`、可选 `max_count`、`max_retries=0..2`。全局条件和真实依赖仍完整检查，候选按原优先序拿够即停。已有不可变基准字节复用对象，新读取字节发布成组合闭包；每次仍重新运行门禁，没有永久PASS缓存。gate、复制和发布验证均在共享锁外。提交时同锁复核完整版本及身份，原子登记回执。重用request_id先找原回执；不同max_count拒绝，释放后要新请求也必须用新ID。

`compile`保留正式包批准及完整检查，输出 `managed_submission_required` 与准确回执。宿主运行 `async_generation.js` 时必须提供 `onBeforeInvoke`：调用 `--action submit`，准确传 `panel_id/attempt_id/round_id/permit_id`。只有首次新登记 `SUBMISSION_REGISTERED`、`invoke_allowed=true` 且scope/attempt/回执均吻合，才调用真实图片工具。重复/丢失登记响应返回ALREADY_REGISTERED，不再次授权调用。不能把幂等登记误当幂等生图。

调用前登记不得替换已经预检的包，QA不得替换原生成图/执行包；只能登记对应阶段的证据。真实工具返回后，宿主保存实际文件，通过evidence冻结请求/响应/输出及真实QA，再把准确updates交save。脚本不从工具文本猜造成功图片、QA或批准。JS保存链单写，登记与最终时间持久化后才通知QA；候选 `onInputHeadRefresh` 仍可选，新派单协议不凭该候选回执启用。刷新或登记失败停止新增调用，已在途结果继续落盘；未知结果保持原attempt和占槽。

返回/QA和IN_FLIGHT完整门禁仍保留保守锁；本版只缩短领取锁，不宣称所有状态提交已经无跨话等待。进程级外层全局串行封装也不属于本次自动修改范围。

## 阶段4：崩溃恢复与并发验收

- 包副本已写但账本未提交：重试同request_id可领取一次；未引用孤立包保留，不未经引用证明清理。
- 账本提交但响应丢失：查state中的reservation_requests恢复原回执，不重复领取。
- IN_FLIGHT登记后进程退出、服务接收未知：禁止再提交；以真实查证/异常记录登记RESULT_UNKNOWN，保留原attempt和占槽。
- 图片/意图保存后GENERATED未登记：用 `--action recover` 读取本话saved_intents准确文件并重跑原登记门禁，不重发生图。
- 相同结果重复登记：查原operation回执；冲突内容拒绝、旧attempt不能覆盖新attempt，容量只释放一次。

`tests/test_managed_recovery.py`使用进程间Event和真实写入口，控制预检、提交、锁竞争及进程退出，覆盖慢A话不阻塞B话领取、同话双领取/双返回、QA/领取、暂停/领取、租约/领取、撤销/IN_FLIGHT两种先后。使用合成图像/调用证据，不能表述为实际图片服务验收。三平台文件锁、替换及异常退出由同一测试进入CI矩阵；未实际运行的平台不标PASS。

## 阶段5：发布、迁移与回退

版本及安装包单独保存第一批/第二批证据。capability显式声明、默认关闭；当前代码支持准入命令，不自动改安装版、冻结包或真实RV。发行前执行核心、安装、JS、Skill/bundle及隔离包安装验收，再等待该提交的三平台CI。

实际RV迁移记录至少包含：旧writer是否停止；原预约/在途/未知请求归属；原attempt/预算保留；原state/control哈希；新协议生效版本和admission ID。存在活动或未知请求就不能原地准入。故障时使用control暂停新增，继续save/recover原返回；保留新账本、容量结算和预算，不恢复旧state，不删策略标记。输入闭包完整性受损时先修复对应真实字节，不用旧状态掩盖损坏。
