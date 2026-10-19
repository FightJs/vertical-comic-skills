# 条漫逐格成品 Skill 五件套

从已批准脚本和资产制作逐格成品图片。支持视觉基准、镜头设计、逐格生图、图片审查、分工ZIP交接与内容一致性检查；不包含拼接、气泡、文字排版或PSD收尾。

仓库是使用者同步来源：`main`提供最新提交，Release/tag提供固定版本。整套更新，避免五个Skill及规则库版本混用。生产RV按其已冻结版本继续，更新不会迁移旧RV或授予新的生图/返修权限。

## 首次安装

需要Codex、Git、Python 3.12+。生成图片还需要当前Codex环境实际可用的生图工具；安装本仓库不自动提供工具权限。GitHub CLI用于访问私有仓库；使用者须先获仓库访问权限。

```sh
gh auth login
gh repo clone FightJs/vertical-comic-skills
cd vertical-comic-skills
python3 -m pip install -r requirements.txt
python3 tools/sync_skills.py
```

默认安装到`$CODEX_HOME/skills`（未设置时为`~/.codex/skills`），配套规则安装到`$CODEX_HOME/skill-bundles/vertical-comic-skills/memory`。

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

复制[配置示例](examples/comic.config.example.json)到项目目录，填写书名、准确话号、源脚本、资产和上述规则记忆的真实绝对路径。示例占位符不能直接运行。`generation.episode_workers`调整话执行者数量，并发仍受实际agent槽位和生图服务容量限制。

首次启动可使用：

```text
使用 $vertical-comic-preproduction。
读取使用配置：【项目配置绝对路径】。
本次范围：【准确话号】。
输出到：【项目输出绝对目录】下的新RV。
按当前固定流程完成，在约定的视觉基准、镜头/生图包及实图验收节点等我审查。
最终只交逐格图片包，我自行拼接和加气泡。
```

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
