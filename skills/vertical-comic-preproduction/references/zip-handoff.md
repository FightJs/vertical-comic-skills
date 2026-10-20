# ZIP正式交接与解压接包演练

适用：split_production_v1前期导出和生产接收。新正式包必须先读[直接交付合同](direct-delivery.md)，采用direct_delivery_v2，本文是ZIP容器及基础索引说明；有差异以直接交付合同为准。策略：rehearsed_zip_handoff_v1。正式交付仅一个ZIP，容器标记`self_contained_handoff_v1`；交接说明、哈希清单、演练与导出证据全部内置，前期仍交一个完整ZIP，不以零散文件夹、路径清单或哈希PASS代替正式发布。接收端提前解压后，完整包根目录是同一正式包的可接受输入，不改变批准及历史范围。旧包不追改；需要修复时建立新候选版本。

## 前期必须完成的顺序

1. 先按[任务来源](task-origin.md)冻结task_id、输入与继承范围，再补齐技术编译及可移植上下文，完成输入审计、A、全话B及包批准；核对源适配与源快照，不改源编号。仅核本任务及选定继承范围的逐次调用、返回图、QA、UNKNOWN与预算。fresh不索要其他任务旧账；资产调用和正文调用分开。原证据保持字节及哈希。
2. 建候选目录，带齐实际参考、旧结果、规则和冻结工具。写`交接说明.md`、`接包生产执行要求.md`及下述验收索引；不替换原生产索引。提供已冻结、可由bind自动验证和落盘的运行模板，不能只写“接手后自行修路径”。
3. 用`handoff_zip.py pack`建立候选ZIP，随后`extract`到全新目录。前期工作目录仍存在也不能使用其中的绝对路径或缓存通过演练。
4. 模拟接包人，用bind按包内模板在包外建立新本地RV与绑定索引。运行原冻结编译器的真实完整预检；`rehearse`提供覆盖全部话的只读编译检查，不调用生图、不领线上许可。实际参考必须落在解压包或新RV内。H001选集包含整半话，实际就绪格须与声明准确相等。H002此时也须通过全话readiness资料/依赖/源审计，不假造第一半话人工批准，也不提前生图。
5. 原门禁不接受路径、源适配或预算时，在前期修复兼容方案并形成新候选/必要新工具快照，再从步骤2重演。不得在生产接收时临时修改冻结检查器、删规则、重签旧批准来放行。新包纯地址解析不再单独确认；确有执行输入变化须在前期合并准确审查，避免重审未变化设计。
6. 最终B/包审查可合并“最终执行输入不变且真实演练通过后直接导出”的条件授权；摘要与范围见直接交付合同。取得该真实授权后不再单独索要ZIP哈希确认。用户要求单独审ZIP时再使用精确候选ZIP/报告确认。
7. `release`附入演练原始日志与本次导出确认，生成新正式ZIP和最终SHA256。源生产文件字节不变，新增证据及更新容器清单有明确记录。正式ZIP自检；接包端仍须按本机环境重新核验。演练是零正文调用，不冒充实图验收。

新正式包不允许遗留前期HOLD、未知历史、缺预算或未批准素材；每话及H002前期资料都须闭合。只有已批准且材料齐全的正常内部实图依赖可留待生产。全HOLD或仅局部就绪只能保存诊断候选，不能发布为直接交付包；具体机器条件见direct-delivery.md。

## 交接说明必须写清什么

`交接说明.md`面向接手人，至少包含以下表格和实际操作，不让接手人从数千文件中猜：

