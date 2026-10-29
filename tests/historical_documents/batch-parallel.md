# 按话并行与五格批次：batch5_v1

本模式仅用于显式 batch5_v1 的旧五格任务恢复；新任务读 [half-episode.md](half-episode.md)。本模式用于逐格成品生产：一个总控，按话分配工作 agent，每话当前批次最多五张独立图片。最终产物仍为每格图片；不拼长条、不加气泡。用户仅请求规划或修改 Skill 时不启动生产。

## 模式与任务归属

显式五格任务在 staged_comic_v1 的生产流程中声明 `execution_mode: batch5_v1`。未声明的旧任务按旧单格、首三格规则恢复；不得静默迁移或把首三格批准改写成首五格批准。迁移需新 RV 和真实批准范围复核。

多话默认目标为总控＋5 个生图工作 agent，episode_workers 可调整请求数；实际工作 agent 数取请求数、话数和当前可用子槽位的最小值，生图在途请求数另受后端容量与 max_inflight 限制。每次运行核对实际容量；用户修改配置不证明当前会话已重新加载。容量不足时话任务排队，不通过额外聊天或绕过工具限制扩容。每话只有一个写入者，独立 RV 根目录；总控写共用调度记录，工作 agent 写本话状态与成果。接管或更换 agent 前先停止旧写入者，核对最后真实返回和状态，再明确交接。

## 固定生产流程

1. 总控核对全部话号、真实格数、源版本、资产和跨话状态。冻结共用人物、衣装、场景、批准画风样例及适用范围；逐话完成 A/B。共用身份和画风由总控维护，工作 agent 不能自行改版。
2. 对没有适用实图校准的共用画风，先完成第一话首五格试产并经 C 确认，再扩大到其他话。已有适用的获批实图直接复用；不重复校准，也不自动把普通候选升级为身份/风格基准。
3. 每话按源序首五格试产（不足五格则全部）。独立格可批内并发；新状态或风险拆批仍累计首五格 C。总控可集中展示多话试产，但分别记录批准范围；获批话可先继续，不强制等待其他话。
4. C 通过后，每话处理当前连续批次：编译输入 → 核对每格门禁与调用额度 → 分别生成 → 逐张六项 QA → 批内及上一批衔接检查 → 修复失败格 → 整批通过 → 下一批。正常批次不增加用户回复停点。
5. 首次未确认状态保留人工实图停点；最后由总控比较各话共用人物、衣装、画风、场景及跨话衔接。每话 D 最终确认并且整个并行批次的跨话复核通过后交付逐格图片包；各话生成进度独立，不因尚未完成跨话最终复核增加生产停点。

## 批次边界与依赖

每批必须为连续源格，最多 5 格，末批按实际数量；不跳格凑数，不能跨首五格边界。一个请求只生成一个独立源格，不用一张五格拼图或接触表冒充五张原图。

获批镜头中每格必须登记：

- `generation_dependencies`：本话前序源格 ID 数组；仅当必须看到前格实际图才能确定后格时登记，普通剧情先后不自动形成实图依赖。B 审查实际核对需求，不能全填空绕过依赖。
- `requires_state_review`：布尔值；高风险或需额外首格实图确认时设 true，并说明原因。
- 原 `visual_state_keys`：持续登记真实身份、衣装、场景、风格状态。P001 之后首次出现新 key 自动成为单格停点，包括首五格试产内；P001 基准状态随首五格 C 校准。

`requires_state_review` 格及自动新状态首现格拆为单格批次，检查后交用户确认再续。同批存在依赖时，可先发独立格；依赖前置格一返回就先做六项 QA，不必等本批全部返回。前置格通过后再提交依赖它的后格，避免“后格等前格 QA、QA 又等全部返回”的死锁。无依赖格可汇总返回后检查，最终仍须整批与跨批检查通过才能进入下一批。跨话需要前话真实结果时由总控保留依赖，收到并核对所需成果之前不授予该话相应请求额度；不得把文字约定冒充已返回图。未确认事实、循环依赖保持 HOLD。

## 统一分配生图请求额度

5 个工作 agent 不等于 25 个并发请求。总控同时控制工作 agent 数与在途生图请求总数，并给每个实际请求分配可追溯的许可。能力未确定时先保守运行，通过实际工具反馈确认可用并发；并发上限、限流、超时或共享工具排队可降低调用额度，不能因此降低模型、输出规格、参考数量或 QA 项目。

工作 agent 只领取自己当前批次中已过门禁、无未满足依赖的格；每次请求前再次检查状态、共用基准版本及当前额度。同一格同一尝试不可重复提交。工具不支持同时调用时保持工具允许的方式，先汇总当前批次返回后检查，不虚称获得并行提速。不改用未经用户选择的生图后端或 CLI。请求耗时、等待及失败按实际记录，不能承诺固定倍速。

