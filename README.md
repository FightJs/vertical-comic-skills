# 条漫逐格成品 Skill 五件套

从已批准脚本和资产制作逐格成品图片。支持视觉基准、镜头设计、逐格生图、图片审查、分工ZIP交接与内容一致性检查；不包含拼接、气泡、文字排版或PSD收尾。

仓库是使用者同步来源：`main`提供最新提交，Release/tag提供固定版本。整套更新，避免五个Skill及规则库版本混用。生产RV按其已冻结版本继续，更新不会迁移旧RV或授予新的生图/返修权限。

## 首次安装（不需要GitHub账号）

公开仓库可直接在GitHub选择Code → Download ZIP，解压后交给Codex：

```text
请按这个目录中的tools/sync_skills.py安装完整条漫五件套。
```

也可用Git下载，无需先运行gh auth login：

```sh
git clone https://github.com/FightJs/vertical-comic-skills.git
cd vertical-comic-skills
python3 -m pip install -r requirements.txt
python3 tools/sync_skills.py
```

需要Codex及兼容Python；生图还需要实际可用的图像工具，安装不自动授予服务权限。GitHub账号和CLI仅用于可选的规则贡献同步，不是制作或本地维护前提。

五个Skill安装到`$CODEX_HOME/skills`（默认`~/.codex/skills`）。通用规则随总控Skill放在`assets/rule-memory/内置规则`，个人方法放`用户增补`；首次使用不需要填写memory_root。旧memory目录仍供显式外置配置兼容，不替换旧生产RV来源。

若检测到已有安装或本地修改，会保留现场并停止。先查看差异：

```sh
python3 tools/sync_skills.py --check
```

确定使用仓库版本时显式执行以下命令。旧文件会先备份，备份位置由工具输出，不自动删除：

```sh
python3 tools/sync_skills.py --replace-existing
```

自定义Codex目录使用`--codex-home /实际目录`。安装完成后在新的Codex轮次/任务中使用Skill；已经冻结的生产任务仍使用原快照。

## 更新到最新版本

在本仓库目录执行：

```sh
python3 tools/sync_skills.py --update
```

它先执行`git pull --ff-only`，再验证整套文件哈希并更新五个Skill和规则。仓库工作区或安装目录有本地改动时不会静默覆盖。更新前的安装保留备份，当前运行中的RV、源剧本、资产、项目使用配置和批准记录不属于更新目标。

需要保持固定版本时，先切换对应tag，再运行安装工具，不使用`--update`：

```sh
git fetch --tags
git checkout v2026.10.19.1
python3 tools/sync_skills.py
```

同步由使用者主动运行；本仓库未创建后台自动更新任务。可在GitHub设置Watch/Releases接收新版本通知。私有仓库使用者需要被所有者邀请；变更仓库可见性由所有者决定。

## 配置与启动

首次只给脚本、资产和准确话号；书名明确时可一并给出。无需先编辑完整JSON：

```text
使用 $vertical-comic-preproduction，进行前期制作。
书名：【书名】
脚本：【脚本路径】
资产：【资产目录】
话号：E026–E030。
其余用默认配置，完成后交正式ZIP。
```

本书路径保存在项目`.comic/books`，本次话号单独保存在新RV。后续只需“前期制作：【书名】E031–E035，使用本书配置”。默认输出项目下的新RV，原A/B及实际图片审核节点继续保留；初始化模板不是实际批准。

接包端：

```text
使用 $vertical-comic-preproduction。
接包生产：【正式ZIP路径】。
审核人是我，其余按包内流程执行。
```

系统按同名SHA256、包内书话和运行模板完成校验、解压、bind、rehearse，通过后按原半话/高风险/D节点生产。高级设置和已有配置仍可使用[配置示例](examples/comic.config.example.json)；脚本/资产填实际路径，内置记忆不需要另一个目录。

## 规则增补与同步

