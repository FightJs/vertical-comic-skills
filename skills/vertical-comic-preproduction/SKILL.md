---
name: vertical-comic-preproduction
description: Coordinate first-batch per-panel comic production for further human editing, preserving real QA, scoped repair decisions and annotated delivery. Use for single or multiple episodes, whole-episode asynchronous generation, split preparation/production handoff, stage routing, resuming production, or explaining the comic skills. Also routes comic-bundle setup, updates, user-requested prompt contributions, and legacy instructions referencing 条漫Skill使用提示词.md even when that external guide is unavailable. Excludes script rewriting, strip assembly, bubbles, lettering and PSD finishing.
---

# 条漫第一批逐格图片生产总控

**新任务默认速度优先、轻审核成品，并启用环节限时自动降级**：先按[轻审核流程](references/light-review.md)执行。每图快速看一次人物与剧情可读性，仅严重剧情问题最多返修一轮；普通瑕疵留人工。此模式不执行下文旧全面审核的六项细节取证、逐MEM记录及整话/跨话重复复审，不为测试返修另做生图。新任务同时绑定 `speed_policy: bounded_stage_fallback_v1`：按轻审核流程内的时限表执行，超时停止可选润饰、缩小编译批次、简化审核或沿用现有图；首轮出齐优先于返修。工具以冻结状态的 `image_review_profile` 分支登记和交付；无该字段的旧任务仍按原合同，不能热改。

**五类短指令**：用户要求条漫Skill“更新”“初次配置”“前期制作与交接”“接包生图与完整交付”或“提炼指定提示词到用户增补”时，先读[统一使用说明与模板](references/条漫Skill使用提示词.md)的对应章节并执行，不要求引用外部Markdown。此入口采用所选模板的main预览更新、内部审查及4小时默认值，用户明确覆盖时按其要求；仅操作所选职责，配置不启动生产、用户增补不主动选材。

