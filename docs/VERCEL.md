# Vercel 静态看板

仓库 `kanban/data/*.json` 是发布输入，包含已审阅的性能结果。执行 `node scripts/kanban/build_vercel.mjs` 生成 `build/vercel-kanban/`。它使用已有 kanban 页面，打包结果为 runs.json，并校验基本字段与 ID 唯一性；不会修改 dog 的 Python 服务。部署后，浏览器仅在当前设备保存手动导入的数据，仓库结果仅在重新部署后更新。

## 安全和访问

静态版不运行 Python 服务。结果 JSON 含模型来源、设备及归档等元信息，应由数据所有者确认其共享范围。当前项目已关闭 Vercel Authentication，所有部署及其静态结果均可匿名访问。仓库本身仍为私有。

## 部署

根目录 `vercel.json` 指定无依赖 Node 构建及唯一静态目录。关联项目后在根目录执行 `vercel deploy` 发布预览，检查页面、runs.json 与访问设置，再执行 `vercel deploy --prod`。首次发布和后续流水线需要 Vercel 账号、项目关联及部署凭证；勿把令牌或 `.vercel/` 提交到 Git。当前生产地址为 https://msl-kanban.vercel.app/。

当前使用 GitHub 与 Vercel 的原生集成自动发布。评测作业成功不代表数据已提交或部署，需独立跟踪这些步骤。Daily workflow 已提供评测结果自动提交，启用方式见 [Daily 说明](DAILY.md)。

## GitHub 原生部署

Vercel 项目关联 GitHub 私有仓库 `vincentzhu007/msl-kanban`。向 GitHub 的 `main` 推送后，Vercel 使用根目录 `vercel.json` 构建静态看板并部署。GitHub 原生集成不需要额外配置 `VERCEL_TOKEN`。本地默认 `origin` 指向该 GitHub 仓库，推送提交即可触发该集成：

```sh
git push origin main
```

部署完成后在 Vercel Deployments 核对提交 SHA、构建状态、网页数据与公开访问状态。此流程只发布已提交的静态数据，不负责触发 dog 评测或将新结果自动写入仓库。