## 工作 agent 的输入和输出

| 固定输入 | 固定输出 |
|---|---|
| 任务 ID、书/话/RV、执行模式、唯一工作目录与写入者 | 同一任务和版本标识、当前批次/源格进度、待审/阻塞原因 |
| 只读源脚本与快照、批准镜头及依赖 | 每格候选图片、实际格式/尺寸/哈希和尝试版本 |
| 共用基准版本、实际批准样例和适用身份/状态参考 | 实际请求/返回证据、实际参考清单及冻结输入版本 |
| 当前批次计划、准确格号、生产授权、人工批准 | 每格六项 QA、批内/跨批报告、局部返修记录 |
| 当前调用额度、跨话依赖和停止条件 | 下一步所需批准或依赖；待总控复核的成果索引 |

存在前格实图依赖时，每格执行包根增加 `dependency_outputs: {前格ID: {path, sha256}}`，路径相对执行包根，准确覆盖镜头 generation_dependencies；无依赖可省略或为空。依赖前格图片必须真实进入 reference_images，仅用于 pose_interaction、scene_view、framing、spatial_layout 或 prop_state，不得绑定 identity、costume_state 或 style。前格换图会使后格旧包的依赖快照失效，须重新核对并按影响返修。

每个参考都由本地实际路径、版本、哈希和用途绑定定位；每次生成或返修持续携带原始批准画风及适用身份/衣装依据。并行任务不使用“最近几张图片”或 `num_last_images_to_include`，防止不同任务的图像串入。输入和输出仍以 [生图合同](generation-io.md) 为准，批次不建立第二套人物或镜头事实。

工作 agent 不互写目录、不自行改共用索引、不虚构批准。把角色切换到“验收 Skill”不等于另一个独立 reviewer；报告如实标明实际审查者，总控跨话复核也要实际看图。

## 批次计划与报告合同

状态保留 `policy: staged_comic_v1`，增加：

```json
{
  "execution_mode": "batch5_v1",
  "batch_plan": {"path": "00_输入审计/批次计划.json", "sha256": "实际哈希"},
  "batch_reviews": {
    "B001": {"path": "06_图片验收/B001/批次验收.json", "sha256": "实际哈希"}
  }
}
```

上述为字段示意；未产生的报告不得填假引用。batch_plan 文件由确定性脚本生成，包含：`policy: batch5_v1`、原 `source_snapshot`/`visual_basis`/`shot_manifest` 文件引用、`max_batch_size: 5`、`pilot_panel_ids`（源首 min(5, 格数)）及 `batches: [{batch_id, panel_ids}]`。每批源序、边界、拆批条件均由批准镜头决定。计划文件引用相对本话根目录。

每份批次报告包含：

```json
{
  "policy": "batch_review_v1",
  "book_id": "本书真实ID",
  "episode_id": "E021",
  "batch_id": "B001",
  "panel_ids": ["P001", "P002", "P003", "P004", "P005"],
  "status": "PASS",
  "reviewer": "实际审查者",
  "evidence": "实际看图后记录的可观察比较结论",
  "visual_basis": {"path": "00_输入审计/视觉基准.json", "sha256": "实际哈希"},
  "shot_manifest": {"path": "01_镜头改编_CANDIDATE/镜头改编表.json", "sha256": "实际哈希"},
  "outputs": [],
  "previous_outputs": []
}
```

此例不是已通过报告：outputs 必须填本批全部实际 output 文件引用，按源序；previous_outputs 必须填上一批全部 output 文件引用，首批才为空。status 在实际检查前为未审，不得照抄 PASS。evidence 至少说明本批及边界的人物/发型、衣装、场景锚点、画风、动作接触和镜头衔接，指出正常变化的脚本或镜头依据。复杂问题另附具体格对记录。

所有引用哈希均核对；任一图、视觉基准或镜头改变，旧报告失效并重审受影响的相邻批次。机器只能检查证据、范围与版本，不能自动写出视觉 PASS。脚本要求逐格真实 QA 和批次报告同时有效，防止只写批次 PASS 放行失败格。

命令：

```text
python <总控>/scripts/batch_workflow.py --state <本话>/00_输入审计/生产流程.json --write-plan <本话>/00_输入审计/批次计划.json
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check status
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check generate --panel P001
python <总控>/scripts/staged_workflow.py --state <本话>/00_输入审计/生产流程.json --check deliver
```

write-plan 只新建尚不存在的计划文件，不修改流程状态，不批准用户；核对后将实际引用登记进状态。status 报告当前批次、可执行格和停点；每个实际请求仍需单独 generate 检查，不凭一次检查无限提交。