本地规则更新不需要GitHub账号。明确说“把这个问题提炼为通用规则并更新”，由Skill先核对跨作品适用性及重复冲突，成功后只影响新运行。剧情、某格坐标、图片、聊天和凭证不进入贡献包。

- **没有GitHub账号**：默认本地保存；说“导出我的规则增补”生成ZIP，交维护者用`rule_contributions.py import --zip <文件>`导入待审队列。未上传会明确标记，不能声称已同步。
- **有账号并明确启用**：使用本机`gh auth`。有仓库写权限，提交到`users/<login>/rule-memory`；无写权限则走自己的fork同名分支和PR。只写`contributions/<login>/rule-memory/<snapshot_id>/`，不改main；同账号多机器的快照互不删除。
- **无账号且希望自动上传**：需要另行部署接收服务。本仓库没有该服务，也不内置维护者令牌。

同步授权、凭证及待同步队列留本机，不进分发包。网络/登录失败保留PENDING_SYNC，不阻塞本地规则生效；维护者审阅后再合入内置规则，不自动执行他人贡献。安装更新保留用户增补，其他本地代码修改仍要求先检查和明确替换。

分工制作有两种职责，使用时明确其中一个：

- **前期准备并导出交接包**：按`direct_delivery_v2`准备，技术编译先于最终审查。最终输入获真实批准、条件导出获授权且完整接包演练通过后，交正式ZIP与SHA256，停在正文生图前。
- **接包生产与审核交付**：提供正式ZIP、SHA256、接手范围、审核人和输出目录。按包内冻结工具执行校验、bind和rehearse，再按批准半话窗口生产与审查。

完整启动词见[分工合同](skills/vertical-comic-preproduction/references/split-production.md)；发布条件见[直接交付](skills/vertical-comic-preproduction/references/direct-delivery.md)。有真实参考/提示词/设计变化时仍按准确范围审查，单纯更新仓库不解除预算、UNKNOWN或素材缺口。

## 内容与验证

| 目录 | 内容 |
| --- | --- |
| `skills/vertical-comic-preproduction` | 总控、共享合同、脚本及回归测试 |
| `skills/vertical-comic-visual-assets` | 身份、衣装、场景和画风依据 |
| `skills/vertical-comic-shot-design` | 逐格镜头、空间、接触及比例 |
| `skills/vertical-comic-panel-generation` | 实际输入编译及生图生产 |
| `skills/vertical-comic-image-review` | 真实QA、返修及逐格交付 |
| `memory` | 11条可跨作品复用的规则及维护说明 |
| `bundle.json` | 整套文件的SHA256清单 |

本仓库不包含实际项目脚本、角色资产、批准消息、生产结果或个人配置。Skill内示例插图属于方法示例，不能替代本书批准素材。索引通过不等于图片质量通过，必须保留实际看图审查。

```sh
python3 tools/check_bundle.py
python3 -B -m unittest discover -s skills/vertical-comic-preproduction/tests
python3 -B -m unittest discover -s tests
node skills/vertical-comic-preproduction/tests/test_async_generation.js
```

GitHub Actions会在push和pull request后执行这些检查。测试使用隔离合成输入，不发起真实生图调用。

## 维护者发布更新

推荐在本仓库维护，再测试、提交和推送。若仍先维护本机安装版，可用以下工具导出新副本；它不修改源安装目录，不复制其他项目目录，并将测试中的本机配置依赖替换成隔离夹具：

```sh
python3 tools/export_bundle.py --skills-root /实际/skills目录 --memory-root /实际/通用规则目录
python3 tools/check_bundle.py
python3 -B -m unittest discover -s skills/vertical-comic-preproduction/tests
python3 -B -m unittest discover -s tests
git add skills memory bundle.json
git commit -m "Update comic Skill bundle"
git push origin main
```

只有已提交并推送的版本可被使用者同步；本机安装目录的后续修改不会自动上传。发布新稳定版本时创建新的tag/Release，保留旧版本用于冻结生产恢复。本仓库未擅自添加开源许可证。
