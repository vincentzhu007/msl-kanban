# GitCode 第三方授权与用户 ID 白名单

## 当前状态

仓库已实现授权码登录、服务端会话、稳定用户 ID 白名单、网页/API/HEAD 访问保护、退出登录和 Docker 接入配置。离线认证测试通过，尚未配置真实应用凭据、域名和白名单，尚未完成真实 GitCode 登录或部署切换。旧 dog 看板未因本次代码改动自动获得认证保护。

## 授权流程

1. `/login` 展示登录按钮，`/auth/login` 跳转 GitCode。
2. 服务端生成一次性 state，并用独立 HttpOnly Cookie 绑定发起登录的浏览器，有效期10分钟。
3. GitCode 回调 `/auth/callback`，服务端核对 state、Cookie、有效期及单次使用约束。
4. 服务端换取令牌，然后请求当前用户身份；只使用 `id` 匹配白名单，不用可改名的 login。
5. 白名单用户获得随机会话 Cookie，有效期8小时；服务端只保存 ID、login 和会话元数据，不保存 GitCode access/refresh token。
6. 每次访问重新读取白名单，移除 ID 后已有会话即时拒绝访问。白名单读取失败或 JSON 无效时拒绝访问。

Cookie 使用 Secure、HttpOnly、SameSite=Lax、`__Host-` 前缀，路径固定为 `/`。不使用 URL 参数或浏览器 localStorage 保存授权令牌。访问日志省略查询参数，避免记录回调 code。退出使用 POST 和会话 CSRF token，同时验证 Origin。

## 官方接口依据（2026-10-27 核对）

- OAuth：https://docs.gitcode.com/docs/apis/oauth/
- Token 参数：https://docs.gitcode.com/en/docs/apis/post-oauth-token-grant-type-authorization-code-code-code-client-id-client-id-client-secret-client-secret/
- 当前用户：https://docs.gitcode.com/docs/apis/get-api-v-5-user/

授权地址为 `https://gitcode.com/oauth/authorize`，令牌地址为 `https://gitcode.com/oauth/token`，用户身份接口为 `https://api.gitcode.com/api/v5/user`。

Token 请求按官方参数表：grant_type/code/client_id 放入 query；client_secret 仅在 multipart form-data 请求体。用户接口使用 Authorization Bearer。上游返回重定向时失败，不自动把凭据转发到其他地址。

GitCode 应用应只申请身份资料所需的最小权限。`GITCODE_SCOPE` 的具体值以已注册应用支持的权限为准，留空时不传 scope，不表示替你授予任何额外权限。当前实现是 OAuth 授权码流程，不假设 GitCode 支持 OIDC 或未公开的 PKCE 参数。

## 上线前需提供

- 对用户可访问的 HTTPS 根域名，例如 `https://dashboard.example.com`（示例不可直接使用）。
- GitCode OAuth 应用 Client ID。
- Client Secret，存于 dog 的受限权限文件，不写进仓库或聊天。
- 允许访问的 GitCode 用户 `id` 列表（是 ID，不是用户名）。

在 GitCode OAuth 应用配置中填写**完全一致**的回调 URL：

```text
https://实际域名/auth/callback
```

不要填写 SSH 转发的 `http://127.0.0.1:18765` 作为生产回调。本实现要求 HTTPS origin；不接受 URL 内带路径、凭据或查询参数。

## Docker 配置

从 `dashboard/.env.example` 建立本机部署配置，填好实际域名和 Client ID。可使用：

```sh
docker compose --env-file dashboard/.env -f dashboard/compose.yaml config
docker compose --env-file dashboard/.env -f dashboard/compose.yaml up -d --build
```

准备以下文件（真实目录已加入 .gitignore）：

```text
dashboard/auth-config/client_secret
dashboard/auth-config/allowlist.json
```

`client_secret` 仅包含密钥本身。白名单格式：

```json
{"user_ids": ["实际GitCode用户ID"]}
```

空列表表示拒绝所有用户。模板在 `dashboard/auth-config.example/allowlist.json`。确保容器 UID/GID 65534 能读取目录与文件，密钥不要开放给其他本机用户。建议目录750、文件640，组设为容器运行组；根据服务器权限通过管理员完成，不能为了方便将密钥设成全局可读。

配置通过只读目录挂载，白名单可原子替换并即时生效。修改 Client ID/Secret、域名或 scope 后重启容器。

Compose 仅绑定 `127.0.0.1:18765`。由同主机已有 HTTPS 反向代理转发到该端口，外部只暴露 TLS 入口，不另开绕过鉴权的数据服务。反向代理也不要记录 OAuth 查询参数；应设置请求头/请求体大小、超时与登录速率限制。反向代理和证书未在本次自动创建。

## 访问控制边界

公开路径仅包括 `/health`（只返回 ok）、登录页和 OAuth 发起/回调。`/api/runs` 未登录返回401；网页/静态资源未登录跳转登录页；HEAD 与 GET 使用相同权限检查。

静态服务只提供 index.html、app.js、style.css，禁止目录浏览以及任意结果/源码路径下载。浏览器导出通过已经鉴权的 API 数据完成。账号页面 `/auth/account` 提供退出入口。

服务启动缺少认证配置时直接失败，不退回匿名模式。显式本地开发例外：

```sh
python3 dashboard/server.py --host 127.0.0.1 --dev-no-auth
```

该模式只允许 loopback 监听，不用于生产。生产启动后 `/health` 正常仅说明进程运行，不代表 OAuth 已真实联调成功。

## 测试与部署验收

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

测试用模拟 GitCode 响应，不消耗真实凭据，覆盖 state 绑定/过期/重放、ID白名单、撤销、会话过期、退出 CSRF、令牌传输位置、网页/API/HEAD拦截。HTTP 测试需要监听本地临时端口。

真实上线还需验证：白名单账号能够登录、非白名单拒绝、退出后 API 返回401、移除白名单使现有会话失效。单进程内存会话随重启清空；多副本部署前需将会话与 state 移至共享存储。目前不支持多副本共享会话。