## 并行控制文件与单次许可

本话状态另增加 `parallel_context`，先落盘后再运行门禁；检查器会读磁盘状态，两者必须一致：

```json
{
  "parallel_context": {
    "control_file": "/绝对路径/批次控制/并行调度.json",
    "job_id": "E021-RV001",
    "worker_id": "实际工作agent标识",
    "epoch": 1
  }
}
```

control_file 是唯一明确允许的绝对控制文件路径；其中共用文件引用相对控制文件父目录，本话 frozen_inputs 引用仍相对各话根目录。控制文件由总控单写，以临时完整文件原子替换；工作 agent 只能请求总控更新，不能并发覆写。

控制文件字段：

- `policy: parallel_episodes_v1`、`version: 1`、`book_id`、正整数 `epoch`、`cancelled: false`、`holds: []`。
- `max_workers`：按实际容量确认的工作 agent 上限；`max_inflight`：实际允许的在途请求上限，两者独立且必须为正整数。
- `shared_files`：冻结文件引用数组。必须恰好一份 `role: style_basis` 的 JSON（含 book_id 和完整 style），至少一份 `role: state_registry` 的既有批准共用账本，以及 style.reference_sha256 涉及的全部真实样例文件。各话视觉基准 style 必须与共用 style 完全一致。
- `jobs`：每项含 job_id、episode_id、绝对 root、worker_id、status、holds 和 frozen_inputs。冻结 source_script/source_snapshot/visual_basis/shot_manifest 四份引用，必须与本话磁盘状态相同；可选 state_file 为话根内相对路径，默认 `00_输入审计/生产流程.json`。各话 root 不可相同或互相嵌套，同一 worker 不同时拥有多话。
- `permits`：每项含唯一 permit_id、job_id、worker_id、epoch、panel_id、status。RESERVED 与 IN_FLIGHT 占用 max_inflight；同话同格不能同时有两个活动许可。完成记录保留，不复用 permit_id。

job 状态为 QUEUED、ASSIGNED、RUNNING、WAIT_REVIEW、HOLD、COMPLETED 或 CANCELLED。只有 ASSIGNED/RUNNING 可发新请求；只有明确用户批准或问题解决后才由总控恢复。许可状态为 RESERVED、IN_FLIGHT、COMPLETED、RELEASED 或 CANCELLED。

实际提交顺序：总控为当前可执行格预留唯一 RESERVED → 工作 agent 逐格运行阶段 generate 门禁 → 总控将许可标为 IN_FLIGHT，工作 agent 将该格尝试状态标为 IN_FLIGHT → 立即实际调用 → 保存真实返回及证据 → 总控登记实际 output_sha256 并将有图许可设为 COMPLETED；无图失败则释放/取消该许可。发出请求后的无图失败照实记录，不能冒充 COMPLETED 图片。释放调用额度只表示工具请求结束，不代表六项 QA 或批次通过；下一批仍被整批门禁约束。许可与磁盘状态不一致、epoch 过期、已有 IN_FLIGHT 的同格，均不得重发。

```text
python <总控>/scripts/parallel_dispatch.py --state <本话>/00_输入审计/生产流程.json --panel P001
```

此脚本只校验读取到的快照，不提供原子调度服务、不验证实际后端容量、不自动派 agent。总控负责许可串行变更、实际 agent 调用和请求前复核；不能将一次 PASS 当作可重复使用的许可。每个并行单格执行包根在新尝试时冻结 `dispatch_receipt: {job_id, worker_id, epoch, permit_id}`。请求前比对唯一 RESERVED 许可；验收时比对同一许可已 COMPLETED，且许可的 output_sha256 等于实际返回图哈希；换执行者或 epoch 的旧图复用还须下节明确的 carry_forward 报告。返回及尝试审计按这个对应关系归档，不能事后将旧回执改成当前 epoch。工具无图失败释放/取消许可，不产生可验收的 COMPLETED 回执。

## 更换执行者或 epoch 后复用合格图片

更换 worker 或 epoch 不必重生历史合格图片。原实际 `dispatch_receipt` 与 COMPLETED 许可保持原值；不得改回执伪装为当前执行者的新调用。总控实际查看旧图、当前批准参考及 QA，确认其仍适用后，在原 COMPLETED permit 中增加 `carry_forward` 文件引用（path 相对该话 root，附实际 sha256）。复用报告字段为：

