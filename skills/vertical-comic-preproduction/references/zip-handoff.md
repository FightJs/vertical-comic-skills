# 整话ZIP交接、发布与接收

新版分工包遵循[整话职责](split-production.md)和[直接交付](direct-delivery.md)。正式内容必须经过真实迁移路径演练；哈希正确不等于输入正确、获准提交或实图通过。

## 索引与兼容边界

交接验收索引.json的新格式：

```json
{
  "policy": "rehearsed_zip_handoff_v2",
  "production_window_policy": "full_episode_v1",
  "delivery_policy": "direct_delivery_v2",
  "package_id": "本包唯一ID",
  "book_id": "实际书ID",
  "episodes": []
}
```

每话保留完整且唯一的源序panel_ids与同序panels。每格classification只取READY、WAIT_DEPENDENCY、HOLD、REUSE；不写halves、READY_H001或PREPARED_H002。READY是已准备且获适用批准的就绪输入，不是已领取生产许可。WAIT_DEPENDENCY须附blockers及production_dependency：准确包内前置episode_id/panel_id、kind=prior_image或state_image_review、completion_plan的path/sha256。只允许真实前置依赖，不以剧情顺序制造串行。

每话同时提供source_snapshot、production_source_snapshot、source_script、visual_basis、shot_manifest、runtime_manifest、approval_evidence、path_binding_plan、run_template、generation_review_packages，适用时加semantic_audit、input_semantics_policy和同一task_context。引用使用包内安全相对路径与准确SHA256。源快照格序、实际执行依据和最终审查输入必须一致。

panels[].history沿原合同：status=NEVER_SUBMITTED/RECONCILED/UNRESOLVED，reviewer、conclusion、evidence、attempts、auto_corrections_used、remaining_auto_corrections；新任务只核本任务，NEVER_SUBMITTED有原始任务证据且attempts为空。已有调用逐attempt列status/kind/evidence，完成调用绑定原output与qa；UNKNOWN先查原请求，不重发或清零。REUSE还须原图、QA、采用确认和当前设计适用复核。正式包不得含未闭合HOLD或UNRESOLVED。

旧policy=rehearsed_zip_handoff_v1保持原halves及首半话就绪证据；容器哈希清单继续使用rehearsed_zip_handoff_v1，这是完整性封装格式，不等于生产窗口。新版/旧版字段混用会被拒绝。旧批准摘要保持原算法；新版摘要额外绑定交接格式及整话窗口。

## 候选、演练与发布

包根至少有交接说明.md、接包生产执行要求.md、交接验收索引.json及索引引用的完整内容。运行模板policy=portable_run_template_v1，包含root、state_file、逐文件path/sha256/bytes；状态位于本话根/审计目录。原图、规则、工具与批准只读保留。

```text
handoff_zip.py review --root <候选包根>
handoff_zip.py pack --root <候选包根> --output <包外新候选ZIP>
handoff_zip.py extract --zip <候选ZIP> --destination <全新演练解压目录>
handoff_zip.py bind --package-root <演练包根> --run-root <包外全新本地运行>
handoff_zip.py rehearse --zip <候选ZIP> --package-root <演练包根> --run-root <本地运行> --run-index <本地绑定索引> --report-dir <新报告目录>
handoff_zip.py release --zip <候选ZIP> --rehearsal-report <演练报告> --approval <真实导出授权> --output <新正式ZIP>
handoff_zip.py publish --zip <新正式ZIP> --contract <本任务交付身份.json> --output <全新发送目录>
```

bind只重绑运行路径，原创作文件、源稿、批准和预算不变。新版冻结工具必须声明receiver_episode_audit=receiver_episode_audit_v1，实际执行production_runtime.py --action receiver-audit --episode-scope --panels <完整源序>，在同一读取事务中完成准备检查与一次全话实际输入编译；不再跑首半话编译。新包不支持该能力时报HOLD，不降级。旧包仍使用原冻结能力和原首半话检查。

审计结果和作业都标记input_audit_only、dispatch_authorized=false、image_calls=0；输出原始JSON与stderr进度。新版报告每话ready_panel_ids及总ready_panel_count须精确等于索引READY集合。任何缺范围、哈希变更、超时、未知能力或引用越界均禁止发布，保留准确错误和原始输出。包中全话准备与实际输入必须闭合，真实依赖格也要有完整准备依据。

release只接受真实批准或原最终输入不变、演练通过后自动导出的有效条件授权。正式ZIP内置清单、交接说明、原始演练证据及导出依据，无需外部sidecar；旧格式仅有外部校验时保持旧要求。不覆盖候选或原件，不伪造APPROVED。接包不能依据统计或进度百分比跳过门禁。

## 接收与运输

```text
comic_start.py receive --zip <正式ZIP或任一运输卷> --output <输出目录>
comic_start.py receive --package-root <完整已解压包根> --output <输出目录>
```

目录接收核对相同内容和内置发布证据，原ZIP容器CRC标为不可获得；不要求重压或找回ZIP。原件只读，本地运行位于包外。书话范围从包内解析，不询问外部脚本、资产或profile。演练完成后，整话就绪格经实际容量许可和正常compile再提交，用户指定审核点与真实前图依赖仍执行。生产、QA和最终交付沿原合同。

微信运输使用[无损去重与分卷](handoff-transport.md)，只对正式ZIP导出；恢复后逐文件核验，缺卷、损坏、混卷均不得生产。

新任务最终交付必须执行[完整交付与容量门禁](delivery-contract.md)：前期交接单ZIP优先、超限自动连续分卷，每文件不超过900000000字节；成品ZIP无容量上限、不因体积自动分包，并必须包含图片问题总览.csv及问题明细.csv。前期内容release之后走publish，成品目录export之后走普通ZIP发布；统一交付验收.json通过后才能finish-check/100%。容量失败只修装配与容器，不重新生图或降质；旧冻结运行不热升级。
