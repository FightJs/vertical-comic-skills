# 前期交接与图片＋CSV极简成品

**新任务四小时交包优先**：执行[限时交付合同](runtime-clock.md)。下文整包演练、全部审核/最终D通过才交付、等待所有任务收敛等要求仅保留为旧协议或明确要求完整认证的路径；新任务默认复用已审输入、逐格编译，以全部源格完整交包为完成条件，争取四小时内交齐，七小时有效运行硬停。恢复快照不算完成，不把未审或未完成改成PASS。

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

## 新成品：图片和一份CSV

新receive明确设置 `completion_profile=minimal_panel_delivery_v1`。交付源是每次实际审核采用或已授权失败处置时写入的delivery_materials。收尾不调用panel_delivery gate/build、整话/跨话终审、最终D批准或旧completed_errors；不重新读全部执行包、QA、决定、重试与批准历史，也不复制整套目录。

唯一完成入口：

```text
python -B <固定scripts>/lean_delivery.py --identity <交付身份.json> --output <成品输出目录>
```

程序核对完整源序、重复格号及明确缺格；确认采用文件存在。图片可读性沿用生产登记时的验证，不重新解码全部图片。原图直接写入ZIP，写入时核对原哈希；完成后一次顺序读取合并成员数量、内容与CRC检查，然后写本地验收回执并完成登记。恢复复用已有效完成的包，变化材料使回执失效，不重审未变内容。

ZIP仅有 `<话号>/<源格号>.<原格式>` 和根目录 `图片清单.csv`。每个源格一行，列为：话号、源格号、图片路径、交付状态、遗留问题或缺图原因。UTF-8 BOM、标准CSV引号、CRLF及公式转义沿用现有编码器。保留原始图片字节，不另加JSON、问题明细、执行包、审查材料、哈希文件或分包索引；证据留工作目录。确认网络重试封顶及内容拒绝如实列缺格，不放假图、不声称全部成功。普通未完成、未审或UNKNOWN不能包装为已完成。

旧交付合同保留原导出和验收实现，仅供旧冻结运行恢复；不因读到旧文档把新profile切回旧链。旧正式交接包仍通过receive导入当前执行器，原件不改写。

## 完成、失败与进度

统一发布保存打包尝试，同一失败/未知输入不重复打包；有真实修订才允许剩余一次自动整理。失败只清理本次新输出，不删除原件、重置预算或生图。前期超限只修装配/容器；成品没有容量失败分支。

```text
task_coordination.py finish-check --directory <协调目录> --revision <当前版本> --zip <已验收实际ZIP> --delivery-report <交付验收.json>
```

新任务缺完整验收记录不能finish-check/100%。前期验证全部卷、容量和真实恢复；新成品沿上述最小核验读取增量材料、原图和容器。实际发送文件变化使完成失效。生产进度沿原10分钟/服务等待15分钟周期，只统计采用图文件大小供参考，max_file_bytes=null/risk=NO_SIZE_LIMIT，不按容量报警或周期性压包。

## 新候选的受控装配

已有正式包只用运输层去重，不原地删旧RV。新候选可用handoff_zip.assemble，读取explicit_handoff_assembly_v1装配计划：files为真实path/sha256/bytes及reason（execution/traceability/runtime/release）、逐项evidence；required_paths和dependencies登记必要引用；unresolved_paths必须为空，并有实际reviewer/evidence。

工具逐文件复制计划内材料，复制后执行原audit_index/运行模板/冻结文件检查，缺必要文件或传递引用HOLD，返回ASSEMBLED_CANDIDATE_NOT_APPROVED。它不自动推断所有自然语言依赖，不按旧RV名称删材料。执行者须先核对追溯范围；未知材料保留并调查，不能把空列表伪装成依赖已审。实际索引/批准版本变化必须在最终输入审查前解决。Windows自定义package_handoff/execute_release须改用这些入口；本机安装不会自动修改远程自定义脚本或旧冻结工具。

## 限定验收

前期测试实际每文件容量边界、自动分卷、第001卷走receive完整接包、缺卷/损坏拒绝。成品测试无容量上限、无自动分包、保留图片字节、一份CSV及源序/采用图/问题记录一致、特殊字符和无问题格、缺失/篡改CSV拦截。大文件容量门禁测试与真实大ZIP生成需区分；合成测试不证明视觉质量。Windows桌面拖拽需实际宿主验证，不能以Python接包测试宣称UI已实测。

网络错误确认无图的有限重试与缺格交付，统一按[网络重试封顶](submission-runtime.md#网络错误最多重试四次)执行。仅经验证的NETWORK_FAILED或CONTENT_REFUSED可计入已处置源格；真实图片数和QA数不补齐，普通缺图/UNKNOWN仍阻止完整交付。