- `policy: dispatch_reuse_v1`、`status: PASS`、真实 `reviewer` 与具体 `evidence`；未实际复核不得填写 PASS。
- 当前上下文的 `worker_id`、`epoch`。
- `source_receipt`：原始且不可修改的 dispatch_receipt。
- `frozen_inputs`：当前 job 的 source_script/source_snapshot/visual_basis/shot_manifest 四份文件引用。
- `package_manifest`、`qa_report`、`output`：当前 state 该格的三份文件引用。

所有文件哈希仍须匹配。复用报告仅证明执行归属变更后允许继续采用指定版本，不豁免原有镜头、基准、逐格 QA、批次报告及人工批准门禁；源或参考变化导致这些门禁失效时须先完成相应复核。只换 worker/epoch 且其他批准仍适用，不新增强制用户停点。缺少合法报告时不能采用旧归属结果；新生图尝试仍必须领取当前唯一 RESERVED 许可，不能使用 carry_forward 充当新请求许可。恢复后保留这些已复核图片，只补当前批次尚未完成项。

## 多话最终交付门禁

同一控制文件 `jobs` 超过一话时，交付前必须有实际完成的跨话复核。总控查看各话全部实际成品及原批准共用依据，比较相同人物、画风、衣装、场景和适用的话间衔接，生成报告并在控制文件登记 `cross_episode_review: {path, sha256}`；path 相对控制文件目录。缺失、未审或任何绑定版本变化时保持 `WAIT_CROSS_EPISODE_REVIEW`，不能把各话单独 PASS 当成跨话通过。单话不增加此门禁。

报告字段：

- `policy: cross_episode_review_v1`、`book_id`、当前 `epoch`。
- `shared_files`：当前 control.shared_files 原数组，保持顺序、角色和真实哈希一致。
- `status: PASS`、实际 `reviewer`、具体 `evidence`；只有实际看图复核通过后填写 PASS。
- `episodes`：按 control.jobs 顺序排列，每项为 job_id、episode_id、该话 state 中原 visual_basis/shot_manifest 文件引用、`outputs`（本话全部 output 按源序）、`qa_reports`（全部 qa_report 按源序）。本数组内各话文件引用相对各自话 root，不相对控制目录。

门禁同时核验每话当前 frozen_inputs、源格清单完整性、全部源格已完成状态、实际单格 QA 及报告绑定的图/QA 版本；缺图、漏格、旧 QA 或旧基准都不能由一个报告 PASS 覆盖。报告不自动生成视觉通过结论，也不能取代各话自己的 D 用户批准。多话最终包须等全批实图跨话复核和各话 D 均通过；生成期间各话仍按本话批次、依赖和既有审查点继续，跨话最终复核只限制交付。

## 失败、暂停、换版与恢复

- 单格失败保留同批合格图，仅修该格及受影响格；前格返修前，先把确实受影响的依赖后格旧图和记录归入历史，在已有授权内将这些格设为 REPAIR_AUTHORIZED。其他合格图保留；受影响依赖格若仍保留旧 VISUAL_PASS/USER_ACCEPTED 完成记录，门禁会 HOLD 阻止采用。整个批次通过前不发下一批。一次针对性返修后同问题仍在则停下诊断。
- 共用画风、人物或状态依据有缺陷，总控暂停所有受影响话的新请求；局部问题仅暂停本话。已在途请求无法取消时保存候选，不能自动采用。
- 源文件或共用基准变更先停止相关发单，生成新版本并确认影响范围，再恢复；更新 epoch 后须重建适用的上下文、冻结输入与许可，旧尝试保留原 epoch，不得改号伪装成新调用。旧版本晚返回图归旧尝试，重新核对后才可复用，不混入新版本批次。
- 取消后不自动重启。恢复时核对实际文件、调用返回、单格 QA、批次报告和批准的版本；只补当前批次未完成项，不重新抽已合格图片。
- 成品交付同时满足各话 D 和适用跨话复核，文件按源序列出；完成数、失败数、待审数如实区分。

## 规则记忆与可配置批次补充

第三来源与按阶段命中读取见 [规则记忆合同](rule-memory.md)，路径、子 agent 数和请求额度见 [使用配置](usage-configuration.md)。启用记忆的新任务在生产流程、批准镜头、冻结执行包绑定一致 memory_source；镜头 memory_tags 冻结传递，生成与图片验收分别留执行记录，不能删除来源绕过。实际人体在床上等命中条件要求适用站位图及实际提示词约束，未核对则 MEMORY_HOLD。

新任务 batch_size 默认5，可配置1–5；文内“五格批次”指最多五格，批次计划 max_batch_size 取实际配置。首五格 C 范围保持不变；独立图片质量、依赖、新状态、批内/跨批及跨话检查不因调小批次或增减 agent 而省略。修改配置不会自动覆盖已有 RV 的冻结状态。
