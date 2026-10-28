# GitHub Actions Runner 容器

Linux Docker Compose 部署。Runner 使用 host 网络，通过 `hdc -s 127.0.0.1:8710` 复用宿主机 HDC 服务；同机的 USB 连接、设备授权、TCP 转发由宿主机维护。镜像挂载同版本 HDC 工具目录，包含 `hdc` 和 `libusb_shared.so`。不需要 privileged、USB 直通或 Docker socket。

## 准备与构建

在本目录准备官方 Runner 发行文件（不会提交 Git）：

```sh
curl -fL --retry 3 -o runner.tar.gz https://github.com/actions/runner/releases/download/v2.338.2/actions-runner-linux-x64-2.338.2.tar.gz
printf '%s  %s\n' baebf204307bac6193480852732f0aba2ae97b6c5597c244f4d5558390147c40 runner.tar.gz | sha256sum -c -
mkdir -p runner-dist
tar xzf runner.tar.gz -C runner-dist
cp .env.example .env
# 按部署主机修改 .env 中的路径、UID/GID 和 HDC 端口。
docker compose build
```

新主机的状态目录需预先创建，并归 RUNNER_UID/RUNNER_GID 所有。HDC 服务必须已经启动并连接手机；迁移主机时重新确认 `hdc list targets`。dog 当前复用已校验的官方 Runner 发行文件，以 `mini-lite-llm:latest` 作为 Ubuntu 22.04 基础镜像。

## 注册和启动

空状态目录首次使用时，从 GitHub 仓库 Settings → Actions → Runners 获取短期注册令牌，在交互式配置中输入。令牌不要放进 .env、镜像或 Git。

```sh
docker compose run --rm runner ./config.sh --url https://github.com/vincentzhu007/msl-kanban --name dog-msl-kanban --labels dog,msl-kanban,container --work _work
docker compose up -d
docker compose logs --tail 30 runner
```

`/runner` 保存注册凭据、运行文件与工作区。Runner 会自动更新此目录中的运行文件；迁移现有 Runner 时先停止旧进程，再启动挂载同一状态目录的新容器，不能同时启动两个实例。迁移到不同机器可以沿用镜像、重新注册独立 Runner，并使用独立状态目录。复制状态目录意味着复制该 Runner 的凭据，应限制访问。

`restart: unless-stopped` 在 Docker 恢复时启动容器；宿主机 HDC 服务和手机转发也必须恢复。测试任务不挂载模型和 DDK，接入正式评测时再按 recipe 配置所需目录。

## 验证

手动运行仓库 `Dog connectivity` workflow。它确认执行环境是 Docker，检查设备列表，并对每个设备执行只读 shell echo。结果通过不代表模型推理、文件传输、BinRunner 或性能采样已验证。

当前 workflow 仅手动触发；绑定私有仓库的可信工作流，不接收来自不可信 PR 的执行任务。不要同时运行其他会占用同一手机的评测任务。