**使用说明统一入口**：《条漫Skill使用提示词》和内置模板已合并为[同一份文档](references/条漫Skill使用提示词.md)。用户沿用旧文件名或作者电脑路径时，按[旧文档路径兼容](references/条漫Skill使用提示词.md#旧文档路径兼容)直接路由到该文档，不寻找外部标准说明，不并行维护两套正文。用户明确指定的自定义补充、特定版本或实际生产素材仍须读取，不以模板代替。

新轻审核任务同时启用[前期轻门禁](references/preparation-efficiency.md#新任务前期轻门禁一次观察细节留人工)：设计与最终输入共用一次观察，普通细节仅提醒；仅剧情关键问题及不可执行输入阻断对应格。使用preparation_review.py自动保存内容绑定记录，在已有准确委托内同次登记B/包决定。下文全面逐项审查要求仅适用于旧冻结或明确全面审核任务。

普通格默认按[五项最小镜头模板](assets/templates/普通格最小镜头模板.md)只填写人物、关键动作、景别、必要背景和参考；共同设置在主表shared维护一次。派生入口自动复用同主表上一轮记录，禁止为局部修改重做未变化整话。

阶段开始时按[规则归属](references/rule-ownership.md)读取共同规则与本阶段合同；授权和进度沿用该页入口，同一运行不重复加载未变内容。新制作按[前期提速](references/preparation-efficiency.md)先贯通代表格，再用[唯一主表](references/draft-authoring.md)增量派生。接包直接使用已审输入。

**接包优先**：用户提供正式ZIP或完整解压包根目录时，直接执行[免外部配置接包](references/quick-start.md#接包生产免外部配置)，优先于首次书籍配置和下文新运行创作步骤。书名、话号、格数、脚本依据和资产从已验证包内读取；不询问外部脚本/资产，不创建本书profile，不调用prepare，不重建主表或重做A/B。缺件只报告包内准确缺项，在现有授权内闭环。

新前期/接包任务默认使用 `--clock-mode active`：同一职责累计有效运行最多四小时，暂停、等待用户不计时；三小时是效率目标，首轮生成继续。按[环节限时降级](references/light-review.md)减少工作并提前滚动归集。用户明确要求自然时间截止时才选 `--clock-mode wall`；其自动封包和3小时30分停止全部调用的规则不套用于默认active。旧冻结任务不迁移、不重置。

本技能负责供人工继续加工的第一批独立逐格图片。新运行先读[生产决定与阶段交接](references/production-decisions.md)：沿用真实审核，逐问题分三类，按影响/成本决定一次合并修复、重生或留人工；采用版本与原QA绑定，交付附简明问题表。旧RV按冻结合同，不热替换工具或规则。

新整话同时执行[服装配饰定位与单画面](references/appearance-and-single-frame.md)：appearance_lock_v1固定当前衣装、配饰归属和身体锚点，single_frame_v1禁止一图双格。源稿多画面只选一幅绘制，原文/格序保留，未选内容不进实际prompt；A/B、实际参考、原QA及返修共用同一依据。新RV默认启用，旧RV按冻结版本，不热升级。

从批准脚本与资产推进到逐格成品图片包；不含拼接、气泡、文字排版或PSD。阶段请求只处理所选范围，不自动启动整套生产。

首次进入运行读[共同约束](references/production-foundation.md)、[固定流程](references/staged-workflow.md)和[规则归属](references/rule-ownership.md)。具体规则只在共享正式来源维护；运行按冻结版本读取，不在生产中更新规则库。

## 简易入口（首次使用优先）

首次执行先按[短启动的执行环境](references/quick-start.md#执行环境)检查当前Python；Windows使用原生跨平台运行时，不安装fcntl、不修改旧冻结包。

仅前期制作的用户首次使用或缺配置时，按[首次配置引导](references/quick-start.md#安装后的首次配置引导)一次收集缺少的书名、脚本、资产和话号，自动校验并生成本书配置；不要求用户预建JSON。已有配置只询问差异。

读[短启动与本书配置](references/quick-start.md)。前期制作用户只需脚本、资产、话号及可明确识别的书名，内部默认配置与规则自动解析，不要求填写技术JSON；“前期制作”路由分工准备阶段并停在正文前，“接包生产”接收正式ZIP或其已解压目录。用comic_start.py合并初始化或校验/解压/bind步骤；正式包默认复用已验证发布证据，不重复rehearse，初始化通过不等于源审计或批准通过。

准备和生产是流程阶段，不要求不同负责人、电脑或会话。正式交付一经接收，当前生图人员负责在同一任务中闭环处理路径、材料、工具、历史账和设计问题：集中列出准确受影响范围并直接询问用户，获批后仅更新和重检该范围。不得要求用户另找前期负责人、返回前期会话或等待外部任务回传。

规则记忆默认随本Skill内置，四个阶段共用assets/rule-memory；用户增补与内置规则分开。维护/导出/可选GitHub同步读[内置规则维护](references/builtin-rule-maintenance.md)；不需要GitHub账号才能生产或本地更新。明确外置来源和旧RV保持原冻结来源，不静默改库。

## 安装更新

用户要求检查、更新五件套或恢复旧版时，读[安装更新](references/installation-update.md)，用当前安装的scripts/update_skills.py处理。默认免账号稳定版；只检查不安装，明确要求更新则无冲突直接执行。个人改动需处理差异，保留用户增补，旧生产RV不热升级。

## 选择任务模式

先读[任务来源与历史范围](references/task-origin.md)，再选职责。明确重新制作/仅根据脚本和资产时建立独立任务，只读取本次输入，不追索同书同话其他任务的调用、旧图、QA或预算。恢复/接包保留原任务，复用仅限用户指定成果。分工制作不等于续做；任务来源必须写入新运行与交接索引。

- 新任务：按[整话异步](references/episode-async.md)使用episode_preparation_v1、episode_async_v1、scoped_episode_review_v1、comic_execution_v2与incremental_runtime_v2。全话准备、[逐格就绪](references/panel-readiness.md)，B与实际包合并展示并分别记录决定；缺口仅阻塞受影响格及真实依赖。默认无固定半话C。
- 恢复任务：先从原冻结入口运行staged_workflow.py --check status；按原模式、源序、输入、规则与预算恢复，不静默迁移旧RV。
- 用户指定分工制作：最终交付一个完整集合，单ZIP优先、超限自动连续分包，交接说明、哈希清单及发布证据内置；接收端可用ZIP路径或其已解压包根目录及可选输出位置启动，旧版sidecar仍兼容。目录校验与发布证据完整时直接接包，不索回原ZIP、不要求重压；接收入口用安装版，生产编译仍用包内冻结工具。读[双电脑交接](references/split-production.md)、[直接交付](references/direct-delivery.md)及[ZIP演练](references/zip-handoff.md)。新包统一整话就绪调度，只有真实依赖及用户指定审核点等待；缺技术编译的候选不能当正式可生产包。

接包只核对包内书话、原文、源序、资产、画风和本地输出，历史配置路径不作为生产输入；不调用usage_config.read_config。前期制作核对准确书话、源脚本、真实格数及源序、资产、批准画风和输出RV，不按估计格数初始化。前期配置存在时读[使用配置](references/usage-configuration.md)，新任务用init_preproduction.py创建未批准模板。

## 阶段职责

新建整话优先按[公共校验、短锁与审核修订](references/incremental-pipeline.md)使用同一运行工作进程复用内容绑定校验；真实返回即保存，QA/问题/采用一次登记，修订留旧版，末尾全量核验。复杂格纳入正常首批；轻审核不为验证返修路径另做生图；四小时按原职责总预算累计，不给每话重开窗口。

提速先按[减少重复检查与版本返工](references/runtime-efficiency.md#减少重复检查与版本返工)执行：代表格先贯通真实入口，批量检查共用一次读取事务，按共因一次收敛问题，仅重建变化格及真实依赖，不为每次字段修正复制整套RV。最终核验完整源序、实际采用图和文件；轻审核每图仅快速看一次，不重复整包演练。

批量铺开逐格包之前，按[真实入口先行验证](references/final-input-semantics.md#批量制作前先走真实入口)用本批代表性复杂格及跨话边界跑完整候选编译，先稳定字段、参考职责和可移植路径。前期授权与正文授权分开，同批候选不提前索要前话B批准；具体边界见该文档。

A由[视觉资产](../vertical-comic-visual-assets/SKILL.md)维护身份、衣装、场景与画风；B由[镜头设计](../vertical-comic-shot-design/SKILL.md)落实动作、承托、机位及裁切；[逐格生图](../vertical-comic-panel-generation/SKILL.md)编译真实输入并提交；[图片验收](../vertical-comic-image-review/SKILL.md)完成实际QA、连续性与最终包。不要复制第二套身份、镜头或参考台账。

全批先按[批次运行](references/batch-runtime.md)冻结唯一快照。每话唯一owner写本话状态，总控单写共享调度；多话可按实际槽位使用最多五个工作agent，不能用新聊天替代。额度服从实际核定服务容量；本话租约内自主领取、预检、提交和保存。独立格异步，状态落盘串行；真实返回保存后释放生图槽，不等待QA。未知结果先查证，不超时重发。

[实际执行质量](references/execution-quality.md)把物理、场景方向、可见饰品、接触与原尺寸观察落到现有字段；技术PASS不证明空间或图片正确。源描述与批准物理条件冲突时先处理受影响A/B，不让模型自行改家具或动作。正文[比例计划](references/frame-ratio-plan.md)保留六种批准比例、竖版严格大于75%与交错要求，先验证内容容纳，不为凑比例扩大取景。

## 授权、修复与完成

用户要求直接完成整批时，先读[完整交付请求](references/grouped-review.md#完整交付请求)：以指定全部源格的完整成品ZIP（不设容量上限，附逐图问题CSV）为结束条件，合格图本地归集，默认不交少量图片阶段包代替完整成果。启动时集中处理必要授权与兼容缺口，生产中在适用委托内自行决定并登记，局部阻塞不停止其他就绪格。

按[合并审查](references/grouped-review.md)处理准确范围。用户亲自批准与执行者在明确委托内的决定分开记录，后者绑定真实用户授权及约束，不伪造APPROVED；配置或泛指继续不授予新权限。仅范围外事项、明确保留亲审项或外部阻塞需要用户处理。

轻审核每图快速看一次，仅严重剧情问题最多返修一轮；具体登记按轻审核流程。以下六项及额外修复授权说明仅适用于全面审核或原冻结合同，失败保留原件和记录。先按三类影响决定处理；第三类留人工，第二类有明确收益才合并修复。超过5张真实失败先登记共因诊断，已有重复低效方法可更早停止；最多一轮自动修正且不必用满。二轮仍失败按采用图保留实际问题；仅值得继续的重大问题且有实质不同方案才集中处理追加授权，次数和attempt不重置。先分流裁切、局部编辑、修输入或停止诊断，不能靠强化措辞整图重抽。

[两级监控](references/worker-watchdog.md)只依据真实保存事件诊断。等人工不催执行者；本话仅等跨话比较时交回总控结束本轮。按[阶段与交付进度](references/review-progress.md)定期汇报，状态不变不重复发事件通知，到期仍报等待状态。

每话独立完成适用真实QA、连续性及原D/委托决定后运行第一批deliver门禁，保存采用图、完整源序索引、简明问题表及证据；未完成格明确去向，重大遗留仅作人工优先加工材料。全面审核多话另做实际跨话边界比较；轻审核仅在明显剧情矛盾时看必要前图；总包从已登记采用版本及准确交接结论组装，校验计数/哈希/CRC，不重新生成合格图。统计按[增量运行](references/runtime-efficiency.md)及production_metrics.py记录，缺失时间不当作0，不把测试通过宣称为生图质量提升。

校验耗时异常时按[批准与上下文复用](references/runtime-efficiency.md#批准与前格上下文复用)定位重复计算；性能修改须比较原判定及批准失效反例，只更新新运行版本，不热改已交付冻结包。

新运行按[最终输入语义审查](references/final-input-semantics.md)执行：先审设计，再核对完整实际prompt、参考和判据；前期闭合后交接，接包只复查实际变化与新实图。审查沿用semantic_audit，不新增用户停点、不热改旧冻结包。

派单短锁是可选运行能力，默认关闭。仅在需要显式准入、保存器接线或恢复该协议运行时读[一致性协议](references/dispatch-consistency.md)；普通RV继续原入口，不自动迁移或热更新。

新整话按[前期输入收敛](references/final-input-semantics.md#前期收敛按包执行v2)组织：前期逐格完成原稿/资产、连续性、规则与完整prompt审查；生产按已审包执行，返图按包内目标做真实QA。人物配饰固定在角色自身身体锚点，机位投影和可见数量另行确定。

微信发送交接包时执行[无损去重与分卷运输](references/handoff-transport.md)：正式发布后导出，完整恢复验证后发送全部交付文件；接收入口自动识别。

新相关格按[空间输入收敛](references/final-input-semantics.md#空间输入收敛)选择MEM-003/006/009并绑定当前投影，首轮空间失败按[二轮分流](references/execution-quality.md#建筑与视角畸形的二轮分流)执行MEM-004；普通格和旧冻结运行保持原路径。

新任务最终交付必须执行[完整交付与容量门禁](references/delivery-contract.md)：前期交接单ZIP优先、超限自动连续分卷，每文件不超过900000000字节；成品ZIP无容量上限、不因体积自动分包，并必须包含图片问题总览.csv及问题明细.csv。前期内容release之后走publish，成品目录export之后走普通ZIP发布；统一交付验收.json通过后才能finish-check/100%。容量失败只修装配与容器，不重新生图或降质；旧冻结运行不热升级。

新协议执行器的正文、返修及资产调用统一经过[提交登记](references/submission-runtime.md)，缺onBeforeInvoke或准确持久化回执时不调用。计时上下文缺失不自动视为不限时。

接包的技术兼容与恢复按[接收入口](references/quick-start.md#接包技术兼容与原运行恢复)执行。receive自动检查冻结提交协议；宿主使用generation_host.py保存实际返回并创建本地规则地址已核验的执行副本。超时后沿原运行receive-resume，不重新bind或清空历史。已有线上许可/调用的运行继续原生产门禁。