- 包ID、版本、正式ZIP文件名；书ID/书名；实际话号、每话源格数、完整源序、H001/H002精确范围。文件名中的历史话号不能代替实际范围。
- 每话逐格或明确格号集合：READY_H001、PREPARED_H002、WAIT_DEPENDENCY、HOLD、REUSE。H002准备完成不等于可提交；REUSE须有获批原图和真实QA。
- 每个阻塞的原因、原门禁代码/报告位置、责任方、解除条件及依赖受影响集合。正常实图依赖可以等待；源冲突、来源不清、预算不明不得包装成普通等待。
- 历史逐次调用：请求ID、轮次、真实返回状态/图/QA、额外人工授权、已用及剩余自动返修次数。缺图、账冲突、未知结果逐项列出。PENDING不能证明零调用；移机和换RV不重置预算；未知不得直接重发。
- 原稿/源快照/源适配及原编号映射；批准原件、适用范围及追溯限制；参考实体、路径基准、顺序和用途；冻结规则/工具版本。历史批准外链缺失可记录追溯限制，但不能把缺少当前必需图也当成追溯限制。
- 解压、校验、建立本地RV、配置依赖、逐项绑定及执行真实预检的具体命令/步骤；包根、新RV根、原证据路径的区别；演练使用的Python版本/平台、所需运行库及实测范围。不得声称同机换目录演练已验证另一操作系统。
- 原人工节点：高风险/首次新状态实图、H001及D；H002释放条件；接手人/审核人/前期变更负责人；每话输出布局、回传材料、异常处理及设计变更边界。

`接包生产执行要求.md`按接手次序列可执行步骤，首先核对包内文件清单、正式发布证据和演练范围；提供ZIP时额外核验其容器CRC。最后展示表格：话号、源格数、H001、H002、可启动格、待补格、历史预算结论、演练报告。不要只给“全部PASS”一句话。

## 附加机器索引（不改原件）

文件引用统一为`{"path":"包根相对POSIX路径","sha256":"实际文件哈希"}`。绑定索引的引用则相对新RV根。拒绝绝对路径、`..`、符号链接、重复/大小写冲突ZIP成员。下面是字段形状示例，不能把示例当真实批准/零调用证明：

```json
{
  "policy":"rehearsed_zip_handoff_v1",
  "delivery_policy":"direct_delivery_v2",
  "package_id":"唯一候选版本ID",
  "book_id":"实际书ID",
  "task_context":{
    "policy":"task_scoped_history_v1","task_id":"本次真实任务ID",
    "book_id":"实际书ID","episode_ids":["E026"],"origin":"fresh",
    "input_scope":"script_and_assets","imports":[],
    "request_source":{"source_kind":"user_message","source_locator":"真实消息位置","quote":"真实重新制作原话"}
  },
  "episodes":[{
    "episode_id":"E026",
    "panel_ids":["源格号1","源格号2"],
    "halves":{"H001":["源格号1"],"H002":["源格号2"]},
    "source_snapshot":{"path":"E026/源序审计.json","sha256":"实际哈希"},
    "runtime_manifest":{"path":"运行版本/manifest.json","sha256":"实际哈希"},
    "approval_evidence":{"path":"E026/批准适用性核对.json","sha256":"实际哈希"},
    "path_binding_plan":{"path":"E026/本地绑定操作.md","sha256":"实际哈希"},
    "panels":[{
      "panel_id":"源格号1",
      "classification":"READY_H001",
      "history":{
        "task_id":"本次真实任务ID",
        "status":"NEVER_SUBMITTED",
        "reviewer":"实际核对者",
        "conclusion":"核查哪些状态及原始调用账后得到的具体结论",
        "evidence":[{"path":"E026/历史核对.json","sha256":"实际哈希"}],
        "attempts":[],
        "auto_corrections_used":0,
        "remaining_auto_corrections":1
      }
    }]
  }]
}
```

示例省略第二格，实际必须完整覆盖`panel_ids`并保持顺序。规范化源序审计JSON根提供`panel_ids`或`id_mapping.panel_ids`，并附原始源适配/原稿哈希与审计结论；它是补充核对视图，不替代原源快照。真实编译器仍核查原source_adapter/source_snapshot合同。

历史status为NEVER_SUBMITTED、RECONCILED或UNRESOLVED，均限定本任务；新包顶层task_context、history.task_id与运行模板一致，逐次attempt另含真实task_id，导入来源须在imports准确选择。逐次attempt含`attempt_id`、`kind`（initial/auto_correction/manual_authorized）、`status`（COMPLETED/FAILED/UNKNOWN）及非空`evidence`引用数组；COMPLETED须附`output`及`qa`引用，manual_authorized须附`authorization`。NEVER_SUBMITTED由本任务来源及真实运行模板状态核对，不能仅填空账或用PENDING证明零调用。已知本任务有图而缺文件必须补齐或保留未解决，不能改FAILED省略图片。UNRESOLVED/UNKNOWN只能HOLD/WAIT_DEPENDENCY；同一任务换路径不重置预算。其他独立任务不因相同书话号被导入。

