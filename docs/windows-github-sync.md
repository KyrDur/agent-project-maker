# Windows 上的 GitHub 同步

在 Windows Git 中执行普通 `git push` 时，推送钩子会自动进入 WSL，
把当前提交取到 Linux 原生文件系统中的专用缓存目录，安装锁定的依赖，
运行完整的后端 pytest 和前端 Vitest。只有全部通过，Windows Git 才继续上传。
GitHub 凭据由 Windows Git 管理，不复制到 Linux 检查目录。

WSL 发行版需要可在 PATH 中访问的 Git、Python 3.12/uv、Node 22、
pnpm 9.15.9、flock 和 sha256sum。Docker 相关检查还需要可信系统路径中的
Docker CLI 能连接正在运行的 Docker Desktop；推荐启用该发行版的 WSL 集成。

默认使用 WSL 默认发行版。可在 PowerShell 中显式选择：

```powershell
$env:APM_WSL_DISTRO = 'Ubuntu-24.04'
git push origin codex/reliable-project-evaluation
```

检查目录位于 WSL 的 `~/.cache/agent-project-maker/`，按源目录区分并加锁。
它只取已提交的 Git 内容，不复制 `.env`、凭据或 Windows 的依赖目录，
也不改变 Windows 工作区。检查失败会阻止推送，日志直接显示失败项。

历史计划测试使用仓库内固定的 `history.json` 和验证账本。
该历史快照取自上游 `YooSuhwa/natural-mold` 的
`7a9cee88c772e29c830cd84fb5578d06d753e080..87b0d1490b4bf5bbced34680298dd176948566d7`，
因此新克隆和独立派生仓库无需额外获取上游历史对象。
