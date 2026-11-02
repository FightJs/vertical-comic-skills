# 衣装补齐和跨交接状态

新前期可将 `--script` 指向单个脚本文件或脚本目录。目录模式启动输出 `脚本来源索引.json`，其中XLSX工作表和格号是原始读取证据、文件名版本是提示；均不是选稿或批准。读取实际源稿和书籍资产后，用 `script_catalog.py select` 绑定每个当前话和可确认的后续话的文件、版本和真实依据。不同内容的同话版本不能按文件名自动选最大版本；集中处理当前话冲突，未来版本不明仅影响复用判断。只初始化用户指定的话；未来脚本不创建生产任务。

A阶段依据本批实际源格、身份及衣装填写原 `visual_basis.asset_tasks` 和当前衣装需求。按人物、衣装状态汇总一次，对候选身份、款式、颜色、层次和配饰实际查证；没有依据的状态标待核实，不以关键词或脚本自动填写通过。逐格数据来自已选定脚本，未来可见出现按源话和源格去重；本次正式范围不计。`costume_requirements.py --input <核定事实.json> --output <新计划.json>` 对当前需求和后续已核定观察作确定性计数；观察包含人物、衣装、话、格、源文件哈希、可见性、判断及证据。工具会核对当前需求和后续观察的真实源格，P001之外的拼写不会当作额外出现；未来观察必须属于选定后续范围。XLSX保留场景、时间和台词中的换装线索。未知未来保持UNKNOWN。使用 `asset_tasks.py --asset-root <资产目录> --visual-basis <本话基准> --reuse-plan <计划>` 复用原分流。所有状态以真实视觉依据及适用委托为准，计划不是批准。

当前需要的缺失衣装在授权和预算内沿原 `asset_runtime.py` 补充，实际看图后采用；当前不需要的不生图。后续确认可见两格以上且无需新的用户亲审时，用 `asset_catalog.py --reuse-plan <计划.json>` 将已保存、真实审核通过的参考追加到全面资产，提供真实用户委托、范围、调用证据和未来观察。生成文件与索引采用可重放追加；发布前保存范围核验回执，已保存图片但索引登记中断时可凭相同记录和回执恢复，原暂存图或源稿不可达也不重生图；已发布的相同版本直接复用。新增索引为 `07_元数据/衣装增量索引.json`，与本书历史索引和明确当前覆盖规则共同读取；不得把某个局部历史增量当全书完整索引。一次或未知按本批参考处理，不声称永不复用。补充是否进入全面资产，不影响下一批仍需要该参考时保存跨包衔接副本。

前期用 `handoff_continuity.py stage --package-root <未批准候选根> --record <边界记录.json> --expected-index <当前交接索引SHA256> --source-root <参考来源根>` 批量保存必要图片、边界并更新候选 `continuity_boundary` 引用；输入记录由现有已核定A依据构建，相同书、包和边界版本可幂等重放，归属或内容变化报告冲突。边界记录使用 `handoff_costume_continuity_v1`，包括书、承接起始话、来源package_id、人物、衣装/外观ID、已核定依据、适用范围、已知换装点和必要图片相对路径及SHA256；未确定的状态只能是UNRESOLVED；已知身份可独立携带identity_reference（图片相对路径/SHA256），不因衣装未知丢弃人物身份依据。图片必须真实放入候选包并由装配计划闭合。`handoff_zip.py release ... --asset-root <全面资产目录>` 发布正式ZIP后同步到资产目录的跨交接衔接索引；若同步失败，保留正式ZIP并使用 `handoff_continuity.py recover --asset-root <全面资产目录> --zip <正式ZIP>` 重放，不重新生图或重发包。恢复会核验正式ZIP和边界引用，并补回归档中缺失的图片；已存在但哈希变化的图保持冲突，不覆盖。下一批 `comic_start.py prepare` 按书及起始话读取候选状态；A阶段逐人对照脚本和当前资产，明确换装从对应源格切换。候选不是确认或批准；分支不唯一、身份/衣装冲突及缺失只影响相关格。接包生产只依赖正式包内图片与依据。

## 批量输入形状

下列字段是输入形状，不是实际证据。执行者从已读材料生成一份批量JSON；不得把占位文字作为依据。未来未明确可见或未核定同一衣装的观察用 `match=UNCERTAIN`，不得填写CONFIRMED。目录 `select` 输入是话号到 `{path, version, source_evidence}` 的对象；输出的选稿索引整个对象放入衣装计数输入的 `source_catalog`。每项观察格式：

```json
{
  "episode_id": "E002", "panel_id": "P003",
  "character_id": "人物ID", "costume_id": "衣装ID",
  "match": "CONFIRMED", "visible": true,
  "source_sha256": "实际所选脚本SHA256", "evidence": "实际源格及判定依据"
}
```

衣装计数输入为 `{book_id, production_episode_ids, source_catalog, coverage, requirements, observations}`；每个需求有 `requirement_id/episode_id/character_id/costume_id/source_basis/panel_ids`。同一人物衣装仅汇总一次；`asset_tasks`的 `requirement_id/episode_id/character_id/costume_id/panel_ids` 与计划的本话范围一致。跨话共享时按话分别构造任务和相应范围计划，复用同一已核定的衣装身份及补图结果；不能把全批格号写成本话格号。

新增资产发布的记录须包含 `policy=costume_asset_append_v1`、`book_id/asset_id/character_id/costume_id`、`production_episode_ids`、`source_basis`、`future_occurrences`、保存图片的 `sha256/relative_path`、真实范围内 `authorization`（原用户消息来源、原话、书、话、资产和publish操作）及 `review`（实际执行者、观察依据、审核资产ID与图片SHA256）。同衣装已入本增量索引时优先复用；需修改的新增版本要注明 `supersedes` 和 `revision_reason`。资产匹配前可通过 `asset_catalog.py --asset-root <目录> --book <书> --character <人物> --indices <选定索引引用数组.json>` 列候选；各历史索引引用含相对路径和SHA256。结果需结合本书当前覆盖规则和实际图像核定，不因候选顺序决定采用。

下一批对齐可将边界记录、准确源序和本批观察交 `handoff_continuity.py reconcile --input <批量输入.json> --output <新记录.json>`；观察逐项为 `panel_id/character_id/decision/source_evidence`。decision为INHERIT、CHANGE或CONFLICT；CHANGE另提供 `costume_id/appearance_state_id/reference`。它生成候选绑定，实际可用状态和批准继续由A及原门禁核对；不把候选本身写为视觉通过。

多件已审状态可一次用 `asset_catalog.py --asset-root <目录> --batch <批量.json>`；数组每项含 `record/source/reuse_plan`，单项冲突返回准确ASSET_HOLD，其余项继续。已保存文件只重放登记。

非XLSX输入若需参与自动衣装计数，选稿条目用source_snapshot引用从该源稿提取的准确源格JSON；快照保留source_sha256、episode_id及panel_ids并绑定实际文件哈希。源格摘要不代替语义判定。新增CLI失败输出结构化HOLD，批量部分失败返回非零退出码并保留逐项结果。

临时人物衣装参考也执行[人物衣装最低版式](stage-asset-production.md#人物衣装参考最低版式)：独立全身主图与正、真侧、背三视图，均头到鞋完整、纯白空白背景。临时仅区别保存和入库生命周期，不降低视图规范。新入库记录须携带绑定实际图片哈希的 `format_review`；新跨包记录携带同一 `asset_format_policy` 与逐状态观察，不合格不标已核定。
