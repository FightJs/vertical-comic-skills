# 内置规则、用户增补与可选同步

正式通用库位于总控assets/rule-memory/内置规则，现有11条MEM保持原正文/版本；用户增补在同目录用户增补，使用USR-前缀。其他四个Skill共用同一来源，不复制第二套。统一有效索引由builtin_memory.resolve按内容合并至本机缓存；重复ID拒绝，不静默覆盖。阶段基准/命中读取、语义审计及原QA格式不变。

默认无需memory_root；新初始化和简易入口自动解析内置库，并冻结索引/正文和index_sha256。显式指定的外置来源继续使用原库；升级不热改旧RV。规则缓存按内容寻址，不缓存视觉PASS。正文或索引变化产生新版本缓存和新任务快照，生产只读。

## 规则维护

用户明确要求“将此问题提炼为通用规则并更新”才进入维护，不因正文生成失败自动回写。先检查是否跨话/跨作品可用，核对已有ID及冲突；剧情、人物状态、某格坐标/修正、批准例外留项目。内置MEM的改进作为用户增补提出方法，不直接覆盖已有MEM；冲突须人工明确处理，不叠加相反指令。

用rule_contributions.py update提交规则元数据JSON、正文MD及本地审查记录；记录source_kind=user_message、source_locator、authorization、portable=true、contains_story_facts=false。引用实际用户授权，不自造。脚本校验当前规则schema、路径/内容哈希及明显作品/格号/路径/凭证特征，然后原子激活用户增补目录并建立持久outbox。正则不是自然语言通用性的证明，执行者仍须实际审查。既有用户规则修改必须更新version。

维护失败保留本地意图/备份与诊断，不删有效旧规则。成功后明确说明哪些规则变了、仅影响新运行、是否已同步。升级器单独保留用户增补；生产阶段不调用update或自动导入远程增补。

## 没有GitHub账号也能正常用

默认仅本地更新并保留待同步包，GitHub不是生产依赖。用户说“导出我的规则增补”时，rule_contributions.py queue取得当前事件，再用export生成增补ZIP及哈希。ZIP只含规则正文、索引和文件清单，不含书名脚本、图片、QA、原聊天授权、路径或凭证。输出状态EXPORTED_NOT_UPLOADED，不能声称已提交仓库。

若需要让无账号用户自动上传，需要另行部署接收服务，服务端持有仓库凭证并做同意、校验和限流；本版本不提供该服务，不在Skill内放维护者令牌。无账号用户可以自行把ZIP交维护者导入；Skill不会未经指示代发消息。维护者可用rule_contributions.py import --zip导入校验后的待审队列；不自动激活规则，确认通用性后再整理或同步到仓库。

## 有GitHub账号时的自动同步

默认目标FightJs/vertical-comic-skills，用户分支users/<GitHub登录名>/rule-memory。每个安装者只在首次规则维护时选择是否启用；不在首次制作时强迫登录。授权保存在本机~/.codex/comic/rule-contributions/sync.json，令牌由gh auth管理，均不进入分发包或任务快照。

已明确同意后，configure --enable --authorization <真实授权依据>，每次成功update自动尝试一次同步：有目标仓库写权限则提交到该用户分支；无写权限则创建/复用自己的fork同名分支，并提交或复用到目标仓库的PR。fork未准备好、网络/授权失败保留PENDING_SYNC，可用sync重试，不阻塞本地规则生效，不自动强推。脚本返回新PR时，执行者须用attach_artifact附加该PR到当前任务。

服务器端只写contributions/<login>/rule-memory/<snapshot_id>/，每次不可变快照，避免同账号不同机器互相删掉增补。相同快照识别为已同步，未知push结果先读远程标记再决定，不盲目重复提交。只允许非force更新用户分支，不改main、不代用户合并PR。

内置库仅由维护者审阅各用户增补后优化发布，不把用户分支自动当正式规则执行。仓库目标只是收集位置，不授予任意使用者写你的仓库权限。GitHub登录名作为有账号贡献者标识；无账号贡献包由维护者归档标识，不伪装GitHub用户。