HOLD/WAIT_DEPENDENCY加`blockers`数组，每项含`reason`、`owner`、`resolution`；REUSE加`accepted_image`、`accepted_qa`、`acceptance`三份引用。H001就绪仅用READY_H001，H002资料齐备用PREPARED_H002。

## 脚本使用顺序

使用本批选定且兼容的Python（需能运行原冻结工具及其依赖）。以下`PYTHON`、`TOOL`和路径须替换为本机真实值；不是新CLI配置字段：

```sh
"$PYTHON" "$TOOL" pack --root "/实际/候选目录" --output "/实际/候选包.zip"
"$PYTHON" "$TOOL" extract --zip "/实际/候选包.zip" --destination "/实际/全新解压目录"
# 从包内冻结工具自动建立本地运行，不重编译创作输入：
"$PYTHON" "$TOOL" bind --package-root "/实际/全新解压目录/候选目录" --run-root "/实际/新RV"
# bind输出本地绑定索引，随后：
"$PYTHON" "$TOOL" rehearse --zip "/实际/候选包.zip" --package-root "/实际/全新解压目录/候选目录" --run-root "/实际/新RV" --run-index "/实际/新RV/本地绑定索引.json" --report-dir "/实际/新演练报告目录"
# 已取得最终输入不变、演练通过后自动导出的真实条件授权，或另有精确ZIP确认后：
"$PYTHON" "$TOOL" release --zip "/实际/候选包.zip" --rehearsal-report "/实际/新演练报告目录/演练报告.json" --approval "/实际/本次导出确认.json" --output "/实际/正式交接包.zip"
```

`TOOL`为`vertical-comic-preproduction/scripts/handoff_zip.py`。绑定索引为：

```json
{"package_id":"准确候选ID","episodes":[{"episode_id":"E026","state":"E026/00_输入审计/生产流程.json","binding_evidence":{"path":"E026/本地绑定映射.json","sha256":"实际哈希"}}]}
```

必须覆盖包内全部话、同序。状态文件须保留原runtime约定的`本话RV/00_输入审计/生产流程.json`层级（原编译器以状态文件父目录的父目录作为本话根）；绑定索引和引用据此填写，不能把状态随意放到RV根。本地状态须将`runtime_snapshot`解析到解压包实际manifest绝对路径及原哈希，其余源/参考/规则/批准解析按原冻结合同逐项建立映射。bind仅自动解析已冻结运行模板的runtime_snapshot/toolchain/memory_source根地址；脚本不改创作输入、不重绑批准，不以修改JSON字符串冒充合同兼容；原门禁不接受就回前期处理。

需要单独确认ZIP时，导出确认JSON记录`status=APPROVED`、`source_kind=user_message`、真实`source_locator`和`quote`、`candidate_zip_sha256`、`rehearsal_report_sha256`。脚本核对字段和文件，不具备鉴别人类消息真实性的能力；执行者必须引用真实消息，禁止自填批准。原A/B/包仍由原门禁独立验证。正式ZIP最终SHA256只记入导出日志，不再生成外部sidecar，也不在ZIP内写自身最终哈希造成循环。包内逐文件哈希和CRC验证完整性，不承担发布者身份认证。

## 工具保证与限制

pack流式归档，PNG/JPEG/WebP等不再重复压缩，文本快速压缩；不为每话重复拷贝整套共用资产。extract先核对清单、路径安全及所需解压空间再建立新目录。解压空间预检不承诺后续生图空间；接手前按真实任务检查，不自动清理任何资产。原目录和候选ZIP不被覆盖。

rehearse从包内实际快照运行真实门禁，明确非candidate、image_calls=0。新整话快照通过已校验的`runtime_capabilities.json`声明`receiver_audit_bundle_v1`后，调用`production_runtime.py --action receiver-audit --progress --h001-panels <H001准确源格号> --panels <全话准确源序>`。分别运行H001、全话readiness及全话输入检查，共享一次读取事务；没有能力声明的旧快照仍使用compile/readiness/compile分开调用。声明未知能力则HOLD，不修改旧快照或偷偷换用安装版。

