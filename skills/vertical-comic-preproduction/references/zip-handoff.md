# ZIP正式交接与解压接包演练

适用：split_production_v1前期导出和生产接收。新正式包必须先读[直接交付合同](direct-delivery.md)，采用direct_delivery_v2，本文是ZIP容器及基础索引说明；有差异以直接交付合同为准。策略：rehearsed_zip_handoff_v1。正式交付为一个ZIP及同名`.zip.sha256`，不以文件夹、路径清单或哈希PASS代替可接包交付。旧包不追改；需要修复时建立新候选版本。

## 前期必须完成的顺序

1. 先补齐完整技术编译与可移植上下文，再完成原输入审计、A、全话镜头B及生图包批准；核对源适配与源快照，不把技术派生编号写回源稿。核对所有话的历史状态、逐次调用账、返回图、QA、未知请求和剩余返修预算。原源稿/批准/调用证据保持字节及哈希。
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

`接包生产执行要求.md`按接手次序列可执行步骤，首先核对正式ZIP校验值和包内演练范围。最后展示表格：话号、源格数、H001、H002、可启动格、待补格、历史预算结论、演练报告。不要只给“全部PASS”一句话。

## 附加机器索引（不改原件）

文件引用统一为`{"path":"包根相对POSIX路径","sha256":"实际文件哈希"}`。绑定索引的引用则相对新RV根。拒绝绝对路径、`..`、符号链接、重复/大小写冲突ZIP成员。下面是字段形状示例，不能把示例当真实批准/零调用证明：

```json
{
  "policy":"rehearsed_zip_handoff_v1",
  "delivery_policy":"direct_delivery_v2",
  "package_id":"唯一候选版本ID",
  "book_id":"实际书ID",
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

历史status为NEVER_SUBMITTED、RECONCILED或UNRESOLVED。逐次attempt含`attempt_id`、`kind`（initial/auto_correction/manual_authorized）、`status`（COMPLETED/FAILED/UNKNOWN）及非空`evidence`引用数组；COMPLETED须附`output`及`qa`引用，manual_authorized须附`authorization`。已知有图而缺文件必须补齐或保留未解决，不能把COMPLETED改FAILED来省略图片。UNRESOLVED或UNKNOWN只能HOLD/WAIT_DEPENDENCY；未知调用占用的轮次仍记录。最多一轮自动返修不变，另有授权的追加调用独立列账。

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

需要单独确认ZIP时，导出确认JSON记录`status=APPROVED`、`source_kind=user_message`、真实`source_locator`和`quote`、`candidate_zip_sha256`、`rehearsal_report_sha256`。脚本核对字段和文件，不具备鉴别人类消息真实性的能力；执行者必须引用真实消息，禁止自填批准。原A/B/包仍由原门禁独立验证。正式ZIPSHA放在外部sidecar，不能在ZIP内写其自身最终哈希造成循环。

## 工具保证与限制

pack流式归档，PNG/JPEG/WebP等不再重复压缩，文本快速压缩；不为每话重复拷贝整套共用资产。extract先核对清单、路径安全及所需解压空间再建立新目录。解压空间预检不承诺后续生图空间；接手前按真实任务检查，不自动清理任何资产。原目录和候选ZIP不被覆盖。

rehearse从包内实际快照调用`production_runtime.py --action compile --panels <H001准确源格号>`，明确非candidate、image_calls=0。保存原始stdout/stderr、实际作业格号、参考落点及错误；无就绪格时不伪造PASS。所有指定话的前期资料闭合、每话有实际启动入口且声明与实测相符，才可发布；未知历史等不可继续带入正式包。不会用候选编译、mock结果、空历史或自造检查器代替这次真实预检。

索引哈希通过只证明“所列证据存在且未变”，不能证明外部历史没有漏记，也不自动证明所有语义正确。执行者必须先完成历史对账与源语义审计；原门禁仍是生产判定依据。正式ZIP增加导出证据后重新建立容器清单；生产输入字节与演练候选相同。接包端先校验外部SHA，再extract到新目录并按说明bind自动绑定/完整预检，任何差异集中报告，不返回一句“请补齐全部材料”。

可复用[交接说明模板](../assets/templates/ZIP交接说明模板.md)，逐项填本次真实数据，并据此写接包执行要求。模板不自动证明完整性，不能随空占位发布。正式接包的解压命令增加`--sha256-file "/实际/正式交接包.zip.sha256"`；校验失败不开始解压。候选演练尚无正式sidecar，可按候选记录哈希核对。
