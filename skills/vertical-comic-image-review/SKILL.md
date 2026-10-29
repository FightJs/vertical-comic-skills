---
name: vertical-comic-image-review
description: Review actual comic images against approved evidence, preserve truthful QA and connect production decisions to annotated first-batch per-panel delivery. Use for image consistency QA, returned-image review or final panel delivery, excluding strip layout and bubbles.
---

# 条漫图片轻审核与成品交付

统一入口为整话轻审核：新任务与旧包导入后都固定当前执行器，旧包代码仅作证据。每话启动一个 `generation_host.py serve` 常驻进程；输入未变复用，局部修改只处理受影响格；返回立即保存并释放槽位。每图快速看一次，仅严重剧情问题最多返修一轮。暂停和等待用户不计时，多话共用四小时有效预算，三小时不停止首轮。完整约定见[统一执行与恢复](../vertical-comic-preproduction/references/execution-compatibility.md)与[轻审核流程](../vertical-comic-preproduction/references/light-review.md)。

新轻审核运行的自动返修阈值为essential_story_only_v1：仅主要人物明显错认、关键剧情缺失、剧情表达相反或剧情不可理解时，最多自动返修一轮。每图一次快速观察，其他问题记录并归集；具体字段及旧包分支见[轻审核流程](../vertical-comic-preproduction/references/light-review.md#必要返修阈值新轻审核运行)。

先读取状态的image_review_profile：新任务默认light_story_review_v1，按[轻审核流程](../vertical-comic-preproduction/references/light-review.md)执行。speed_policy=bounded_stage_fallback_v1时执行该页环节限时；暂停及等用户不计时，三小时不停止首轮，四小时为累计有效预算。旧任务先导入原证据并保留时钟。

## 默认轻审核

1. 返回图立即落盘、登记真实返回并释放生图槽；审核独立排队，继续生成其他就绪格。用production_runtime.py review --prepare-qa取得准确模板，不把模板当观察。
2. 每图快速看一次人物是否明显错认、关键动作对象和剧情是否可理解。只在关键剧情看不清时查看必要局部或前图，不常规放大饰品、不填六项或逐MEM细节、不做整话跨话第二遍复审。
3. 用review_pipeline.py或workflow_session的qa-save一次保存真实观察、问题、处理决定和采用。超30秒用一句实际观察；工具补身份、路径和哈希。普通瑕疵留人工，严重剧情问题最多返修一轮；返修预算耗尽沿用已有图并标明严重遗留，不假报PASS。
4. 修后快速检查人物及关键动作，采用较可用的真实版本。旧QA、原图、失败、attempt和调用预算保留；未知调用先查原请求，不超时重发。首轮出齐优先于返修，不专门生图演练返修路径。
5. 每格采用后增量归集原图、QA和问题。依据[生产决定](../vertical-comic-preproduction/references/production-decisions.md)及panel_delivery导出真实采用版本，严重遗留标注人工优先处理。仅范围外事项或明确保留亲审项询问用户，不新增D确认。
6. 最后运行完整deliver与[成品发布](../vertical-comic-preproduction/references/delivery-contract.md)，核对全部源格、真实采用图、索引、问题CSV、哈希和ZIP容器，不再次审遍所有图片。全部源格交齐后提供完整成品包；缺图、待审或UNKNOWN不冒充完成。不拼接、不加气泡、不改原图字节。

同一话优先复用[工作进程](../vertical-comic-preproduction/references/incremental-pipeline.md)处理登记，避免每图启动新进程重查公共输入。实际图片变化才重审受影响格；修订使用准确base_qa与当前状态哈希。

接包QA使用generation_host核验过本机规则地址的实际执行副本，并绑定其哈希；原批准包保留。地址修复不改变实际观察和原证据。

历史全面QA保持原文件、原结论和原引用，由导入器按原证据读取，不要求重填六项。用户另设的审核点继续保留；未审图不能自动补PASS。
