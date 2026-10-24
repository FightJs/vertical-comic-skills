# 完整交付、前期容量与成品问题CSV

新任务执行validated_delivery_v1。前期与成品分别设定交付约束；旧冻结运行及已有合同不自动迁移。机器校验不代替视觉QA、批准或原内容门禁。

## 两类交付

- 前期：max_file_bytes=900000000，package_mode=allow_parts。先无损去重，能装下就单ZIP，超限自动连续分卷，整个集合可超过1GB，每文件须小于1GB。只有用户明确禁止分包才设single_zip。
- 成品：max_file_bytes=null，package_mode=single_zip，csv_policy=adopted_issue_csv_v1。没有900MB/1GB容量门禁，不因体积自动分包。图片保留采用版本原字节，ZIP支持ZIP64；仍验证源格完整、图片/CSV对应、哈希及CRC。

comic_start.prepare/receive在显示初始化之外建立00_任务协调/交付要求.json及交付身份.json。身份绑定要求文件哈希、职责、准确书话、权威状态；不因显示失败而跳过。容量参数--delivery-mode/--max-file-bytes仅用于prepare，receive没有这些参数，不继承前期发送限制。缺合同/身份、内容变化或范围变化保持HOLD，不降级为旧任务。

## 前期发布与接收

原review→pack→extract→bind→rehearse→release保留，随后必须走安装版完整发布：

```text
handoff_zip.py publish --zip <内部正式内容ZIP> --contract <00_任务协调/交付身份.json> --output <全新发送目录>
```

Python入口handoff_zip.publish(source_zip,contract,output)与CLI相同。原内部release不是最终发送结果。完整恢复原路径/原字节并核验后才写交付验收.json，最终仅发送artifacts列出的ZIP。运输验证JSON留本地，无需额外传递。

将全部分卷下载到同一个本机文件夹，无需手动解压；把“正式交接包_第001卷_共NNN卷.zip”拖入条漫接包会话并发送即可。按user-prompts接包职责路由，安装版comic_start.receive从原本机路径寻找同目录同集合分卷，核对序号、数量、SHA并自动恢复、绑定、预检。缺卷/损坏提示准确序号，不能先生产部分包。其他序号仍兼容，推荐第001卷作为统一说明。若宿主仅提供孤立上传副本，需定位原目录；不声称单个副本包含其余卷。用户明确只查看/核验时不自动生产。

## 成品导出与CSV

```text
panel_delivery.py --publish <全新发送目录> --contract <00_任务协调/交付身份.json>
```

同等入口delivery_publish.py production --contract <身份> --output <目录>。调用原panel_delivery gate/export，仅收采用图、准确索引、必要问题表及审查依据。最终ZIP根目录包含以下两份CSV，每话目录也保存对应本话版本：

| 文件 | 行与字段 |
|---|---|
| 图片问题总览.csv | 每个源格一行，保留源序；话号、格号、图片路径、采用版本、交付结论、遗留问题数量、最高优先级、问题摘要、处理建议 |
| 问题明细.csv | 每个采用版本遗留问题一行，重大优先；话号、格号、图片路径、采用版本、问题编号、问题类别、具体位置、当前问题、正确目标、优先级、处理情况、确认情况 |

以delivery_review的准确采用图/QA/生产决定为唯一来源。采用旧图不能套用新图结论；不带已解决历史问题冒充当前遗留。没有问题的图仍在总览。INCOMPLETE只能用于用户明确要求的部分诊断导出，不能通过完整发布；未核实保留疑点标签。CSV不烧标记到原图，不产生额外QA或调用。

编码UTF-8 BOM、标准CSV引号及CRLF，保留中文、逗号、引号和单元格换行。以=、+、-、@等开头的值按文本转义，原文保留于绑定JSON。图片路径相对各CSV所在目录；根总览覆盖完整批次，本话表只覆盖本话。CSV不包含颜色或缩略图，可在Excel/WPS中筛选话号、优先级和交付结论。

导出白名单必须包含CSV。验收从当前采用索引重新确定CSV字节，检查其真实ZIP成员及哈希，不能仅检查文件名存在；漏CSV、漏/重格、错路径、错采用版本、遗漏问题、伪造无问题或CSV与原QA不符均HOLD。修改已采用图或问题记录使原交付验收失效。旧无csv_policy的有界合同保持原布局与限制，不自动升级。

## 完成、失败与进度

统一发布保存打包尝试，同一失败/未知输入不重复打包；有真实修订才允许剩余一次自动整理。失败只清理本次新输出，不删除原件、重置预算或生图。前期超限只修装配/容器；成品没有容量失败分支。

```text
task_coordination.py finish-check --directory <协调目录> --revision <当前版本> --zip <已验收实际ZIP> --delivery-report <交付验收.json>
```

新任务缺完整验收记录不能finish-check/100%。前期验证全部卷、容量和真实恢复；成品验证全部采用图、CSV语义与文件完整性。实际发送文件变化使完成失效。生产进度沿原10分钟/服务等待15分钟周期，只统计采用图文件大小供参考，max_file_bytes=null/risk=NO_SIZE_LIMIT，不按容量报警或周期性压包。

## 新候选的受控装配

已有正式包只用运输层去重，不原地删旧RV。新候选可用handoff_zip.assemble，读取explicit_handoff_assembly_v1装配计划：files为真实path/sha256/bytes及reason（execution/traceability/runtime/release）、逐项evidence；required_paths和dependencies登记必要引用；unresolved_paths必须为空，并有实际reviewer/evidence。

工具逐文件复制计划内材料，复制后执行原audit_index/运行模板/冻结文件检查，缺必要文件或传递引用HOLD，返回ASSEMBLED_CANDIDATE_NOT_APPROVED。它不自动推断所有自然语言依赖，不按旧RV名称删材料。执行者须先核对追溯范围；未知材料保留并调查，不能把空列表伪装成依赖已审。实际索引/批准版本变化必须在最终输入审查前解决。Windows自定义package_handoff/execute_release须改用这些入口；本机安装不会自动修改远程自定义脚本或旧冻结工具。

## 限定验收

前期测试实际每文件容量边界、自动分卷、第001卷走receive完整接包、缺卷/损坏拒绝。成品测试无容量上限、无自动分包、保留图片字节、两个CSV及源序/采用图/问题记录一致、特殊字符和无问题格、缺失/篡改CSV拦截。大文件容量门禁测试与真实大ZIP生成需区分；合成测试不证明视觉质量。Windows桌面拖拽需实际宿主验证，不能以Python接包测试宣称UI已实测。
