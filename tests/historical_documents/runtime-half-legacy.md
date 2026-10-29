# 增量执行：incremental_runtime_v1

当前新RV使用 `incremental_runtime_v2`，整话就绪格返图即审、滚动返修，没有固定C；见 [整话异步生产](episode-async.md)。本页其余H001/H002与incremental_runtime_v1细节只供旧半话RV。

启用readiness_policy=panel_readiness_v1时优先按 [全话准备、逐格放行](panel-readiness.md)：全话总览保持完整，就绪设计和完整输入按准确范围集中交B及包审，缺口列待补；当前半话获批独立格可先生成。前格设计未定及真实图片依赖继续等待，C/D仍须完整。本文全话准备一次不要求无关缺口清零；未声明该策略的旧RV继续原完整准备门禁。

新初始化的 comic_execution_v2 半话任务默认绑定 runtime，旧 RV 不自动改写。此扩展减少重复执行和审查往返，保留准确原稿、真实批准参考、逐图六项 QA、命中记忆、实图依赖、全话比例计划、C/D及一次自动修正。生产期间规则库只读。只修改当前 RV 的本话状态；共享 control 始终总控单写。

执行者长时间无实际进展的监控见 [执行者两级监控](worker-watchdog.md)。进度账本与生产状态分开；监控只给T1/T2建议，不改变批准或唯一许可。当前本话已完成而只等跨话比较时，执行者交总控后结束本轮。

## 固定推进方式

本批源稿与需求审计 → 全话必要资产与A → 全话镜头/比例/语义及候选生图包合并展示、B与包分别批准 → H001并发与返图自审 → C → 沿原批准全话依据及包生产H002 → D整话及实际跨话比较。

**按话完成即交审。** 某话H001完成真实自审、必要返修及连续性后立即提交C，不等其他话。C获批后该话直接从原批准全话包选H002，只有真实修改依据才回受影响A/B/包审查。D跨话比较等待需要的实际图片，不扩大成其他阶段全局屏障。

总控以完成/待审事件为主要调度依据，收到 C 就绪事件即给用户材料；避免反复查询未变化状态。许可按当前就绪集合集中分配，各个请求仍有唯一 permit/attempt。候选资产只阻塞实际使用该状态的格及依赖，不暂停无关话。共用画风错误、服务熔断和真正全局问题仍按全局处理。

## 统一入口

scripts/production_runtime.py 直接调用现有共同检查器。镜头和实际 prompt 仍由执行者根据批准依据完成；compile 将现有逐格包编译成实际工具 jobs，不自动创作镜头、不重写 prompt，也不是 shell 生图后端。准备各格时保留唯一镜头与 prompt 权威，不复制竞争版本。functions.exec 用共享 async_generation.js 注入真实工具调用与保存函数。

~~~text
python <scripts>/production_runtime.py --state <本话生产流程.json> --action compile --candidate --write <本话/04_B提示词包_CANDIDATE/H001_待审调用集合.json>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action bundle --dependency-plan <本话相对路径/全话依赖补齐方案.json> --write <本话/04_B提示词包_CANDIDATE/全话生图审查包.json>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action compile --write <本话/04_B提示词包_CANDIDATE/H001_实际调用集合.json>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action review --batch H001 --prepare-qa --write <本话/06_图片验收/H001_增量待审.json>
python <scripts>/production_runtime.py --state <本话生产流程.json> --action checkpoint
python <scripts>/production_runtime.py --state <本话生产流程.json> --action commit --updates <真实返回或QA更新.json> --expected-state-sha256 <读取时实际哈希>
~~~

写入路径必须是新的本话文件；compile/bundle/审查队列不改批准、不调用图像工具。新状态/局部 HOLD 导致部分就绪时只导出完整预检通过格，其他格保持未提交。candidate 只允许预检待审 B 的真实技术输入；暂不要求 B/包批准和派发回执，绝不作为正式调用许可。实际 compile/generate 和提交前检查仍须真实 A/B、包批准、许可、规则及所有输入通过。更新冻结依据时重新检查受影响内容。

整话无实图依赖时，bundle命令省略 `--dependency-plan`；未启用readiness时有依赖须提供完整方案；启用时已完成方案的格可先交审，方案尚未完成的格明确待补。bundle校验完整源格序、共同依据及版本；启用readiness时实际就绪格须完成语义核对和A批准，未就绪格保留缺口，输出仍是未批准候选；B与包需分别保存真实用户批准。H002无需再运行bundle，仅对当次实际可调用单格执行完整预检。

批量预检只遍历一次当前半话共同依据，然后执行每个所选格的原完整门禁。文件哈希和 JSON 仅在一次只读检查事务内复用；事务中发生文件变化立即 HOLD，下一次事务重新读取。缓存不跨进程持久信任，不产生视觉或用户批准。

## 生图包批准与依赖补齐

episode_preparation_v1的bundle产生一份覆盖整话源格序的generation_review_package_v1，scope=episode；generation_packages.EPISODE登记其文件引用。无实图依赖格冻结实际prompt、参考路径/哈希、透明参数和输出规格；有依赖格绑定同一次准备的dependency_completion_plan_v1，scope=episode，逐格给最终文本、同序参考槽、依赖源格和输出规格。approval_index的generation_package批准须绑定包、根visual_basis和根shot_manifest，未启用readiness时覆盖整话；启用时按approval_panel_ids内准确范围批准。B与包可在一次消息分别批准；candidate不能写APPROVED。旧半话包继续按原batch_id恢复。

