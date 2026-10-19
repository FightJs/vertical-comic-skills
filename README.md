# 条漫逐格成品 Skill 五件套

从已批准脚本和资产制作逐格成品图片。支持视觉基准、镜头设计、逐格生图、图片审查、分工ZIP交接与内容一致性检查；不包含拼接、气泡、文字排版或PSD收尾。

仓库是使用者同步来源：`main`提供最新提交，Release/tag提供固定版本。整套更新，避免五个Skill及规则库版本混用。生产RV按其已冻结版本继续，更新不会迁移旧RV或授予新的生图/返修权限。

## 首次安装（公开下载无需GitHub账号）

需要Codex和Python 3.12+。图片生成还需要当前Codex环境实际可用的生图工具；安装不会自动提供工具权限。下面命令适用于macOS/Linux；Windows的虚拟环境解释器位于`.venv\Scripts\python.exe`。Git仅供Git下载及更新使用，Download ZIP安装不需要Git或GitHub CLI。

先下载，任选一种方式：

- **Git**：运行`git clone https://github.com/FightJs/vertical-comic-skills.git`，再`cd vertical-comic-skills`。
- **ZIP**：在[仓库](https://github.com/FightJs/vertical-comic-skills)选择Code → Download ZIP，解压后进入包含`README.md`和`tools`的目录。

然后建立独立Python环境并安装完整五件套：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/sync_skills.py
```

也可以把解压后的目录交给Codex，说“请按README创建虚拟环境并安装完整条漫五件套”。不要直接向系统Python安装依赖；Homebrew等环境会拒绝此操作。后续命令继续使用此虚拟环境的Python，无需激活环境或修改系统Python设置。

默认安装到`$CODEX_HOME/skills`（未设置时为`~/.codex/skills`），默认规则随总控Skill安装到`assets/rule-memory`；`$CODEX_HOME/skill-bundles/vertical-comic-skills/memory`保留外置来源兼容副本，新用户不用配置它。

若检测到已有安装或本地修改，会保留现场并停止。先查看差异：

```sh
.venv/bin/python tools/sync_skills.py --check
```

确定使用仓库版本时显式执行以下命令。旧文件会先备份，备份位置由工具输出，不自动删除：

```sh
.venv/bin/python tools/sync_skills.py --replace-existing
```

自定义Codex目录使用`--codex-home /实际目录`，检查和后续更新也沿用该参数。内置规则缓存和本机规则增补状态跟随`CODEX_HOME`；未设置环境变量时，工具识别受管理安装目录。安装完成后在新的Codex轮次/任务中使用Skill；已经冻结的生产任务仍使用原快照。

## 更新到最新版本

**Git下载版**：在原仓库目录执行：

```sh
.venv/bin/python tools/sync_skills.py --update
```

它先执行`git pull --ff-only`，再验证整套文件哈希并更新五个Skill和规则。仓库工作区或安装目录有本地改动时不会静默覆盖。更新前的安装保留备份，当前运行中的RV、源剧本、资产、项目使用配置和批准记录不属于更新目标。本机用户规则增补独立保留，不上传到共享发布版，也不被更新覆盖。

**ZIP下载版**：重新下载新版ZIP，解压到新目录。在新目录建立虚拟环境，检查后安装到原来的Codex目录：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python tools/sync_skills.py --check
.venv/bin/python tools/sync_skills.py
```

ZIP版不使用`--update`；误用时工具会提示以上路径。已有安装由同一工具管理且没有代码改动时会直接更新；存在本地代码改动时先检查，再按明确选择使用`--replace-existing`。用户增补保留，旧版本备份；不要手工覆盖`skills`目录。

需要保持固定版本时，从GitHub下载对应tag的ZIP，或在Git副本中切换tag，再安装，不使用`--update`：

```sh
git fetch --tags
git checkout v2026.10.19.2
.venv/bin/python tools/sync_skills.py
```

同步由使用者主动运行；本仓库未创建后台自动更新任务。可在GitHub设置Watch/Releases接收新版本通知。只有访问私有副本或明确选择规则贡献上传时才需要相应账号和权限，公开下载及本地制作无需GitHub登录。

## 首次使用：让Skill引导配置

安装后在Codex里只需说：

```text
使用 $vertical-comic-preproduction。
第一次使用，请引导我配置，进行前期制作。
```

Skill会先检查本项目已有配置，再一次收集缺少的书名、源脚本文件、资产目录和话号。用户可拖入文件/文件夹或提供本机路径；规则库、默认并发和输出位置自动设置，无需先创建或编辑JSON，也无需GitHub登录才能制作。

信息齐全后自动校验路径，保存项目`.comic/books`中的本书配置，建立本次配置和全新RV，并展示保存位置。源剧本审计、视觉基准和镜头/生图包审查仍正常执行；初始化不等于批准生产。已有配置不重复填写，路径变化或真实冲突才集中询问。

完整填写也可以直接开始：

```text
使用 $vertical-comic-preproduction，进行前期制作。
书名：【书名】
脚本：【本机源脚本路径】
资产：【本机资产目录】
话号：E021–E025。
其余用默认配置，完成后交正式ZIP，停在正文生图前。
```

以后同一本书只需“前期制作：《书名》E026–E030，使用本书配置”。接包端只需“接包生产：【正式ZIP路径】，审核人是我”；包内完整性清单、发布证据、书话范围自动核验；可填写输出位置，无需外置校验文件。

明确“只根据脚本和资产重新制作”会建立独立任务，不寻找或继承同书同话其他任务的旧图、QA和返修账。恢复与接包保留原任务及预算；仅明确选中的旧成果才进入复用核对。缺资产先判断本批实际需求，再分为正式资产候选、视角/状态补充、临时参考或一次性直接描述，按A审查决定入库；旧索引的无关断链不阻塞整批。具体规则见[任务来源与历史范围](skills/vertical-comic-preproduction/references/task-origin.md)。

详细引导见[首次使用](skills/vertical-comic-preproduction/references/quick-start.md)。[JSON配置示例](examples/comic.config.example.json)只供高级用户显式配置；默认规则来自总控Skill的`assets/rule-memory`，新用户无需指定规则目录。执行agent数量和输出目录可在对话中临时指定，实际并行仍服从可用容量。

## 规则增补与同步

本地规则更新不需要GitHub账号。明确说“把这个问题提炼为通用规则并更新”，由Skill先核对跨作品适用性及重复冲突，成功后只影响新运行。剧情、某格坐标、图片、聊天和凭证不进入贡献包。

- **没有GitHub账号**：默认本地保存；说“导出我的规则增补”生成ZIP，交维护者用`rule_contributions.py import --zip <文件>`导入待审队列。未上传会明确标记，不能声称已同步。
- **有账号并明确启用**：使用本机`gh auth`。有仓库写权限，提交到`users/<login>/rule-memory`；无写权限则走自己的fork同名分支和PR。只写`contributions/<login>/rule-memory/<snapshot_id>/`，不改main；同账号多机器的快照互不删除。
- **无账号且希望自动上传**：需要另行部署接收服务。本仓库没有该服务，也不内置维护者令牌。

同步授权、凭证及待同步队列留本机，不进分发包。网络/登录失败保留PENDING_SYNC，不阻塞本地规则生效；维护者审阅后再合入内置规则，不自动执行他人贡献。安装更新保留用户增补，其他本地代码修改仍要求先检查和明确替换。

分工制作有两种职责，使用时明确其中一个：

- **前期准备并导出交接包**：按`direct_delivery_v2`准备，技术编译先于最终审查。最终输入获真实批准、条件导出获授权且完整接包演练通过后，仅交一个正式交接包.zip，说明、校验清单和演练/导出证据内置，停在正文生图前。
- **接包生产与审核交付**：提供一个正式ZIP、接手范围、审核人和输出目录。按包内冻结工具执行校验、bind和rehearse，再按批准半话窗口生产与审查。

完整启动词见[分工合同](skills/vertical-comic-preproduction/references/split-production.md)；发布条件见[直接交付](skills/vertical-comic-preproduction/references/direct-delivery.md)。有真实参考/提示词/设计变化时仍按准确范围审查，单纯更新仓库不解除预算、UNKNOWN或素材缺口。

## 内容与验证

| 目录 | 内容 |
| --- | --- |
| `skills/vertical-comic-preproduction` | 总控、共享合同、脚本及回归测试 |
| `skills/vertical-comic-visual-assets` | 身份、衣装、场景和画风依据 |
| `skills/vertical-comic-shot-design` | 逐格镜头、空间、接触及比例 |
| `skills/vertical-comic-panel-generation` | 实际输入编译及生图生产 |
| `skills/vertical-comic-image-review` | 真实QA、返修及逐格交付 |
| `skills/vertical-comic-preproduction/assets/rule-memory` | 内置11条通用规则及本机用户增补入口 |
| `memory` | 外置规则兼容副本及维护说明 |
| `bundle.json` | 整套文件的SHA256清单 |

本仓库不包含实际项目脚本、角色资产、批准消息、生产结果或个人配置。Skill内示例插图属于方法示例，不能替代本书批准素材。索引通过不等于图片质量通过，必须保留实际看图审查。

```sh
.venv/bin/python tools/check_bundle.py
.venv/bin/python -B -m unittest discover -s skills/vertical-comic-preproduction/tests
.venv/bin/python -B -m unittest discover -s tests
node skills/vertical-comic-preproduction/tests/test_async_generation.js
```

GitHub Actions会在push和pull request后执行这些检查。测试使用隔离合成输入，不发起真实生图调用。

## 维护者发布更新

推荐在本仓库维护，再测试、提交和推送。若仍先维护本机安装版，可用以下工具导出新副本；它不修改源安装目录，不复制其他项目目录，并将测试中的本机配置依赖替换成隔离夹具：

```sh
.venv/bin/python tools/export_bundle.py --skills-root /实际/skills目录
.venv/bin/python tools/check_bundle.py
.venv/bin/python -B -m unittest discover -s skills/vertical-comic-preproduction/tests
.venv/bin/python -B -m unittest discover -s tests
git add skills memory bundle.json
git commit -m "Update comic Skill bundle"
git push origin main
```

只有已提交并推送的版本可被使用者同步；本机安装目录的后续修改不会自动上传。发布新稳定版本时创建新的tag/Release，保留旧版本用于冻结生产恢复。本仓库未擅自添加开源许可证。
