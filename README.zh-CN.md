# agent-ledger 中文快速开始

完整文档见 [README.md](README.md)。agent-ledger 是一个项目级、本地 SQLite 协作台账，供人类与多个 Claude Code session 协调 planner、consult、worker 三类工作。

```bash
pipx install git+https://github.com/hcsum/agent-ledger.git
cd /path/to/your-project
agent-ledger install
# 重启 Claude Code
agent-ledger demo
agent-ledger-dashboard
```

打开 <http://127.0.0.1:8765>。在三个独立的新 Claude Code session 中分别运行 `/planner`、`/consult`、`/worker`。

当前 Claude adapter 支持 macOS 和 Linux。若项目已有同名 skill，安装器会拒绝覆盖，先移动或改名后再重试。

数据保存在目标项目的 `.agent-ledger/ledger.sqlite`，默认已被 `.gitignore` 忽略。Dashboard 只读、默认仅监听 `127.0.0.1`，**没有身份认证**；不要暴露到不可信网络，也不要把密钥写入台账。