首轮提交门禁核对本格实际输入与批准包；常规 round2 沿原获批范围及诊断，不加逐张人工停点。改变人物/衣装/场景、画风、镜头或规格须回受影响 A/B 和包审查。

有实图依赖时，可在同一次审查提供已经冻结的 dependency_completion_plan_v1，bundle 用 --dependency-plan <本话相对路径> 绑定它。方案的 inputs 逐格登记 panel_id、dependency_panel_ids、完整 arguments、output_spec 与同序 reference_files；arguments 只含当前工具支持的 prompt、referenced_image_paths、transparent_background。文字为最终实际文字，不用“随后补充动作”等占位。参考数组中仅允许以 @DEPENDENCY:P001 等标记尚未返回的真实前格；其他路径和哈希必须明确并展示实际参考。依赖图占一个参考槽，仍最多五条。

新全话方案声明 policy、scope=episode、book_id、episode_id、visual_basis和shot_manifest；旧半话RV保留batch_id。用户明确批准方案所在全话包后，后续只可将规定的参考路径标记替换为该前格已经真实 QA 通过的输出或其逐字节副本；prompt、参考数组顺序、其他参考、衣装、画风和透明参数保持方案规定。最终完整 generate 门禁仍核对实际依赖、用途、哈希和适用规则。方案未覆盖或需要改文字/其他依据时，集中审新增包。

## 返图与增量自审

配置默认 review_group_size=4、review_max_wait_seconds=30，可在3–5张及1–30秒内调整。runHalfWave 使用 onReviewBatchReady；保存成功后积累少量待审通知，组满、等待到期或波次收尾就通知。校准/高风险/解锁后续请求的 job.review_priority=true，保存后立即通知。仅合并通知，图片和真实返回证据立即保存，不等凑组才落盘、不占用生图槽等审查。

`ordinary_state_parallel_v1` 下首现普通视觉状态的格也标为优先审查；优先只改变返图通知顺序，不等待首图QA才提交已批准的同状态后格。实际失败应即时诊断受影响状态并局部暂停尚未发出的请求，已发出的继续记录和审查。

执行者在通知 yield 后实际审图，一次观察填写原六项 QA 和命中规则；不清楚的细节打开原图。有效且未变的通过图从增量待审集合移出；整个流程门禁和最终连续性仍核对原 QA 的有效性。review_token/processed 只去重通知，不作为 PASS。新图片、尝试或 QA 变化重新进入队列。

review --prepare-qa按当前组创建尚未存在的UNREVIEWED逐格QA模板，并制作一次组联系表；直接使用真实返回路径及实际版本包，不复制/改名图片。可用--panels明确本次通知格；不指定时优先选依赖/校准格并按配置取一组。已审后用原QA更新commit，剩余队列继续处理，半话收尾确保没有遗漏。

commit 接受完整真实证据形成的格级更新；限制状态转换、原 attempt/轮次，核对真实返回或 QA。采用本话单写、文件锁及旧状态哈希比较后原子保存；并发返回冲突时读最新状态重新合并，不覆盖。只保存小型原状态快照，不重复复制参考和图片。总控 control 不由 worker commit 修改。

submitted_at、returned_at、saved_at、qa_completed_at 分开记录；保存回调与实际审图处理应将这些真实时间写入本话记录。工具开始时间只有真实工具证据公开时才能填写，否则留未知；不把客户端提交时间冒充服务开始。记录最终通过验收时间、调用次数、准备/审查间隔；并行调用时长不可直接相加为墙钟时间。

## 修正路线

runtime 任务的首轮诊断新增 repair_routes，每个失败格有 earliest_layer、route、evidence 和非空 preserve_constraints：

- 身份/衣装/画风/场景参考错 → 回受影响 A；
- 镜头/裁切/动作目标冲突 → 回受影响 B；
- prompt 编译或参考职责错 → 重编并核对包；
- 依据与实际输入正确，成图执行失败 → earliest_layer=generation_execution、route=targeted_image_repair。

只有最后一种进入唯一自动第二轮，repair_constraints 仍逐格写清修正和保留要求。超过5张失败还须共因诊断；校准格也使用同一规则及预算。用户后来明确提出新修订须保留消息来源、变化范围与版本，另建修订记录，不重置原自动轮次。服务异常和未知结果查证，不计视觉失败或自动抽图。

## 新任务与旧任务

新初始化默认绑定 runtime；完整配置可显式填写本文对应 runtime 对象。旧 RV 按原冻结记录恢复；更换共享 Skill/工具版本后若不一致，按原合同迁移到新 RV，复用真实成功图、请求、QA及适用批准，不能只改旧哈希。配置合法、技术检查和候选包不授予生产或最终验收。

新runtime的H001→H002仅更新本话job.active_batch_id及实际半话max_inflight；全话frozen_inputs保持原版本，不增加frozen_halves。C通过、全话包适用、旧半话无在途许可后进行，保留H001历史及其他话状态。

启用readiness时，readiness入口只报告设计/语义准备状态；bundle逐格校验实际输入并列candidate_technical_errors，缺单格包或依赖方案不拖住其他完整输入。compile仍要求本格真实A/B及包批准。成功的忠实图集像素证明仅在同一次只读事务内复用，失败不缓存，修改或新事务重新核验。preparation_check_elapsed_seconds、preflight_elapsed_seconds分别记录包检查与预检耗时；人工等待和实际生图耗时用原真实时间戳，不合并为估算速度。