新入口保存`<话号>_receiver_audit.json`原始结果和对应stderr，再从该结果生成`<话号>_stdout.json`、`<话号>_preparation.json`、`<话号>_all_inputs.json`三个证据视图。stderr每10秒报告阶段/格号/耗时，不能替代批准。超时写`<话号>_<阶段>_timeout.json`，关联保留下来的部分stdout/stderr及最后进度，结论为HOLD；日志写盘失败或子进程非零退出也阻塞交付。保存实际作业格号、参考落点及错误；无就绪格时不伪造PASS。所有指定话的前期资料闭合、每话有实际启动入口且声明与实测相符，才可发布；未知历史等不可继续带入正式包。不会用候选编译、mock结果、空历史或自造检查器代替这次真实预检。输入审计结果`dispatch_authorized=false`，不能直接作为生图调度作业。

索引哈希通过只证明“所列证据存在且未变”，不能证明外部历史没有漏记，也不自动证明所有语义正确。执行者必须先完成历史对账与源语义审计；原门禁仍是生产判定依据。正式ZIP增加导出证据后重新建立容器清单；生产输入字节与演练候选相同。接包端收到ZIP时先用check_delivery_archive验证内置逐文件SHA256、CRC及正式发布证据，再extract到新目录；收到已解压目录时用check_delivery_directory核验清单、文件集合、大小/SHA256及同一发布证据，随后按说明bind自动绑定/完整预检，任何差异集中报告，不返回一句“请补齐全部材料”。

可复用[交接说明模板](../assets/templates/ZIP交接说明模板.md)，逐项填本次真实数据，并据此写接包执行要求。模板不自动证明完整性，不能随空占位发布。正式接包使用安装版`comic_start.py`，按输入形态二选一，先校验再创建运行：

```sh
"$PYTHON" /安装目录/vertical-comic-preproduction/scripts/comic_start.py receive --zip "/实际/正式交接包.zip" --output "/本机/输出目录"
"$PYTHON" /安装目录/vertical-comic-preproduction/scripts/comic_start.py receive --package-root "/实际/已解压包根" --output "/包外/输出目录"
```

已解压目录须含原`ZIP文件清单.json`、交接验收索引及演练/导出证据，不能重新生成清单冒充正式包。文件集合（忽略`.DS_Store`及`__MACOSX`元数据）、大小、SHA256、路径与发布证据完整即可继续；符号链接/目录联接、路径越界、大小写冲突和实际缺件须具体报告。若用户给的是外层解压目录，定位唯一包含清单与索引的直接子目录；多个包时只问选哪个。

目录原件保持只读，新的运行和报告放在包外，不必再复制数千文件。报告记录`source_type=extracted_directory`及`archive_crc=NOT_AVAILABLE_EXTRACTED_DIRECTORY`，不声称核验了原ZIP字节，也不因无法重算容器CRC要求找回ZIP。原始导出授权中的候选哈希用于对照内置演练证据；不拿重新压缩的ZIP替代。目录接收不改冻结快照，安装版接收入口继续调用包内原冻结编译器。接收端不要求新版包的外部校验文件、不要求重压或套第二层ZIP。旧版ZIP可继续携同名.zip.sha256接收；候选仍仅供演练，不能经新版接包入口直接生产。

## Windows及跨系统接包

包内引用与快照清单统一POSIX相对路径，实际工具参数在接收端解析为本机绝对路径。冻结Skill身份按名称和内容哈希核对，不使用来源电脑路径解析结果代替身份。UTF-8/LF仅用于新输出；复制源文件和批准证据时保留原字节。系统保留名称、大小写冲突、路径越界和缺失文件不得自动重命名后重签。

安装版更新不改变旧包内脚本。Windows遇到旧Unix专用冻结运行时，报告FROZEN_RUNTIME_UNSUPPORTED并回前期创建明确迁移的新RV、核对批准和原预算后重新导出，不能接收端临时修包。环境检查只证明本机运行基础，正式接收仍须执行冻结工具的bind/rehearse。

旧冻结工具尚未采用任务来源标记文件时，接收端根据已校验快照识别旧合同，不追加新版本的标记文件或摘要字段要求；仍核对原有任务身份、实际调用记录、UNKNOWN及预算。新版本快照缺任务来源标记仍须报告缺件，不能以旧版兼容为由放行。
