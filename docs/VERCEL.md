# Vercel 静态看板

仓库 `dashboard/data/*.json` 是发布输入，包含已审阅的性能结果。执行 `node scripts/dashboard/build_vercel.mjs` 生成 `build/vercel-dashboard/`。它使用已有 dashboard 页面，打包结果为 runs.json，并校验基本字段与 ID 唯一性；不会修改 dog 的 Python 服务。部署后，浏览器仅在当前设备保存手动导入的数据，仓库结果仅在重新部署后更新。

## 安全和访问

静态版不运行当前 Python 服务或 GitCode OAuth 白名单。结果 JSON 含模型来源、设备及归档等元信息，应由数据所有者确认其共享范围。Vercel 项目的访问保护需要单独配置；启用 Vercel Authentication 的 All Deployments 后，访问者需登录有项目访问权的 Vercel 账号。此方式不是 GitCode 登录。生产和预览地址均须验证鉴权及静态 JSON 不可匿名读取，避免先公开数据再设置保护。

## 部署

根目录 `vercel.json` 指定无依赖 Node 构建及唯一静态目录。关联项目后在根目录执行 `vercel deploy` 发布预览，检查页面、runs.json 与登录保护，再执行 `vercel deploy --prod`。首次发布和后续流水线需要 Vercel 账号、项目关联及部署凭证；勿把令牌或 `.vercel/` 提交到 Git。账号尚未连接时不能生成真实线上链接。

建议后续使用 GitCode 流水线在通过校验的数据提交后调用 Vercel CLI；GitCode 不是 Vercel 原生 Git 集成。评测作业成功不代表数据已提交或部署，需独立跟踪这些步骤。当前未配置自动提交、调度或发布流程。
