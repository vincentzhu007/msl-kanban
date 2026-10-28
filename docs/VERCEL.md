# Vercel 静态看板

仓库 `dashboard/data/*.json` 是发布输入，包含已审阅的性能结果。执行 `node scripts/dashboard/build_vercel.mjs` 生成 `build/vercel-dashboard/`。它使用已有 dashboard 页面，打包结果为 runs.json，并校验基本字段与 ID 唯一性；不会修改 dog 的 Python 服务。部署后，浏览器仅在当前设备保存手动导入的数据，仓库结果仅在重新部署后更新。

## 安全和访问

静态版不运行当前 Python 服务或 GitCode OAuth 白名单。结果 JSON 含模型来源、设备及归档等元信息，应由数据所有者确认其共享范围。Vercel 项目的访问保护需要单独配置；启用 Vercel Authentication 的 All Deployments 后，访问者需登录有项目访问权的 Vercel 账号。此方式不是 GitCode 登录。生产和预览地址均须验证鉴权及静态 JSON 不可匿名读取，避免先公开数据再设置保护。

## 部署

根目录 `vercel.json` 指定无依赖 Node 构建及唯一静态目录。关联项目后在根目录执行 `vercel deploy` 发布预览，检查页面、runs.json 与登录保护，再执行 `vercel deploy --prod`。首次发布和后续流水线需要 Vercel 账号、项目关联及部署凭证；勿把令牌或 `.vercel/` 提交到 Git。账号尚未连接时不能生成真实线上链接。

建议后续使用 GitCode 流水线在通过校验的数据提交后调用 Vercel CLI；GitCode 不是 Vercel 原生 Git 集成。评测作业成功不代表数据已提交或部署，需独立跟踪这些步骤。当前未配置自动提交、调度或发布流程。

## GitCode 自动发布

`.gitcode/workflows/publish-dashboard.yml` 在 `main` 分支 push 或手动触发时，先构建和校验现有结果，再以 Vercel Build Output API 仅上传 4 个静态文件；部署到 `slm-lab/project-6x6w4` 生产环境。并发配置会请求取消旧任务，以减少旧构建排队覆盖新内容的风险；若旧任务已向 Vercel 提交部署，仍需检查最终线上版本。Vercel 项目的 All Deployments 登录保护独立于部署任务，必须保持启用。

前提：GitCode 仓库已开通代码化流水线及可用的 runner；在仓库设置的 Action 密钥与变量中设置 `VERCEL_TOKEN`（必须有此项目部署权限）。令牌不写入代码或日志。首次提交后在 GitCode 流水线检查实际运行结果，并在 Vercel 检查新部署与未登录访问保护。密钥缺失时任务会明确失败，不会生成新的生产部署。

修改模型数据并提交并推送到 main 才会触发网站更新；dog 上的评测不会自动提交数据。手动导入依然只保存在当前浏览器。

## GitHub 原生部署

Vercel 项目关联 GitHub 私有仓库 `vincentzhu007/msl-dashboard`。向 GitHub 的 `main` 推送后，Vercel 使用根目录 `vercel.json` 构建静态看板并部署。GitHub 原生集成不依赖 GitCode workflow 或 `VERCEL_TOKEN`。本地默认 `origin` 仍指向 GitCode；将提交推送到 `github` 远端才会触发该集成：

```sh
git push github main
```

部署完成后在 Vercel Deployments 核对提交 SHA、构建状态、网页数据与登录保护。此流程只发布已提交的静态数据，不负责触发 dog 评测或将新结果自动写入仓库。
